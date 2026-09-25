"""Replacement values.

Rules the fakes follow:
  * deterministic: the same real value always gets the same fake (seeded hash),
    so a document stays internally consistent and reruns are reproducible;
  * format-preserving: "+91 22 3075 2929" stays shaped like a phone number;
  * safe: fakes come from ranges that cannot belong to a real person
    (RFC 5737 IPs, example.com domains, SSN areas 900-999, Aadhaar starting 1).

Names are mapped token by token, so "Kushal Hegde" and "KUSHAL SUBBAYYA HEGDE"
share fakes and family surnames stay shared.
"""
import hashlib
import random
import re
from datetime import date, timedelta

from faker import Faker

from .detectors.address import STATES
from .detectors.names import DESCRIPTORS, TRIM, WORD, _norm, is_roman

FUNCTIONAL_MAILBOX = {"cs", "ipo", "investor", "investors", "grievance", "grievances", "info",
                      "support", "contact", "connect", "compliance", "secretarial", "legal",
                      "ir", "mbd", "ecm", "care", "help", "admin", "sales", "hr", "mail", "email"}
STATE_CODES = ["MH", "GJ", "KA", "TN", "DL", "UP", "WB", "RJ", "MP", "AP", "TS", "HR", "PN"]
CC3 = {"971", "966", "880", "977", "974", "965", "973", "968", "353", "852", "886"}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
MONTH_RE = "|".join(m[:3] for m in MONTH_NAMES)


def _keep_case(src: str, fake: str) -> str:
    if src.isupper() and len(src) > 1:
        return fake.upper()
    if src.islower():
        return fake.lower()
    return fake


def _fill_digits(template: str, digits: str) -> str:
    it = iter(digits)
    return "".join(next(it) if ch.isdigit() else ch for ch in template)


