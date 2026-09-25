"""Streamlit front end:  streamlit run app.py

Upload a .docx, get back a redacted .docx. Files are processed in memory and never stored.
"""
import io
import time

import pandas as pd
import streamlit as st

from pii_redactor import Policy, Redactor
from pii_redactor.pipeline import load_spacy

LABELS = ["PERSON", "ORG", "EMAIL", "PHONE", "ADDRESS", "LOCALITY", "URL", "ID_NUMBER",
          "AADHAAR", "SSN", "CREDIT_CARD", "DOB", "IP_ADDRESS"]
MAX_MB = 10

st.set_page_config(page_title="PII Redactor", page_icon="🔒", layout="wide")


@st.cache_resource(show_spinner="Loading language model...")
def get_nlp():
    return load_spacy()


st.title("PII Redaction Tool")
st.caption("Detects personal data in a Word document and replaces it with realistic, consistent fake values. "
           "Formatting, tables and headers are preserved. Your file is processed in memory and not stored.")

with st.sidebar:
    st.header("Options")
    mode = st.radio("Detection mode", ["hybrid", "regex"], format_func=lambda m: {
        "hybrid": "Hybrid: patterns + NER + name lexicon (recommended)",
        "regex": "Regex only: fastest, misses names and companies"}[m])
    skip = st.multiselect("Leave these types untouched", LABELS, help="e.g. keep company names or websites")
    seed = st.text_input("Seed", "pii-redactor", help="Same seed + same file = identical fake values")
    st.markdown("**Kept on purpose:** regulators, stock exchanges and depositories (SEBI, BSE, NSE, RoC ...), "
                "ordinary dates, amounts, order and ticket numbers.")

upload = st.file_uploader(f"Word document (.docx, up to {MAX_MB} MB)", type=["docx"])

if upload is not None:
    if upload.size > MAX_MB * 1024 * 1024:
        st.error(f"File is larger than {MAX_MB} MB.")
        st.stop()
    if st.button("Redact document", type="primary"):
        t0 = time.time()
        with st.spinner("Reading, detecting and replacing PII ..."):
            red = Redactor(Policy(mode=mode, skip_labels=frozenset(skip), seed=seed),
                           nlp=get_nlp() if mode == "hybrid" else None)
            out = io.BytesIO()
            try:
                report = red.redact_file(io.BytesIO(upload.getvalue()), out)
            except Exception as exc:                       # a corrupt or password-protected file
                st.error(f"Could not process this file: {exc}")
                st.stop()
        st.success(f"Done in {time.time() - t0:.1f}s: {len(report.entities)} values replaced.")

        left, right = st.columns([1, 2])
        counts = pd.Series(report.counts, name="replaced").sort_values(ascending=False)
        with left:
            st.download_button("Download redacted .docx", out.getvalue(),
                               file_name=f"redacted_{upload.name}",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               type="primary")
            st.dataframe(counts, use_container_width=True)
        with right:
            st.bar_chart(counts)

        rows = pd.DataFrame(report.entities)
        if not rows.empty:
            unique = (rows.drop_duplicates(["label", "original"])[["label", "original", "replacement"]]
                      .rename(columns={"original": "before", "replacement": "after"}))
            with st.expander(f"What changed ({len(unique)} distinct values)"):
                st.caption("Shown to you only; nothing is logged. Use this to spot anything that should not have changed.")
                st.dataframe(unique, use_container_width=True, hide_index=True)
else:
    st.info("Upload a .docx to begin. Tip: try it on a document with names, emails, phone numbers and addresses.")
