"""Regex detectors for PII that has a checkable shape.

Adding a new type is one entry in PATTERN_DETECTORS (plus a faker in fakes.py).
Where a format has a checksum (cards, Aadhaar) it is verified, which is what
keeps random long numbers in financial tables from being flagged.
"""
import re
from dataclasses import dataclass
from typing import Callable, Iterator

from ..spans import Span

MONTHS = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
          r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
DATE = (rf"(?:\d{{1,2}}[/.-]\d{{1,2}}[/.-]\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}"
        rf"|\d{{1,2}}(?:st|nd|rd|th)?[ -]{MONTHS}\.?,?[ -]\d{{4}}"
        rf"|{MONTHS}\.? \d{{1,2}}(?:st|nd|rd|th)?,? \d{{4}})")


# ---- validators ----------------------------------------------------------

def luhn_ok(s: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", s)]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    if digits[0] not in (2, 3, 4, 5, 6) and digits[:4] != [1, 8, 0, 0]:   # 1800 = legacy JCB; nothing else starts 0/1/7/8/9
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


_VD = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
       [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
       [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
       [9,8,7,6,5,4,3,2,1,0]]
_VP = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
       [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
       [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]


def verhoeff_ok(s: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(re.sub(r"\D", "", s))):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return c == 0


def phone_digits_ok(s: str) -> bool:
    return 8 <= len(re.sub(r"\D", "", s)) <= 15


def aadhaar_ok(s: str) -> bool:
    d = re.sub(r"\D", "", s)
    return len(d) == 12 and d[0] in "23456789" and verhoeff_ok(d)


# ---- detector ------------------------------------------------------------

@dataclass(frozen=True)
class RegexDetector:
    label: str
    pattern: re.Pattern
    priority: int
    group: int = 0
    validate: Callable[[str], bool] | None = None
    not_after: re.Pattern | None = None     # skip when the text just before matches (e.g. "firmware 1.2.3.4")

    def find(self, text: str) -> Iterator[Span]:
        for m in self.pattern.finditer(text):
            start, end = m.span(self.group)
            if start < 0:
                continue
            if self.validate and not self.validate(m.group(self.group)):
                continue
            if self.not_after and self.not_after.search(text[max(0, start - 30):start]):
                continue
            yield Span(start, end, self.label, self.priority)


def _d(label, regex, priority, flags=0, **kw) -> RegexDetector:
    return RegexDetector(label, re.compile(regex, flags), priority, **kw)


_VERSION_CUE = re.compile(r"\b(?:v|ver|version|firmware|build|release|rev|patch|sdk|api|python|java|node)\.?\s*$", re.I)
_ID_CUE = re.compile(r"(?:order|ticket|invoice|awb|tracking|txn|transaction|ref|reference|case|\bid|#)\s*(?:id|no|number)?\.?\s*[:#-]?\s*$", re.I)
_PHONE_CUE = (r"(?:tel(?:ephone)?|phone|mobile|mob|fax|whatsapp|call(?:\s+me)?(?:\s+(?:on|at))?|"
              r"reach(?:\s+me)?(?:\s+at)?|contact\s+(?:no|number))\.?\s*(?:no\.?)?\s*[:\-–]?\s*")

PATTERN_DETECTORS: list[RegexDetector] = [
    _d("EMAIL", r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", 100),
    _d("URL", r"\b(?:https?://|www\.)[^\s<>\"')\];,]*[^\s<>\"')\].;,:]", 90),
    _d("URL", r"(?<![@\w.-])[a-z0-9-]{3,}\.(?:com|co\.in|in|org|net|io|edu|gov\.in)\b(?![\w@])", 88,
       flags=re.I),

    # Indian & general identifiers
    _d("ID_NUMBER", r"\b[LU]\d{5}[A-Z]{2}\d{4}(?:PLC|PTC|FTC|GAP|GAT|NPL|SGC|ULT|OPC)\d{6}\b", 85),
    _d("ID_NUMBER", r"\b[A-Z]{5}\d{4}[A-Z]\b", 85),
    _d("ID_NUMBER", r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", 85),
    _d("ID_NUMBER", r"\bIN[A-Z]\d{9}\b", 85),
    _d("ID_NUMBER", r"\b(?i:registration|membership|licen[cs]e)\s+(?i:no\.?|number)\s*[:.]?\s*([A-Z]{0,4}-?\d{4,9})\b", 83, group=1),
    _d("AADHAAR", r"(?<![\d-])[2-9]\d{3}[ -]\d{4}[ -]\d{4}(?![\d-])", 84, validate=aadhaar_ok),
    _d("AADHAAR", r"(?:aadhaar|aadhar|uidai?)\b[^\d\n]{0,25}?([2-9]\d{11})(?!\d)", 84, flags=re.I, group=1,
       validate=aadhaar_ok),

    _d("SSN", r"(?<![\d-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d-])", 82),
    _d("SSN", r"(?:\bssn|social\s+security)\b[^\d\n]{0,25}?(\d{9})(?!\d)", 82, flags=re.I, group=1),
    _d("CREDIT_CARD", r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])", 80, validate=luhn_ok),
    _d("IP_ADDRESS", r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
                      r"(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d]|\.\d)", 78, not_after=_VERSION_CUE),
    _d("IP_ADDRESS", r"(?<![\w:])(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}(?![\w:])", 78),
    _d("IP_ADDRESS", r"(?<![\w:])(?:[0-9A-Fa-f]{1,4}:){1,6}:(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4}){0,5})?(?![\w:])", 77),

    _d("DOB", rf"(?:\bd\.?o\.?b\.?|date\s+of\s+birth|\bborn(?:\s+on)?)\b[\s:.,-]*({DATE})", 72,
       flags=re.I, group=1),

    _d("PHONE", r"(?<![\w.])\+\s?\d{1,3}(?:[\s.-]?\(?\d{1,5}\)?){2,4}(?!\d)", 60, validate=phone_digits_ok),
    _d("PHONE", rf"(?i:{_PHONE_CUE})(\+?\(?\d[\d\s().-]{{6,17}}\d)", 59, group=1, validate=phone_digits_ok),
    _d("PHONE", r"(?<![\d.,-])(?:0|\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?![\d,]|\.\d)", 58, not_after=_ID_CUE),
    # North American numbering plan: area code 2-9xx, exchange 2-9xx, optional extension
    _d("PHONE", r"(?<![\w.,-])(?:(?:\+?1|001)[\s.-]?)?(?:\([2-9]\d{2}\)\s?|[2-9]\d{2}[\s.-])[2-9]\d{2}[\s.-]\d{4}"
                r"(?:\s?(?:x|ext\.?)\s?\d{1,6})?(?![\d-])", 57, not_after=_ID_CUE),
    _d("PHONE", r"(?<![\w.,-])(?:\+?1|001)[\s.-][2-9]\d{2}[\s.-][2-9]\d{2}[\s.-]\d{4}(?:\s?(?:x|ext\.?)\s?\d{1,6})?(?![\d-])", 57),
]
