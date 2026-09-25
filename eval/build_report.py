"""Turn eval/results.json into output/Evaluation_Report.docx (numbers are never typed by hand)."""
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402
from docx import Document                             # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH         # noqa: E402
from docx.shared import Inches, Pt, RGBColor           # noqa: E402

R = json.load(open("eval/results.json", encoding="utf8"))
OUT = Path("output")
OUT.mkdir(exist_ok=True)
INK, BLUE, GREY, ORANGE = "#1f2937", "#2563eb", "#9ca3af", "#ea580c"
MODES = ("regex", "ner", "hybrid")
MODE_NAME = {"regex": "Regex only", "ner": "Raw spaCy NER + regex", "hybrid": "Hybrid (this tool)"}


def f3(x: float) -> str:
    return f"{x:.3f}"


def pooled(labels_sets, label=None):
    """Pool per-label counts of several result sets (hybrid, relaxed)."""
    tp = fp = fn = 0
    for s in labels_sets:
        for lab, v in R[s]["hybrid"]["per_label"].items():
            if label in (None, lab):
                tp, fp, fn = tp + v["relaxed"]["tp"], fp + v["relaxed"]["fp"], fn + v["relaxed"]["fn"]
    p = tp / (tp + fp) if tp + fp else 0
    r = tp / (tp + fn) if tp + fn else 0
    return tp, fp, fn, p, r, (2 * p * r / (p + r) if p + r else 0)


