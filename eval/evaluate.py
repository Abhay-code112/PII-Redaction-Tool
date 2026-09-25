"""Evaluate the redactor against hand-labelled data.

Two gold sets
  real       70 sampled paragraphs of the prospectus, hand annotated (eval/gold_real.py)
  synthetic  labelled ticket sentences for SSN / card / DOB / IP / phone ... (eval/synthetic.json)

Three system variants (ablation): regex only, raw spaCy NER + regex, and the hybrid.

Metrics
  entity level  precision / recall / F1 per PII type. A prediction is a true positive when
                its label matches and the spans overlap with IoU >= 0.5 ("relaxed"); the
                exact-boundary variant ("strict") is reported too.
  token level   every whitespace token is PII or not; accuracy = (TP+TN)/N, plus P/R/F1.
                Label-agnostic: it answers "was the sensitive text replaced?".
  leak rate     share of gold PII strings still present in the redacted .docx
  fake quality  consistency, format preservation, no original text left in a fake
"""
import json
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, ".")
from eval.gold_real import GOLD                       # noqa: E402
from eval.gold_real_test import GOLD as GOLD_TEST     # noqa: E402
from pii_redactor import Policy, Redactor, docx_io   # noqa: E402
from pii_redactor.pipeline import load_spacy         # noqa: E402

LABEL_GROUP = {"LOCALITY": "ADDRESS", "AADHAAR": "ID_NUMBER"}
MODES = ("regex", "ner", "hybrid")


# ---------------------------------------------------------------- gold ----
def gold_spans_real(text: str, items) -> list[tuple[int, int, str]]:
    spans = []
    for sub, label in items:
        for m in re.finditer(re.escape(sub), text):
            spans.append((m.start(), m.end(), label))
    return _drop_nested(spans)


def _drop_nested(spans):
    spans = sorted(set(spans), key=lambda s: (s[0], -(s[1] - s[0])))
    out = []
    for s in spans:
        if not any(o[0] <= s[0] and s[1] <= o[1] and o != s for o in out):
            out.append(s)
    return out


# ------------------------------------------------------------- matching ----
def iou(a, b) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union else 0.0


def match(pred, gold, thresh: float):
    """Greedy one-to-one matching on same-label spans. Returns per-label Counters."""
    tp, fp, fn = Counter(), Counter(), Counter()
    used = set()
    for p in sorted(pred):
        best, best_i = 0.0, None
        for i, g in enumerate(gold):
            if i in used or g[2] != p[2]:
                continue
            v = iou(p, g)
            if v > best:
                best, best_i = v, i
        if best_i is not None and best >= thresh:
            used.add(best_i)
            tp[p[2]] += 1
        else:
            fp[p[2]] += 1
    for i, g in enumerate(gold):
        if i not in used:
            fn[g[2]] += 1
    return tp, fp, fn


def token_confusion(text: str, pred, gold) -> Counter:
    c = Counter()
    for m in re.finditer(r"\S+", text):
        a = (m.start(), m.end())
        p = any(a[0] < s[1] and s[0] < a[1] for s in pred)
        g = any(a[0] < s[1] and s[0] < a[1] for s in gold)
        c["tp" if p and g else "fp" if p else "fn" if g else "tn"] += 1
    return c


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4), "tp": tp, "fp": fp, "fn": fn}


# ----------------------------------------------------------------- runs ----
def predict(red: Redactor, text: str) -> list[tuple[int, int, str]]:
    return [(s.start, s.end, LABEL_GROUP.get(s.label, s.label)) for s in red.detect(text)]


def score(items, mode: str, nlp) -> dict:
    """items: list of (text, gold_spans, group). Detector is fitted on the same corpus it is scored on."""
    red = Redactor(Policy(mode=mode), nlp=nlp if mode != "regex" else None)
    return red, None


