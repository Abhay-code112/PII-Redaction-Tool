# PII Redaction Tool

Reads a Word document, finds personal data, and writes a new `.docx` where every piece of PII is replaced by a
realistic but fake value. Layout, tables, headers and formatting are left as they were.

> The assignment text says "ticket log", but the attached dataset is the **Red Herring Prospectus** of KSH International
> Limited (an IPO filing, 126 pages, 76 tables). The tool works on any `.docx`; this README and the evaluation are about that file.

**Live demo:** _add your deployed link here_ · **Evaluation report:** `output/Evaluation_Report.docx`

## Run it

```bash
pip install -r requirements-dev.txt
python redact.py "Red Herring Prospectus.docx" -o output/redacted.docx    # CLI, ~10 s
streamlit run app.py                                                       # web UI (upload -> download)
pytest                                                                     # 49 tests
python eval/evaluate.py && python eval/build_report.py                     # metrics + report
```

`--mode regex` needs no model, `--skip URL ORG` leaves a category alone, `--seed` changes the fakes,
`--audit log.json` writes every replacement (that file contains the **original** PII, so it is git-ignored).

## Approach

**Hybrid: regex with validation + NER that has to earn its output + a document-wide name lexicon.**

| PII | Method |
|---|---|
| Email, IP, SSN, credit card, DOB, phone, URL | Regex plus checks: Luhn and card-prefix for cards, Verhoeff for Aadhaar, octet range for IPs, birth cue for dates, order/ticket/version cues to *reject* look-alikes |
| CIN, PAN, GSTIN, Aadhaar, SEBI reg. no. | Format regex (India-specific extras) |
| Addresses | Anchored on a PIN / ZIP code, then walked outwards to the start of the address and its state/country tail; locality names learned from those addresses are then found elsewhere |
| Companies | Legal-suffix rules (Limited, LLP, Bank, Trust ...), then their brand words are matched everywhere |
| Names | spaCy proposes candidates; a candidate is kept only if it is not a common word of this document, not a place, not an acronym, and contains a known given name/surname or initial (or follows a cue like "Contact Person:"). Accepted names go into a lexicon matched case-insensitively across the document |

Why not plain NER: on this document spaCy tags "Offer", "Promoters" and "Bandra Kurla Complex" as people and misses
ALL-CAPS headings. Its precision was 0.35 on my held-out sample; the curated version is 0.98.

**Replacement is consistent and format-preserving.** The same real value always gets the same fake (seeded hash), so the
document still makes sense: "Kushal Subbayya Hegde", "Kushal Hegde" and "KUSHAL SUBBAYYA HEGDE" map to the same fake person and
the family keeps one shared surname. An email's fake domain matches the company's fake name. Fakes come from ranges that cannot belong to a
real person: `example.com`, RFC 5737 IPs, SSN area 9xx, Aadhaar starting with 1, Luhn-valid cards.

**Also handled:** 105 hidden `HYPERLINK "mailto:..."` field codes (they keep the real address when only the visible text is
changed), text boxes, headers/footers, tracking-URL query strings, document author/last-modified-by.

## What I chose to treat as PII

Redacted: people, private companies/trusts/banks (including the issuer), emails, phones, websites, addresses, ID numbers.
**Kept:** regulators and exchanges (SEBI, BSE, NSE, RoC ...), ordinary dates, amounts, and order/ticket/invoice numbers (not personal data).
Public bodies stay because redacting them destroys the document without protecting anyone.

## Results (details and method in the evaluation report)

Hand-labelled prospectus paragraphs plus synthetic ticket text for the types the prospectus lacks (SSN, cards, DOB, IP). Dev and held-out test sets are kept separate; the test sets were not used for tuning.

| Set | Precision | Recall | F1 | Token accuracy |
|---|---|---|---|---|
| Prospectus, held-out test (45 spans) | 0.978 | 0.978 | 0.978 | 0.996 |
| Synthetic tickets, held-out test (480 spans) | 0.978 | 0.915 | 0.945 | 0.970 |
| Baselines on the prospectus test: regex only / raw NER | 0.963 / 0.349 | 0.578 / 0.844 | 0.722 / 0.493 | 0.958 / 0.872 |

## Trade-offs and errors I saw

- **False negatives:** addresses without a PIN code (`Lodha I Think Techno Campus, O-3 Level`), company names with no legal suffix
  (`Medina, Roberts and Thomas`), names outside the name list with no context cue, a bare 10-digit phone number with no cue.
- **False positives:** the URL rule redacts regulator websites too; a 4-octet version number with no "version/firmware" word before it
  looks like an IP; a 10-digit order ID starting with 6-9 and no "order" word looks like a mobile number.
- The 0.97-1.0 scores come from small gold sets (about 130 prospectus spans); expect a couple of points of noise either way.
- Images (the cover QR code, logos) are not processed.

## Extending it: a new PII type in three steps

1. **Detect:** one line in `pii_redactor/detectors/patterns.py`, e.g. an IBAN
   `_d("IBAN", r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", 81, validate=iban_ok)`
   (`validate=` for a checksum, `not_after=` for a context that rules it out).
2. **Fake:** add a method in `pii_redactor/fakes.py` and register it in `Pseudonymizer._fakers`.
3. **Test:** add cases to `tests/test_patterns.py` and, if you have labelled text, to `eval/`.

## Layout

```
redact.py            CLI                        app.py           Streamlit UI
pii_redactor/
  pipeline.py        load -> clean -> learn -> detect -> fake -> save
  docx_io.py         paragraph text <-> XML runs, headers, text boxes, field codes
  clean.py           invisible characters, non-breaking and repeated spaces
  detectors/         patterns.py (regex) · address.py · names.py (NER + lexicon)
  fakes.py           deterministic, format-preserving replacements
  data/              indian_names.txt (extra name list)
tests/               49 pytest cases        eval/   gold sets, generator, evaluation, report builder
output/              redacted.docx, Evaluation_Report.docx
```

The gold files in `eval/` contain names and addresses from the public prospectus (they have to, to score the tool);
delete them if you do not want that in a public repository.
