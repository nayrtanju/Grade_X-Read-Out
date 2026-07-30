from __future__ import annotations

import hashlib
import pandas as pd
import streamlit as st

from compliance import validate
from frs_database import load_reference_catalog, load_reference_sheet, recommended_sheet, release_sheets
from parser import parse_session, records_frame
from report import build_report
from translations import TEXT
from utils import model_year_from_vin

APP_TITLE = "Grade-X Software Compliance Checker"

st.set_page_config(page_title=APP_TITLE, page_icon="✅", layout="wide")
st.markdown(
    """
    <style>
    .block-container{padding-top:1.4rem}
    .stMetric{border:1px solid #e6e6e6;border-radius:8px;padding:12px}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def cached_release_sheets(workbook_data: bytes):
    return release_sheets(workbook_data)


@st.cache_data(show_spinner=False)
def cached_reference_sheet(workbook_data: bytes, sheet_name: str):
    return load_reference_sheet(workbook_data, sheet_name)


@st.cache_data(show_spinner=False)
def cached_reference_catalog(workbook_data: bytes, sheet_names: tuple[str, ...]):
    return load_reference_catalog(workbook_data, list(sheet_names))


with st.sidebar:
    language = st.selectbox("Language / Sprache", ["English", "Deutsch"])
    t = TEXT[language]
    st.divider()
    history_mode = st.toggle(t["history_mode"], value=True, help=t["history_help"])
    st.caption(
        "Direct workbook mode: the reference file is processed in memory and is not stored."
        if language == "English"
        else "Direkter Arbeitsmappenmodus: Die Referenzdatei wird im Speicher verarbeitet und nicht gespeichert."
    )

st.title(t["title"])
st.caption(t["subtitle"])

upload_left, upload_right = st.columns(2)
with upload_left:
    sessions = st.file_uploader(t["sessions"], type=["session", "xml"], accept_multiple_files=True)
with upload_right:
    reference_file = st.file_uploader(t["reference"], type=["xlsx", "xlsm"])

if not sessions or reference_file is None:
    st.info(t["upload_info"])
    st.stop()

reference_bytes = reference_file.getvalue()
reference_hash = hashlib.sha256(reference_bytes).hexdigest()
st.caption(f"Reference: {reference_file.name} · SHA-256: {reference_hash[:12]}… · {len(reference_bytes)/(1024*1024):.1f} MB")

rows: list[dict] = []
raw_rows: list[dict] = []
for uploaded in sessions:
    try:
        parsed, raw = parse_session(uploaded.name, uploaded.getvalue())
        rows.extend(parsed)
        raw_rows.extend(raw)
    except Exception as exc:
        st.error(f"{uploaded.name}: {exc}")

if not rows:
    st.stop()
summary = records_frame(rows)
raw = pd.DataFrame(raw_rows)
model_years = [model_year_from_vin(v) for v in summary["VIN"].dropna().astype(str).unique()]
model_year = next((v for v in model_years if v), "")

try:
    infos = cached_release_sheets(reference_bytes)
except Exception as exc:
    st.error(f"Unable to read the FRS/IASRC workbook: {exc}")
    st.stop()
options = [item.sheet for item in infos]
if not options:
    st.error("No FRS/IASRC release sheets were found.")
    st.stop()

default = recommended_sheet(infos, model_year)
selected = st.selectbox(t["release"], options, index=options.index(default) if default in options else 0)

try:
    target_reference = cached_reference_sheet(reference_bytes, selected)
    if history_mode:
        # Restrict history to the detected model year where possible. This improves speed and avoids false cross-MY matches.
        history_sheets = tuple(x.sheet for x in infos if not model_year or x.model_year == model_year)
        release_catalog = cached_reference_catalog(reference_bytes, history_sheets)
    else:
        release_catalog = target_reference
except Exception as exc:
    st.error(f"Unable to read reference data: {exc}")
    st.stop()

with st.spinner("Running Sprint 2 compliance analysis…"):
    overview, details, candidates = validate(summary, target_reference, release_catalog)

status = overview.get("Status", pd.Series(dtype=str))
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(t["ecus"], len(overview))
c2.metric(t["compliant"], int((status == "COMPLIANT").sum()))
c3.metric(t["update"], int((status == "UPDATE_AVAILABLE").sum()))
c4.metric(t["mismatch"], int(status.isin(["MISMATCH", "WRONG_RELEASE"]).sum()))
c5.metric(t["review"], int(status.isin(["PARTIAL_MATCH", "REVIEW", "NO_REFERENCE"]).sum()))

status_filter = st.multiselect("Status", sorted(status.unique()), default=sorted(status.unique()))
filtered_overview = overview[overview.Status.isin(status_filter)]


def status_style(value):
    colors = {
        "COMPLIANT": "background-color:#C6EFCE", "MATCH": "background-color:#C6EFCE",
        "UPDATE_AVAILABLE": "background-color:#FFF2CC", "PARTIAL_MATCH": "background-color:#FFEB9C",
        "PART_MATCH": "background-color:#FFEB9C", "REVIEW": "background-color:#FCE4D6",
        "MISSING": "background-color:#FCE4D6", "MISMATCH": "background-color:#FFC7CE",
        "WRONG_RELEASE": "background-color:#F4B084", "NO_REFERENCE": "background-color:#D9E1F2",
        "NOT_APPLICABLE": "background-color:#E7E6E6",
    }
    return colors.get(str(value), "")


tabs = st.tabs([t["overview"], t["details"], t["identifiers"], t["candidates"], t["raw"], t["comparison"]])
with tabs[0]:
    st.dataframe(filtered_overview.style.map(status_style, subset=["Status"]), use_container_width=True, hide_index=True)
with tabs[1]:
    st.dataframe(details.style.map(status_style, subset=["Status"]), use_container_width=True, hide_index=True)
with tabs[2]:
    st.dataframe(summary, use_container_width=True, hide_index=True)
with tabs[3]:
    st.dataframe(candidates.sort_values(["Source File", "ECU", "Candidate Score"], ascending=[True, True, False]), use_container_width=True, hide_index=True)
with tabs[4]:
    st.dataframe(raw, use_container_width=True, hide_index=True)
with tabs[5]:
    files = list(summary["Source File"].unique())
    if len(files) < 2:
        st.info("Upload at least two session files." if language == "English" else "Mindestens zwei Session-Dateien hochladen.")
    else:
        left_col, right_col = st.columns(2)
        file_a = left_col.selectbox("Vehicle A", files, index=0)
        file_b = right_col.selectbox("Vehicle B", files, index=1)
        fields = ["Hardware Number", "Application SW", "Calibration SW", "Part Number", "Basic SW", "Software Number", "Bootloader"]
        left = summary[summary["Source File"] == file_a].set_index("ECU ID")[fields]
        right = summary[summary["Source File"] == file_b].set_index("ECU ID")[fields]
        comparison = left.join(right, how="outer", lsuffix=" A", rsuffix=" B").reset_index()
        st.dataframe(comparison, use_container_width=True, hide_index=True)

excel = build_report(overview, details, summary, raw, candidates, selected)
st.download_button(t["download"], excel, "GradeX_Software_Compliance_Report_Sprint2.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
