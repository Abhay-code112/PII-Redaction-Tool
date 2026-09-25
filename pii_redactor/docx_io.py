"""Read and rewrite paragraph text in a .docx without losing formatting.

Text in Word is split across many <w:t> nodes (runs, hyperlinks, fields).
Each paragraph is treated as one string; edits are applied to the underlying
nodes so bold/italic/fonts on untouched text stay exactly as they were.
"""
from collections import Counter
from dataclasses import dataclass, field

from docx import Document
from docx.oxml.ns import qn

from .clean import clean_text

W_P, W_T = qn("w:p"), qn("w:t")
W_TAB, W_BR, W_CR = qn("w:tab"), qn("w:br"), qn("w:cr")
W_INSTR = qn("w:instrText")
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@dataclass
class _Segment:
    start: int
    text: str
    node: object | None  # None for read-only pieces such as tabs


@dataclass
class ParagraphText:
    element: object
    segments: list[_Segment] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.segments)

    def apply(self, edits: list[tuple[int, int, str]]) -> None:
        """Replace [start, end) with new text; edits must not overlap."""
        for start, end, new in sorted(edits, reverse=True):
            placed = False
            for seg in self.segments:
                seg_end = seg.start + len(seg.text)
                if seg.node is None or seg_end <= start or seg.start >= end:
                    continue
                lo, hi = max(start, seg.start) - seg.start, min(end, seg_end) - seg.start
                seg.text = seg.text[:lo] + (new if not placed else "") + seg.text[hi:]
                placed = True
        for seg in self.segments:
            if seg.node is not None:
                seg.node.text = seg.text
                seg.node.set(XML_SPACE, "preserve")


def _walk(el):
    """Yield text-bearing nodes of one paragraph, skipping nested paragraphs
    (text boxes) which are visited as paragraphs in their own right."""
    for child in el:
        if child.tag == W_P:
            continue
        yield child
        yield from _walk(child)


def _read(p_el, stats: Counter) -> ParagraphText:
    para = ParagraphText(p_el)
    pos = 0
    for node in _walk(p_el):
        if node.tag == W_T:
            txt = clean_text(node.text or "", stats)
            para.segments.append(_Segment(pos, txt, node))
        elif node.tag == W_TAB:
            txt = "\t"
            para.segments.append(_Segment(pos, txt, None))
        elif node.tag in (W_BR, W_CR):
            txt = "\n"
            para.segments.append(_Segment(pos, txt, None))
        else:
            continue
        pos += len(txt)
    return para


def load(path: str):
    return Document(path)


def _roots(doc) -> list:
    """Body plus every header/footer that really exists. Touching a header python-docx has
    no definition for would create an empty one, so linked (inherited) ones are skipped."""
    roots = [doc.element.body]
    for sec in doc.sections:
        for part in (sec.header, sec.footer, sec.first_page_header,
                     sec.first_page_footer, sec.even_page_header, sec.even_page_footer):
            if not part.is_linked_to_previous:
                roots.append(part._element)
    return roots


def iter_paragraphs(doc, stats: Counter | None = None) -> list[ParagraphText]:
    """Every paragraph in body, tables (nested too), text boxes, headers, footers."""
    stats = stats if stats is not None else Counter()
    seen, paras = set(), []
    for root in _roots(doc):
        for p in root.iter(W_P):
            if id(p) in seen:
                continue
            seen.add(id(p))
            paras.append(_read(p, stats))
    for para in paras:  # write the cleaned text back so offsets match the file
        para.apply([])
    return paras


def iter_field_codes(doc) -> list[ParagraphText]:
    """HYPERLINK "mailto:..." field codes: invisible on the page but they still
    carry the real address, so they are redacted as well."""
    seen, out = set(), []
    for root in _roots(doc):
        for node in root.iter(W_INSTR):
            if id(node) in seen or not node.text:
                continue
            seen.add(id(node))
            out.append(ParagraphText(node, [_Segment(0, node.text, node)]))
    return out


def scrub_metadata(doc, replacements: dict[str, str]) -> None:
    """Document properties often carry author names."""
    props = doc.core_properties
    for attr, value in replacements.items():
        setattr(props, attr, value)
