import pytest

from pii_redactor.detectors import PATTERN_DETECTORS, find_addresses


def found(text: str, label: str) -> list[str]:
    spans = [s for d in PATTERN_DETECTORS if d.label == label for s in d.find(text)]
    return sorted({text[s.start:s.end] for s in spans})


@pytest.mark.parametrize("text, expected", [
    ("mail a.b+tag@sub.example.co.in now", ["a.b+tag@sub.example.co.in"]),
    ("no address here", []),
    ("trailing dot user@example.com.", ["user@example.com"]),
])
def test_email(text, expected):
    assert found(text, "EMAIL") == expected


@pytest.mark.parametrize("text, expected", [
    ("call +91 22 3075 2929 today", ["+91 22 3075 2929"]),
    ("Telephone: 022-68052182", ["022-68052182"]),
    ("Mobile 9876543210", ["9876543210"]),
    ("reach me at (212) 555-0123", ["(212) 555-0123"]),
    ("Order ID 9039007922 confirmed", []),          # looks like a mobile, is an order id
    ("revenue of 1,234,567.89", []),
])
def test_phone(text, expected):
    assert found(text, "PHONE") == expected


def test_credit_card_needs_luhn_and_valid_prefix():
    assert found("card 4111 1111 1111 1111 ok", "CREDIT_CARD") == ["4111 1111 1111 1111"]
    assert found("tracking 4111111111111112", "CREDIT_CARD") == []      # fails Luhn
    assert found("id 0000000000000000", "CREDIT_CARD") == []


@pytest.mark.parametrize("text, expected", [
    ("SSN 123-45-6789.", ["123-45-6789"]),
    ("Social security number on file: 373606918", ["373606918"]),
    ("000-12-3456 and 666-12-3456 are never issued", []),
    ("phone 123 456 7890", []),
])
def test_ssn(text, expected):
    assert found(text, "SSN") == expected


@pytest.mark.parametrize("text, expected", [
    ("from 192.168.1.10 to 10.0.0.255", ["10.0.0.255", "192.168.1.10"]),
    ("bad 999.1.1.1", []),
    ("Firmware 2.10.4.15 released", []),               # version string
    ("Server 203.0.113.9 rejected", ["203.0.113.9"]),   # 'Server' must not trip the 'ver' cue
    ("host 2001:db8:85a3:0:0:8a2e:370:7334 up", ["2001:db8:85a3:0:0:8a2e:370:7334"]),
])
def test_ip(text, expected):
    assert found(text, "IP_ADDRESS") == expected


@pytest.mark.parametrize("text, expected", [
    ("DOB: 1990-04-12", ["1990-04-12"]),
    ("Date of Birth 12/04/1990", ["12/04/1990"]),
    ("born on April 12, 1990", ["April 12, 1990"]),
    ("Dated December 10, 2025", []),                   # ordinary date, no birth cue
    ("shipped on 12/04/2025", []),
])
def test_dob(text, expected):
    assert found(text, "DOB") == expected


def test_indian_identifiers():
    assert found("CIN U28129PN1979PLC141032.", "ID_NUMBER") == ["U28129PN1979PLC141032"]
    assert found("PAN ABCDE1234F", "ID_NUMBER") == ["ABCDE1234F"]
    assert found("SEBI Registration No.: INM000011179", "ID_NUMBER") == ["INM000011179"]


def test_aadhaar_is_checksummed():
    from pii_redactor.detectors.patterns import verhoeff_ok
    prefix = "23456789012"
    valid = next(prefix + str(d) for d in range(10) if verhoeff_ok(prefix + str(d)))
    invalid = next(prefix + str(d) for d in range(10) if not verhoeff_ok(prefix + str(d)))
    fmt = lambda n: f"{n[:4]} {n[4:8]} {n[8:]}"          # noqa: E731
    assert found(f"Aadhaar {fmt(valid)}", "AADHAAR") == [fmt(valid)]
    assert found(f"Aadhaar {fmt(invalid)}", "AADHAAR") == []
    assert found(f"Aadhaar no. {valid}", "AADHAAR") == [valid]      # bare 12 digits need the cue word
    assert found(f"order {valid}", "AADHAAR") == []


@pytest.mark.parametrize("text, expected", [
    ("Office: 11/3, Village Birdewadi, Chakan, Pune – 410 501, Maharashtra, India;",
     ["11/3, Village Birdewadi, Chakan, Pune – 410 501, Maharashtra, India"]),
    ("ship to 742 Evergreen Terrace, Springfield, IL 62704 today",
     ["742 Evergreen Terrace, Springfield, IL 62704"]),
    ("Flat 5, Andheri Surat 371844", ["Flat 5, Andheri Surat 371844"]),
    ("Ticket TKT-542727 is resolved and Order 123456 shipped", []),
])
def test_address(text, expected):
    assert [text[s.start:s.end] for s in find_addresses(text)] == expected
