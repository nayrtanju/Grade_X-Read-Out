from __future__ import annotations

import hashlib
import pandas as pd
import streamlit as st

from compliance import validate
from dashboard import action_items, apply_dashboard_filters, confidence_distribution, status_counts, vehicle_summary
from frs_database import load_reference_catalog, load_reference_sheet, recommended_sheet, release_sheets
from parser import parse_session, records_frame
from dtc_parser import combine_dtc_results, correlate_dtc_with_ecus, infer_session_mapping, parse_dtc_log
from release_viewer import field_comparison, release_timeline, target_variants
from report import build_report
from professional_report import build_pdf_report
from translations import TEXT
from utils import model_year_from_vin
from vehicle_history import build_change_log, build_vehicle_history, fleet_summary
from risk_engine import apply_risk_assessment, load_risk_rules, vehicle_health_summary
from decision_engine import apply_decision_advisor, load_decision_rules, vehicle_decision_summary
from warranty_engine import ecu_warranty_triage, enhanced_vehicle_health, load_warranty_rules, warranty_triage_summary
from engineering_summary import engineering_summary, fleet_engineering_summary
from dependency_engine import build_dependency_analysis, load_dependency_rules
from root_cause_engine import rank_root_ecus, root_cause_path_summary
from consistency_engine import analyze_release_consistency, load_consistency_rules
from fleet_intelligence import build_fleet_intelligence, load_fleet_rules
from findings_engine import generate_engineering_findings
from engineering_assistant import build_engineering_assistant, load_assistant_rules

APP_TITLE = "Grade-X Software Configuration Intelligence Platform"

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

upload_left, upload_middle, upload_right = st.columns(3)
with upload_left:
    sessions = st.file_uploader(t["sessions"], type=["session", "xml"], accept_multiple_files=True)
with upload_middle:
    reference_file = st.file_uploader(t["reference"], type=["xlsx", "xlsm"])
with upload_right:
    dtc_logs = st.file_uploader(
        t["dtc_logs"], type=["log", "txt"], accept_multiple_files=True,
        help=t["dtc_logs_help"],
    )

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

dtc_results = []
session_file_names = list(summary["Source File"].dropna().astype(str).unique())
if dtc_logs:
    with st.expander(t["dtc_mapping"], expanded=len(session_file_names) > 1):
        st.caption(t["dtc_mapping_help"])
        for index, log_file in enumerate(dtc_logs):
            inferred = infer_session_mapping(log_file.name, session_file_names)
            mapping_options = [""] + session_file_names
            default_index = mapping_options.index(inferred) if inferred in mapping_options else 0
            mapped_session = st.selectbox(
                f"{log_file.name} → {t['mapped_session']}",
                mapping_options,
                index=default_index,
                format_func=lambda x: x or t["unassigned"],
                key=f"dtc_mapping_{index}_{log_file.name}",
            )
            try:
                dtc_results.append(parse_dtc_log(log_file.name, log_file.getvalue(), mapped_session))
            except Exception as exc:
                st.error(f"{log_file.name}: {exc}")

dtc_summary, dtc_events = combine_dtc_results(dtc_results)
summary = correlate_dtc_with_ecus(summary, dtc_summary)

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

with st.spinner("Running Sprint 8.2 configuration, risk and decision-support analysis…"):
    overview, details, candidates = validate(summary, target_reference, release_catalog)

dtc_columns = ["Source File", "ECU ID", "External DTC Count", "Persistent DTC Count", "DTC Codes", "DTC Severity", "Risk Score", "Risk Level", "Top Contributors"]
available_dtc_columns = [c for c in dtc_columns if c in summary.columns]
if available_dtc_columns:
    overview = overview.merge(
        summary[available_dtc_columns].rename(columns={"ECU ID": "ECU"}),
        on=["Source File", "ECU"],
        how="left",
    )
for column, default_value in {
    "External DTC Count": 0,
    "Persistent DTC Count": 0,
    "DTC Codes": "",
    "DTC Severity": "",
}.items():
    if column not in overview.columns:
        overview[column] = default_value
    else:
        overview[column] = overview[column].fillna(default_value)

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


vehicle_history = build_vehicle_history(summary, overview)
change_log = build_change_log(vehicle_history)
fleet_overview = fleet_summary(vehicle_history, change_log)

risk_rules = load_risk_rules()
overview, risk_breakdown = apply_risk_assessment(
    overview,
    details=details,
    change_log=change_log,
    rules=risk_rules,
)
vehicle_health = vehicle_health_summary(overview)

decision_rules = load_decision_rules()
overview, decision_actions = apply_decision_advisor(
    overview,
    details=details,
    change_log=change_log,
    rules=decision_rules,
)
vehicle_decisions = vehicle_decision_summary(overview)

warranty_rules = load_warranty_rules()
vehicle_health = enhanced_vehicle_health(
    overview,
    change_log=change_log,
    rules=warranty_rules,
)
warranty_summary = warranty_triage_summary(
    overview,
    vehicle_health,
    rules=warranty_rules,
)
ecu_warranty = ecu_warranty_triage(overview, rules=warranty_rules)
engineering_summaries = engineering_summary(
    overview,
    vehicle_health,
    warranty_summary,
    language=language,
)
fleet_summary_text = fleet_engineering_summary(
    engineering_summaries,
    language=language,
)

dependency_rules = load_dependency_rules()
dependency_nodes, dependency_edges = build_dependency_analysis(
    summary,
    rules=dependency_rules,
)
vehicle_root_causes, root_cause_ranking = rank_root_ecus(
    overview,
    dependency_nodes,
    dependency_edges,
    change_log=change_log,
    rules=dependency_rules,
)
root_cause_paths = root_cause_path_summary(
    vehicle_root_causes,
    dependency_edges,
)

