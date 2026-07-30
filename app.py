from __future__ import annotations
import pandas as pd
import streamlit as st
from parser import parse_session, records_frame
from frs_database import load_reference_sheet, recommended_sheet, release_sheets
from compliance import validate
from report import build_report
from translations import TEXT
from utils import model_year_from_vin

st.set_page_config(page_title="Grade-X Software Compliance Checker", page_icon="✅", layout="wide")
st.markdown("""<style>.block-container{padding-top:1.4rem}.stMetric{border:1px solid #e6e6e6;border-radius:8px;padding:12px}</style>""", unsafe_allow_html=True)

with st.sidebar:
    language = st.selectbox("Language / Sprache", ["English", "Deutsch"])
t = TEXT[language]
st.title(t["title"]); st.caption(t["subtitle"])

sessions = st.file_uploader(t["sessions"], type=["session", "xml"], accept_multiple_files=True)
reference_file = st.file_uploader(t["reference"], type=["xlsx", "xlsm"])
if not sessions or reference_file is None:
    st.info(t["upload_info"]); st.stop()

rows, raw_rows, errors = [], [], []
for f in sessions:
    try:
        r, raw = parse_session(f.name, f.getvalue()); rows += r; raw_rows += raw
    except Exception as exc: errors.append(f"{f.name}: {exc}")
for error in errors: st.error(error)
if not rows: st.stop()
summary = records_frame(rows); raw = pd.DataFrame(raw_rows)
model_years = [model_year_from_vin(x) for x in summary["VIN"].dropna().astype(str).unique()]
model_year = next((x for x in model_years if x), "")

ref_bytes = reference_file.getvalue()
@st.cache_data(show_spinner=False)
def cached_release_sheets(data: bytes): return release_sheets(data)
@st.cache_data(show_spinner=False)
def cached_reference(data: bytes, sheet: str): return load_reference_sheet(data, sheet)
infos = cached_release_sheets(ref_bytes)
options = [x.sheet for x in infos]
default = recommended_sheet(infos, model_year)
selected = st.selectbox(t["release"], options, index=options.index(default) if default in options else 0)
reference = cached_reference(ref_bytes, selected)
overview, details, candidates = validate(summary, reference)

c1,c2,c3,c4,c5 = st.columns(5)
c1.metric(t["ecus"], len(overview)); c2.metric(t["compliant"], int((overview.Status=="COMPLIANT").sum()))
c3.metric(t["mismatch"], int((overview.Status=="MISMATCH").sum()))
c4.metric(t["review"], int(overview.Status.isin(["PART_MATCH","REVIEW"]).sum()))
c5.metric(t["no_reference"], int((overview.Status=="NO_REFERENCE").sum()))

status_filter = st.multiselect("Status", sorted(overview.Status.unique()), default=sorted(overview.Status.unique()))
filtered_overview = overview[overview.Status.isin(status_filter)]

def status_style(value):
    colors={"COMPLIANT":"background-color:#C6EFCE","MATCH":"background-color:#C6EFCE","MISMATCH":"background-color:#FFC7CE",
            "PART_MATCH":"background-color:#FFEB9C","REVIEW":"background-color:#FFEB9C","MISSING":"background-color:#FFEB9C",
            "NO_REFERENCE":"background-color:#D9E1F2","NOT_APPLICABLE":"background-color:#E7E6E6"}
    return colors.get(str(value), "")

tabs = st.tabs([t["overview"], t["details"], t["identifiers"], t["candidates"], t["raw"], t["comparison"]])
with tabs[0]: st.dataframe(filtered_overview.style.map(status_style, subset=["Status"]), use_container_width=True, hide_index=True)
with tabs[1]: st.dataframe(details.style.map(status_style, subset=["Status"]), use_container_width=True, hide_index=True)
with tabs[2]: st.dataframe(summary, use_container_width=True, hide_index=True)
with tabs[3]: st.dataframe(candidates.sort_values(["Source File","ECU","Candidate Score"], ascending=[True,True,False]), use_container_width=True, hide_index=True)
with tabs[4]: st.dataframe(raw, use_container_width=True, hide_index=True)
with tabs[5]:
    files = list(summary["Source File"].unique())
    if len(files) < 2: st.info("Upload at least two session files / Mindestens zwei Session-Dateien hochladen.")
    else:
        a,b = st.columns(2); fa=a.selectbox("Vehicle A",files,index=0); fb=b.selectbox("Vehicle B",files,index=1)
        fields=["Hardware Number","Application SW","Calibration SW","Part Number","Basic SW","Software Number","Bootloader"]
        left=summary[summary["Source File"]==fa].set_index("ECU ID")[fields]; right=summary[summary["Source File"]==fb].set_index("ECU ID")[fields]
        comp=left.join(right,how="outer",lsuffix=" A",rsuffix=" B").reset_index()
        st.dataframe(comp,use_container_width=True,hide_index=True)

excel = build_report(overview, details, summary, raw, candidates, selected)
st.download_button(t["download"], excel, "GradeX_Software_Compliance_Report.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