class Pseudonymizer:
    def __init__(self, seed: str = "pii-redactor", real_tokens: set[str] | None = None):
        self.seed = seed
        self._faker = Faker("en_IN")
        self._words: dict[str, str] = {}      # real token -> fake token (names and brands)
        self._cache: dict[tuple, str] = {}
        self._taken: set[str] = set(real_tokens or ())
        self._person_tokens = set(real_tokens or ())
        self._fakers = {
            "PERSON": self.person, "ORG": self.org, "LOCALITY": self.org, "EMAIL": self.email, "URL": self.url,
            "PHONE": self.phone, "ADDRESS": self.address, "SSN": self.ssn,
            "CREDIT_CARD": self.credit_card, "DOB": self.dob, "IP_ADDRESS": self.ip,
            "ID_NUMBER": self.id_number, "AADHAAR": self.aadhaar,
        }

    # ---- public -----------------------------------------------------------
    def fake(self, label: str, original: str) -> str:
        # ALL-CAPS and Title Case mentions of one entity share word-level fakes but keep their own casing
        key = (label, re.sub(r"\s+", " ", original.strip().lower()), original.isupper())
        if key not in self._cache:
            self._cache[key] = self._fakers[label](original)
        return self._cache[key]

    def _rng(self, *parts: str) -> random.Random:
        h = hashlib.sha256("|".join((self.seed, *parts)).encode()).digest()
        return random.Random(int.from_bytes(h[:8], "big"))

    def _seeded_faker(self, rng: random.Random) -> Faker:
        self._faker.seed_instance(rng.getrandbits(32))
        return self._faker

    # ---- names and organisations -------------------------------------------
    def _word(self, token: str, kind: str = "surname") -> str:
        key = _norm(token)
        if key not in self._words:
            rng = self._rng("word", key)
            f = self._seeded_faker(rng)
            for _ in range(50):
                pool = f.first_name if kind == "first" else f.last_name
                cand = re.sub(r"[^A-Za-z]", "", pool().split()[0])
                if len(cand) >= 3 and cand.lower() not in self._taken:
                    break
            self._taken.add(cand.lower())
            self._words[key] = cand
        return _keep_case(token.strip("."), self._words[key])

    def person(self, text: str) -> str:
        words = list(WORD.finditer(text))
        out, last = [], len(words) - 1
        for i, m in enumerate(words):
            tok = m.group(0)
            if re.fullmatch(r"[A-Z]\.", tok):
                out.append((m.span(), _keep_case(tok, self._rng("init", tok).choice("ABCDEFGHJKLMNPRSTV")) + "."))
            else:
                out.append((m.span(), self._word(tok, "surname" if i == last and last > 0 else "first")))
        return self._splice(text, out)

    def org(self, text: str) -> str:
        """Swap the distinctive words of a company name, keep descriptors and legal
        suffixes ("Waterloo Industrial Park VI Private Limited" -> "Bera Industrial Park VI Private Limited")."""
        words = list(WORD.finditer(text))
        out = [(m.span(), self._word(m.group(0))) for m in words
               if _norm(m.group(0)) not in DESCRIPTORS and _norm(m.group(0)) not in TRIM
               and len(_norm(m.group(0))) >= 2 and not is_roman(_norm(m.group(0)))]
        if not out and words:                       # nothing distinctive: never leave a name unchanged
            out = [(words[0].span(), self._word(words[0].group(0)))]
        return self._splice(text, out)

    @staticmethod
    def _splice(text: str, parts: list[tuple[tuple[int, int], str]]) -> str:
        for (s, e), new in sorted(parts, reverse=True):
            text = text[:s] + new + text[e:]
        return text

    # ---- domains, emails, urls ----------------------------------------------
    def _fake_domain(self, host: str) -> str:
        labels = host.lower().split(".")
        idx = -3 if len(labels) >= 3 and labels[-2] in ("co", "gov", "ac") else -2
        base = labels[idx] if len(labels) >= abs(idx) else labels[0]
        for real in sorted(self._words, key=len, reverse=True):   # brand match: "hdfcbank" <- "hdfc"
            if len(real) >= 3 and base.startswith(real):
                return f"{self._words[real].lower()}{base[len(real):]}.example.com"
        return f"{self._word(base).lower()}.example.com"

    def email(self, text: str) -> str:
        """Every non-functional word in the local part is replaced (names, brands,
        initials); role words such as 'cs' or 'ipo' stay so the mailbox still reads
        as a role mailbox. Digits are kept."""
        local, host = text.rsplit("@", 1)

        def swap(m: re.Match) -> str:
            seg = m.group(0)
            if seg.lower() in FUNCTIONAL_MAILBOX:
                return seg
            for real in sorted(self._words, key=len, reverse=True):     # "kshinternational" <- "ksh"
                if len(real) >= 3 and seg.lower().startswith(real) and seg.lower() != real:
                    return (self._words[real] + seg[len(real):]).lower()
            return self._word(seg, "first" if m.start() == 0 else "surname").lower()

        return re.sub(r"[A-Za-z]+", swap, local) + "@" + self._fake_domain(host)

    def url(self, text: str) -> str:
        m = re.match(r"(?i)(https?://)?(www\.)?([^/\s?#]+)(.*)", text, re.S)
        scheme, www, host, rest = m.groups("")
        rest = re.sub(r"\?.*", "", rest, flags=re.S)     # tracking/redirect parameters embed the real domain
        return f"{scheme}{www}{self._fake_domain(host)}{rest}"

    # ---- numbers ------------------------------------------------------------
    def phone(self, text: str) -> str:
        digits = re.sub(r"\D", "", text)
        rng = self._rng("phone", digits)
        keep = 0
        if text.lstrip().startswith("+") or (digits.startswith("91") and len(digits) == 12):
            keep = 3 if digits[:3] in CC3 else 1 if digits[0] in "17" else 2
        new = list(digits[:keep])
        for i in range(keep, len(digits)):
            india_mobile = digits[:keep] in ("", "91") and len(digits) - keep == 10
            new.append(rng.choice("6789") if i == keep and india_mobile else str(rng.randint(1 if i == keep else 0, 9)))
        return _fill_digits(text, "".join(new))

    def ssn(self, text: str) -> str:
        rng = self._rng("ssn", text)
        digits = f"{rng.randint(900, 999)}{rng.randint(10, 99)}{rng.randint(1000, 9999)}"
        return _fill_digits(text, digits)

    def credit_card(self, text: str) -> str:
        digits = re.sub(r"\D", "", text)
        rng = self._rng("card", digits)
        body = [digits[0]] + [str(rng.randint(0, 9)) for _ in range(len(digits) - 2)]
        for check in "0123456789":                     # pick the Luhn check digit
            total = 0
            for i, d in enumerate(reversed([int(x) for x in body + [check]])):
                if i % 2:
                    d = d * 2 - 9 if d > 4 else d * 2
                total += d
            if total % 10 == 0:
                break
        return _fill_digits(text, "".join(body) + check)

    def ip(self, text: str) -> str:
        rng = self._rng("ip", text)
        if ":" in text:
            return "2001:db8::" + format(rng.randint(1, 0xFFFF), "x")
        block = rng.choice(["192.0.2", "198.51.100", "203.0.113"])     # RFC 5737 documentation ranges
        return f"{block}.{rng.randint(1, 254)}"

    def aadhaar(self, text: str) -> str:
        rng = self._rng("aadhaar", text)
        digits = "1" + "".join(str(rng.randint(0, 9)) for _ in range(11))   # real ones never start with 0/1
        return _fill_digits(text, digits)

    def id_number(self, text: str) -> str:
        rng = self._rng("id", text)
        if re.fullmatch(r"[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}", text):     # CIN
            return (f"{text[0]}{rng.randint(10000, 99999)}{rng.choice(STATE_CODES)}"
                    f"{rng.randint(1975, 2018)}{text[12:15]}{rng.randint(100000, 999999)}")
        if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", text):                       # PAN
            up = "ABCDEFGHJKLMNPRSTUVWXYZ"
            return "".join(rng.choice(up) for _ in range(3)) + text[3:5] + f"{rng.randint(1000, 9999)}" + rng.choice(up)
        if re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", text):  # GSTIN
            pan = self.id_number(text[2:12])
            return f"{rng.randint(1, 37):02d}{pan}1Z{rng.choice('ABCDEFGHJKLMNPRSTUVWXYZ0123456789')}"
        return "".join(str(rng.randint(0, 9)) if c.isdigit() else rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ") if c.isalpha() else c
                       for c in text)

    # ---- dates ----------------------------------------------------------------
    def dob(self, text: str) -> str:
        rng = self._rng("dob", text)
        shift = timedelta(days=rng.choice([-1, 1]) * rng.randint(200, 2500))

        def pad(n: int, like: str) -> str:
            return f"{n:0{len(like)}d}" if len(like) > 1 else str(n)

        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
            d = date(int(m[1]), int(m[2]), int(m[3])) + shift
            return d.isoformat()
        if m := re.fullmatch(r"(\d{1,2})([/.-])(\d{1,2})\2(\d{2,4})", text):
            a, sep, b, y = int(m[1]), m[2], int(m[3]), int(m[4])
            y += 2000 if y < 100 and y < 30 else 1900 if y < 100 else 0
            month_first = a <= 12 < b          # 03/25/1990 can only be month-first
            dd, mm = (b, a) if month_first else (a, b)
            try:
                d = date(y, mm, dd) + shift
            except ValueError:
                return _fill_digits(text, "".join(str(rng.randint(0, 9)) for _ in range(len(re.sub(r"\D", "", text)))))
            first, second = (d.month, d.day) if month_first else (d.day, d.month)
            year = f"{d.year}" if len(m[4]) == 4 else f"{d.year % 100:02d}"
            return f"{pad(first, m[1])}{sep}{pad(second, m[3])}{sep}{year}"
        if m := re.fullmatch(rf"(\d{{1,2}})(st|nd|rd|th)?([ -])({MONTH_RE})\w*(\.?,?)([ -])(\d{{4}})", text, re.I):
            d = date(int(m[7]), MONTH_NAMES.index(next(n for n in MONTH_NAMES if n[:3].lower() == m[4].lower())) + 1, int(m[1])) + shift
            name = MONTH_NAMES[d.month - 1]
            full = len(re.search(r"[A-Za-z]+", text[len(m[1]) + len(m[2] or "") + 1:]).group(0)) > 3
            return f"{d.day}{self._ord(d.day) if m[2] else ''}{m[3]}{name if full else name[:3]}{m[5]}{m[6]}{d.year}"
        if m := re.fullmatch(rf"({MONTH_RE})[A-Za-z]*(\.?) (\d{{1,2}})(st|nd|rd|th)?(,?) (\d{{4}})", text, re.I):
            d = date(int(m[6]), next(i for i, n in enumerate(MONTH_NAMES, 1) if n[:3].lower() == m[1].lower()), int(m[3])) + shift
            full = len(re.match(r"[A-Za-z]+", text).group(0)) > 3
            name = MONTH_NAMES[d.month - 1]
            return f"{name if full else name[:3]}{m[2]} {d.day}{self._ord(d.day) if m[4] else ''}{m[5]} {d.year}"
        return _fill_digits(text, "".join(str(rng.randint(0, 9)) for _ in range(len(re.sub(r"\D", "", text)))))

    @staticmethod
    def _ord(n: int) -> str:
        return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")

    # ---- addresses --------------------------------------------------------------
    def address(self, text: str) -> str:
        rng = self._rng("address", text)
        f = self._seeded_faker(rng)
        pin = re.search(r"(\d{3})( ?)(\d{3})(?!\d)", text)
        dash = re.search(r"([\-–—,])\s*\d{3} ?\d{3}", text)
        state_line = re.fullmatch(r"\s*[A-Za-z ]+(?:,\s*India)?\s*", text) and not pin
        if state_line:
            return f"{f.state()}, India" if "India" in text else f.state()
        new_pin = f"{rng.randint(100, 999)}{pin.group(2) if pin else ''}{rng.randint(100, 999)}"
        body = f"{rng.randint(1, 240)}, {f.street_name()}, {f.city()}"
        out = f"{body} {dash.group(1) if dash else '-'} {new_pin}"
        if re.search(r"India", text):
            out += f", {f.state()}, India"
        elif re.search(STATES, text):
            out += f", {f.state()}"
        return out
