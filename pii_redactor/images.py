"""Redact PII inside pictures embedded in a Word file (ID card scans, screenshots, photos).

Text in a picture is pixels, so the text pipeline never sees it. Here:
  1. OCR reads the text lines of each image (RapidOCR, pure pip, runs on CPU);
  2. the lines are joined in reading order and go through the *same* detectors as body
     text, plus a label rule ("Name" / "Father's Name" is followed by a name line);
  3. the matching part of each line is painted over with a black box;
  4. faces are pixelated and QR codes are blanked (they often encode personal data).

Pictures where nothing is found are returned byte-for-byte unchanged. Everything degrades
gracefully: without the optional OCR packages images are skipped and a warning is reported.
A photograph cannot be given a "fake" value the way text can, so blanking is the right
replacement here.
"""
import io
import re
from dataclasses import dataclass
from typing import Callable

from .spans import Span

IMAGE_TYPES = {"image/png": "PNG", "image/jpeg": "JPEG", "image/bmp": "BMP", "image/tiff": "TIFF"}
MIN_SIDE = 48                       # skip icons and bullets
PAD = 4                             # pixels around a box, OCR boxes are tight
NAME_LABEL = re.compile(r"(?i)(?:father|mother|husband|wife|guardian)?'?s?name$")

_engine = None


def available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


def _ocr():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


@dataclass
class Line:
    text: str
    box: tuple[int, int, int, int]      # x0, y0, x1, y1
    start: int = 0                      # offset of this line in the joined text


