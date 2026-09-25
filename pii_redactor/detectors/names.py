"""People and organisation detection.

Raw spaCy NER is too noisy on a legal/financial document ("Offer", "Promoters"
and "Cap Price" all come back as PERSON, real directors come back as ORG) and
it cannot read ALL-CAPS headings. So NER only *proposes* names and every
proposal must pass independent checks:

  * a token that also appears lowercase in the document is a common word
    ("Offer" <-> "offer"), not a name;
  * a token NER mostly labels as a place (GPE/LOC/FAC) is not a name;
  * ALL-CAPS tokens in normal-case text are acronyms (UPI, EBITDA, CARE);
  * the run must be 2-4 tokens and contain a known given name / surname
    (gazetteer) or a middle initial.

Accepted names go into a lexicon matched case-insensitively over the whole
document, which is how "KUSHAL SUBBAYYA HEGDE" and "Kushal Hegde" are both
caught after NER has only seen one of them.

Organisations use a legal-suffix pattern (Limited, LLP, Bank, Trust ...) rather
than NER. Public bodies (regulators, exchanges, depositories) are kept on
purpose: they are not private data and redacting them destroys the document.
"""
import importlib
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator

from ..spans import Span
from .address import CITIES, STATES, find_addresses

PRIORITY_ORG, PRIORITY_PERSON = 40, 30

# -- organisations ----------------------------------------------------------

LEGAL = r"(?:Private\s+Limited|Pvt\.?\s+Ltd\.?|Limited|LIMITED|Ltd\.?|LLP|LLC|PLC|GmbH|Inc\.?|Corporation|Corp\.?)"
HEAD = (r"(?:Bank|Trust|HUF|Group|Industries|Enterprises|Holdings|Technologies|Solutions|Systems|"
        r"Associates|Partners|Sons|Brothers|Ventures)")
_WORD = r"(?:[A-Z][\w&'’.\-]*|\([A-Z]\w*(?:\s+\w+)*\))"
_LINK = r"(?:\s+and\s+|\s+|\s*&\s*)"
CONJUNCTION = re.compile(rf"(?:{LEGAL}|{HEAD})(\s+and\s+)(?=[A-Z])")
ORG_RE = re.compile(
    rf"\b(?:{_WORD}{_LINK}){{1,6}}(?i:{LEGAL})(?![\w])"
    rf"|\b(?:{_WORD}{_LINK}){{1,5}}(?:{HEAD})\b"
    rf"|(?<!Reserve )\bBank\s+of\s+[A-Z]\w+(?:\s+[A-Z]\w+)?"
)
# leading words that get swept into the match ("Book Running Lead Manager Kotak ...")
TRIM = {w.lower() for w in (
    "The Our We Its Their Of And To By For In At On As With From Such Each All Any This That "
    "These Those Book Running Lead Manager Managers BRLM BRLMs Registrar Statutory Auditor Auditors "
    "Sole Joint Offer Company Issuer Sponsor Escrow Collection Refund Public Account Banker Bankers "
    "Anchor Designated Scheduled Commercial Nationalised Peer Reviewed Independent Chartered "
    "Accountants Legal Counsel Domestic International Indian Selling Shareholder Shareholders "
    "Promoter Promoters Group Director Directors Board Committee Person Contact Details Name Address "
    "Note Notes Refer Please Further However Accordingly Also Subsidiary Subsidiaries Associate "
    "Material Key Managerial Personnel Senior Management Agreement Agreements Between Among "
    "Notwithstanding Pursuant Under Upon Whether Which Where While Since Until Unless Certain "
    "Bid Bids Bidder Bidders Investor Investors Registered Corporate Office Head Branch Short Long Term "
    "Formerly Known Self-Certified Syndicate Advisory Investment Electricals Industrial Solutions Cash "
    "India Limited Private Family Trust Bank Co"
).split()}

