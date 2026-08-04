from __future__ import annotations

import hashlib
import pandas as pd
import streamlit as st

from compliance import validate
from dashboard import action_items, apply_dashboard_filters, confidence_distribution, status_counts, vehicle_summary
from frs_database import load_reference_catalog, load_reference_sheet, recommended_sheet, release_sheets
from parser import parse_session, records_frame
from release_viewer import field_comparison, release_timeline, target_variants
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
    .gx-card{border:1px solid #dde3ea;border-radius:10px;padding:14px;margin-bottom:10px;background:#fafbfd}
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

rows: list = []
raw_rows: list[dict] = []
for uploaded in sessions:
    try:
        parsed, raw_part = parse_session(uploaded.name, uploaded.getvalue())
        rows.extend(parsed)
        raw_rows.extend(raw_part)
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
        history_sheets = tuple(x.sheet for x in infos if not model_year or x.model_year == model_year)
        release_catalog = cached_reference_catalog(reference_bytes, history_sheets)
    else:
        release_catalog = target_reference
except Exception as exc:
    st.error(f"Unable to read reference data: {exc}")
    st.stop()

with st.spinner("Running Sprint 4 dashboard and compliance analysis…"):
    overview, details, candidates = validate(summary, target_reference, release_catalog)

status = overview.get("Status", pd.Series(dtype=str))

with st.sidebar:
    st.divider()
    st.subheader(t.get("filters", "Filters"))
    all_files = sorted(overview.get("Source File", pd.Series(dtype=str)).dropna().astype(str).unique())
    all_ecus = sorted(overview.get("ECU", pd.Series(dtype=str)).dropna().astype(str).unique())
    all_statuses = sorted(status.dropna().astype(str).unique())
    selected_files = st.multiselect(t["filter_vehicle"], all_files, default=all_files)
    selected_ecus = st.multiselect(t["filter_ecu"], all_ecus, default=all_ecus)
    selected_statuses = st.multiselect(t["filter_status"], all_statuses, default=all_statuses)
    minimum_confidence = st.slider(t["min_confidence"], 0, 100, 0, 5)

filtered_overview, filtered_details = apply_dashboard_filters(
    overview, details, selected_files, selected_ecus, selected_statuses, minimum_confidence
)
filtered_status = filtered_overview.get("Status", pd.Series(dtype=str))

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


tabs = st.tabs([
    t["dashboard"], t["overview"], t["release_viewer"], t["details"], t["identifiers"],
    t["candidates"], t["raw"], t["comparison"]
])
with tabs[0]:
    if filtered_overview.empty:
        st.warning(t["no_results"])
    else:
        total = len(filtered_overview)
        compliant_count = int((filtered_status == "COMPLIANT").sum())
        critical_count = int(filtered_status.isin(["MISMATCH", "WRONG_RELEASE"]).sum())
        avg_conf = pd.to_numeric(filtered_overview.get("Confidence %", pd.Series(dtype=float)), errors="coerce").mean()
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(t["filtered_ecus"], total)
        k2.metric(t["compliance_rate"], f"{(compliant_count / total * 100):.1f}%" if total else "0.0%")
        k3.metric(t["critical_findings"], critical_count)
        k4.metric(t["avg_confidence"], f"{avg_conf:.1f}%" if pd.notna(avg_conf) else "0.0%")

        left_chart, right_chart = st.columns(2)
        with left_chart:
            st.subheader(t["status_distribution"])
            status_df = status_counts(filtered_overview)
            st.bar_chart(status_df.set_index("Status")["Count"], width="stretch")
            st.dataframe(status_df, width="stretch", hide_index=True)
        with right_chart:
            st.subheader(t["confidence_distribution"])
            confidence_df = confidence_distribution(filtered_overview)
            st.bar_chart(confidence_df.set_index("Confidence Band")["Count"], width="stretch")
            st.dataframe(confidence_df, width="stretch", hide_index=True)

        st.subheader(t["vehicle_summary"])
        st.dataframe(vehicle_summary(filtered_overview), width="stretch", hide_index=True)

        st.subheader(t["priority_actions"])
        actions = action_items(filtered_overview, filtered_details)
        if actions.empty:
            st.success("No open compliance actions." if language == "English" else "Keine offenen Konformitätsmaßnahmen.")
        else:
            st.dataframe(actions.style.map(status_style, subset=["Status"]), width="stretch", hide_index=True)

with tabs[1]:
    st.dataframe(filtered_overview.style.map(status_style, subset=["Status"]), width="stretch", hide_index=True)

with tabs[2]:
    vehicle_files = list(summary["Source File"].dropna().unique())
    left, right = st.columns(2)
    selected_file = left.selectbox(t["select_vehicle"], vehicle_files, key="release_vehicle")
    ecu_options = list(summary.loc[summary["Source File"] == selected_file, "ECU ID"].dropna().unique())
    selected_ecu = right.selectbox(t["select_ecu"], ecu_options, key="release_ecu")

    ecu_rows = summary[(summary["Source File"] == selected_file) & (summary["ECU ID"] == selected_ecu)]
    overview_rows = overview[(overview["Source File"] == selected_file) & (overview["ECU"] == selected_ecu)]
    if ecu_rows.empty:
        st.warning("No ECU data available.")
    else:
        ecu_row = ecu_rows.iloc[0]
        ov = overview_rows.iloc[0] if not overview_rows.empty else pd.Series(dtype=object)
        best_history_df = release_timeline(ecu_row, release_catalog)
        best_history = best_history_df.iloc[0] if not best_history_df.empty else pd.Series(dtype=object)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(t["decision"], ov.get("Status", "NO_REFERENCE"))
        m2.metric(t["confidence"], f"{int(ov.get('Confidence %', 0) or 0)}%")
        m3.metric(t["best_history"], best_history.get("Release", "—") or "—")
        m4.metric(t["target_release"], ov.get("Target Release", "—") or "—")
        st.info(str(ov.get("Decision Reason", "")))

        st.subheader(t["installed_values"])
        installed_columns = [
            "ECU ID", "ECU Name", "VIN", "Hardware Number", "Application SW", "Calibration SW",
            "Part Number", "Basic SW", "Software Number", "Bootloader", "DTC Count"
        ]
        installed_df = pd.DataFrame([ecu_row.reindex(installed_columns).to_dict()])
        st.dataframe(installed_df, width="stretch", hide_index=True)

        variants = target_variants(ecu_row, target_reference)
        matched_variant = str(ov.get("Matched Variant", ""))
        matched = variants[variants["ECU Variant"].astype(str) == matched_variant] if not variants.empty else pd.DataFrame()
        if matched.empty and not variants.empty:
            matched = variants.iloc[[0]]
        st.subheader(t["target_values"])
        if matched.empty:
            st.warning("No target variant exists for this ECU.")
        else:
            comparison_df = field_comparison(ecu_row, matched.iloc[0])
            st.dataframe(comparison_df.style.map(status_style, subset=["Status"]), width="stretch", hide_index=True)

        st.subheader(t["release_history"])
        if best_history_df.empty:
            st.info("No historical reference found.")
        else:
            display_history = best_history_df.drop(columns=["Release Rank"], errors="ignore")
            st.dataframe(display_history, width="stretch", hide_index=True)

        with st.expander(t["target_variants"]):
            if variants.empty:
                st.info("No target variants found.")
            else:
                st.dataframe(variants.drop(columns=["Release Rank"], errors="ignore"), width="stretch", hide_index=True)

with tabs[3]:
    st.dataframe(filtered_details.style.map(status_style, subset=["Status"]), width="stretch", hide_index=True)
with tabs[4]:
    st.dataframe(summary, width="stretch", hide_index=True)
with tabs[5]:
    st.dataframe(candidates.sort_values(["Source File", "ECU", "Candidate Score"], ascending=[True, True, False]), width="stretch", hide_index=True)
with tabs[6]:
    st.dataframe(raw, width="stretch", hide_index=True)
with tabs[7]:
    files = list(summary["Source File"].unique())
    if len(files) < 2:
        st.info("Upload at least two session files." if language == "English" else "Mindestens zwei Session-Dateien hochladen.")
    else:
        left_col, right_col = st.columns(2)
        file_a = left_col.selectbox("Vehicle A", files, index=0)
        file_b = right_col.selectbox("Vehicle B", files, index=1)
        fields = ["Hardware Number", "Application SW", "Calibration SW", "Part Number", "Basic SW", "Software Number", "Bootloader"]
        left_df = summary[summary["Source File"] == file_a].set_index("ECU ID")[fields]
        right_df = summary[summary["Source File"] == file_b].set_index("ECU ID")[fields]
        comparison = left_df.join(right_df, how="outer", lsuffix=" A", rsuffix=" B").reset_index()
        st.dataframe(comparison, width="stretch", hide_index=True)

excel = build_report(overview, details, summary, raw, candidates, selected)
st.download_button(
    t["download"], excel, "GradeX_Software_Compliance_Report_Sprint4.xlsx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary"
)