def evaluate_set(name: str, texts_for_fit: list[str], scored: list[tuple[int, str, list]], nlp) -> dict:
    """scored = (paragraph index, text, gold spans)."""
    out = {}
    for mode in MODES:
        red = Redactor(Policy(mode=mode), nlp=nlp)
        t0 = time.time()
        red.fit(texts_for_fit)
        strict = [Counter(), Counter(), Counter()]
        relaxed = [Counter(), Counter(), Counter()]
        tok = Counter()
        by_pool = defaultdict(Counter)
        for _, text, gold in scored:
            pred = predict(red, text)
            for agg, thr in ((strict, 1.0), (relaxed, 0.5)):
                for k, cnt in zip(range(3), match(pred, gold, thr)):
                    agg[k].update(cnt)
            tok.update(token_confusion(text, pred, gold))
        errors = error_examples(red, scored) if mode == "hybrid" else []
        labels = sorted(set(strict[0]) | set(strict[1]) | set(strict[2]))
        per_label = {}
        for lab in labels:
            per_label[lab] = {"relaxed": prf(relaxed[0][lab], relaxed[1][lab], relaxed[2][lab]),
                              "strict": prf(strict[0][lab], strict[1][lab], strict[2][lab])}
        micro = {kind: prf(sum(agg[0].values()), sum(agg[1].values()), sum(agg[2].values()))
                 for kind, agg in (("relaxed", relaxed), ("strict", strict))}
        n = sum(tok.values())
        tp, fp, fn, tn = (tok[k] for k in ("tp", "fp", "fn", "tn"))
        out[mode] = {
            "per_label": per_label, "micro": micro,
            "token": {**prf(tp, fp, fn), "tn": tn, "accuracy": round((tp + tn) / n, 4), "tokens": n},
            "seconds": round(time.time() - t0, 1), "errors": errors,
        }
    return out


def error_examples(red: Redactor, scored) -> list[dict]:
    """Every false positive / false negative (relaxed matching) with a little context."""
    rows = []
    for para, text, gold in scored:
        pred = predict(red, text)
        for p in pred:
            if not any(g[2] == p[2] and iou(p, g) >= 0.5 for g in gold):
                near = [g[2] for g in gold if iou(p, g) > 0]
                rows.append({"kind": "FP", "label": p[2], "text": text[p[0]:p[1]], "context": text[:110],
                             "note": f"overlaps gold {near[0]}" if near else "not PII"})
        for g in gold:
            if not any(p[2] == g[2] and iou(p, g) >= 0.5 for p in pred):
                near = [p[2] for p in pred if iou(p, g) > 0]
                rows.append({"kind": "FN", "label": g[2], "text": text[g[0]:g[1]], "context": text[:110],
                             "note": f"predicted as {near[0]}" if near else "missed entirely"})
    return rows


def synthetic_name_recall(nlp, items) -> dict:
    """PERSON recall split by whether the name is in the tool's gazetteer locales."""
    texts = [it["text"] for it in items]
    red = Redactor(Policy(mode="hybrid"), nlp=nlp)
    red.fit(texts)
    hit, tot = Counter(), Counter()
    for it in items:
        pred = predict(red, it["text"])
        for s in it["pii"]:
            if s["label"] != "PERSON":
                continue
            g = (s["start"], s["end"], "PERSON")
            tot[s["pool"]] += 1
            hit[s["pool"]] += any(iou(p, g) >= 0.5 for p in pred if p[2] == "PERSON")
    return {pool: {"recall": round(hit[pool] / tot[pool], 4), "n": tot[pool]} for pool in tot}