# words that describe a business rather than name it; kept when a company is renamed
DESCRIPTORS = {w.lower() for w in (
    "Wealth Management Securities Capital Bank Trust Family Finance Financial Services Industries "
    "Industrial Park Holdings Enterprises Company International India Infrastructure Power Energy "
    "Electricals Electric Engineering Metal Metals Extrusion Technologies Solutions Systems Group "
    "Investments Investment Partners Associates Pandit Housing Realty Logistics Foods Pharma "
    "Private Limited Ltd LLP Corporation Corp Inc HUF Pvt & and of the Asset Advisors Advisory "
    "Consultants Consulting Insurance Life General Mutual Fund Funds Markets Broking Stock "
    "Exchange Depository Sons Brothers Co Motors Project Integrated Transformer Switchgear "
    "Infra Distriparks Analytics Ratings"
).split()}

# public / statutory bodies that stay untouched
PUBLIC_BODIES = re.compile(
    r"^(?:securities and exchange board|reserve bank|bse\b|national stock exchange|nse\b|"
    r"national securities depository|central depository services|national payments|"
    r"registrar of companies|ministry of|government of|institute of chartered|"
    r"competition commission|indian bank association|rbi\b|sebi\b|nsdl|cdsl|npci|"
    r"stock exchanges?|depositor(?:y|ies)|the companies act)", re.I)

# -- people -----------------------------------------------------------------

