"""Held-out test annotation (eval/test_paragraphs.json, seed 99, disjoint from the dev sample).

Annotated BEFORE running the detector on these paragraphs and never used for tuning.
Same policy as eval/gold_real.py. One deliberate consequence of that policy: the SEBI website
URL (#4275) is a regulator, so it is NOT marked - the tool redacts every URL, so it will
count as a false positive.
"""
HEG = [("KUSHAL SUBBAYYA HEGDE", "PERSON"), ("PUSHPA KUSHAL HEGDE", "PERSON"),
       ("RAJESH KUSHAL HEGDE", "PERSON"), ("ROHIT KUSHAL HEGDE", "PERSON"), ("RAKHI GIRIJA SHETTY", "PERSON")]
PHONES = [("+91 22 30752929", "PHONE"), ("+91 22 30752928", "PHONE"), ("+91 22 30752914", "PHONE")]
PIN_ADDR = "11/3, 11/4 and 11/5, Village Birdewadi, Chakan Taluka - Khed, Pune – 410 501, Maharashtra, India"

GOLD = {
    28: HEG + [("DHAULAGIRI FAMILY TRUST", "ORG"), ("EVEREST FAMILY TRUST", "ORG"), ("MAKALU FAMILY TRUST", "ORG"),
               ("BROAD FAMILY TRUST", "ORG"), ("ANNAPURNA FAMILY TRUST", "ORG"), ("KANCHENJUNGA FAMILY TRUST", "ORG")],
    113: [("kshinternational.ipo@in.mpms.mufg.com", "EMAIL")],
    167: [("Nuvama Wealth Management Limited", "ORG")],
    188: [("www.in.mpms.mufg.com", "URL")],
    241: [("Kirtane & Pandit LLP", "ORG")],
    248: [("CARE Analytics and Advisory Private Limited", "ORG")],
    251: [("Kushal Subbayya Hegde", "PERSON")],
    354: [(PIN_ADDR, "ADDRESS")],
    607: [("HDFC Bank Limited", "ORG")],
    3837: [("Kushal Subbayya Hegde", "PERSON"), ("Pushpa Kushal Hegde", "PERSON"), ("Rajesh Kushal Hegde", "PERSON"),
           ("Rohit Kushal Hegde", "PERSON"), ("Rakhi Girija Shetty", "PERSON")],
    4079: [("KSH International Limited", "ORG")],
    4084: [("KSH International Limited", "ORG")],
    4086: [("Pune 411 045 Maharashtra, India", "ADDRESS")],
    4117: [("3 Prabhat Road, opposite PYC basketball court, Erandawane, Deccan Gymkhana, Pune – 411 004 Maharashtra, India", "ADDRESS")],
    4153: [("Bandra East, Mumbai – 400 051 Maharashtra, India", "ADDRESS")],
    4280: PHONES,
    4311: PHONES,
    4355: [("Opposite Harshal Hall, above HDFC Limited Karve Road, Pune – 411 038", "ADDRESS")],
    4364: [("hingnetare@gmail.com", "EMAIL")],
    4378: [("http://commercialbanking.citibank.com", "URL")],
    4386: [("Signature Building, Bhandarkar road Shivaji Nagar, Pune – 411 004 Maharashtra, India", "ADDRESS")],
    4418: [("+ 91 91586 40360", "PHONE")],
    4426: [("+91 20 7157 6403", "PHONE"), ("Anand Soni", "PERSON"), ("www.bajajfinance.com", "URL"),
           ("anand.soni@bajajfinserv.in", "EMAIL")],
}