def leak_and_fake_quality(src: str, nlp, gold_sets: dict[str, dict]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        dst, audit = str(Path(tmp) / "out.docx"), str(Path(tmp) / "audit.json")
        red = Redactor(Policy(mode="hybrid"), nlp=nlp)
        t0 = time.time()
        report = red.redact_file(src, dst, audit)
        seconds = time.time() - t0
        before = [p.text for p in docx_io.iter_paragraphs(docx_io.load(src))]
        after = [p.text for p in docx_io.iter_paragraphs(docx_io.load(dst))]
    leaks = {}
    for name, gold in gold_sets.items():
        leaked, total = [], 0
        for para, items in gold.items():
            for sub, label in items:
                total += 1
                if sub in after[para]:
                    leaked.append((para, sub, label))
        leaks[name] = {"gold_spans": total, "leaked": len(leaked), "leak_rate": round(len(leaked) / total, 4),
                       "leaked_examples": leaked[:12]}
    ents = report.entities
    # consistency: same original (case-insensitive) -> same fake (case-insensitive)
    seen, inconsistent = {}, 0
    for e in ents:
        k = (e["label"], re.sub(r"\s+", " ", e["original"].lower()))
        v = re.sub(r"\s+", " ", e["replacement"].lower())
        inconsistent += seen.setdefault(k, v) != v
    fmt_ok = fmt_n = 0
    for e in ents:
        o, r = e["original"], e["replacement"]
        if e["label"] == "PHONE":
            fmt_n += 1
            fmt_ok += len(re.sub(r"\D", "", o)) == len(re.sub(r"\D", "", r)) and o != r
        elif e["label"] == "EMAIL":
            fmt_n += 1
            fmt_ok += bool(re.fullmatch(r"[\w.+-]+@[\w.-]+\.\w+", r)) and o != r
        elif e["label"] == "ID_NUMBER":
            fmt_n += 1
            fmt_ok += len(o) == len(r) and o != r
    unchanged = sum(e["original"] == e["replacement"] for e in ents)
    return {
        "leak": leaks,
        "entities_replaced": len(ents), "by_label": dict(report.counts),
        "inconsistent_mappings": inconsistent, "unchanged_replacements": unchanged,
        "format_preserved": f"{fmt_ok}/{fmt_n}", "seconds": round(seconds, 1),
        "cleaning": dict(report.cleaning),
    }


def load_real(rows_file: str, gold: dict):
    rows = {r["para"]: r["text"] for r in json.load(open(rows_file, encoding="utf8"))}
    return [(i, t, gold_spans_real(t, gold.get(i, []))) for i, t in sorted(rows.items())]


def load_synth(path: str):
    items = json.load(open(path, encoding="utf8"))
    return items, [(i, it["text"], [(s["start"], s["end"], s["label"]) for s in it["pii"]])
                   for i, it in enumerate(items)]


def summarise(scored) -> dict:
    return {"items": len(scored), "gold_spans": sum(len(g) for _, _, g in scored),
            "gold_by_label": dict(Counter(s[2] for _, _, g in scored for s in g))}


def main(src: str = r"D:\Red Herring Prospectus.docx") -> None:
    nlp = load_spacy()
    all_texts = [p.text for p in docx_io.iter_paragraphs(docx_io.load(src))]
    real_dev = load_real("eval/sample_paragraphs.json", GOLD)
    real_test = load_real("eval/test_paragraphs.json", GOLD_TEST)
    synth_dev_items, synth_dev = load_synth("eval/synthetic.json")
    synth_test_items, synth_test = load_synth("eval/synthetic_test.json")
    res = {
        "real_dev": {**summarise(real_dev), **evaluate_set("real_dev", all_texts, real_dev, nlp)},
        "real_test": {**summarise(real_test), **evaluate_set("real_test", all_texts, real_test, nlp)},
        "synth_dev": {**summarise(synth_dev), **evaluate_set("synth_dev", [t for _, t, _ in synth_dev], synth_dev, nlp)},
        "synth_test": {**summarise(synth_test),
                       **evaluate_set("synth_test", [t for _, t, _ in synth_test], synth_test, nlp)},
        "synth_test_person_by_pool": synthetic_name_recall(nlp, synth_test_items),
        "end_to_end": leak_and_fake_quality(src, nlp, {"dev": GOLD, "test": GOLD_TEST}),
    }
    json.dump(res, open("eval/results.json", "w", encoding="utf8"), indent=1)
    for ds in ("real_dev", "real_test", "synth_dev", "synth_test"):
        print(f"\n=== {ds}: {res[ds]['gold_spans']} gold spans ===")
        for mode in MODES:
            m = res[ds][mode]
            print(f" {mode:7s} entity(relaxed) P={m['micro']['relaxed']['precision']:.3f} R={m['micro']['relaxed']['recall']:.3f} "
                  f"F1={m['micro']['relaxed']['f1']:.3f} | token acc={m['token']['accuracy']:.3f} "
                  f"P={m['token']['precision']:.3f} R={m['token']['recall']:.3f}")
        if ds.endswith("test"):
            for lab, v in res[ds]["hybrid"]["per_label"].items():
                r = v["relaxed"]
                print(f"   {lab:12s} P={r['precision']:.2f} R={r['recall']:.2f} F1={r['f1']:.2f}  (tp={r['tp']} fp={r['fp']} fn={r['fn']})")
    e = res["end_to_end"]
    print("\nleak:", {k: (v["leaked"], v["gold_spans"]) for k, v in e["leak"].items()})
    print("test leaked examples:", e["leak"]["test"]["leaked_examples"])
    print({k: v for k, v in e.items() if k != "leak"})
    print("synthetic-test PERSON recall by pool:", res["synth_test_person_by_pool"])


if __name__ == "__main__":
    main(*sys.argv[1:])
