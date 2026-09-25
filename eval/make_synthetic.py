"""Synthetic ticket-style test set for the PII types the prospectus does not contain.

The prospectus has no SSNs, credit cards, dates of birth or IP addresses, so recall
for those cannot be measured on it. This builds labelled support-ticket sentences
from Faker values, plus look-alike NON-PII (order/ticket numbers, tracking ids,
plain dates, version strings) so precision is tested as well.

Names come from two pools:
  in-gazetteer      en_US / en_IN / en_GB Faker names (the tool's name list is built from the
                    same Faker locales, so recall here is optimistic - reported separately)
  out-of-gazetteer  de_DE / fr_FR / es_ES / pl_PL / nl_NL names the tool has never been given
"""
import json
import random
import re
import sys
from datetime import date, timedelta

from faker import Faker

SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
rng = random.Random(SEED)
F = {loc: Faker(loc) for loc in ("en_US", "en_IN", "en_GB", "de_DE", "fr_FR", "es_ES", "pl_PL", "nl_NL")}
for i, f in enumerate(F.values()):
    f.seed_instance(SEED + i)


def luhn_ok(num: str) -> bool:
    total = 0
    for i, d in enumerate(reversed([int(c) for c in num])):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def name(pool: str) -> str:
    locs = ["en_US", "en_IN", "en_GB"] if pool == "in" else ["de_DE", "fr_FR", "es_ES", "pl_PL", "nl_NL"]
    while True:
        n = F[rng.choice(locs)].name()
        n = re.sub(r"^(Mr|Mrs|Ms|Dr|Prof|Herr|Frau|Dhr|Mevr|Sr|Sra)\.?\s+", "", n)
        n = re.sub(r"\s+(Jr|Sr|II|III|MD|DDS|PhD|DVM)\.?$", "", n)
        if re.fullmatch(r"[A-Za-zÀ-ÿ'’\-]+(?: [A-Za-zÀ-ÿ'’\-]+){1,2}", n):
            return n


def dob() -> str:
    d = date(1950, 1, 1) + timedelta(days=rng.randint(0, 20000))
    fmts = [d.strftime("%Y-%m-%d"), d.strftime("%d/%m/%Y"), d.strftime("%B %d, %Y").replace(" 0", " "),
            d.strftime("%d %B %Y").lstrip("0"), d.strftime("%d-%b-%Y")]
    return rng.choice(fmts)


def card() -> str:
    while True:
        n = F["en_US"].credit_card_number()
        n = re.sub(r"\D", "", n)
        if 13 <= len(n) <= 19 and luhn_ok(n):
            break
    style = rng.choice(["plain", "space", "dash"])
    if style == "plain":
        return n
    sep = " " if style == "space" else "-"
    return sep.join(n[i:i + 4] for i in range(0, len(n), 4))


def fake_tracking() -> str:            # 16 digits that FAIL Luhn: looks like a card, is not
    while True:
        n = "".join(str(rng.randint(0, 9)) for _ in range(16))
        if not luhn_ok(n):
            return n


def address() -> str:
    if rng.random() < 0.5:
        return F["en_IN"].address().replace("\n", ", ")
    return F["en_US"].address().replace("\n", ", ")


def phone() -> str:
    return rng.choice([F["en_US"].phone_number(), F["en_IN"].phone_number(),
                       f"+91 {rng.randint(6, 9)}{rng.randint(10**8, 10**9 - 1)}",
                       f"({rng.randint(200, 999)}) {rng.randint(200, 999)}-{rng.randint(1000, 9999)}"])


def ip() -> str:
    return F["en_US"].ipv6() if rng.random() < 0.15 else F["en_US"].ipv4()