consistency_rules = load_consistency_rules()
release_consistency, consistency_fields, ecu_consistency = analyze_release_consistency(
    overview,
    details,
    summary,
    rules=consistency_rules,
)

fleet_rules = load_fleet_rules()
fleet_intelligence = build_fleet_intelligence(
    overview,
    vehicle_health,
    release_consistency,
    ecu_consistency,
    warranty_summary,
    vehicle_root_causes,
    dtc_summary,
    rules=fleet_rules,
)

engineering_findings = generate_engineering_findings(
    overview,
    vehicle_health,
    warranty_summary,
    vehicle_root_causes,
    release_consistency,
    fleet_alerts=fleet_intelligence["alerts"],
)
assistant_rules = load_assistant_rules()
assistant_summary, assistant_action_plan = build_engineering_assistant(
    overview,
    vehicle_health,
    warranty_summary,
    vehicle_root_causes,
    release_consistency,
    engineering_findings,
    fleet_intelligence=fleet_intelligence,
    rules=assistant_rules,
)

# Reapply dashboard filters after the intelligence columns are added.
filtered_overview, filtered_details = apply_dashboard_filters(
    overview, details, selected_files, selected_ecus, selected_statuses, minimum_confidence
)
filtered_status = filtered_overview.get("Status", pd.Series(dtype=str))