PERSON_STOP = {w.lower() for w in (
    "India Indian Private Limited Ltd LLP Bank Trust Family Company Capital Securities Services "
    "Industries Management Wealth Corporation Industrial Park Holdings Group HUF Pvt Inc Fund "
    "Promoters Promoter Directors Director Investors Bidders Offer Price Equity Shares Share "
    "Registrar Manager Managers Committee Board Act Rules Regulations Schedule Section "
    "Maharashtra Pune Mumbai Delhi Gujarat Karnataka Bengaluru Chennai Kolkata Hyderabad "
    "Village Taluka Marg Road Nagar Chowk Floor Tower Plaza East West North South Branch Email Tel "
    "Opp Opposite Hall Chambers Hospital Apartment Society Colony Complex Garden Estate Building Centre Center "
    "House Bhavan Residency Mantri Yojana Abhiyan Mission Bunglow Bungalow Gram Kisan Urja Suraksha"
).split()}
TITLE_CUE = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Shri|Smt|Sri)\.?\s+((?:[A-Z][a-z'’\-]+)(?:\s+[A-Z][a-z'’\-]+){0,3})")
WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|['’\-])*\.?")          # unicode letters: Ferrán, Kühn
# "this is X", "Regards, X", "Customer X": a capitalised pair after such a cue is a name even if unknown
CONTEXT_CUE = re.compile(
    r"\b(?i:this is|my name is|i am|i'm|customer|client|user|dear|hi|hello|regards|thanks|thank you|"
    r"sincerely|cheers|attn|attention|contact person|contact)[ ,:\-]+"
    r"([^\W\d_a-z][^\W\d_]+(?:[ \-][^\W\d_a-z][^\W\d_]+){1,2})")
INITIAL = re.compile(r"[A-Z]\.")
NEXT_WORD = re.compile(r"[ \t]+([A-Za-z][A-Za-z'’\-]{2,})\b")
PLACE_LABELS = {"GPE", "LOC", "FAC"}
ADDRESS_HINT = re.compile(r"\b(?:Plot|Unit|Floor|Road|Marg|Village|Taluka|Tower|Building|Campus|Society|Nagar|Gat|Survey|"
                          r"Sector|Phase|Area|MIDC|Dist|Wing|Block|Colony|Opp|Opposite|Near|Next to|Off|Centre|Center)\b"
                          r"|\b[A-Z]-?\d{2,4}\b")
NON_PROSE = re.compile(r"\S+@\S+|(?:https?://|www\.)\S+|\b[a-z0-9-]+\.(?:com|co\.in|in|org|net)\b", re.I)
# a name directly followed by one of these is a street/locality, not a person ("Appasaheb Marathe Marg")
PLACE_SUFFIX = re.compile(r"\s+(?:Marg|Road|Rd|Nagar|Chowk|Path|Street|St|Lane|Colony|Society|Vihar|Peth|Wadi|Complex|"
                          r"Park|Garden|Gardens|Estate|Hall|Chambers|Hospital|Apartments?|Bunglow|Bungalow)\b", re.I)


def is_roman(t: str) -> bool:
    """Numerals used in entity names (Park VI, IX B); 'icici' must not count."""
    return len(t) <= 4 and re.fullmatch(r"[ivxlc]+", t) is not None


def _norm(tok: str) -> str:
    return tok.strip(".").lower()


def _prep_for_ner(text: str) -> str:
    """spaCy misses names in ALL-CAPS lines; title-casing keeps offsets intact."""
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7 and len(text.title()) == len(text):
        return text.title()
    return text


def _gazetteer() -> set[str]:
    """Known given names / surnames: Faker's locale lists plus data/indian_names.txt."""
    names: set[str] = set()
    for loc in ("en_IN", "en_US", "en_GB"):
        prov = importlib.import_module(f"faker.providers.person.{loc}").Provider
        for attr in ("first_names", "last_names", "first_names_male", "first_names_female"):
            vals = getattr(prov, attr, None)
            if vals:
                names |= {v.lower() for v in (vals.keys() if hasattr(vals, "keys") else vals)}
    extra = Path(__file__).resolve().parent.parent / "data" / "indian_names.txt"
    for line in extra.read_text(encoding="utf8").splitlines():
        if not line.startswith("#"):
            names |= set(line.lower().split())
    return names


class NameLexicon:
    def __init__(self, nlp=None):
        self.nlp = nlp
        self.gazetteer = _gazetteer()
        self.lower_vocab: set[str] = set()
        self.place_tokens: set[str] = set()
        self.person_phrases: Counter = Counter()   # tuple of lowercase tokens -> count
        self.person_tokens: set[str] = set()       # tokens backed by >= 2 different names
        self.org_core: set[str] = set()
        self.locality_tokens: set[str] = set()
        self._locality_re: re.Pattern | None = None
        self._locality_ctx_re: re.Pattern | None = None
        self.org_names: Counter = Counter()
        self._person_re: re.Pattern | None = None
        self._org_re: re.Pattern | None = None

    # ---- learning pass ----------------------------------------------------
    def learn(self, texts: list[str]) -> None:
        prose = NON_PROSE.sub(" ", "\n".join(texts))   # emails/URLs are lowercase but say nothing about words
        self.lower_vocab = set(re.findall(r"\b[a-z]{3,}\b", prose))
        for text in texts:
            for sp in self.org_spans_by_suffix(text):
                name = text[sp.start:sp.end]
                self.org_names[name] += 1
                self.org_core.update(self._core_tokens(name))
        if self.nlp is not None:
            self._learn_people(texts)
        self._learn_localities(texts)
        self._compile()

    def _learn_people(self, texts: list[str]) -> None:
        texts = [t for t in texts if t.strip()]
        pairs = list(zip(texts, self.nlp.pipe((_prep_for_ner(t) for t in texts), batch_size=64)))
        place, other = Counter(), Counter()
        for _, doc in pairs:
            for ent in doc.ents:
                for w in WORD.findall(ent.text):
                    (place if ent.label_ in PLACE_LABELS else other)[_norm(w)] += 1
        self.place_tokens = {w for w, n in place.items() if n > other[w]}

        for text, doc in pairs:
            caps_para = _prep_for_ner(text) != text
            org_ranges = [(s.start, s.end) for s in self.org_spans_by_suffix(text)]

            def usable(start: int, end: int) -> bool:
                return (not any(start < e and s < end for s, e in org_ranges)
                        and not PLACE_SUFFIX.match(text, end))

            runs: set[tuple[str, ...]] = set()
            saw_person = False
            for ent in doc.ents:
                if ent.label_ not in ("PERSON", "ORG"):
                    continue
                saw_person |= ent.label_ == "PERSON"
                for run, a, b in self._candidate_names(text[ent.start_char:ent.end_char], caps_para,
                                                       text, ent.start_char):
                    if usable(ent.start_char + a, ent.start_char + b):
                        runs.add(tuple(_norm(t) for t in run))
            if saw_person:
                # NER often draws bad boundaries inside "A B/ C D/ E F" contact lists;
                # once it has confirmed a person here, rescan the whole line with the same strict filters
                for run, a, b in self._candidate_names(text, caps_para, text, 0):
                    if usable(a, b):
                        runs.add(tuple(_norm(t) for t in run))
            for m in TITLE_CUE.finditer(text):
                runs.add(tuple(_norm(t) for t in m.group(1).split()))
            for m in CONTEXT_CUE.finditer(text):
                toks = WORD.findall(m.group(1))
                if 2 <= len(toks) <= 3 and all(self._good(t, caps_para) for t in toks) and usable(m.start(1), m.end(1)):
                    runs.add(tuple(_norm(t) for t in toks))
            self.person_phrases.update(runs)

        support = Counter(tok for phrase in self.person_phrases for tok in set(phrase) if len(tok) >= 3)
        # a token that stands alone in the text ("Rakhi Branch") is trusted if two different names
        # use it, or if it is a known given name / surname
        self.person_tokens = {t for t, n in support.items() if n >= 2 or (t in self.gazetteer and len(t) >= 4)}

    def _learn_localities(self, texts: list[str]) -> None:
        """Locality names (Birdewadi, Baner) also occur outside full addresses, e.g. in
        "Unit No. 2 (Birdewadi)". Learn them from the addresses that were found."""
        skip = PERSON_STOP | TRIM | DESCRIPTORS | CITIES | {s.lower() for s in STATES.split("|")} | self.lower_vocab
        for text in texts:
            for sp in find_addresses(text):
                for m in re.finditer(r"[A-Z][A-Za-z]{4,}", text[sp.start:sp.end]):
                    w = m.group(0).lower()
                    if w not in skip and w not in self.gazetteer and w not in self.org_core:
                        self.locality_tokens.add(w)

    def _good(self, tok: str, allow_caps: bool) -> bool:
        t = _norm(tok)
        if not (len(t) >= 2 and tok[0].isupper()) or t in self.lower_vocab or t in self.place_tokens:
            return False
        if tok.isupper() and not allow_caps:      # UPI, EBITDA, CARE in normal text are acronyms
            return False
        return t not in PERSON_STOP and t not in TRIM and t not in DESCRIPTORS

    def _sentence_start_word(self, tok: str, text: str | None, pos: int) -> bool:
        """A capitalised word opening a sentence proves nothing ("Customer", "Order"): it only
        counts as a name there if it is a known given name / surname."""
        if text is None or _norm(tok) in self.gazetteer:
            return False
        before = text[:pos].rstrip()
        return not before or before[-1] in ".!?"

    def _candidate_names(self, s: str, allow_caps: bool = False, text: str | None = None,
                         base: int = 0) -> Iterator[tuple[list[str], int, int]]:
        """Runs of name-like tokens (2-4 long, separated only by whitespace) that
        contain at least one known name or a middle initial."""
        run: list[str] = []
        run_start = prev_end = 0
        for m in [*WORD.finditer(s), None]:
            tok = m.group(0) if m else None
            contiguous = m is not None and not s[prev_end:m.start()].strip()
            good = bool(tok) and self._good(tok, allow_caps) and not self._sentence_start_word(tok, text, base + m.start())
            if tok and contiguous and (good or (INITIAL.fullmatch(tok) and run)):
                run.append(tok)
                prev_end = m.end()
                continue
            while run and INITIAL.fullmatch(run[-1]):
                run.pop()
            known = any(_norm(t) in self.gazetteer for t in run) or any(INITIAL.fullmatch(t) for t in run)
            if 2 <= len(run) <= 4 and known and sum(len(_norm(t)) >= 3 for t in run) >= 2:
                yield run, run_start, prev_end
            run = []
            if tok and good:                          # this token starts the next run
                run, run_start = [tok], m.start()
            if m:
                prev_end = m.end()

    def _core_tokens(self, org: str) -> list[str]:
        return [_norm(w) for w in WORD.findall(org)
                if len(_norm(w)) >= 3 and _norm(w) not in DESCRIPTORS and _norm(w) not in TRIM
                and _norm(w) not in self.lower_vocab and not is_roman(_norm(w))]

    def _compile(self) -> None:
        def alt(tokens: Iterable[str]) -> str:
            return "|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True))

        if self.person_phrases:
            phrases = sorted(self.person_phrases, key=lambda p: -sum(map(len, p)))
            phrase_alt = "|".join(
                r"[ \t]+".join(re.escape(t) + (r"\.?" if len(t) == 1 else "") for t in p) for p in phrases)
            seq = ""
            if self.person_tokens:
                tok = rf"(?:{alt(self.person_tokens)})"
                seq = rf"|{tok}(?:[ \t]+{tok})*"
            self._person_re = re.compile(rf"\b(?:{phrase_alt}{seq})\b", re.I)
        # places NER agrees on (Chakan, Baner) are replaced anywhere; other address words
        # (building names such as "Venture", "Inspire") only where the line looks like an address
        for attr, toks in (("_locality_re", self.locality_tokens & self.place_tokens),
                           ("_locality_ctx_re", self.locality_tokens - self.place_tokens)):
            if toks:
                t = rf"(?:{alt(toks)})"
                setattr(self, attr, re.compile(rf"\b{t}(?:[ \t]+{t})*\b", re.I))
        core = self.org_core - self.person_tokens
        if core:
            c = rf"(?:{alt(core)})"
            desc = rf"(?:{alt(DESCRIPTORS - {'&', 'and', 'of', 'the'})}|[IVXLC]{{1,4}}|\d+)"
            self._org_re = re.compile(
                rf"\b{c}(?:\s*&\s*{c}|\s+{c}|\s+{desc})*\b(?:\s+(?i:{LEGAL}))?", re.I)

    # ---- detection --------------------------------------------------------
    @property
    def all_person_tokens(self) -> set[str]:
        return {t for phrase in self.person_phrases for t in phrase}

    @staticmethod
    def org_spans_by_suffix(text: str) -> Iterator[Span]:
        for m in ORG_RE.finditer(text):
            # "X Limited and Y Limited" is two companies: cut after a legal suffix followed by "and"
            cuts = [(m.start(), m.end())]
            for c in CONJUNCTION.finditer(m.group(0)):
                cuts = [(m.start(), m.start() + c.start(1)), (m.start() + c.end(1), m.end())]
                break
            for lo, hi in cuts:
                words = list(re.finditer(r"\S+", text[lo:hi]))
                i = 0
                while i < len(words) - 1 and _norm(words[i].group(0).strip("()&,")) in TRIM:
                    i += 1
                if not words:
                    continue
                start = lo + words[i].start()
                name = text[start:hi]
                if len(name.split()) < 2 or PUBLIC_BODIES.match(name):
                    continue
                yield Span(start, hi, "ORG", PRIORITY_ORG)

    def org_spans(self, text: str) -> Iterator[Span]:
        yield from self.org_spans_by_suffix(text)
        if self._org_re:
            for m in self._org_re.finditer(text):
                if not PUBLIC_BODIES.match(m.group(0)):
                    yield Span(m.start(), m.end(), "ORG", PRIORITY_ORG - 1)

    def locality_spans(self, text: str) -> Iterator[Span]:
        patterns = [self._locality_re]
        if ADDRESS_HINT.search(text):
            patterns.append(self._locality_ctx_re)
        for pat in filter(None, patterns):
            for m in pat.finditer(text):
                yield Span(m.start(), m.end(), "LOCALITY", PRIORITY_ORG - 5)

    def person_spans(self, text: str) -> Iterator[Span]:
        if self._person_re:
            for m in self._person_re.finditer(text):
                end = m.end()
                nxt = NEXT_WORD.match(text, end)      # "Tushar Wakhele": surname NER never saw
                if nxt and self._good(nxt.group(1), nxt.group(1).isupper() and m.group(0).isupper()):
                    end = nxt.end()
                yield Span(m.start(), end, "PERSON", PRIORITY_PERSON)
        for m in TITLE_CUE.finditer(text):
            yield Span(m.start(1), m.end(1), "PERSON", PRIORITY_PERSON)
