"""Image-redaction check on the two ID-card photos that are embedded in the prospectus.

Text fields were transcribed by reading the cards. A field counts as *covered* if OCR could read it
in the original image but can no longer read it in the redacted one. Photo, QR code and signature
were checked by eye (see the report figure); the face detector is also re-run on the output.
Machine readability is a proxy: it says nothing about a human squinting at a partly covered word.
"""
import io
import json
import re
import sys
import zipfile

from PIL import Image

sys.path.insert(0, ".")
from pii_redactor import images  # noqa: E402

SRC, OUT = r"D:\Red Herring Prospectus.docx", "output/redacted.docx"
FIELDS = {
    "word/media/image4.png": {                      # PAN card
        "PAN number": "NBWPS1951N", "Name": "VISHALSINGH", "Father's name": "SUGRIVSINGH", "Date of birth": "06/05/2000"},
    "word/media/image5.png": {                      # Aadhaar card
        "Name": "MERAJKHAN", "Father's name": "SudhdanKhan", "Date of birth": "12/12/1988",
        "Aadhaar number (front)": "294365933461", "Address (locality)": "KATRAULI", "Address (PIN)": "212402"},
}


def norm(s: str) -> str:
    return re.sub(r"\W", "", s).lower()


def read(zf, name) -> str:
    img = Image.open(io.BytesIO(zf.read(name)))
    return norm("".join(l.text for l in images.read_lines(img)))


def main() -> None:
    a, b = zipfile.ZipFile(SRC), zipfile.ZipFile(OUT)
    rows, readable_before, covered = [], 0, 0
    for name, fields in FIELDS.items():
        before, after = read(a, name), read(b, name)
        for label, value in fields.items():
            v = norm(value)
            was, now = v in before, v in after
            readable_before += was
            covered += was and not now
            rows.append({"image": name.split("/")[-1], "field": label, "readable_before": was, "readable_after": now})
    faces_before = sum(len(images._faces(Image.open(io.BytesIO(a.read(n))))) for n in FIELDS)
    faces_after = sum(len(images._faces(Image.open(io.BytesIO(b.read(n))))) for n in FIELDS)
    res = {"rows": rows, "fields_readable_before": readable_before, "fields_covered": covered,
           "faces_before": faces_before, "faces_after": faces_after,
           "images_in_document": len([n for n in a.namelist() if "/media/" in n])}
    json.dump(res, open("eval/results_images.json", "w"), indent=1)
    for r in rows:
        print(r)
    print({k: v for k, v in res.items() if k != "rows"})


if __name__ == "__main__":
    main()
