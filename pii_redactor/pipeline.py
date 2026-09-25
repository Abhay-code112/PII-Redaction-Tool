"""End-to-end flow: load -> clean -> learn names -> detect -> fake -> save."""
import json
from collections import Counter
from dataclasses import dataclass, field

from . import docx_io, images
from .detectors import PATTERN_DETECTORS, NameLexicon, find_addresses
from .fakes import Pseudonymizer
from .spans import Span, resolve_overlaps

MODES = ("regex", "ner", "hybrid")


@dataclass
class Policy:
    """mode: 'regex' (patterns only), 'ner' (raw spaCy) or 'hybrid' (default).
    skip_labels lets a caller leave a category untouched, e.g. {'URL'}."""
    mode: str = "hybrid"
    skip_labels: frozenset[str] = frozenset()
    seed: str = "pii-redactor"
    images: bool = True          # OCR + blank PII inside embedded pictures


@dataclass
class Report:
    entities: list[dict] = field(default_factory=list)
    cleaning: Counter = field(default_factory=Counter)
    images: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def counts(self) -> Counter:
        return Counter(e["label"] for e in self.entities)


def load_spacy():
    import spacy
    return spacy.load("en_core_web_sm", disable=["lemmatizer"])


class Redactor:
    def __init__(self, policy: Policy | None = None, nlp=None):
        self.policy = policy or Policy()
        if self.policy.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        self.nlp = nlp if nlp is not None or self.policy.mode == "regex" else load_spacy()
        self.lexicon = NameLexicon(self.nlp if self.policy.mode == "hybrid" else None)
        self.pseudo = Pseudonymizer(self.policy.seed)

    # -- pass 1: learn who is in this document ---------------------------------
    def fit(self, texts: list[str]) -> None:
        if self.policy.mode == "hybrid":
            self.lexicon.learn(texts)
            self.pseudo = Pseudonymizer(self.policy.seed, self.lexicon.all_person_tokens | self.lexicon.org_core)
        else:
            self.lexicon.lower_vocab = set()

    # -- pass 2: find spans ----------------------------------------------------------
    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for det in PATTERN_DETECTORS:
            spans.extend(det.find(text))
        spans.extend(find_addresses(text))
        mode = self.policy.mode
        if mode == "hybrid":
            spans.extend(self.lexicon.person_spans(text))
            spans.extend(self.lexicon.org_spans(text))
            spans.extend(self.lexicon.locality_spans(text))
        elif mode == "regex":
            spans.extend(NameLexicon.org_spans_by_suffix(text))
        else:
            for ent in self.nlp(text).ents:
                if ent.label_ in ("PERSON", "ORG"):
                    spans.append(Span(ent.start_char, ent.end_char, ent.label_, 30))
        spans = [s for s in spans if s.label not in self.policy.skip_labels]
        return resolve_overlaps(spans)

    def detect_in_image_text(self, text: str) -> list[Span]:
        """OCR text has no document context, so on top of the normal detectors accept any
        capitalised name that contains a known given name/surname (a scanned ID lists a
        person nobody has mentioned in the body text)."""
        spans = self.detect(text)
        if self.policy.mode == "hybrid":
            for run, a, b in self.lexicon._candidate_names(text, True, text, 0):
                spans.append(Span(a, b, "PERSON", 30))
        return resolve_overlaps(spans)

    # -- file level -----------------------------------------------------------------
    def redact_file(self, src, dst, audit_path: str | None = None) -> Report:
        report = Report()
        doc = docx_io.load(src)
        paras = docx_io.iter_paragraphs(doc, report.cleaning)
        self.fit([p.text for p in paras])
        fields = docx_io.iter_field_codes(doc)
        for idx, para in enumerate(paras + fields):
            text = para.text
            if not text.strip():
                continue
            edits = []
            for s in self.detect(text):
                original = text[s.start:s.end]
                fake = self.pseudo.fake(s.label, original)
                edits.append((s.start, s.end, fake))
                report.entities.append({"para": idx, "field_code": idx >= len(paras), "start": s.start, "end": s.end,
                                        "label": s.label, "original": original, "replacement": fake})
            para.apply(edits)
        if self.policy.images:
            if images.available():
                report.images = images.redact_document_images(doc, self.detect_in_image_text)
                report.warnings += [f"{r['image']}: {r['error']}" for r in report.images if "error" in r]
            else:
                report.warnings.append("Image redaction skipped: OCR packages are not installed.")
        docx_io.drop_thumbnail(doc)      # a picture of the ORIGINAL first page
        docx_io.scrub_metadata(doc, {"author": "Redacted", "last_modified_by": "Redacted",
                                     "comments": "", "keywords": ""})
        doc.save(dst)
        if audit_path:
            with open(audit_path, "w", encoding="utf8") as fh:
                json.dump(report.entities, fh, ensure_ascii=False, indent=1)
        return report
