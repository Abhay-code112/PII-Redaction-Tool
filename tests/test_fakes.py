import re

from pii_redactor.detectors.patterns import luhn_ok
from pii_redactor.fakes import Pseudonymizer


def test_same_input_same_fake_and_seed_changes_it():
    a, b, c = Pseudonymizer("s1"), Pseudonymizer("s1"), Pseudonymizer("s2")
    assert a.fake("PERSON", "Rajesh Hegde") == b.fake("PERSON", "Rajesh Hegde")
    assert a.fake("PERSON", "Rajesh Hegde") != c.fake("PERSON", "Rajesh Hegde")


def test_name_tokens_are_shared_across_variants():
    p = Pseudonymizer()
    full = p.fake("PERSON", "Kushal Subbayya Hegde").split()
    short = p.fake("PERSON", "Kushal Hegde").split()
    caps = p.fake("PERSON", "RAJESH KUSHAL HEGDE").split()
    assert short == [full[0], full[-1]]                  # first + surname reuse the same fakes
    assert caps[-1] == full[-1].upper()                  # family surname stays shared, casing follows source
    assert p.fake("PERSON", "KUSHAL SUBBAYYA HEGDE").isupper()
    assert not p.fake("PERSON", "Kushal Subbayya Hegde").isupper()


def test_email_is_valid_uses_example_domain_and_keeps_role_mailbox():
    p = Pseudonymizer()
    e = p.fake("EMAIL", "siddharth.jadhav@hdfcbank.com")
    assert re.fullmatch(r"[a-z]+\.[a-z]+@[a-z]+\.example\.com", e)
    assert "siddharth" not in e and "hdfc" not in e
    assert p.fake("EMAIL", "cs.connect@acme.com").startswith("cs.connect@")


def test_email_domain_matches_org_brand():
    p = Pseudonymizer()
    org = p.fake("ORG", "HDFC Bank Limited")
    email = p.fake("EMAIL", "x.y@hdfcbank.com")
    assert org.split()[0].lower() in email          # same brand -> same fake brand


def test_phone_keeps_format_and_country_code():
    p = Pseudonymizer()
    out = p.fake("PHONE", "+91 22 3075 2929")
    assert re.fullmatch(r"\+91 \d\d \d{4} \d{4}", out) and out != "+91 22 3075 2929"
    assert re.fullmatch(r"\(\d{3}\) \d{3}-\d{4}", p.fake("PHONE", "(212) 555-0123"))


def test_safe_ranges():
    p = Pseudonymizer()
    assert p.fake("SSN", "123-45-6789").startswith("9")                 # area 9xx is never issued
    assert p.fake("IP_ADDRESS", "8.8.8.8").startswith(("192.0.2.", "198.51.100.", "203.0.113."))
    assert p.fake("AADHAAR", "2345 6789 0128").startswith("1")


def test_credit_card_luhn_valid_same_length_and_grouping():
    out = Pseudonymizer().fake("CREDIT_CARD", "4111 1111 1111 1111")
    assert luhn_ok(out) and re.fullmatch(r"\d{4} \d{4} \d{4} \d{4}", out) and out != "4111 1111 1111 1111"


def test_dob_formats_preserved():
    p = Pseudonymizer()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.fake("DOB", "1990-04-12"))
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", p.fake("DOB", "12/04/1990"))
    assert re.fullmatch(r"[A-Z][a-z]+ \d{1,2}, \d{4}", p.fake("DOB", "April 12, 1990"))
    assert p.fake("DOB", "1990-04-12") != "1990-04-12"


def test_org_changes_brand_keeps_legal_suffix_and_never_returns_unchanged():
    p = Pseudonymizer()
    out = p.fake("ORG", "Waterloo Industrial Park VI Private Limited")
    assert out.endswith("Industrial Park VI Private Limited") and not out.startswith("Waterloo")
    assert p.fake("ORG", "CG Power and Industrial Solutions Limited") != "CG Power and Industrial Solutions Limited"


def test_id_number_shapes():
    p = Pseudonymizer()
    cin = p.fake("ID_NUMBER", "U28129PN1979PLC141032")
    assert re.fullmatch(r"U\d{5}[A-Z]{2}\d{4}PLC\d{6}", cin) and cin != "U28129PN1979PLC141032"
    assert re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", p.fake("ID_NUMBER", "ABCDE1234F"))


def test_url_drops_query_and_swaps_domain():
    out = Pseudonymizer().fake("URL", "https://www.acme.com/investors/report?token=acme.com")
    assert out.startswith("https://www.") and out.endswith(".example.com/investors/report")
    assert "acme" not in out