def make_item(template: str, **vals) -> dict:
    """vals maps placeholder -> (value, label); label None means a distractor."""
    text, pii, offset = "", [], 0
    for part in re.split(r"(\{\w+\})", template):
        m = re.fullmatch(r"\{(\w+)\}", part)
        if not m:
            text += part
            continue
        value, label = vals[m.group(1)]
        if label:
            pii.append({"start": len(text), "end": len(text) + len(value), "label": label,
                        "pool": vals.get("_pool_" + m.group(1), "")})
        text += value
    return {"text": text, "pii": pii}


def build(n_each: int = 24) -> list[dict]:
    items = []
    for i in range(n_each):
        pool = "in" if i % 3 else "out"
        n1 = name(pool)
        items += [
            make_item("Hi, this is {n}. Please call me on {p} or write to {e}.",
                      n=(n1, "PERSON"), p=(phone(), "PHONE"), e=(F["en_US"].email(), "EMAIL"), _pool_n=pool),
            make_item("Customer {n} (DOB: {d}) reported a login failure from IP {ip}.",
                      n=(name(pool), "PERSON"), d=(dob(), "DOB"), ip=(ip(), "IP_ADDRESS"), _pool_n=pool),
            make_item("Payment failed for card {c}. Cardholder SSN {s}.",
                      c=(card(), "CREDIT_CARD"), s=(F["en_US"].ssn(), "SSN")),
            make_item("Please ship the replacement to {a}. Company: {o}.",
                      a=(address(), "ADDRESS"), o=(F["en_US"].company(), "ORG")),
            make_item("Born on {d}. Contact {e} for verification.",
                      d=(dob(), "DOB"), e=(F["en_IN"].company_email(), "EMAIL")),
            make_item("Callback number: {p}. Alternate line {p2}.", p=(phone(), "PHONE"), p2=(phone(), "PHONE")),
            make_item("Server {ip} rejected the request from {ip2}.",
                      ip=(ip(), "IP_ADDRESS"), ip2=(ip(), "IP_ADDRESS")),
            make_item("Social security number on file: {s}. Date of birth {d}.",
                      s=(F["en_US"].ssn().replace("-", ""), "SSN"), d=(dob(), "DOB")),
            make_item("Regards, {n}, {o}", n=(name(pool), "PERSON"),
                      o=(F["en_IN"].company().replace(" Ltd", " Limited"), "ORG"), _pool_n=pool),
        ]
        # distractors: text that looks like PII but is not
        items += [
            make_item("Order #{o} was shipped on {d}. Ticket TKT-{t} is resolved.",
                      o=(str(rng.randint(10**7, 10**8)), None), d=(dob(), None), t=(str(rng.randint(10**5, 10**6)), None)),
            make_item("Tracking number {tr} is in transit; invoice total $1,234.56 for 3 items.",
                      tr=(fake_tracking(), None)),
            make_item("Firmware {v} fixes the crash. Reference {r}, batch {b}.",
                      v=(f"{rng.randint(1, 9)}.{rng.randint(10, 99)}.{rng.randint(1, 9)}.{rng.randint(10, 99)}", None),
                      r=(f"INV-{rng.randint(2020, 2026)}-{rng.randint(1000, 9999)}", None),
                      b=(str(rng.randint(10**11, 10**12)), None)),
            make_item("Order ID {o} confirmed; parcel weight {w} kg.",
                      o=(str(rng.randint(10**9, 10**10 - 1)), None), w=(f"{rng.randint(1, 30)}.{rng.randint(0, 9)}", None)),
            make_item("The plan renews on the 15th; support hours are 9:00-17:30, ext. {x}.",
                      x=(str(rng.randint(100, 999)), None)),
        ]
    for it in items:
        it["pii"].sort(key=lambda s: s["start"])
    return items


if __name__ == "__main__":
    data = build()
    out = sys.argv[1] if len(sys.argv) > 1 else "eval/synthetic.json"
    json.dump(data, open(out, "w", encoding="utf8"), ensure_ascii=False, indent=1)
    from collections import Counter
    print(len(data), "items,", Counter(s["label"] for it in data for s in it["pii"]))