tabs = st.tabs([
    t["dashboard"], t["overview"], t["release_viewer"], t["dtc_center"], t["fleet_history"],
    t["risk_assessment"], t["decision_center"], t["vehicle_intelligence"],
    t["dependency_analysis"], t["root_cause_analysis"], t["release_consistency"],
    t["fleet_intelligence"], t["engineering_assistant"], t["details"], t["identifiers"],
    t["candidates"], t["raw"], t["comparison"], t["report_center"]
])
with tabs[0]:
    if filtered_overview.empty:
        st.warning(t["no_results"])
    else:
        total = len(filtered_overview)
        compliant_count = int((filtered_status == "COMPLIANT").sum())
        critical_count = int(filtered_status.isin(["MISMATCH", "WRONG_RELEASE"]).sum())
        avg_conf = pd.to_numeric(filtered_overview.get("Confidence %", pd.Series(dtype=float)), errors="coerce").mean()
        persistent_dtc_count = int(pd.to_numeric(
            filtered_overview.get("Persistent DTC Count", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0).sum())
        average_risk = pd.to_numeric(
            filtered_overview.get("Risk Score", pd.Series(dtype=float)), errors="coerce"
        ).mean()
        critical_risk_ecus = int(
            (filtered_overview.get("Risk Level", pd.Series(dtype=str)).astype(str) == "CRITICAL").sum()
        )
        selected_health = vehicle_health[
            vehicle_health["Source File"].isin(selected_files)
        ] if selected_files else vehicle_health
        avg_vehicle_health = pd.to_numeric(
            selected_health.get("Vehicle Health Score", pd.Series(dtype=float)),
            errors="coerce",
        ).mean()
        escalation_count = int(
            warranty_summary[
                warranty_summary["Source File"].isin(selected_files)
            ]["Warranty Recommendation"].eq("ENGINEERING_ESCALATION").sum()
        ) if selected_files and not warranty_summary.empty else int(
            warranty_summary.get("Warranty Recommendation", pd.Series(dtype=str))
            .eq("ENGINEERING_ESCALATION").sum()
        )
        selected_root_causes = vehicle_root_causes[
            vehicle_root_causes["Source File"].isin(selected_files)
        ] if selected_files and not vehicle_root_causes.empty else vehicle_root_causes
        lead_root_ecu = (
            selected_root_causes.sort_values(
                "Root Cause Confidence %", ascending=False
            ).iloc[0]["Most Probable Root ECU"]
            if not selected_root_causes.empty else "—"
        )
        selected_consistency = release_consistency[
            release_consistency["Source File"].isin(selected_files)
        ] if selected_files and not release_consistency.empty else release_consistency
        avg_consistency = pd.to_numeric(
            selected_consistency.get("Release Consistency Score", pd.Series(dtype=float)),
            errors="coerce",
        ).mean()
        k1, k2, k3, k4, k5, k6, k7, k8, k9, k10, k11 = st.columns(11)
        k1.metric(t["filtered_ecus"], total)
        k2.metric(t["compliance_rate"], f"{(compliant_count / total * 100):.1f}%" if total else "0.0%")
        k3.metric(t["critical_findings"], critical_count)
        k4.metric(t["persistent_dtcs"], persistent_dtc_count)
        k5.metric(t["average_risk"], f"{average_risk:.1f}" if pd.notna(average_risk) else "0.0")
        k6.metric(t["critical_risk_ecus"], critical_risk_ecus)
        k7.metric(t["vehicle_health_score"], f"{avg_vehicle_health:.1f}%" if pd.notna(avg_vehicle_health) else "0.0%")
        k8.metric(t["engineering_escalations"], escalation_count)
        k9.metric(t["probable_root_ecu"], lead_root_ecu)
        k10.metric(t["release_consistency_score"], f"{avg_consistency:.1f}%" if pd.notna(avg_consistency) else "0.0%")
        k11.metric(t["avg_confidence"], f"{avg_conf:.1f}%" if pd.notna(avg_conf) else "0.0%")

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

        st.markdown(f"### {t['engineering_advisor']}")
        a1, a2, a3, a4 = st.columns(4)
        a1.metric(t["advisor_decision"], ov.get("Decision", "—") or "—")
        a2.metric(t["decision_urgency"], ov.get("Decision Urgency", "—") or "—")
        a3.metric(t["decision_confidence"], f"{float(ov.get('Decision Confidence %', 0) or 0):.0f}%")
        a4.metric(t["risk_score"], f"{float(ov.get('Risk Score', 0) or 0):.0f}/100")
        st.warning(str(ov.get("Primary Root Cause", "")))
        st.markdown(f"**{t['recommended_actions']}:**")
        for action in str(ov.get("Recommended Actions", "")).split(" | "):
            if action.strip():
                st.markdown(f"- {action.strip()}")

        st.subheader(t["installed_values"])
        installed_columns = [
            "ECU ID", "ECU Name", "VIN", "Hardware Number", "Application SW", "Calibration SW",
            "Part Number", "Basic SW", "Software Number", "Bootloader", "DTC Count", "External DTC Count", "Persistent DTC Count", "DTC Codes", "DTC Severity", "Risk Score", "Risk Level", "Top Contributors"
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
    st.subheader(t["dtc_center"])
    if dtc_summary.empty:
        st.info(t["no_dtc_logs"])
    else:
        d1, d2, d3, d4 = st.columns(4)
        d1.metric(t["unique_dtcs"], len(dtc_summary))
        d2.metric(t["affected_ecus"], dtc_summary["ECU"].nunique())
        d3.metric(t["reappeared_dtcs"], int((dtc_summary["Persistence"] == "REAPPEARED_AFTER_CLEAR").sum()))
        d4.metric(t["dtc_events"], len(dtc_events))

        severity_filter = st.multiselect(
            t["dtc_severity"], sorted(dtc_summary["Severity"].dropna().astype(str).unique()),
            default=sorted(dtc_summary["Severity"].dropna().astype(str).unique()),
        )
        persistence_filter = st.multiselect(
            t["dtc_persistence"], sorted(dtc_summary["Persistence"].dropna().astype(str).unique()),
            default=sorted(dtc_summary["Persistence"].dropna().astype(str).unique()),
        )
        dtc_view = dtc_summary[
            dtc_summary["Severity"].isin(severity_filter)
            & dtc_summary["Persistence"].isin(persistence_filter)
        ].copy()
        st.dataframe(dtc_view, width="stretch", hide_index=True)

        with st.expander(t["dtc_event_log"]):
            st.dataframe(dtc_events, width="stretch", hide_index=True)

with tabs[4]:
    st.subheader(t["fleet_history"])
    h1, h2, h3, h4 = st.columns(4)
    h1.metric(t["vehicles"], int(vehicle_history["VIN"].nunique()) if not vehicle_history.empty else 0)
    h2.metric(t["sessions_count"], int(vehicle_history["Source File"].nunique()) if not vehicle_history.empty else 0)
    h3.metric(t["software_changes"], int((change_log.get("Change Type", pd.Series(dtype=str)) == "SOFTWARE_CHANGE").sum()) if not change_log.empty else 0)
    h4.metric(t["regressions"], int(change_log.get("Regression", pd.Series(dtype=bool)).fillna(False).sum()) if not change_log.empty else 0)
    st.markdown(f"### {t['fleet_summary']}")
    st.dataframe(fleet_overview, width="stretch", hide_index=True)
    st.markdown(f"### {t['change_log']}")
    if change_log.empty:
        st.info(t["no_history_changes"])
    else:
        history_status = change_log["Regression"].map({True: "MISMATCH", False: "MATCH"})
        styled_changes = change_log.assign(_Status=history_status).style.map(status_style, subset=["_Status"])
        st.dataframe(styled_changes, width="stretch", hide_index=True)
    with st.expander(t["history_records"]):
        st.dataframe(vehicle_history, width="stretch", hide_index=True)

with tabs[5]:
    st.subheader(t["risk_assessment"])
    if overview.empty:
        st.info(t["no_risk_results"])
    else:
        r1, r2, r3, r4 = st.columns(4)
        average_risk_all = pd.to_numeric(overview["Risk Score"], errors="coerce").mean()
        critical_count_all = int((overview["Risk Level"].astype(str) == "CRITICAL").sum())
        highest_row = overview.sort_values("Risk Score", ascending=False).iloc[0]
        average_health = pd.to_numeric(
            vehicle_health.get("Vehicle Health Score", pd.Series(dtype=float)), errors="coerce"
        ).mean()
        r1.metric(t["average_risk"], f"{average_risk_all:.1f}")
        r2.metric(t["critical_risk_ecus"], critical_count_all)
        r3.metric(t["highest_risk_ecu"], f"{highest_row.get('ECU', '')} ({highest_row.get('Risk Score', 0):.0f})")
        r4.metric(t["average_vehicle_health"], f"{average_health:.1f}%" if pd.notna(average_health) else "0.0%")

        st.markdown(f"### {t['vehicle_health']}")
        st.dataframe(vehicle_health, width="stretch", hide_index=True)

        risk_levels = sorted(overview["Risk Level"].dropna().astype(str).unique())
        selected_risk_levels = st.multiselect(
            t["risk_level"], risk_levels, default=risk_levels, key="risk_level_filter"
        )
        risk_view = overview[overview["Risk Level"].isin(selected_risk_levels)].copy()
        display_columns = [
            "Source File", "VIN", "ECU", "Status", "Risk Score", "Risk Level",
            "Top Contributors", "Risk Factor Count", "DTC Codes", "Decision Reason",
        ]
        display_columns = [column for column in display_columns if column in risk_view.columns]
        st.markdown(f"### {t['ecu_risk_overview']}")
        st.dataframe(
            risk_view[display_columns].sort_values("Risk Score", ascending=False),
            width="stretch", hide_index=True
        )

        st.markdown(f"### {t['risk_explainability']}")
        risk_sources = sorted(risk_view["Source File"].dropna().astype(str).unique())
        if risk_sources:
            risk_source = st.selectbox(t["vehicle_session"], risk_sources, key="risk_source")
            risk_ecus = sorted(
                risk_view[risk_view["Source File"] == risk_source]["ECU"].dropna().astype(str).unique()
            )
            if risk_ecus:
                risk_ecu = st.selectbox(t["ecu"], risk_ecus, key="risk_ecu")
                selected_assessment = risk_view[
                    (risk_view["Source File"] == risk_source) & (risk_view["ECU"] == risk_ecu)
                ].iloc[0]
                x1, x2, x3 = st.columns(3)
                x1.metric(t["risk_score"], f"{selected_assessment['Risk Score']:.0f}/100")
                x2.metric(t["risk_level"], selected_assessment["Risk Level"])
                x3.metric(t["risk_factor_count"], int(selected_assessment["Risk Factor Count"]))
                breakdown_view = risk_breakdown[
                    (risk_breakdown["Source File"] == risk_source)
                    & (risk_breakdown["ECU"] == risk_ecu)
                ].copy()
                st.dataframe(breakdown_view, width="stretch", hide_index=True)

with tabs[6]:
    st.subheader(t["decision_center"])
    st.caption(t["decision_center_help"])

    if overview.empty:
        st.info(t["no_decision_results"])
    else:
        q1, q2, q3, q4 = st.columns(4)
        high_critical = int(overview["Decision Urgency"].isin(["HIGH", "CRITICAL"]).sum())
        manual_reviews = int(overview["Decision"].astype(str).str.contains("REVIEW").sum())
        avg_decision_conf = pd.to_numeric(
            overview["Decision Confidence %"], errors="coerce"
        ).mean()
        action_total = len(decision_actions)

        q1.metric(t["high_critical_decisions"], high_critical)
        q2.metric(t["manual_reviews"], manual_reviews)
        q3.metric(t["average_decision_confidence"], f"{avg_decision_conf:.1f}%")
        q4.metric(t["recommended_action_count"], action_total)

        st.markdown(f"### {t['vehicle_decision_summary']}")
        st.dataframe(vehicle_decisions, width="stretch", hide_index=True)

        decision_sources = sorted(overview["Source File"].dropna().astype(str).unique())
        decision_source = st.selectbox(
            t["vehicle_session"], decision_sources, key="decision_source"
        )
        decision_ecus = sorted(
            overview[overview["Source File"] == decision_source]["ECU"]
            .dropna().astype(str).unique()
        )
        decision_ecu = st.selectbox(t["ecu"], decision_ecus, key="decision_ecu")
        selected_decision = overview[
            (overview["Source File"] == decision_source)
            & (overview["ECU"] == decision_ecu)
        ].iloc[0]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(t["advisor_decision"], selected_decision["Decision"])
        c2.metric(t["decision_urgency"], selected_decision["Decision Urgency"])
        c3.metric(
            t["decision_confidence"],
            f"{selected_decision['Decision Confidence %']:.0f}%",
        )
        c4.metric(t["risk_score"], f"{selected_decision['Risk Score']:.0f}/100")

        st.markdown(f"### {t['root_cause_advisor']}")
        st.info(selected_decision["Primary Root Cause"])

        with st.expander(t["all_hypotheses"], expanded=True):
            for hypothesis in str(selected_decision["Root Cause Hypotheses"]).split(" | "):
                if hypothesis.strip():
                    st.markdown(f"- {hypothesis.strip()}")

        st.markdown(f"### {t['recommended_actions']}")
        selected_actions = decision_actions[
            (decision_actions["Source File"] == decision_source)
            & (decision_actions["ECU"] == decision_ecu)
        ].sort_values("Action Priority")
        st.dataframe(
            selected_actions[
                ["Action Priority", "Recommended Action", "Decision Urgency",
                 "Decision Confidence %", "Evidence"]
            ],
            width="stretch",
            hide_index=True,
        )

        with st.expander(t["decision_evidence"]):
            st.write(selected_decision["Decision Evidence"])

        st.markdown(f"### {t['all_decisions']}")
        decision_columns = [
            "Source File", "VIN", "ECU", "Status", "Risk Score", "Risk Level",
            "Decision", "Decision Urgency", "Decision Confidence %",
            "Primary Root Cause", "Recommended Actions", "Mismatch Fields",
        ]
        decision_columns = [
            column for column in decision_columns if column in overview.columns
        ]
        st.dataframe(
            overview[decision_columns].sort_values(
                ["Decision Urgency", "Risk Score"],
                ascending=[False, False],
            ),
            width="stretch",
            hide_index=True,
        )

with tabs[7]:
    st.subheader(t["vehicle_intelligence"])
    st.caption(t["vehicle_intelligence_help"])

    if vehicle_health.empty:
        st.info(t["no_vehicle_intelligence"])
    else:
        v1, v2, v3, v4 = st.columns(4)
        average_health_score = pd.to_numeric(
            vehicle_health["Vehicle Health Score"], errors="coerce"
        ).mean()
        critical_vehicles = int(
            (vehicle_health["Vehicle Health Level"].astype(str) == "CRITICAL").sum()
        )
        escalation_vehicles = int(
            (warranty_summary["Warranty Recommendation"].astype(str) == "ENGINEERING_ESCALATION").sum()
        )
        software_first = int(
            (warranty_summary["Warranty Recommendation"].astype(str) == "SOFTWARE_CORRECTION_FIRST").sum()
        )
        v1.metric(t["average_vehicle_health"], f"{average_health_score:.1f}%")
        v2.metric(t["critical_vehicles"], critical_vehicles)
        v3.metric(t["engineering_escalations"], escalation_vehicles)
        v4.metric(t["software_correction_first"], software_first)

        st.info(fleet_summary_text)
        st.markdown(f"### {t['vehicle_health_index']}")
        st.dataframe(vehicle_health, width="stretch", hide_index=True)

        st.markdown(f"### {t['warranty_triage']}")
        st.warning(t["warranty_disclaimer"])
        st.dataframe(warranty_summary, width="stretch", hide_index=True)

        intelligence_sources = sorted(
            engineering_summaries["Source File"].dropna().astype(str).unique()
        )
        selected_intelligence_source = st.selectbox(
            t["vehicle_session"],
            intelligence_sources,
            key="vehicle_intelligence_source",
        )
        selected_summary_row = engineering_summaries[
            engineering_summaries["Source File"] == selected_intelligence_source
        ].iloc[0]
        selected_warranty_row = warranty_summary[
            warranty_summary["Source File"] == selected_intelligence_source
        ].iloc[0]

        i1, i2, i3, i4 = st.columns(4)
        i1.metric(
            t["vehicle_health_score"],
            f"{selected_summary_row['Vehicle Health Score']:.1f}/100",
        )
        i2.metric(
            t["vehicle_health_level"],
            selected_summary_row["Vehicle Health Level"],
        )
        i3.metric(
            t["warranty_recommendation"],
            selected_warranty_row["Warranty Recommendation Label"],
        )
        i4.metric(
            t["warranty_priority"],
            int(selected_warranty_row["Warranty Priority"]),
        )

        st.markdown(f"### {t['automatic_engineering_summary']}")
        st.success(selected_summary_row["Executive Summary"])
        st.info(selected_summary_row["Technical Summary"])
        st.warning(selected_summary_row["Warranty Summary"])

        with st.expander(t["ecu_warranty_details"]):
            st.dataframe(
                ecu_warranty[
                    ecu_warranty["Source File"] == selected_intelligence_source
                ].sort_values(
                    ["Warranty Priority", "Risk Score"],
                    ascending=[False, False],
                ),
                width="stretch",
                hide_index=True,
            )

with tabs[8]:
    st.subheader(t["dependency_analysis"])
    st.caption(t["dependency_analysis_help"])
    if dependency_nodes.empty:
        st.info(t["no_dependency_results"])
    else:
        dep_sources = sorted(dependency_nodes["Source File"].dropna().astype(str).unique())
        dep_source = st.selectbox(
            t["vehicle_session"], dep_sources, key="dependency_source"
        )
        scoped_nodes = dependency_nodes[
            dependency_nodes["Source File"] == dep_source
        ].sort_values(["Impact Radius", "Importance"], ascending=[False, False])
        scoped_edges = dependency_edges[
            dependency_edges["Source File"] == dep_source
        ] if not dependency_edges.empty else dependency_edges

        d1, d2, d3, d4 = st.columns(4)
        d1.metric(t["dependency_nodes"], len(scoped_nodes))
        d2.metric(t["dependency_edges"], len(scoped_edges))
        d3.metric(
            t["maximum_impact_radius"],
            int(scoped_nodes["Impact Radius"].max()) if not scoped_nodes.empty else 0,
        )
        top_dependency = scoped_nodes.iloc[0] if not scoped_nodes.empty else None
        d4.metric(
            t["highest_impact_ecu"],
            top_dependency["ECU"] if top_dependency is not None else "—",
        )

        st.markdown(f"### {t['dependency_node_summary']}")
        st.dataframe(scoped_nodes, width="stretch", hide_index=True)

        st.markdown(f"### {t['dependency_edges_table']}")
        st.dataframe(scoped_edges, width="stretch", hide_index=True)

        dependency_ecus = sorted(scoped_nodes["ECU"].astype(str).unique())
        selected_dependency_ecu = st.selectbox(
            t["ecu"], dependency_ecus, key="dependency_ecu"
        )
        selected_node = scoped_nodes[
            scoped_nodes["ECU"] == selected_dependency_ecu
        ].iloc[0]
        n1, n2, n3, n4 = st.columns(4)
        n1.metric(t["ecu_role"], selected_node["Role"])
        n2.metric(t["ecu_importance"], f"{selected_node['Importance']:.2f}")
        n3.metric(t["upstream_count"], int(selected_node["Direct Upstream Count"]))
        n4.metric(t["impact_radius"], int(selected_node["Impact Radius"]))
        st.info(
            f"{t['upstream_ecus']}: {selected_node['Direct Upstream ECUs'] or '—'}\n\n"
            f"{t['impacted_ecus']}: {selected_node['Impacted ECUs'] or '—'}"
        )

with tabs[9]:
    st.subheader(t["root_cause_analysis"])
    st.caption(t["root_cause_analysis_help"])
    if vehicle_root_causes.empty:
        st.info(t["no_root_cause_results"])
    else:
        r1, r2, r3, r4 = st.columns(4)
        lead_vehicle = vehicle_root_causes.sort_values(
            "Root Cause Confidence %", ascending=False
        ).iloc[0]
        r1.metric(t["probable_root_ecu"], lead_vehicle["Most Probable Root ECU"])
        r2.metric(
            t["root_cause_confidence"],
            f"{lead_vehicle['Root Cause Confidence %']:.1f}%",
        )
        r3.metric(t["root_ecu_role"], lead_vehicle["Root ECU Role"])
        r4.metric(t["impact_radius"], int(lead_vehicle["Impact Radius"]))

        st.markdown(f"### {t['vehicle_root_cause_summary']}")
        st.dataframe(vehicle_root_causes, width="stretch", hide_index=True)

        root_sources = sorted(
            vehicle_root_causes["Source File"].dropna().astype(str).unique()
        )
        root_source = st.selectbox(
            t["vehicle_session"], root_sources, key="root_cause_source"
        )
        selected_root = vehicle_root_causes[
            vehicle_root_causes["Source File"] == root_source
        ].iloc[0]
        st.warning(selected_root["Primary Vehicle Root Cause"])
        st.info(selected_root["Root Cause Evidence"])
        st.markdown(
            f"**{t['recommended_root_action']}:** "
            f"{selected_root['Recommended Root Action']}"
        )

        st.markdown(f"### {t['root_cause_ranking']}")
        scoped_ranking = root_cause_ranking[
            root_cause_ranking["Source File"] == root_source
        ].sort_values("Root Cause Rank")
        st.dataframe(scoped_ranking, width="stretch", hide_index=True)

        with st.expander(t["root_cause_paths"]):
            st.dataframe(
                root_cause_paths[
                    root_cause_paths["Source File"] == root_source
                ],
                width="stretch",
                hide_index=True,
            )

with tabs[10]:
    st.subheader(t["release_consistency"])
    st.caption(t["release_consistency_help"])
    if release_consistency.empty:
        st.info(t["no_consistency_results"])
    else:
        c1, c2, c3, c4 = st.columns(4)
        average_consistency = pd.to_numeric(
            release_consistency["Release Consistency Score"], errors="coerce"
        ).mean()
        mixed_count = int(release_consistency["Mixed Package Detected"].fillna(False).sum())
        variant_count = int(release_consistency["Variant Review Required"].fillna(False).sum())
        lowest_vehicle = release_consistency.sort_values(
            "Release Consistency Score"
        ).iloc[0]
        c1.metric(t["average_release_consistency"], f"{average_consistency:.1f}%")
        c2.metric(t["mixed_packages"], mixed_count)
        c3.metric(t["variant_reviews"], variant_count)
        c4.metric(
            t["lowest_consistency_vehicle"],
            f"{lowest_vehicle['Release Consistency Score']:.1f}%",
        )

        st.markdown(f"### {t['vehicle_consistency_summary']}")
        st.dataframe(release_consistency, width="stretch", hide_index=True)

        consistency_sources = sorted(
            release_consistency["Source File"].dropna().astype(str).unique()
        )
        consistency_source = st.selectbox(
            t["vehicle_session"], consistency_sources, key="consistency_source"
        )
        selected_vehicle_consistency = release_consistency[
            release_consistency["Source File"] == consistency_source
        ].iloc[0]

        s1, s2, s3, s4 = st.columns(4)
        s1.metric(
            t["release_consistency_score"],
            f"{selected_vehicle_consistency['Release Consistency Score']:.1f}/100",
        )
        s2.metric(
            t["release_consistency_level"],
            selected_vehicle_consistency["Release Consistency Level"],
        )
        s3.metric(
            t["consistency_confidence"],
            f"{selected_vehicle_consistency['Consistency Confidence %']:.1f}%",
        )
        s4.metric(
            t["mixed_package_detected"],
            t["yes"] if selected_vehicle_consistency["Mixed Package Detected"] else t["no"],
        )
        st.info(selected_vehicle_consistency["Consistency Findings"])

        st.markdown(f"### {t['field_consistency']}")
        field_view = consistency_fields[
            consistency_fields["Source File"] == consistency_source
        ].sort_values("Weight", ascending=False)
        st.dataframe(field_view, width="stretch", hide_index=True)

        st.markdown(f"### {t['ecu_package_consistency']}")
        ecu_view = ecu_consistency[
            ecu_consistency["Source File"] == consistency_source
        ].sort_values(["ECU Consistency Score", "ECU"])
        st.dataframe(ecu_view, width="stretch", hide_index=True)

with tabs[11]:
    st.subheader(t["fleet_intelligence"])
    st.caption(t["fleet_intelligence_help"])

    fleet_kpi = fleet_intelligence["kpis"]
    if fleet_kpi.empty:
        st.info(t["no_fleet_intelligence"])
    else:
        kpi = fleet_kpi.iloc[0]
        f1, f2, f3, f4, f5, f6 = st.columns(6)
        f1.metric(t["fleet_vehicles"], int(kpi["Vehicles / Sessions"]))
        f2.metric(t["fleet_average_risk"], f"{kpi['Average Risk Score']:.1f}")
        f3.metric(t["fleet_average_health"], f"{kpi['Average Vehicle Health']:.1f}%")
        f4.metric(t["fleet_average_consistency"], f"{kpi['Average Release Consistency']:.1f}%")
        f5.metric(t["fleet_persistent_dtcs"], int(kpi["Persistent DTCs"]))
        f6.metric(t["fleet_escalations"], int(kpi["Engineering Escalations"]))

        alerts = fleet_intelligence["alerts"]
        if not alerts.empty:
            st.markdown(f"### {t['fleet_alerts']}")
            st.dataframe(alerts, width="stretch", hide_index=True)

        left, right = st.columns(2)
        with left:
            st.markdown(f"### {t['top_problematic_ecus']}")
            st.dataframe(
                fleet_intelligence["problematic_ecus"].head(10),
                width="stretch", hide_index=True,
            )
            st.markdown(f"### {t['top_dtc_patterns']}")
            if fleet_intelligence["dtc_ranking"].empty:
                st.info(t["no_dtc_patterns"])
            else:
                st.dataframe(
                    fleet_intelligence["dtc_ranking"].head(10),
                    width="stretch", hide_index=True,
                )
            st.markdown(f"### {t['root_ecu_patterns']}")
            st.dataframe(
                fleet_intelligence["root_ecus"].head(10),
                width="stretch", hide_index=True,
            )

        with right:
            st.markdown(f"### {t['release_patterns']}")
            st.dataframe(
                fleet_intelligence["release_patterns"].head(10),
                width="stretch", hide_index=True,
            )
            st.markdown(f"### {t['warranty_patterns']}")
            st.dataframe(
                fleet_intelligence["warranty_patterns"].head(10),
                width="stretch", hide_index=True,
            )

        with st.expander(t["fleet_kpi_details"]):
            st.dataframe(fleet_kpi, width="stretch", hide_index=True)

with tabs[12]:
    st.subheader(t["engineering_assistant"])
    st.caption(t["engineering_assistant_help"])

    if assistant_summary.empty:
        st.info(t["no_assistant_results"])
    else:
        a1, a2, a3, a4, a5 = st.columns(5)
        critical_statuses = int(
            assistant_summary["Executive Vehicle Status"].astype(str).eq("CRITICAL").sum()
        )
        avg_assistant_conf = pd.to_numeric(
            assistant_summary["Assistant Confidence %"], errors="coerce"
        ).mean()
        total_findings = len(engineering_findings)
        total_actions = len(assistant_action_plan)
        escalations = int(
            assistant_summary["Warranty Recommendation"]
            .astype(str).eq("ENGINEERING_ESCALATION").sum()
        )
        a1.metric(t["critical_vehicle_statuses"], critical_statuses)
        a2.metric(t["assistant_confidence"], f"{avg_assistant_conf:.1f}%")
        a3.metric(t["engineering_findings_count"], total_findings)
        a4.metric(t["action_plan_items"], total_actions)
        a5.metric(t["engineering_escalations"], escalations)

        assistant_sources = sorted(
            assistant_summary["Source File"].dropna().astype(str).unique()
        )
        assistant_source = st.selectbox(
            t["vehicle_session"], assistant_sources, key="assistant_source"
        )
        selected_assistant = assistant_summary[
            assistant_summary["Source File"] == assistant_source
        ].iloc[0]

        x1, x2, x3, x4 = st.columns(4)
        x1.metric(t["executive_vehicle_status"], selected_assistant["Executive Vehicle Status"])
        x2.metric(
            t["vehicle_health_score"],
            f"{selected_assistant['Vehicle Health Score']:.1f}/100",
        )
        x3.metric(
            t["release_consistency_score"],
            f"{selected_assistant['Release Consistency Score']:.1f}/100",
        )
        x4.metric(
            t["assistant_confidence"],
            f"{selected_assistant['Assistant Confidence %']:.1f}%",
        )

        st.markdown(f"### {t['executive_summary']}")
        st.success(selected_assistant["Executive Summary"])

        st.markdown(f"### {t['assistant_interpretation']}")
        st.info(selected_assistant["Engineering Assistant Message"])

        st.markdown(f"### {t['management_summary']}")
        st.warning(selected_assistant["Management Summary"])

        st.markdown(f"### {t['engineering_findings']}")
        scoped_findings = engineering_findings[
            engineering_findings["Source File"] == assistant_source
        ]
        st.dataframe(scoped_findings, width="stretch", hide_index=True)

        st.markdown(f"### {t['phased_action_plan']}")
        scoped_actions = assistant_action_plan[
            assistant_action_plan["Source File"] == assistant_source
        ]
        st.dataframe(scoped_actions, width="stretch", hide_index=True)

        with st.expander(t["assistant_disclaimer"]):
            st.write(selected_assistant["Disclaimers"])

        st.markdown(f"### {t['all_executive_summaries']}")
        st.dataframe(assistant_summary, width="stretch", hide_index=True)

with tabs[13]:
    st.dataframe(filtered_details.style.map(status_style, subset=["Status"]), width="stretch", hide_index=True)
with tabs[14]:
    st.dataframe(summary, width="stretch", hide_index=True)
with tabs[15]:
    st.dataframe(candidates.sort_values(["Source File", "ECU", "Candidate Score"], ascending=[True, True, False]), width="stretch", hide_index=True)
with tabs[16]:
    st.dataframe(raw, width="stretch", hide_index=True)
with tabs[17]:
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

with tabs[18]:
    st.subheader(t["report_center"])
    st.caption(t["report_center_help"])

    meta_left, meta_right = st.columns(2)
    with meta_left:
        report_title = st.text_input(t["report_title"], value=t["default_report_title"])
        prepared_by = st.text_input(t["prepared_by"])
        project = st.text_input(t["project_department"])
        executive_comment = st.text_area(t["executive_comment"], height=130)
    with meta_right:
        report_subtitle = st.text_input(t["report_subtitle"], value=t["default_report_subtitle"])
        engineering_notes = st.text_area(t["engineering_notes"], height=180)
        logo_file = st.file_uploader(t["optional_logo"], type=["png", "jpg", "jpeg"], key="report_logo")
        report_files = st.multiselect(
            t["report_scope"],
            sorted(overview["Source File"].dropna().astype(str).unique()),
            default=sorted(overview["Source File"].dropna().astype(str).unique()),
        )

    report_metadata = {
        "report_title": report_title,
        "report_subtitle": report_subtitle,
        "prepared_by": prepared_by,
        "project": project,
        "executive_comment": executive_comment,
        "engineering_notes": engineering_notes,
        "reference_file": reference_file.name,
        "generated_fleet_summary": fleet_summary_text,
        "generated_executive_summary": (
            assistant_summary[
                assistant_summary["Source File"].isin(report_files)
            ]["Management Summary"].str.cat(sep=" ")
            if not assistant_summary.empty else ""
        ),
    }

    selected_overview = overview[overview["Source File"].isin(report_files)].copy() if report_files else overview.iloc[0:0].copy()
    selected_details = details[details["Source File"].isin(report_files)].copy() if report_files else details.iloc[0:0].copy()
    selected_summary = summary[summary["Source File"].isin(report_files)].copy() if report_files else summary.iloc[0:0].copy()
    selected_raw = raw[raw["Source File"].isin(report_files)].copy() if report_files and "Source File" in raw.columns else raw.copy()
    selected_candidates = candidates[candidates["Source File"].isin(report_files)].copy() if report_files and "Source File" in candidates.columns else candidates.copy()

    if not report_files:
        st.warning(t["select_report_scope"])
    else:
        excel = build_report(
            selected_overview, selected_details, selected_summary, selected_raw,
            selected_candidates, selected, report_metadata,
            dtc_summary=dtc_summary[dtc_summary["Mapped Session"].isin(report_files)].copy()
                if not dtc_summary.empty else dtc_summary,
            dtc_events=dtc_events[dtc_events["Mapped Session"].isin(report_files)].copy()
                if not dtc_events.empty else dtc_events,
            vehicle_history=vehicle_history[vehicle_history["Source File"].isin(report_files)].copy(),
            change_log=change_log[
                change_log["Current Session"].isin(report_files) | change_log["Previous Session"].isin(report_files)
            ].copy() if not change_log.empty else change_log,
            fleet_overview=fleet_overview,
            risk_breakdown=risk_breakdown,
            vehicle_health=vehicle_health,
            risk_rules=risk_rules,
            decision_actions=decision_actions[
                decision_actions["Source File"].isin(report_files)
            ].copy() if not decision_actions.empty else decision_actions,
            vehicle_decisions=vehicle_decisions[
                vehicle_decisions["Source File"].isin(report_files)
            ].copy() if not vehicle_decisions.empty else vehicle_decisions,
            decision_rules=decision_rules,
            warranty_summary=warranty_summary[
                warranty_summary["Source File"].isin(report_files)
            ].copy() if not warranty_summary.empty else warranty_summary,
            ecu_warranty=ecu_warranty[
                ecu_warranty["Source File"].isin(report_files)
            ].copy() if not ecu_warranty.empty else ecu_warranty,
            engineering_summaries=engineering_summaries[
                engineering_summaries["Source File"].isin(report_files)
            ].copy() if not engineering_summaries.empty else engineering_summaries,
            warranty_rules=warranty_rules,
            dependency_nodes=dependency_nodes[
                dependency_nodes["Source File"].isin(report_files)
            ].copy() if not dependency_nodes.empty else dependency_nodes,
            dependency_edges=dependency_edges[
                dependency_edges["Source File"].isin(report_files)
            ].copy() if not dependency_edges.empty else dependency_edges,
            vehicle_root_causes=vehicle_root_causes[
                vehicle_root_causes["Source File"].isin(report_files)
            ].copy() if not vehicle_root_causes.empty else vehicle_root_causes,
            root_cause_ranking=root_cause_ranking[
                root_cause_ranking["Source File"].isin(report_files)
            ].copy() if not root_cause_ranking.empty else root_cause_ranking,
            root_cause_paths=root_cause_paths[
                root_cause_paths["Source File"].isin(report_files)
            ].copy() if not root_cause_paths.empty else root_cause_paths,
            dependency_rules=dependency_rules,
            release_consistency=release_consistency[
                release_consistency["Source File"].isin(report_files)
            ].copy() if not release_consistency.empty else release_consistency,
            consistency_fields=consistency_fields[
                consistency_fields["Source File"].isin(report_files)
            ].copy() if not consistency_fields.empty else consistency_fields,
            ecu_consistency=ecu_consistency[
                ecu_consistency["Source File"].isin(report_files)
            ].copy() if not ecu_consistency.empty else ecu_consistency,
            consistency_rules=consistency_rules,
            fleet_kpis=fleet_intelligence["kpis"],
            fleet_problematic_ecus=fleet_intelligence["problematic_ecus"],
            fleet_dtc_ranking=fleet_intelligence["dtc_ranking"],
            fleet_release_patterns=fleet_intelligence["release_patterns"],
            fleet_root_ecus=fleet_intelligence["root_ecus"],
            fleet_warranty_patterns=fleet_intelligence["warranty_patterns"],
            fleet_alerts=fleet_intelligence["alerts"],
            fleet_rules=fleet_rules,
            engineering_findings=engineering_findings[
                engineering_findings["Source File"].isin(report_files)
            ].copy() if not engineering_findings.empty else engineering_findings,
            assistant_summary=assistant_summary[
                assistant_summary["Source File"].isin(report_files)
            ].copy() if not assistant_summary.empty else assistant_summary,
            assistant_action_plan=assistant_action_plan[
                assistant_action_plan["Source File"].isin(report_files)
            ].copy() if not assistant_action_plan.empty else assistant_action_plan,
            assistant_rules=assistant_rules,
        )
        pdf = build_pdf_report(
            selected_overview, selected_details, selected_summary, selected,
            report_metadata,
            logo_bytes=logo_file.getvalue() if logo_file is not None else None,
            selected_files=report_files,
            dtc_summary=dtc_summary,
            dtc_events=dtc_events,
            risk_breakdown=risk_breakdown,
            vehicle_health=vehicle_health,
            decision_actions=decision_actions,
            vehicle_decisions=vehicle_decisions,
            warranty_summary=warranty_summary,
            engineering_summaries=engineering_summaries,
            dependency_nodes=dependency_nodes,
            dependency_edges=dependency_edges,
            vehicle_root_causes=vehicle_root_causes,
            root_cause_ranking=root_cause_ranking,
            release_consistency=release_consistency,
            consistency_fields=consistency_fields,
            ecu_consistency=ecu_consistency,
            fleet_kpis=fleet_intelligence["kpis"],
            fleet_problematic_ecus=fleet_intelligence["problematic_ecus"],
            fleet_dtc_ranking=fleet_intelligence["dtc_ranking"],
            fleet_release_patterns=fleet_intelligence["release_patterns"],
            fleet_root_ecus=fleet_intelligence["root_ecus"],
            fleet_warranty_patterns=fleet_intelligence["warranty_patterns"],
            fleet_alerts=fleet_intelligence["alerts"],
            engineering_findings=engineering_findings,
            assistant_summary=assistant_summary,
            assistant_action_plan=assistant_action_plan,
        )

        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                t["download_excel"], excel, "GradeX_Configuration_Intelligence_Report_Sprint8_4_4.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary", width="stretch"
            )
        with d2:
            st.download_button(
                t["download_pdf"], pdf, "GradeX_Configuration_Intelligence_Report_Sprint8_4_4.pdf",
                "application/pdf", width="stretch"
            )

        st.success(t["reports_ready"])