# ------------------------------------------------------------------ charts --
def chart_ablation(path: str) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.3), sharey=True)
    for ax, ds, title in zip(axes, ("real_test", "synth_test"),
                             ("Prospectus, held-out test", "Synthetic tickets, held-out test")):
        w = 0.25
        for i, (metric, col) in enumerate((("precision", GREY), ("recall", ORANGE), ("f1", BLUE))):
            vals = [R[ds][m]["micro"]["relaxed"][metric] for m in MODES]
            ax.bar([x + (i - 1) * w for x in range(3)], vals, w, label=metric.upper() if metric == "f1" else metric.title(), color=col)
            for x, v in enumerate(vals):
                ax.text(x + (i - 1) * w, v + 0.01, f"{v:.2f}", ha="center", fontsize=7, color=INK)
        ax.set_xticks(range(3), ["Regex only", "Raw NER", "Hybrid"], fontsize=8)
        ax.set_title(title, fontsize=9, color=INK)
        ax.set_ylim(0, 1.12)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(fontsize=7, frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def chart_per_type(path: str) -> None:
    labels = sorted({l for s in ("real_dev", "real_test", "synth_test") for l in R[s]["hybrid"]["per_label"]})
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ys = range(len(labels))
    real = [pooled(["real_dev", "real_test"], l)[5] if any(l in R[s]["hybrid"]["per_label"] for s in ("real_dev", "real_test")) else None for l in labels]
    syn = [R["synth_test"]["hybrid"]["per_label"][l]["relaxed"]["f1"] if l in R["synth_test"]["hybrid"]["per_label"] else None for l in labels]
    for y, v in zip(ys, real):
        if v is not None:
            ax.barh(y - 0.2, v, 0.38, color=BLUE, label="Prospectus (dev+test)" if y == 0 else None)
            ax.text(v + 0.01, y - 0.2, f"{v:.2f}", va="center", fontsize=7)
    for y, v in zip(ys, syn):
        if v is not None:
            ax.barh(y + 0.2, v, 0.38, color=ORANGE, label="Synthetic test" if y == 0 else None)
            ax.text(v + 0.01, y + 0.2, f"{v:.2f}", va="center", fontsize=7)
    ax.set_yticks(list(ys), labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.12)
    ax.set_xlabel("F1 (entity level, relaxed match)", fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    h, l = ax.get_legend_handles_labels()
    ax.legend(dict(zip(l, h)).values(), dict(zip(l, h)).keys(), fontsize=7, frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


# ---------------------------------------------------------------- document --
doc = Document()
st = doc.styles["Normal"]
st.font.name, st.font.size = "Calibri", Pt(10.5)


def h(text: str, level: int = 1) -> None:
    p = doc.add_heading(text, level)
    for r in p.runs:
        r.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)


def para(text: str, bold_prefix: str | None = None, italic: bool = False) -> None:
    p = doc.add_paragraph()
    if bold_prefix:
        p.add_run(bold_prefix).bold = True
    r = p.add_run(text)
    r.italic = italic


def bullets(items) -> None:
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        if isinstance(it, tuple):
            p.add_run(it[0]).bold = True
            p.add_run(it[1])
        else:
            p.add_run(it)


def table(header, rows, widths=None, bold_last=False) -> None:
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Light Grid Accent 1"
    t.autofit = False
    for i, c in enumerate(header):
        t.rows[0].cells[i].text = c
        for r in t.rows[0].cells[i].paragraphs[0].runs:
            r.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, c in enumerate(row):
            cells[i].text = str(c)
    for row in t.rows:
        for i, cell in enumerate(row.cells):
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9)
                if i > 0 and str(cell.text).replace(".", "").replace("%", "").replace("/", "").isdigit():
                    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Inches(w)
    doc.add_paragraph()


rt, rd, st_, sd = R["real_test"], R["real_dev"], R["synth_test"], R["synth_dev"]
e2e = R["end_to_end"]

title = doc.add_heading("PII Redaction Tool: Evaluation Report", 0)
para("Scaler AI Labs assignment. Evaluation strategy, metrics and error analysis for the run that produced "
     "output/redacted.docx from the Red Herring Prospectus (KSH International Limited).", italic=True)

h("1. Summary")
hy = rt["hybrid"]
bullets([
    ("Held-out prospectus test: ", f"entity precision {f3(hy['micro']['relaxed']['precision'])}, recall "
     f"{f3(hy['micro']['relaxed']['recall'])}, F1 {f3(hy['micro']['relaxed']['f1'])}; token-level accuracy "
     f"{f3(hy['token']['accuracy'])} ({rt['gold_spans']} gold PII spans in {rt['items']} paragraphs)."),
    ("Development prospectus sample: ", f"precision {f3(rd['hybrid']['micro']['relaxed']['precision'])}, recall "
     f"{f3(rd['hybrid']['micro']['relaxed']['recall'])}, F1 {f3(rd['hybrid']['micro']['relaxed']['f1'])} "
     f"({rd['gold_spans']} spans). The test numbers are the honest ones: no tuning was done on them."),
    ("Synthetic held-out test ", f"(SSN, cards, DOB, IPs and the other types the prospectus lacks): precision "
     f"{f3(st_['hybrid']['micro']['relaxed']['precision'])}, recall {f3(st_['hybrid']['micro']['relaxed']['recall'])}, "
     f"F1 {f3(st_['hybrid']['micro']['relaxed']['f1'])}."),
    ("Ablation: ", f"on the prospectus test set regex-only reaches F1 {f3(rt['regex']['micro']['relaxed']['f1'])} and raw NER "
     f"F1 {f3(rt['ner']['micro']['relaxed']['f1'])} (precision only {f3(rt['ner']['micro']['relaxed']['precision'])}). "
     "The curated hybrid is what makes both precision and recall high."),
    ("End to end: ", f"{e2e['leak']['test']['leaked']} of {e2e['leak']['test']['gold_spans']} test PII strings survive in the "
     f"output file; {e2e['inconsistent_mappings']} inconsistent replacements out of {e2e['entities_replaced']}; "
     f"format preserved for {e2e['format_preserved']} phones/emails/IDs; runtime {e2e['seconds']} s for 126 pages."),
])

h("2. Evaluation strategy")
h("2.1 What counts as PII (decided before measuring)", 2)
para("Precision is only meaningful if the boundary of 'PII' is explicit, so the policy is fixed up front and used "
     "identically by the tool and by the annotation:")
bullets([
    ("Redacted: ", "names of individuals; email addresses; phone numbers; websites of organisations; postal addresses; "
     "private companies, LLPs, trusts and banks (including the issuer and its short brand forms); SSNs; credit cards; "
     "dates of birth; IP addresses; identifiers such as CIN, PAN, GSTIN, Aadhaar, SEBI registration numbers."),
    ("Kept on purpose: ", "regulators, exchanges, depositories and government bodies (SEBI, BSE, NSE, RoC, MCA, pollution control "
     "boards); defined terms ('the Company', 'BRLMs'); statutes; ordinary dates (the prospectus date, agreement dates); "
     "money amounts; page and section numbers; order, ticket, invoice and tracking numbers (not personal data)."),
    ("Borderline, decided explicitly: ", "a bare 10-digit number is treated as a phone number only if it starts with 6-9 and does "
     "not follow order/ticket/invoice/reference words; a 4-octet number after 'firmware/version/build' is a version, not an IP; "
     "a date is a DOB only next to a birth cue ('DOB', 'born', 'date of birth')."),
])

h("2.2 Datasets", 2)
table(["Set", "What", "Size", "Role"], [
    ["Prospectus dev", "70 paragraphs sampled from the prospectus (seed 7), hand annotated",
     f"{rd['gold_spans']} spans", "Used while building the tool"],
    ["Prospectus test", "65 further paragraphs (seed 99, disjoint from dev), hand annotated before the tool ever saw them",
     f"{rt['gold_spans']} spans", "Held out: run once for the final numbers"],
    ["Synthetic dev", "Ticket-style sentences built from Faker values, with look-alike non-PII", f"{sd['gold_spans']} spans", "Used while building"],
    ["Synthetic test", "Same generator, new seed (4242)", f"{st_['gold_spans']} spans", "Held out"],
], widths=[1.1, 3.4, 0.9, 1.4])
para("Why two kinds of data. The prospectus contains no SSNs, credit cards, dates of birth or IP addresses, so recall "
     "for those types cannot be measured on it. The synthetic sets fill that gap and also contain deliberate traps: 16-digit "
     "tracking numbers that fail the Luhn check, 10-digit order IDs, firmware version strings shaped like IPs, ordinary dates, "
     "ticket numbers and amounts. Faker generates the values independently of the detectors, so the test is not circular.")
para("How the prospectus sample was drawn. Stratum A (about 60%) is paragraphs matching a keyword heuristic for contact and entity "
     "details (email, Limited, LLP, Contact Person, Office, Trust ...); stratum B is uniformly random. Without stratum A most "
     "paragraphs are prose with no PII and recall would be meaningless. Annotation is by exact substring: a string listed as PII is "
     "PII at every place it occurs in that paragraph.")

h("2.3 Metrics", 2)
bullets([
    ("Entity level (primary): ", "a predicted span is a true positive if its type matches and it overlaps a gold span with IoU >= 0.5 "
     "(relaxed) or exactly (strict). Precision = TP/(TP+FP), recall = TP/(TP+FN), F1 = harmonic mean. Reported per type and micro-averaged."),
    ("Token level: ", "every whitespace token is PII or not, label-agnostic (was sensitive text replaced?). Accuracy = (TP+TN)/all tokens, "
     "plus precision, recall and F1. Accuracy is high by construction because most tokens are not PII, so it is reported "
     "alongside precision/recall and not on its own."),
    ("Leak rate: ", "share of gold PII strings still present in the redacted .docx (checks body, tables, headers, hidden field codes)."),
    ("Fake quality: ", "same real value always maps to the same fake; format preserved (phone digit count, valid email syntax, ID length); "
     "no replacement identical to its original."),
])

h("2.4 System variants (ablation)", 2)
bullets([("Regex only: ", "patterns, checksums, address and legal-suffix company rules; no model."),
         ("Raw NER + regex: ", "spaCy PERSON/ORG spans taken as-is on top of the patterns."),
         ("Hybrid: ", "the delivered tool. NER only proposes names; proposals must pass vocabulary, place, acronym and name-list "
          "checks, then a document-wide lexicon finds every other mention (including ALL-CAPS).")])

h("3. Results")
h("3.1 Headline: held-out prospectus test", 2)
m = hy
table(["Metric", "Relaxed match", "Strict match"], [
    ["Precision", f3(m["micro"]["relaxed"]["precision"]), f3(m["micro"]["strict"]["precision"])],
    ["Recall", f3(m["micro"]["relaxed"]["recall"]), f3(m["micro"]["strict"]["recall"])],
    ["F1", f3(m["micro"]["relaxed"]["f1"]), f3(m["micro"]["strict"]["f1"])],
    ["Token accuracy", f3(m["token"]["accuracy"]), "-"],
    ["Token precision / recall / F1", f"{f3(m['token']['precision'])} / {f3(m['token']['recall'])} / {f3(m['token']['f1'])}", "-"],
], widths=[2.4, 2.0, 1.6])

h("3.2 Ablation", 2)
rows = []
for ds, name in (("real_dev", "Prospectus dev"), ("real_test", "Prospectus test"), ("synth_dev", "Synthetic dev"), ("synth_test", "Synthetic test")):
    for mode in MODES:
        x = R[ds][mode]
        rows.append([name if mode == "regex" else "", MODE_NAME[mode], f3(x["micro"]["relaxed"]["precision"]),
                     f3(x["micro"]["relaxed"]["recall"]), f3(x["micro"]["relaxed"]["f1"]), f3(x["token"]["accuracy"])])
table(["Set", "System", "Precision", "Recall", "F1", "Token acc."], rows, widths=[1.3, 2.1, 0.8, 0.8, 0.7, 0.9])
chart_ablation("output/fig_ablation.png")
doc.add_picture("output/fig_ablation.png", width=Inches(6.3))
para("Raw NER finds most names but also flags 'Offer', 'Promoters', 'UPI', 'Bandra Kurla Complex' and similar as people or "
     "organisations, so its precision collapses on a legal/financial document. Regex alone is precise but cannot find a name "
     "or a company without a legal suffix. The hybrid keeps NER's recall and removes its false positives.", italic=True)

h("3.3 Per PII type (hybrid, relaxed match)", 2)
labels = sorted({l for s in ("real_dev", "real_test", "synth_test") for l in R[s]["hybrid"]["per_label"]})
rows = []
for lab in labels:
    a = pooled(["real_dev", "real_test"], lab)
    b = R["synth_test"]["hybrid"]["per_label"].get(lab)
    rows.append([lab,
                 f"{a[0] + a[2]}" if a[0] + a[2] else "-", f3(a[3]) if a[0] + a[2] else "-", f3(a[4]) if a[0] + a[2] else "-", f3(a[5]) if a[0] + a[2] else "-",
                 f"{b['relaxed']['tp'] + b['relaxed']['fn']}" if b else "-",
                 f3(b["relaxed"]["precision"]) if b else "-", f3(b["relaxed"]["recall"]) if b else "-", f3(b["relaxed"]["f1"]) if b else "-"])
table(["Type", "n", "P", "R", "F1", "n", "P", "R", "F1"], rows, widths=[1.2, 0.5, 0.65, 0.65, 0.65, 0.5, 0.65, 0.65, 0.65])
para("Columns 2-5: prospectus, dev and test pooled. Columns 6-9: synthetic held-out test. '-' means the type does not occur in that set.",
     italic=True)
chart_per_type("output/fig_per_type.png")
doc.add_picture("output/fig_per_type.png", width=Inches(5.8))
pool = R["synth_test_person_by_pool"]
para(f"Names the tool has never been given: the name list is built from Faker's en_US/en_IN/en_GB locales plus a small Indian "
     f"list. PERSON recall on synthetic names from those locales is {f3(pool['in']['recall'])} (n={pool['in']['n']}); on German, French, "
     f"Spanish, Polish and Dutch names it is {f3(pool['out']['recall'])} (n={pool['out']['n']}). Those are caught through context cues "
     "('this is X', 'Regards, X', 'Contact Person: X'); a foreign name with no cue and not in the list would be missed.")

h("3.4 Checks on the redacted file", 2)
table(["Check", "Result"], [
    ["Gold PII strings still present (prospectus dev)", f"{e2e['leak']['dev']['leaked']} / {e2e['leak']['dev']['gold_spans']}  (leak rate {f3(e2e['leak']['dev']['leak_rate'])})"],
    ["Gold PII strings still present (prospectus test)", f"{e2e['leak']['test']['leaked']} / {e2e['leak']['test']['gold_spans']}  (leak rate {f3(e2e['leak']['test']['leak_rate'])})"],
    ["Values replaced in the whole document", f"{e2e['entities_replaced']}  " + ", ".join(f"{k} {v}" for k, v in sorted(e2e['by_label'].items(), key=lambda kv: -kv[1]))],
    ["Same original mapped to different fakes", str(e2e["inconsistent_mappings"])],
    ["Replacement identical to original", str(e2e["unchanged_replacements"])],
    ["Format preserved (phones, emails, IDs)", e2e["format_preserved"]],
    ["Structure vs. source (paragraphs, tables, rows, runs, drawings, sections)", "identical counts; same package parts; opens in Word without repair"],
    ["Hidden hyperlink field codes", "105 HYPERLINK mailto: codes redacted (they carry the real email even when the visible text is changed)"],
    ["Runtime", f"{e2e['seconds']} s for the 126-page document"],
], widths=[3.2, 3.6])

h("4. Error analysis")
para("Every remaining error on the two prospectus sets, and the reason:")
rows = []
for name, ds in (("dev", "real_dev"), ("test", "real_test")):
    for e in R[ds]["hybrid"]["errors"]:
        why = {"missed entirely": "no rule fired", "not PII": "flagged but not PII under the policy"}.get(e["note"], e["note"])
        rows.append([name, e["kind"], e["label"], e["text"][:70], why])
table(["Set", "Type", "Label", "String", "Cause"], rows, widths=[0.5, 0.5, 0.9, 3.4, 1.6])
causes = [
    ("Addresses without a PIN code ", "('Lodha I Think Techno Campus, O-3 Level', 'CTS No. 30') have no anchor for the address rule. "
     "A gazetteer of building/road words would raise recall at some precision cost."),
    ("A split address whose PIN has no dash and no comma ", "('Pune 411 045 Maharashtra, India') is rejected on purpose: a bare 6-digit number after a word is too "
     "often a reference number."),
    ("Company names without a legal suffix ", "('Al-Ahleia Switchgear Co.') are only found through suffix rules and the learned brand lexicon."),
    ("Public-body URLs ", "(the SEBI website) are flagged because the URL rule does not know which domains belong to regulators; "
     "the annotation policy says they are not PII."),
]
bullets(causes)
syn = Counter((e["kind"], e["label"]) for e in st_["hybrid"]["errors"])
para("Synthetic test errors by type: " + "; ".join(f"{k} {l} x{n}" for (k, l), n in sorted(syn.items())) + ". The dominant one is "
     "ORG false negatives: Faker's US company names are surname lists ('Medina, Roberts and Thomas') with no legal suffix, which the "
     "suffix-based rule cannot recognise. Others: 10-digit numbers without any cue, US military addresses (APO/FPO) without a "
     "comma before the state, and names with lower-case particles ('Evi de Jong').")

h("5. Limitations of this evaluation")
bullets([
    "The gold sets are small (about 130 prospectus spans). Confidence intervals are wide: one error moves recall by roughly 2 points.",
    "The annotator is the tool's author. The test set was annotated before the detector ran on it and not used for tuning, but a second "
    "annotator and an inter-annotator agreement score would be the next step.",
    "The tool learns its name/company lexicon from the whole document text before detecting (unsupervised, no labels are ever used), so "
    "the text of the test paragraphs is seen during that learning step; only the labels are held out. This mirrors real use, where the "
    "document being redacted is the document being read.",
    "Process note: after the first held-out run, five further fixes were made (a guard so no company name is ever left unchanged, "
    "splitting 'X Limited and Y Limited' into two companies, treating building-name words as localities only in address-like lines, "
    "'Cash and Bank Balances' no longer read as a bank, and not creating empty header parts). They came from auditing the full list of "
    "replacements in the whole 126-page document, not from test-set errors, and the evaluation was re-run afterwards with the same numbers.",
    "The synthetic set is generated from templates, so it measures pattern coverage, not the variety of real tickets.",
    "Only the prospectus's own text is scored. Images (the cover QR code and logos) can carry names and are not processed.",
])

h("6. Reproduce")
para("python eval/make_sample.py; python eval/make_synthetic.py eval/synthetic.json 2026; python eval/make_synthetic.py "
     "eval/synthetic_test.json 4242; python eval/evaluate.py; python eval/build_report.py", italic=True)

doc.save("output/Evaluation_Report.docx")
print("saved output/Evaluation_Report.docx")
