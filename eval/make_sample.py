"""Draw the paragraphs that get hand-annotated for the real-document gold set.

Two strata so the sample is not all prose (which would make recall meaningless):
  A) paragraphs that look like they hold contact/entity details (keyword heuristic,
     deliberately independent of the detectors)
  B) uniformly random paragraphs
Seeded, so the sample is reproducible.
"""
import json
import random
import re
import sys

sys.path.insert(0, ".")
from pii_redactor import docx_io

CUES = re.compile(r"@|Limited|LLP|Private|Contact Person|Telephone|Tel\b|Office|Promoter|Registrar|Trust|"
                  r"Maharashtra|Website|CIN|Corporate Identity|Managing Director|Chairman|Auditor", re.I)


def main(src: str, out: str, n_a: int = 45, n_b: int = 25, seed: int = 7, exclude: str | None = None) -> None:
    paras = [p.text for p in docx_io.iter_paragraphs(docx_io.load(src))]
    rng = random.Random(seed)
    taken = {r["para"] for r in json.load(open(exclude, encoding="utf8"))} if exclude else set()
    idx = [i for i, t in enumerate(paras) if 25 <= len(t.strip()) <= 700 and i not in taken]
    a = rng.sample([i for i in idx if CUES.search(paras[i])], n_a)
    b = rng.sample([i for i in idx if i not in a], n_b)
    rows = [{"para": i, "stratum": "A" if i in a else "B", "text": paras[i]} for i in sorted(a + b)]
    json.dump(rows, open(out, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"{len(rows)} paragraphs -> {out}")


if __name__ == "__main__":
    doc = r"D:\Red Herring Prospectus.docx"
    main(doc, "eval/sample_paragraphs.json")                                              # dev set (used while tuning)
    main(doc, "eval/test_paragraphs.json", 40, 25, seed=99, exclude="eval/sample_paragraphs.json")  # held-out test set
