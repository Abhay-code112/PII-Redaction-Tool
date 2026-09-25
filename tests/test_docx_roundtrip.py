"""End-to-end: build a small .docx with formatting, tables and a mailto field, redact, inspect."""
import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from pii_redactor import Policy, Redactor, docx_io


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp("docs") / "in.docx"
    doc = Document()
    p = doc.add_paragraph()
    p.add_run("Contact ").bold = True
    p.add_run("Sarthak Malvadkar").italic = True                       # name split over runs with formatting
    p.add_run(" on +91 20 4505 3237 or cs.connect@acme-industries.com.")
    doc.add_paragraph("Registered Office: 11/3, Village Birdewadi, Chakan, Pune – 410 501, Maharashtra, India;")
    doc.add_paragraph("Auditors: Kirtane & Pandit LLP audited Acme Industries Limited. Order 4471 shipped.")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Promoter: RAJESH KUSHAL HEGDE"
    table.cell(0, 1).text = "Rajesh Kushal Hegde holds 40%. Tushar Wakhele, Rajesh Hegde"
    doc.core_properties.author = "Real Author"
    run = doc.add_paragraph().add_run()                                  # invisible HYPERLINK field code
    instr = OxmlElement("w:instrText")
    instr.text = ' HYPERLINK "mailto:cs.connect@acme-industries.com" '
    run._r.append(instr)
    doc.save(path)
    return str(path)


@pytest.fixture(scope="module")
def redacted(source, tmp_path_factory):
    out = str(tmp_path_factory.mktemp("out") / "out.docx")
    report = Redactor(Policy(mode="hybrid")).redact_file(source, out)
    return out, report


def texts(path):
    doc = docx_io.load(path)
    return [p.text for p in docx_io.iter_paragraphs(doc)], [f.text for f in docx_io.iter_field_codes(doc)]


def test_original_pii_is_gone_everywhere(redacted):
    paras, fields = texts(redacted[0])
    blob = "\n".join(paras + fields)
    for secret in ("Malvadkar", "Hegde", "4505", "acme-industries", "Birdewadi", "Kirtane", "Wakhele", "Acme"):
        assert secret not in blob, secret
    assert "example.com" in blob and "Order 4471" in blob      # non-PII survives


def test_hyperlink_field_code_is_redacted(redacted):
    _, fields = texts(redacted[0])
    assert fields and all("acme" not in f and "@" in f for f in fields)


def test_same_person_gets_same_fake_across_variants(redacted):
    paras, _ = texts(redacted[0])
    table_text = "\n".join(paras)
    upper = next(p for p in paras if p.startswith("Promoter:")).split(": ")[1]
    title = next(p for p in paras if "holds 40%" in p).split(" holds")[0]
    assert upper.lower() == title.lower() and upper.isupper() and not title.isupper()


def test_formatting_survives(redacted):
    doc = Document(redacted[0])
    runs = doc.paragraphs[0].runs
    assert runs[0].bold and runs[1].italic                    # bold "Contact ", italic name
    assert "Malvadkar" not in runs[1].text and runs[1].text.strip()


def test_metadata_scrubbed_and_structure_kept(redacted, source):
    assert Document(redacted[0]).core_properties.author == "Redacted"
    assert len(Document(redacted[0]).tables) == len(Document(source).tables) == 1


def test_rerun_is_deterministic(source, tmp_path):
    a, b = str(tmp_path / "a.docx"), str(tmp_path / "b.docx")
    Redactor(Policy(seed="x")).redact_file(source, a)
    Redactor(Policy(seed="x")).redact_file(source, b)
    assert texts(a) == texts(b)


def test_regex_mode_needs_no_model(source, tmp_path):
    out = str(tmp_path / "r.docx")
    report = Redactor(Policy(mode="regex")).redact_file(source, out)
    assert report.counts["EMAIL"] >= 1 and "cs.connect@acme-industries.com" not in "".join(texts(out)[0])


def test_in_memory_streams_like_the_web_app(source):
    import io
    out = io.BytesIO()
    report = Redactor(Policy(mode="regex")).redact_file(io.BytesIO(open(source, "rb").read()), out)
    assert report.entities and Document(io.BytesIO(out.getvalue())).paragraphs