def read_lines(img) -> list[Line]:
    import numpy as np
    result, _ = _ocr()(np.array(img.convert("RGB")))
    lines = []
    for poly, text, score in result or []:
        if float(score) < 0.5 or not text.strip():
            continue
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        lines.append(Line(text.strip(), (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))))
    lines.sort(key=lambda ln: ((ln.box[1] + ln.box[3]) // 2 // 12, ln.box[0]))   # top-to-bottom, then left-to-right
    pos = 0
    for ln in lines:
        ln.start = pos
        pos += len(ln.text) + 1
    return lines


def find_pii(lines: list[Line], detect: Callable[[str], list[Span]]) -> list[tuple[Line, int, int, str]]:
    """(line, char_from, char_to, label) for every PII fragment, in line-local offsets."""
    text = "\n".join(ln.text for ln in lines)
    found: list[tuple[Line, int, int, str]] = []
    for sp in detect(text):
        for ln in lines:
            lo, hi = max(sp.start, ln.start), min(sp.end, ln.start + len(ln.text))
            if lo < hi:
                found.append((ln, lo - ln.start, hi - ln.start, sp.label))
    for prev, nxt in zip(lines, lines[1:]):           # "Name" / "Father's Name" label, value on the next line
        if len(prev.text) <= 24 and NAME_LABEL.search(re.sub(r"\W", "", prev.text)) \
                and sum(c.isalpha() for c in nxt.text) >= 3 and not NAME_LABEL.search(re.sub(r"\W", "", nxt.text)):
            found.append((nxt, 0, len(nxt.text), "PERSON"))
    found += id_card_rules(lines, found)
    return found


def _paint(img, found, faces, qrs):
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    for ln, a, b, _ in found:
        x0, y0, x1, y1 = ln.box
        n, w = max(len(ln.text), 1), x1 - x0
        left = x0 if a == 0 else x0 + int(w * a / n)
        right = x1 if b >= n else x0 + int(w * b / n)
        draw.rectangle((left - PAD, y0 - PAD, right + PAD, y1 + PAD), fill="black")
    for x, y, w, h in faces:
        m = int(0.25 * max(w, h))
        box = (max(x - m, 0), max(y - m, 0), min(x + w + m, img.width), min(y + h + m, img.height))
        region = img.crop(box)
        small = region.resize((max(region.width // 12, 1), max(region.height // 12, 1)))
        img.paste(small.resize(region.size, resample=0), box)      # pixelate
    for poly in qrs:
        draw.polygon([tuple(map(int, p)) for p in poly], fill="black")


def _faces(img) -> list[tuple[int, int, int, int]]:
    import cv2
    import numpy as np
    gray = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    min_side = max(24, min(img.size) // 12)
    return [tuple(map(int, f)) for f in cascade.detectMultiScale(gray, 1.1, 6, minSize=(min_side, min_side))]


def _qr_codes(img) -> list:
    import cv2
    import numpy as np
    try:
        ok, pts = cv2.QRCodeDetector().detect(np.array(img.convert("RGB")))
    except Exception:
        return []
    return [p.reshape(-1, 2) for p in ([pts] if ok and pts is not None else [])]


def redact_image(data: bytes, detect: Callable[[str], list[Span]]) -> tuple[bytes, dict]:
    """Returns (new bytes, info). Bytes are unchanged when nothing was found."""
    from PIL import Image
    info = {"regions": 0, "faces": 0, "qr": 0, "labels": {}}
    img = Image.open(io.BytesIO(data))
    fmt = img.format
    if min(img.size) < MIN_SIDE or fmt not in IMAGE_TYPES.values():
        return data, info
    img.load()
    lines = read_lines(img)
    found = find_pii(lines, detect) if lines else []
    faces, qrs = _faces(img), _qr_codes(img)
    if not qrs and any(f[3] in ("ID_NUMBER", "AADHAAR", "DOB", "PERSON") for f in found):
        qrs = _qr_by_texture(img)
    info.update(regions=len(found), faces=len(faces), qr=len(qrs))
    for _, _, _, label in found:
        info["labels"][label] = info["labels"].get(label, 0) + 1
    if not (found or faces or qrs):
        return data, info
    work = img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")
    _paint(work, found, faces, qrs)
    out = io.BytesIO()
    if fmt == "JPEG":
        work.convert("RGB").save(out, "JPEG", quality=92)
    elif fmt == "PNG":
        work.save(out, "PNG")
    else:
        work.convert("RGB").save(out, fmt)
    return out.getvalue(), info


def redact_document_images(doc, detect: Callable[[str], list[Span]]) -> list[dict]:
    rows = []
    for part in doc.part.package.iter_parts():
        if part.content_type not in IMAGE_TYPES:
            continue
        try:
            new, info = redact_image(part.blob, detect)
        except Exception as exc:                    # a corrupt or exotic image must not sink the whole document
            rows.append({"image": str(part.partname), "error": str(exc)})
            continue
        if new is not part.blob:
            part._blob = new
        rows.append({"image": str(part.partname), **info})
    return rows


# ---- ID-card rules ---------------------------------------------------------
# OCR of a photographed card drops spaces and cannot read Devanagari, so plain text detection is
# not enough. Once an image looks like an identity document, these layout rules apply as well.
ID_HINT = re.compile(r"(?i)incometax|govt|governmentofindia|uniqueidentification|permanentaccount|aadhaar|"
                     r"dateofbirth|\bdob\b|male|female")
AADHAAR_LIKE = re.compile(r"(?<!\d)[2-9]\d{3}\s?\d{4}\s?\d{4}(?!\d)")     # no checksum: OCR misreads digits
FULL_DATE = re.compile(r"(?<!\d)\d{1,2}[/.-]\d{1,2}[/.-]\d{4}(?!\d)")
RELATION = re.compile(r"(?i)^(?:father|mother|husband|wife|guardian|s/?o|d/?o|w/?o|c/?o)\W*[:;\-]\s*(.+)$")
ADDRESS_LABEL = re.compile(r"(?i)^address\s*[:;\-]?\s*(.*)$")
PIN = re.compile(r"(?<!\d)\d{6}(?!\d)")
NOT_NAMES = re.compile(r"(?i)^(?:incometaxdepartment|govtofindia|governmentofindia|male|female|transgender|"
                       r"permanentaccountnumber(?:card)?|uniqueidentification\w*|signature|address|name)$")
COVER_ABOVE = 1.3                                                        # height multiples covered above a name


def _twin(ln: Line) -> tuple[Line, int, int, str]:
    """The Hindi/regional-script line printed directly above an English name: OCR cannot read it
    but it carries the same person, so the strip above is covered too."""
    x0, y0, x1, y1 = ln.box
    h = y1 - y0
    return (Line("x", (x0, max(y0 - int(COVER_ABOVE * h), 0), x1, y0)), 0, 1, "PERSON")


def id_card_rules(lines: list[Line], found: list) -> list[tuple[Line, int, int, str]]:
    flat = [re.sub(r"\W", "", ln.text) for ln in lines]
    is_id = any(ID_HINT.search(t) for t in flat) or any(f[3] in ("ID_NUMBER", "AADHAAR", "DOB") for f in found)
    if not is_id:
        return []
    extra = []
    for ln, compact in zip(lines, flat):
        if AADHAAR_LIKE.search(ln.text):
            m = AADHAAR_LIKE.search(ln.text)
            extra.append((ln, m.start(), m.end(), "AADHAAR"))
        for m in FULL_DATE.finditer(ln.text):
            extra.append((ln, m.start(), m.end(), "DOB"))
        m = RELATION.match(ln.text.strip())
        if m and sum(c.isalpha() for c in m.group(1)) >= 3:
            a = ln.text.find(m.group(1))
            extra += [(ln, a, len(ln.text), "PERSON"), _twin(ln)]
        elif compact.isalpha() and compact.isupper() and 6 <= len(compact) <= 30 and not NOT_NAMES.match(compact):
            extra += [(ln, 0, len(ln.text), "PERSON"), _twin(ln)]         # ALL-CAPS name line
    for prev, nxt in zip(lines, lines[1:]):
        if any(f[0] is nxt and f[3] == "PERSON" for f in found):
            extra.append(_twin(nxt))                                         # value under a "Name" label
    for i, ln in enumerate(lines):                                           # address block after "Address"
        if "address" not in ln.text.lower():                                # (OCR often glues the label to other text)
            continue
        extra.append((ln, 0, len(ln.text), "ADDRESS"))
        row_end = None
        for nxt in lines[i + 1:i + 7]:
            if row_end is not None and nxt.box[1] > row_end:
                break                                                        # past the row that holds the PIN
            extra.append((nxt, 0, len(nxt.text), "ADDRESS"))
            if row_end is None and PIN.search(nxt.text):
                row_end = nxt.box[3]
    for ln, compact in zip(lines, flat):                                     # handwriting cannot be OCR'd: cover its usual spot
        if "signature" in compact.lower():
            x0, y0, x1, y1 = ln.box
            w, h = x1 - x0, y1 - y0
            extra.append((Line("x", (max(x0 - int(0.9 * w), 0), max(y0 - int(3.4 * h), 0), x1, y0)), 0, 1, "SIGNATURE"))
    return extra


def _qr_by_texture(img) -> list:
    """Photographed QR codes defeat OpenCV's decoder. They are, however, the one square, uniformly
    high-edge-density block on an ID card, which is enough to find and cover them."""
    import cv2
    import numpy as np
    g = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    scale = 500 / max(g.shape) if max(g.shape) > 500 else 1.0
    g = cv2.resize(g, None, fx=scale, fy=scale) if scale != 1 else g
    edges = cv2.Canny(cv2.GaussianBlur(g, (3, 3), 0), 60, 160).astype(np.float32) / 255
    density = cv2.boxFilter(edges, -1, (11, 11))
    mask = cv2.morphologyEx((density > 0.24).astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total = g.shape[0] * g.shape[1]
    out = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if 0.02 < w * h / total < 0.25 and 0.8 < w / h < 1.25 and cv2.contourArea(c) / (w * h) > 0.7:
            r = 1 / scale
            out.append(np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]]) * r)
    return out
