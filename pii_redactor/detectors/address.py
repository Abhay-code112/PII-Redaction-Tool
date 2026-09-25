"""Postal address detection, tuned for Indian addresses (PIN code anchored).

Strategy: a 6-digit PIN written the way addresses write it ("Pune - 411 045")
is a strong anchor. From there walk left to the start of the address (a label
like "Registered Office:", a semicolon or a line start) and right through an
optional state / country tail.
"""
import re
from typing import Iterator

from ..spans import Span

STATES = ("Andhra Pradesh|Arunachal Pradesh|Assam|Bihar|Chhattisgarh|Goa|Gujarat|Haryana|"
          "Himachal Pradesh|Jharkhand|Karnataka|Kerala|Madhya Pradesh|Maharashtra|Manipur|"
          "Meghalaya|Mizoram|Nagaland|Odisha|Punjab|Rajasthan|Sikkim|Tamil Nadu|Telangana|"
          "Tripura|Uttar Pradesh|Uttarakhand|West Bengal|Delhi|New Delhi|Jammu and Kashmir|"
          "Chandigarh|Puducherry|Ladakh")
CITIES = {c.lower() for c in (
    "Mumbai Pune Delhi Bengaluru Bangalore Chennai Kolkata Hyderabad Ahmedabad Surat Jaipur Lucknow Nagpur "
    "Indore Bhopal Thane Nashik Vadodara Raigad Kochi Coimbatore Gurugram Gurgaon Noida Navi Bandra Vikhroli "
    "Chandigarh Patna Kanpur Ludhiana Agra Visakhapatnam Panvel Ahmednagar Aurangabad Kolhapur").split()}
TAIL = rf"(?:\s*,?\s*(?:{STATES}))?(?:\s*,?\s*India)?"

# PIN: 6 digits (optionally split 3+3), preceded by a dash/comma and not part of a bigger number.
PIN = re.compile(r"(?<=[\-–—,] )(?<![\d,.])[1-9]\d{2} ?\d{3}(?![\d,]\d)|(?<=[\-–—,])(?<![\d,.])[1-9]\d{2} ?\d{3}(?![\d,]\d)")
US_ZIP = re.compile(r"(?<=, [A-Z]{2} )(?<!\d)\d{5}(?:-\d{4})?(?!\d)")   # "Austin, TX 78701"
# "Surat 371844": no dash, but a capitalised city right before an unbroken 6-digit PIN
PIN_BARE = re.compile(r"(?<=[A-Za-z]{3} )(?<![\d,.])[1-9]\d{5}(?!\d)")
TAIL_RE = re.compile(TAIL, re.I)
STATE_LINE = re.compile(rf"^\s*(?:{STATES})(?:\s*,?\s*India)?\s*[.;]?\s*$", re.I)
BOUNDARY = re.compile(r"[;:\n]|\b(?:at|to|from|is)\s(?=\d)|\bat\s(?=[A-Z])")
MAX_LOOKBACK = 220


def find_addresses(text: str) -> Iterator[Span]:
    if STATE_LINE.match(text):
        # "Maharashtra, India" left alone on the line after a split address
        s = len(text) - len(text.lstrip())
        yield Span(s, len(text.rstrip(" .;")), "ADDRESS", 50)
        return
    anchors = [(m, "pin") for m in PIN.finditer(text)]
    anchors += [(m, "us") for m in US_ZIP.finditer(text)]
    anchors += [(m, "bare") for m in PIN_BARE.finditer(text)]
    for m, kind in anchors:
        window_start = max(0, m.start() - MAX_LOOKBACK)
        head = text[window_start:m.start()]
        cuts = list(BOUNDARY.finditer(head))
        start = window_start + (cuts[-1].end() if cuts else 0)
        while start < m.start() and text[start] in " ,-–—\"'“‘(":
            start += 1
        chunk = text[start:m.start()]
        if len(re.findall(r"[A-Za-z]{3,}", chunk)) < 2:
            continue  # a bare number pair, not an address
        if kind != "us":
            city = re.search(r"([A-Za-z]{3,})\s*[\-–—,]?\s*$", text[:m.start()])
            if not city or (city.group(1).isupper() and len(city.group(1)) < 4):
                continue  # "TKT-542727" is a ticket number, not "Pune-411045"
        if not re.search(r"[,\d]", chunk) or (kind == "bare" and "," not in chunk):
            continue  # "Order 123456 shipped" is not "Flat 5, Andheri 400053"
        tail = TAIL_RE.match(text, m.end())
        end = tail.end() if tail else m.end()
        yield Span(start, end, "ADDRESS", 50)
