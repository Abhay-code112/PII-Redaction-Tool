"""Hand annotation of eval/sample_paragraphs.json (70 paragraphs of the prospectus).

Written by reading each paragraph, before looking at detector output.

Annotation policy (same one the tool implements; see README):
  PERSON   named individuals (promoters, directors, officers, contacts, engineers)
  ORG      private organisations: companies, LLPs, trusts, banks, incl. the issuer and its
           short brand forms ("KSH", "CARE"). NOT regulators/exchanges/depositories/tribunals
           (SEBI, BSE, NSE, RoC, MCA, pollution control boards), NOT defined terms
           ("the Company", "BRLMs") and NOT statutes.
  ADDRESS  postal address strings, house/plot number through PIN/state/country
  EMAIL, PHONE, URL (websites), ID_NUMBER (CIN, SEBI registration, professional registration)
A string listed here is PII at every place it occurs in that paragraph.
"""
GOLD = {
    109: [("MUFG Intime India Private Limited", "ORG")],
    132: [("KSH INTERNATIONAL LIMITED", "ORG")],
    134: [("U28129PN1979PLC141032", "ID_NUMBER")],
    135: [("11/3, 11/4 and 11/5, Village Birdewadi, Chakan Taluka - Khed, Pune – 410 501, Maharashtra, India", "ADDRESS")],
    139: [("KUSHAL SUBBAYYA HEGDE", "PERSON"), ("PUSHPA KUSHAL HEGDE", "PERSON"),
          ("RAJESH KUSHAL HEGDE", "PERSON"), ("ROHIT KUSHAL HEGDE", "PERSON"),
          ("RAKHI GIRIJA SHETTY", "PERSON"), ("DHAULAGIRI FAMILY TRUST", "ORG"), ("EVEREST", "ORG")],
    140: [("MAKALU FAMILY TRUST", "ORG"), ("BROAD FAMILY TRUST", "ORG"), ("ANNAPURNA FAMILY TRUST", "ORG"),
          ("KANCHENJUNGA FAMILY TRUST", "ORG"), ("WATERLOO INDUSTRIAL PARK VI PRIVATE LIMITED", "ORG")],
    170: [("ksh.ipo@nuvama.com", "EMAIL")],
    173: [("Lokesh Shah", "PERSON"), ("Soumavo Sarkar", "PERSON")],
    184: [("Link Intime India Private Limited", "ORG")],
    187: [("kshinternational.ipo@in.mpms.mufg.com", "EMAIL")],
    189: [("kshinternational.ipo@in.mpms.mufg.com", "EMAIL")],
    255: [("Amod Joshi", "PERSON")],
    263: [("201, Tower 2, Montreal Business Centre, Off Pallod Farms, Baner, Pune – 411 045, Maharashtra, India", "ADDRESS")],
    275: [("KSH", "ORG")],
    286: [("Lalit Muljibhai Sarvaiya", "PERSON"), ("M-140388", "ID_NUMBER")],
    296: [("Rajesh Kushal Hegde", "PERSON")],
    314: [("Annapurna Family Trust", "ORG"), ("Kanchenjunga Family Trust", "ORG"),
          ("Waterloo Industrial Park VI Private Limited", "ORG")],
    322: [("Rakhi Girija Shetty", "PERSON"), ("Annapurna Family Trust", "ORG")],
    1497: [("Kanchenjunga Family Trust", "ORG")],
    1536: [("Malabar India Fund Limited", "ORG")],
    2396: [("Al-Ahleia Switchgear Co.", "ORG"), ("Bharat Bijlee Limited", "ORG"),
           ("CG Power and Industrial Solutions Limited", "ORG"),
           ("Emirates Transformer & Switchgear Limited", "ORG"), ("Georgia Transformer Corporation", "ORG"),
           ("Nidec Industrial Automation India Private Limited", "ORG"),
           ("Transformers & Rectifiers (India) Limited", "ORG"), ("Virginia Transformer Corporation", "ORG")],
    3135: [("CARE", "ORG")],
    3499: [("Plot No. F-223, Supa Parner Industrial Park, Mauje Palve Khurd, Taluka Parner, Dist – Ahmednagar, Maharashtra – 414 301", "ADDRESS")],
    4093: [("PCNTDA Green Building Block A 1st and 2nd floor Near Akurdi Railway Station Akurdi, Pune – 411 044 Maharashtra, India", "ADDRESS")],
    4258: [("Kishan Rastogi", "PERSON"), ("Abhijit Diwan", "PERSON")],
    4272: [("kshinternational.ipo@in.mpms.mufg.com", "EMAIL")],
    4274: [("www.in.mpms.mufg.com", "URL"), ("Shanti Gopalkrishnan", "PERSON"), ("INR000004058", "ID_NUMBER")],
    4276: [("U67190MH1999PTC118368", "ID_NUMBER")],
    4282: [("Eric Bacha", "PERSON"), ("Sachin Gawade", "PERSON"), ("Pravin Teli", "PERSON"),
           ("Siddharth Jadhav", "PERSON"), ("Tushar Gavankar", "PERSON")],
    4291: [("L65190GJ1994PLC021012", "ID_NUMBER")],
    4294: [("HDFC Bank Limited", "ORG"), ("Lodha I Think Techno Campus, O-3 Level", "ADDRESS")],
    4297: [("siddharth.jadhav@hdfcbank.com", "EMAIL"), ("sachin.gawade@hdfcbank.com", "EMAIL"),
           ("eric.bacha@hdfcbank.com", "EMAIL"), ("tushar.gavankar@hdfcbank.com", "EMAIL"),
           ("pravin.teli2@hdfcbank.com", "EMAIL"), ("www.hdfcbank.com", "URL")],
    4305: [("163, 5th Floor, H.T.Parekh Marg Backbay Reclamation Churchgate, Mumbai – 400020", "ADDRESS"),
           ("022-68052182", "PHONE"), ("Ipocmg@icicibank.com", "EMAIL"), ("www.icicibank.com", "URL"),
           ("Varun Badai", "PERSON")],
    4310: [("Next to Kanjurmarg Railway Station, Kanjurmarg (East) Mumbai – 400042, Maharashtra, India", "ADDRESS")],
    4313: [("Eric Bacha", "PERSON"), ("Sachin Gawade", "PERSON"), ("Pravin Teli", "PERSON"),
           ("Siddharth Jadhav", "PERSON"), ("Tushar Gavankar", "PERSON")],
    4315: [("L65920MH1994PLC080618", "ID_NUMBER")],
    4376: [("+91 20 6606 4494", "PHONE")],
    4377: [("Hitesh Ramani", "PERSON")],
    4397: [("ICICI Bank", "ORG"), ("3rd Floor, 362, Satguru House Next to Tanishq Showroom, CTS No. 30", "ADDRESS")],
    4412: [("+91 20 2561 8211", "PHONE"), ("Tushar Wakhele", "PERSON"), ("www.sbi.co.in", "URL")],
}
# every other sampled paragraph contains no PII (regulators, defined terms, statutes, prose)
