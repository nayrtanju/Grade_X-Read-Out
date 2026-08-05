from __future__ import annotations

import hashlib
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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
from timeseries_engine import build_timeseries_intelligence, load_timeseries_rules
from ecu_network import build_network_intelligence, load_network_rules
from network_graph_analytics import build_graph_analytics
from network_visualizer import heat_bar_html, network_svg
from update_impact_engine import (
    candidate_target_releases,
    load_update_impact_rules,
    simulate_update_impact,
    simulation_summary,
)
from release_path_planner import (
    available_release_catalog,
    build_network_timeline,
    compare_update_scenarios,
    load_release_path_rules,
    release_path_summary,
)
from release_recommendation_engine import (
    build_update_plan,
    historical_release_performance,
    load_release_recommendation_rules,
    recommend_release,
)
from configuration_diff_engine import (
    compare_configurations,
    load_diff_rules,
    normalize_reference,
    normalize_session,
)
from multi_session_engine import build_multi_session_analysis
from advanced_search_engine import (
    advanced_search,
    combine_search_sources,
    search_facets,
    search_summary,
)
from compliance_dashboard_engine import build_compliance_dashboard
from release_coverage_engine import build_release_coverage
from oem_audit_engine import build_oem_audit, load_oem_audit_rules
from session_merge_engine import build_unified_snapshot
from dynamic_report_builder import (
    available_sections,
    build_dynamic_excel,
    build_dynamic_pdf,
    report_manifest,
)
from data_quality_engine import evaluate_data_quality, load_data_quality_rules
from fleet_snapshot_engine import build_fleet_snapshot
from analysis_orchestrator import build_full_assessment
from programming_validation_engine import build_programming_validation
from corrective_action_engine import build_corrective_action_plan
from closure_verification_engine import (
    ALLOWED_CLOSURE_STATUS,
    ALLOWED_VERIFICATION,
    evaluate_action_closure,
    prepare_closure_register,
)

APP_TITLE = "Grade-X Software Configuration Intelligence Platform"

st.set_page_config(page_title=APP_TITLE, page_icon="✅", layout="wide")
diff_rules = load_diff_rules()
oem_audit_rules = load_oem_audit_rules()
data_quality_rules = load_data_quality_rules()
timeseries_rules = load_timeseries_rules()
workspace_timeseries = {
    "timeseries": pd.DataFrame(),
    "transitions": pd.DataFrame(),
    "vehicle_trends": pd.DataFrame(),
    "timeline": pd.DataFrame(),
}
network_timeline = pd.DataFrame()

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


def _session_frame(uploaded) -> pd.DataFrame:
    rows, _ = parse_session(uploaded.name, uploaded.getvalue())
    return records_frame(rows)


def _reference_frame(uploaded, sheet_name: str) -> pd.DataFrame:
    return cached_reference_sheet(uploaded.getvalue(), sheet_name)


def render_configuration_diff(t: dict[str, str], key_prefix: str) -> None:
    st.subheader(t["configuration_diff"])
    st.caption(t["configuration_diff_help"])
    st.info(t["stateless_diff_notice"])

    comparison_type = st.radio(
        t["comparison_type"],
        [
            t["session_vs_session"],
            t["session_vs_reference"],
            t["reference_vs_reference"],
        ],
        horizontal=True,
        key=f"{key_prefix}_comparison_type",
    )

    left_col, right_col = st.columns(2)
    is_left_reference = comparison_type == t["reference_vs_reference"]
    is_right_reference = comparison_type in {
        t["session_vs_reference"], t["reference_vs_reference"]
    }

    with left_col:
        st.markdown(f"### {t['configuration_a']}")
        left_file = st.file_uploader(
            t["upload_reference_a"] if is_left_reference else t["upload_session_a"],
            type=["xlsx", "xlsm"] if is_left_reference else ["session", "xml"],
            key=f"{key_prefix}_left_file",
        )
        left_sheet = ""
        if is_left_reference and left_file is not None:
            left_infos = cached_release_sheets(left_file.getvalue())
            left_sheet_names = [item.sheet for item in left_infos]
            if left_sheet_names:
                left_sheet = st.selectbox(
                    t["reference_sheet_a"],
                    left_sheet_names,
                    key=f"{key_prefix}_left_sheet",
                )

    with right_col:
        st.markdown(f"### {t['configuration_b']}")
        right_file = st.file_uploader(
            t["upload_reference_b"] if is_right_reference else t["upload_session_b"],
            type=["xlsx", "xlsm"] if is_right_reference else ["session", "xml"],
            key=f"{key_prefix}_right_file",
        )
        right_sheet = ""
        if is_right_reference and right_file is not None:
            right_infos = cached_release_sheets(right_file.getvalue())
            right_sheet_names = [item.sheet for item in right_infos]
            if right_sheet_names:
                right_sheet = st.selectbox(
                    t["reference_sheet_b"],
                    right_sheet_names,
                    key=f"{key_prefix}_right_sheet",
                )

    all_fields = list(diff_rules["fields"])
    ignored_fields = st.multiselect(
        t["ignore_fields"],
        all_fields,
        default=diff_rules["default_ignore_fields"],
        key=f"{key_prefix}_ignore_fields",
    )

    ready = (
        left_file is not None
        and right_file is not None
        and (not is_left_reference or bool(left_sheet))
        and (not is_right_reference or bool(right_sheet))
    )
    if st.button(
        t["compare_configurations"],
        type="primary",
        disabled=not ready,
        key=f"{key_prefix}_compare",
    ):
        try:
            if is_left_reference:
                left_raw = _reference_frame(left_file, left_sheet)
                left = normalize_reference(
                    left_raw,
                    label=f"{left_file.name} · {left_sheet}",
                    release_name=left_sheet,
                )
                left_label = f"{left_file.name} · {left_sheet}"
            else:
                left_raw = _session_frame(left_file)
                left = normalize_session(left_raw, label=left_file.name)
                left_label = left_file.name

            if is_right_reference:
                right_raw = _reference_frame(right_file, right_sheet)
                right = normalize_reference(
                    right_raw,
                    label=f"{right_file.name} · {right_sheet}",
                    release_name=right_sheet,
                )
                right_label = f"{right_file.name} · {right_sheet}"
            else:
                right_raw = _session_frame(right_file)
                right = normalize_session(right_raw, label=right_file.name)
                right_label = right_file.name

            result = compare_configurations(
                left,
                right,
                left_label=left_label,
                right_label=right_label,
                ignore_fields=ignored_fields,
                rules=diff_rules,
            )
            st.session_state[f"{key_prefix}_diff_result"] = result
        except Exception as exc:
            st.error(str(exc))

    result = st.session_state.get(f"{key_prefix}_diff_result")
    if not result:
        return

    summary = result["summary"]
    ecu_diff = result["ecu_diff"]
    field_diff = result["field_diff"]
    summary_row = summary.iloc[0]

    d1, d2, d3, d4, d5, d6 = st.columns(6)
    d1.metric(t["added_ecus"], int(summary_row["Added ECUs"]))
    d2.metric(t["removed_ecus"], int(summary_row["Removed ECUs"]))
    d3.metric(t["modified_ecus"], int(summary_row["Modified ECUs"]))
    d4.metric(t["unchanged_ecus"], int(summary_row["Unchanged ECUs"]))
    d5.metric(t["critical_differences"], int(summary_row["Critical Differences"]))
    d6.metric(t["total_field_differences"], int(summary_row["Total Field Differences"]))

    st.markdown(f"### {t['difference_summary']}")
    st.dataframe(summary, width="stretch", hide_index=True)

    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.markdown(f"### {t['status_distribution']}")
        status_chart = pd.DataFrame({
            "Status": ["ADDED", "REMOVED", "MODIFIED", "UNCHANGED"],
            "Count": [
                summary_row["Added ECUs"],
                summary_row["Removed ECUs"],
                summary_row["Modified ECUs"],
                summary_row["Unchanged ECUs"],
            ],
        }).set_index("Status")
        st.bar_chart(status_chart)
    with chart_right:
        st.markdown(f"### {t['category_distribution']}")
        category_chart = pd.DataFrame({
            "Category": ["SOFTWARE", "HARDWARE", "RELEASE", "IDENTITY"],
            "Count": [
                summary_row["Software Differences"],
                summary_row["Hardware Differences"],
                summary_row["Release Differences"],
                summary_row["Identity Differences"],
            ],
        }).set_index("Category")
        st.bar_chart(category_chart)

    statuses = sorted(ecu_diff["Diff Status"].dropna().astype(str).unique())
    severities = sorted(ecu_diff["Highest Severity"].dropna().astype(str).unique())
    categories = sorted(field_diff["Category"].dropna().astype(str).unique()) if not field_diff.empty else []
    f1, f2, f3 = st.columns(3)
    selected_statuses = f1.multiselect(
        t["diff_status_filter"], statuses, default=statuses,
        key=f"{key_prefix}_status_filter",
    )
    selected_severities = f2.multiselect(
        t["diff_severity_filter"], severities, default=severities,
        key=f"{key_prefix}_severity_filter",
    )
    selected_categories = f3.multiselect(
        t["diff_category_filter"], categories, default=categories,
        key=f"{key_prefix}_category_filter",
    )

    filtered_ecus = ecu_diff[
        ecu_diff["Diff Status"].isin(selected_statuses)
        & ecu_diff["Highest Severity"].isin(selected_severities)
    ]
    filtered_fields = field_diff[
        field_diff["Category"].isin(selected_categories)
    ] if not field_diff.empty else field_diff

    st.markdown(f"### {t['ecu_differences']}")
    st.dataframe(filtered_ecus, width="stretch", hide_index=True)

    st.markdown(f"### {t['field_differences']}")
    st.dataframe(filtered_fields, width="stretch", hide_index=True)

    detail_tabs = st.tabs([
        t["software_differences"],
        t["hardware_differences"],
        t["release_differences"],
        t["added_removed_ecus"],
    ])
    with detail_tabs[0]:
        st.dataframe(result["software"], width="stretch", hide_index=True)
    with detail_tabs[1]:
        st.dataframe(result["hardware"], width="stretch", hide_index=True)
    with detail_tabs[2]:
        st.dataframe(result["release"], width="stretch", hide_index=True)
    with detail_tabs[3]:
        st.dataframe(result["added_removed"], width="stretch", hide_index=True)

    excel_buffer = pd.ExcelWriter
    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Diff Summary", index=False)
        ecu_diff.to_excel(writer, sheet_name="ECU Differences", index=False)
        field_diff.to_excel(writer, sheet_name="Field Differences", index=False)
        result["software"].to_excel(writer, sheet_name="Software Differences", index=False)
        result["hardware"].to_excel(writer, sheet_name="Hardware Differences", index=False)
        result["release"].to_excel(writer, sheet_name="Release Differences", index=False)
        result["added_removed"].to_excel(writer, sheet_name="Added Removed ECUs", index=False)
    st.download_button(
        t["download_diff_excel"],
        output.getvalue(),
        "GradeX_Configuration_Diff_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download_diff",
    )



def render_multi_session_analysis(t: dict[str, str], key_prefix: str) -> None:
    st.subheader(t["multi_session_analysis"])
    st.caption(t["multi_session_help"])
    st.info(t["multi_session_stateless_notice"])

    uploaded_sessions = st.file_uploader(
        t["upload_multiple_sessions"],
        type=["session", "xml"],
        accept_multiple_files=True,
        key=f"{key_prefix}_sessions",
    )
    ignored_fields = st.multiselect(
        t["ignore_fields"],
        list(diff_rules["fields"]),
        default=diff_rules["default_ignore_fields"],
        key=f"{key_prefix}_ignore_fields",
    )

    if st.button(
        t["analyse_session_history"],
        type="primary",
        disabled=not uploaded_sessions or len(uploaded_sessions) < 2,
        key=f"{key_prefix}_run",
    ):
        try:
            frames = [
                (uploaded.name, _session_frame(uploaded))
                for uploaded in uploaded_sessions
            ]
            st.session_state[f"{key_prefix}_result"] = build_multi_session_analysis(
                frames,
                ignore_fields=ignored_fields,
            )
        except Exception as exc:
            st.error(str(exc))

    result = st.session_state.get(f"{key_prefix}_result")
    if not result:
        if uploaded_sessions and len(uploaded_sessions) < 2:
            st.warning(t["minimum_two_sessions"])
        return

    catalog = result["catalog"]
    timeline = result["ecu_timeline"]
    transition_summary = result["transition_summary"]
    transition_ecus = result["transition_ecus"]
    transition_fields = result["transition_fields"]
    change_history = result["change_history"]
    vehicle_trend = result["vehicle_trend"]

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(t["sessions_count"], len(catalog))
    m2.metric(t["tracked_ecus"], timeline["ECU"].nunique() if not timeline.empty else 0)
    m3.metric(t["total_transitions"], len(transition_summary))
    m4.metric(t["ecu_changes"], len(transition_ecus))
    m5.metric(t["field_changes"], len(transition_fields))

    st.markdown(f"### {t['session_catalog']}")
    st.dataframe(catalog, width="stretch", hide_index=True)

    if not vehicle_trend.empty:
        st.markdown(f"### {t['vehicle_session_trend']}")
        st.line_chart(
            vehicle_trend.set_index("Session Date")[
                ["ECU Count", "DTC Count", "Modified ECUs", "Critical Differences"]
            ]
        )
        st.dataframe(vehicle_trend, width="stretch", hide_index=True)

    st.markdown(f"### {t['pairwise_transition_summary']}")
    st.dataframe(transition_summary, width="stretch", hide_index=True)

    available_ecus = (
        sorted(timeline["ECU"].dropna().astype(str).unique())
        if not timeline.empty else []
    )
    selected_ecu = (
        st.selectbox(
            t["select_ecu_timeline"],
            available_ecus,
            key=f"{key_prefix}_ecu",
        )
        if available_ecus else ""
    )

    if selected_ecu:
        scoped_timeline = timeline[
            timeline["ECU"].astype(str) == str(selected_ecu)
        ].sort_values("Session Date")
        st.markdown(f"### {t['ecu_timeline']}")
        st.dataframe(scoped_timeline, width="stretch", hide_index=True)

        scoped_changes = (
            change_history[
                change_history["ECU"].astype(str) == str(selected_ecu)
            ]
            if not change_history.empty else pd.DataFrame()
        )
        st.markdown(f"### {t['ecu_change_history']}")
        if scoped_changes.empty:
            st.success(t["no_ecu_changes"])
        else:
            st.dataframe(scoped_changes, width="stretch", hide_index=True)

    detail_tabs = st.tabs([
        t["transition_ecu_details"],
        t["transition_field_details"],
        t["complete_ecu_timeline"],
        t["complete_change_history"],
    ])
    with detail_tabs[0]:
        st.dataframe(transition_ecus, width="stretch", hide_index=True)
    with detail_tabs[1]:
        st.dataframe(transition_fields, width="stretch", hide_index=True)
    with detail_tabs[2]:
        st.dataframe(timeline, width="stretch", hide_index=True)
    with detail_tabs[3]:
        st.dataframe(change_history, width="stretch", hide_index=True)

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        catalog.to_excel(writer, sheet_name="Session Catalog", index=False)
        vehicle_trend.to_excel(writer, sheet_name="Vehicle Session Trend", index=False)
        transition_summary.to_excel(writer, sheet_name="Transition Summary", index=False)
        transition_ecus.to_excel(writer, sheet_name="Transition ECU Diff", index=False)
        transition_fields.to_excel(writer, sheet_name="Transition Field Diff", index=False)
        timeline.to_excel(writer, sheet_name="ECU Timeline", index=False)
        change_history.to_excel(writer, sheet_name="ECU Change History", index=False)

    st.download_button(
        t["download_multi_session_excel"],
        output.getvalue(),
        "GradeX_Multi_Session_Analysis_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )



def render_advanced_search(
    t: dict[str, str],
    *,
    overview_frame: pd.DataFrame,
    details_frame: pd.DataFrame,
    summary_frame: pd.DataFrame,
    dtc_frame: pd.DataFrame,
    key_prefix: str,
) -> None:
    st.subheader(t["advanced_search"])
    st.caption(t["advanced_search_help"])
    st.info(t["advanced_search_stateless_notice"])

    multi_result = st.session_state.get("main_multi_result", {})
    diff_result = st.session_state.get("main_diff_diff_result", {})

    sources = [
        ("ANALYSIS_OVERVIEW", "Current analysis overview", overview_frame),
        ("ANALYSIS_DETAILS", "Current analysis details", details_frame),
        ("SESSION_IDENTIFIERS", "Current session identifiers", summary_frame),
        ("DTC_RESULTS", "Current DTC results", dtc_frame),
    ]
    if multi_result:
        sources.extend([
            ("MULTI_SESSION_CATALOG", "Multi-session catalog", multi_result.get("catalog", pd.DataFrame())),
            ("ECU_TIMELINE", "Multi-session ECU timeline", multi_result.get("ecu_timeline", pd.DataFrame())),
            ("SESSION_TRANSITIONS", "Multi-session transitions", multi_result.get("transition_ecus", pd.DataFrame())),
            ("FIELD_TRANSITIONS", "Multi-session field transitions", multi_result.get("transition_fields", pd.DataFrame())),
            ("ECU_CHANGE_HISTORY", "ECU change history", multi_result.get("change_history", pd.DataFrame())),
        ])
    if diff_result:
        sources.extend([
            ("CONFIGURATION_DIFF", "Configuration ECU differences", diff_result.get("ecu_diff", pd.DataFrame())),
            ("CONFIGURATION_FIELD_DIFF", "Configuration field differences", diff_result.get("field_diff", pd.DataFrame())),
        ])

    search_index = combine_search_sources(sources)
    if search_index.empty:
        st.info(t["no_search_data"])
        return

    facets = search_facets(search_index)
    query_col, option_col = st.columns([3, 1])
    with query_col:
        search_query = st.text_input(
            t["search_query"],
            placeholder=t["search_placeholder"],
            key=f"{key_prefix}_query",
        )
    with option_col:
        regex_search = st.checkbox(
            t["regex_search"],
            value=False,
            key=f"{key_prefix}_regex",
        )

    filter_tabs = st.tabs([
        t["source_filters"],
        t["ecu_status_filters"],
        t["risk_date_filters"],
    ])
    with filter_tabs[0]:
        selected_source_types = st.multiselect(
            t["source_types"],
            facets["source_types"],
            default=facets["source_types"],
            key=f"{key_prefix}_source_types",
        )
    with filter_tabs[1]:
        c1, c2, c3, c4 = st.columns(4)
        selected_ecus = c1.multiselect(
            t["search_ecus"],
            facets["ecus"],
            key=f"{key_prefix}_ecus",
        )
        selected_statuses = c2.multiselect(
            t["search_statuses"],
            facets["statuses"],
            key=f"{key_prefix}_statuses",
        )
        selected_severities = c3.multiselect(
            t["search_severities"],
            facets["severities"],
            key=f"{key_prefix}_severities",
        )
        selected_categories = c4.multiselect(
            t["search_categories"],
            facets["categories"],
            key=f"{key_prefix}_categories",
        )
    with filter_tabs[2]:
        r1, r2, r3, r4 = st.columns(4)
        use_date_filter = r1.checkbox(
            t["use_date_filter"],
            key=f"{key_prefix}_use_date",
        )
        date_from = r2.date_input(
            t["date_from"],
            key=f"{key_prefix}_date_from",
            disabled=not use_date_filter,
        )
        date_to = r3.date_input(
            t["date_to"],
            key=f"{key_prefix}_date_to",
            disabled=not use_date_filter,
        )
        risk_range = r4.slider(
            t["risk_range"],
            min_value=0,
            max_value=100,
            value=(0, 100),
            key=f"{key_prefix}_risk",
        )
        changed_only = st.checkbox(
            t["changed_records_only"],
            key=f"{key_prefix}_changed",
        )
        dtc_only = st.checkbox(
            t["dtc_records_only"],
            key=f"{key_prefix}_dtc_only",
        )

    results = advanced_search(
        search_index,
        query=search_query,
        regex=regex_search,
        source_types=selected_source_types,
        ecus=selected_ecus or None,
        statuses=selected_statuses or None,
        severities=selected_severities or None,
        categories=selected_categories or None,
        date_from=date_from if use_date_filter else None,
        date_to=date_to if use_date_filter else None,
        min_risk=risk_range[0] if risk_range != (0, 100) else None,
        max_risk=risk_range[1] if risk_range != (0, 100) else None,
        changed_only=changed_only,
        dtc_only=dtc_only,
    )
    summary_data = search_summary(results)
    st.session_state[f"{key_prefix}_results"] = results
    st.session_state[f"{key_prefix}_summary"] = summary_data

    summary_row = summary_data.iloc[0]
    q1, q2, q3, q4, q5, q6 = st.columns(6)
    q1.metric(t["search_results"], int(summary_row["Results"]))
    q2.metric(t["search_source_count"], int(summary_row["Source Types"]))
    q3.metric(t["search_session_count"], int(summary_row["Sessions"]))
    q4.metric(t["search_vin_count"], int(summary_row["VINs"]))
    q5.metric(t["search_ecu_count"], int(summary_row["ECUs"]))
    q6.metric(t["search_dtc_count"], int(summary_row["DTC Records"]))

    st.markdown(f"### {t['search_result_table']}")
    if results.empty:
        st.warning(t["no_search_results"])
    else:
        preferred_columns = [
            "Source Type", "Source Name", "Session File", "Session Date",
            "VIN", "ECU", "ECU Name", "Status", "Diff Status",
            "Severity", "Category", "Risk Score", "Risk Level",
            "DTC Code", "DTC Description", "DTC Status",
            "Hardware Number", "Part Number", "Application SW",
            "Calibration SW", "Basic SW", "Software Number",
            "Bootloader", "Installed Release", "Target Release",
            "Changed Fields",
        ]
        visible_columns = [
            column for column in preferred_columns
            if column in results.columns
            and results[column].astype(str).str.strip().ne("").any()
        ]
        st.dataframe(
            results[visible_columns] if visible_columns else results,
            width="stretch",
            hide_index=True,
        )

        source_distribution = (
            results["Source Type"].value_counts().rename_axis("Source Type")
            .reset_index(name="Count").set_index("Source Type")
        )
        st.markdown(f"### {t['search_source_distribution']}")
        st.bar_chart(source_distribution)

        import io
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            summary_data.to_excel(writer, sheet_name="Search Summary", index=False)
            results.to_excel(writer, sheet_name="Search Results", index=False)
        st.download_button(
            t["download_search_results"],
            output.getvalue(),
            "GradeX_Advanced_Search_Results_Sprint11_4.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            key=f"{key_prefix}_download",
        )



def render_compliance_dashboard(
    t: dict[str, str],
    *,
    overview_frame: pd.DataFrame,
    release_consistency_frame: pd.DataFrame,
    vehicle_health_frame: pd.DataFrame,
    network_health_frame: pd.DataFrame,
    dtc_frame: pd.DataFrame,
    key_prefix: str,
) -> None:
    st.subheader(t["compliance_dashboard"])
    st.caption(t["compliance_dashboard_help"])
    st.info(t["dashboard_stateless_notice"])

    diff_result = st.session_state.get("main_diff_diff_result", {})
    multi_result = st.session_state.get("main_multi_result", {})

    dashboard = build_compliance_dashboard(
        overview_frame,
        release_consistency=release_consistency_frame,
        vehicle_health=vehicle_health_frame,
        network_health=network_health_frame,
        dtc_events=dtc_frame,
        diff_result=diff_result,
        multi_session_result=multi_result,
    )
    st.session_state[f"{key_prefix}_dashboard"] = dashboard

    summary = dashboard["summary"]
    if summary.empty:
        st.info(t["no_dashboard_data"])
        return
    row = summary.iloc[0]

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric(t["overall_quality_score"], f"{row['Overall Quality Score']:.1f}/100")
    k2.metric(t["overall_quality_level"], row["Overall Quality Level"])
    k3.metric(t["compliance_rate"], f"{row['Compliance Rate %']:.1f}%")
    k4.metric(t["wrong_release_ecus"], int(row["Wrong Release ECUs"]))
    k5.metric(t["critical_risk_ecus"], int(row["Critical-Risk ECUs"]))
    k6.metric(t["persistent_dtcs"], int(row["Persistent DTCs"]))

    k7, k8, k9, k10, k11, k12 = st.columns(6)
    k7.metric(t["vehicle_health"], f"{row['Vehicle Health']:.1f}")
    k8.metric(t["network_health"], f"{row['Network Health']:.1f}")
    k9.metric(t["release_consistency"], f"{row['Release Consistency %']:.1f}%")
    k10.metric(t["mixed_package"], t["yes"] if row["Mixed Package"] else t["no"])
    k11.metric(t["modified_ecus"], int(row["Modified ECUs"]))
    k12.metric(t["critical_differences"], int(row["Critical Differences"]))

    level = row["Overall Quality Level"]
    if level == "GOOD":
        st.success(t["dashboard_good"])
    elif level == "FAIR":
        st.info(t["dashboard_fair"])
    elif level == "POOR":
        st.warning(t["dashboard_poor"])
    else:
        st.error(t["dashboard_critical"])

    st.markdown(f"### {t['quality_summary']}")
    st.dataframe(summary, width="stretch", hide_index=True)

    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.markdown(f"### {t['compliance_distribution']}")
        status_distribution = dashboard["status_distribution"]
        if not status_distribution.empty:
            st.bar_chart(status_distribution.set_index("Status"))
        else:
            st.info(t["no_dashboard_data"])
    with chart_right:
        st.markdown(f"### {t['risk_distribution']}")
        risk_distribution = dashboard["risk_distribution"]
        if not risk_distribution.empty:
            st.bar_chart(risk_distribution.set_index("Risk Band"))

    release_distribution = dashboard["release_distribution"]
    if not release_distribution.empty:
        st.markdown(f"### {t['release_distribution']}")
        st.bar_chart(release_distribution.set_index("Release"))

    st.markdown(f"### {t['top_failing_ecus']}")
    top_failing = dashboard["top_failing_ecus"]
    if top_failing.empty:
        st.success(t["no_failing_ecus"])
    else:
        preferred = [
            "Source File", "VIN", "ECU", "ECU Name", "Status",
            "Risk Score", "Risk Level", "Persistent DTC Count",
            "Installed Release", "Target Release",
        ]
        columns = [column for column in preferred if column in top_failing.columns]
        st.dataframe(
            top_failing[columns] if columns else top_failing,
            width="stretch",
            hide_index=True,
        )

    transition_trend = dashboard["transition_trend"]
    st.markdown(f"### {t['quality_transition_trend']}")
    if transition_trend.empty:
        st.info(t["run_multi_session_for_trend"])
    else:
        numeric_columns = [
            column for column in
            ("ECU Count", "DTC Count", "Modified ECUs", "Critical Differences")
            if column in transition_trend.columns
        ]
        if numeric_columns and "Session Date" in transition_trend.columns:
            st.line_chart(transition_trend.set_index("Session Date")[numeric_columns])
        st.dataframe(transition_trend, width="stretch", hide_index=True)

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, frame in dashboard.items():
            if frame is not None and not frame.empty:
                sheet_name = {
                    "summary": "Quality Summary",
                    "status_distribution": "Status Distribution",
                    "risk_distribution": "Risk Distribution",
                    "top_failing_ecus": "Top Failing ECUs",
                    "release_distribution": "Release Distribution",
                    "transition_trend": "Quality Trend",
                }[name]
                frame.to_excel(writer, sheet_name=sheet_name, index=False)

    st.download_button(
        t["download_dashboard_excel"],
        output.getvalue(),
        "GradeX_Compliance_Dashboard_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )



def render_release_coverage_dashboard(
    t: dict[str, str],
    *,
    overview_frame: pd.DataFrame,
    reference_frame: pd.DataFrame,
    release_consistency_frame: pd.DataFrame,
    key_prefix: str,
) -> None:
    st.subheader(t["release_coverage_dashboard"])
    st.caption(t["release_coverage_help"])
    st.info(t["release_coverage_stateless_notice"])

    multi_result = st.session_state.get("main_multi_result", {})
    coverage = build_release_coverage(
        overview_frame,
        reference=reference_frame,
        release_consistency=release_consistency_frame,
        multi_session_result=multi_result,
    )
    st.session_state[f"{key_prefix}_coverage"] = coverage

    summary = coverage["summary"]
    if summary.empty:
        st.info(t["no_release_coverage_data"])
        return

    row = summary.iloc[0]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric(t["release_coverage_rate"], f"{row['Release Coverage %']:.1f}%")
    c2.metric(t["target_level_ecus"], int(row["Target-Level ECUs"]))
    c3.metric(t["below_target_ecus"], int(row["Below-Target ECUs"]))
    c4.metric(t["unknown_release_ecus"], int(row["Unknown Release ECUs"]))
    c5.metric(t["obsolescence_candidates"], int(row["Obsolescence Candidates"]))
    c6.metric(t["coverage_level"], row["Coverage Level"])

    d1, d2, d3, d4 = st.columns(4)
    d1.metric(t["unique_installed_releases"], int(row["Unique Installed Releases"]))
    d2.metric(t["unique_target_releases"], int(row["Unique Target Releases"]))
    d3.metric(t["release_consistency"], f"{row['Release Consistency %']:.1f}%")
    d4.metric(t["mixed_package"], t["yes"] if row["Mixed Package"] else t["no"])

    if row["Coverage Level"] == "GOOD":
        st.success(t["release_coverage_good"])
    elif row["Coverage Level"] == "FAIR":
        st.info(t["release_coverage_fair"])
    elif row["Coverage Level"] == "POOR":
        st.warning(t["release_coverage_poor"])
    else:
        st.error(t["release_coverage_critical"])

    st.markdown(f"### {t['release_coverage_summary']}")
    st.dataframe(summary, width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        st.markdown(f"### {t['installed_release_distribution']}")
        installed = coverage["installed_distribution"]
        if not installed.empty:
            st.bar_chart(installed.set_index("Installed Release")[["ECU Count"]])
    with right:
        st.markdown(f"### {t['target_release_distribution']}")
        target = coverage["target_distribution"]
        if not target.empty:
            st.bar_chart(target.set_index("Target Release")[["ECU Count"]])

    st.markdown(f"### {t['coverage_by_target_release']}")
    st.dataframe(
        coverage["coverage_by_target"],
        width="stretch",
        hide_index=True,
    )

    detail_tabs = st.tabs([
        t["ecu_release_coverage"],
        t["legacy_release_candidates"],
        t["unknown_release_records"],
        t["reference_coverage"],
        t["session_release_trend"],
    ])
    with detail_tabs[0]:
        st.dataframe(coverage["ecu_coverage"], width="stretch", hide_index=True)
    with detail_tabs[1]:
        legacy = coverage["legacy_candidates"]
        if legacy.empty:
            st.success(t["no_legacy_candidates"])
        else:
            st.warning(t["obsolescence_inference_notice"])
            st.dataframe(legacy, width="stretch", hide_index=True)
    with detail_tabs[2]:
        unknown = coverage["unknown_releases"]
        if unknown.empty:
            st.success(t["no_unknown_releases"])
        else:
            st.dataframe(unknown, width="stretch", hide_index=True)
    with detail_tabs[3]:
        reference_coverage = coverage["reference_coverage"]
        if reference_coverage.empty:
            st.info(t["no_reference_coverage"])
        else:
            st.dataframe(reference_coverage, width="stretch", hide_index=True)
    with detail_tabs[4]:
        trend = coverage["session_release_trend"]
        if trend.empty:
            st.info(t["run_multi_session_for_release_trend"])
        else:
            st.dataframe(trend, width="stretch", hide_index=True)

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        sheet_map = {
            "summary": "Release Coverage Summary",
            "ecu_coverage": "ECU Release Coverage",
            "installed_distribution": "Installed Distribution",
            "target_distribution": "Target Distribution",
            "coverage_by_target": "Coverage by Target",
            "legacy_candidates": "Legacy Candidates",
            "unknown_releases": "Unknown Releases",
            "reference_coverage": "Reference Coverage",
            "session_release_trend": "Session Release Trend",
        }
        for key, frame in coverage.items():
            if frame is not None and not frame.empty:
                frame.to_excel(writer, sheet_name=sheet_map[key], index=False)

    st.download_button(
        t["download_release_coverage_excel"],
        output.getvalue(),
        "GradeX_Release_Coverage_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )



def render_oem_audit(
    t: dict[str, str],
    *,
    overview_frame: pd.DataFrame,
    details_frame: pd.DataFrame,
    summary_frame: pd.DataFrame,
    vehicle_health_frame: pd.DataFrame,
    release_consistency_frame: pd.DataFrame,
    network_health_frame: pd.DataFrame,
    dtc_frame: pd.DataFrame,
    reference_frame: pd.DataFrame,
    key_prefix: str,
) -> None:
    st.subheader(t["oem_audit_mode"])
    st.caption(t["oem_audit_help"])
    st.info(t["oem_audit_stateless_notice"])

    diff_result = st.session_state.get("main_diff_diff_result", {})
    multi_result = st.session_state.get("main_multi_result", {})
    update_summary = st.session_state.get("impact_summary", pd.DataFrame())
    path_summary = st.session_state.get("release_path_summary", pd.DataFrame())

    release_coverage = build_release_coverage(
        overview_frame,
        reference=reference_frame,
        release_consistency=release_consistency_frame,
        multi_session_result=multi_result,
    )

    audit = build_oem_audit(
        overview_frame,
        details=details_frame,
        summary=summary_frame,
        vehicle_health=vehicle_health_frame,
        release_consistency=release_consistency_frame,
        network_health=network_health_frame,
        dtc_events=dtc_frame,
        release_coverage=release_coverage,
        configuration_diff=diff_result,
        update_impact_summary=update_summary,
        release_path_summary=path_summary,
        rules=oem_audit_rules,
    )
    st.session_state[f"{key_prefix}_audit"] = audit

    audit_summary = audit["summary"]
    if audit_summary.empty:
        st.info(t["no_oem_audit_data"])
        return

    row = audit_summary.iloc[0]
    a1, a2, a3, a4, a5, a6 = st.columns(6)
    a1.metric(t["audit_score"], f"{row['Audit Score']:.1f}/100")
    a2.metric(t["audit_decision"], row["Audit Decision"])
    a3.metric(t["passed_checks"], int(row["Passed Checks"]))
    a4.metric(t["warning_checks"], int(row["Warning Checks"]))
    a5.metric(t["failed_checks"], int(row["Failed Checks"]))
    a6.metric(t["mandatory_failures"], int(row["Mandatory Failures"]))

    decision = row["Audit Decision"]
    if decision == "PASS":
        st.success(t["audit_pass_message"])
    elif decision == "CONDITIONAL_PASS":
        st.warning(t["audit_conditional_message"])
    else:
        st.error(t["audit_fail_message"])

    st.markdown(f"### {t['audit_summary']}")
    st.dataframe(audit_summary, width="stretch", hide_index=True)

    st.markdown(f"### {t['audit_area_summary']}")
    area_summary = audit["area_summary"]
    st.dataframe(area_summary, width="stretch", hide_index=True)
    if not area_summary.empty:
        st.bar_chart(area_summary.set_index("Audit Area")[["Average Score"]])

    st.markdown(f"### {t['audit_checklist']}")
    checklist = audit["checklist"]
    status_filter = st.multiselect(
        t["audit_status_filter"],
        sorted(checklist["Status"].astype(str).unique()),
        default=sorted(checklist["Status"].astype(str).unique()),
        key=f"{key_prefix}_status_filter",
    )
    area_filter = st.multiselect(
        t["audit_area_filter"],
        sorted(checklist["Audit Area"].astype(str).unique()),
        default=sorted(checklist["Audit Area"].astype(str).unique()),
        key=f"{key_prefix}_area_filter",
    )
    filtered = checklist[
        checklist["Status"].isin(status_filter)
        & checklist["Audit Area"].isin(area_filter)
    ]
    st.dataframe(filtered, width="stretch", hide_index=True)

    st.markdown(f"### {t['open_audit_findings']}")
    findings = audit["findings"]
    if findings.empty:
        st.success(t["no_open_audit_findings"])
    else:
        st.dataframe(findings, width="stretch", hide_index=True)

    st.warning(t["oem_audit_disclaimer"])

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        audit_summary.to_excel(writer, sheet_name="OEM Audit Summary", index=False)
        checklist.to_excel(writer, sheet_name="OEM Audit Checklist", index=False)
        findings.to_excel(writer, sheet_name="Open Audit Findings", index=False)
        area_summary.to_excel(writer, sheet_name="Audit Area Summary", index=False)
        release_coverage["summary"].to_excel(
            writer, sheet_name="Release Coverage Evidence", index=False
        )

    st.download_button(
        t["download_oem_audit_excel"],
        output.getvalue(),
        "GradeX_OEM_Software_Audit_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )



def render_session_merge(
    t: dict[str, str],
    key_prefix: str,
) -> None:
    st.subheader(t["session_merge"])
    st.caption(t["session_merge_help"])
    st.info(t["session_merge_stateless_notice"])

    uploaded_sessions = st.file_uploader(
        t["upload_sessions_to_merge"],
        type=["session", "xml"],
        accept_multiple_files=True,
        key=f"{key_prefix}_files",
    )

    if st.button(
        t["build_unified_snapshot"],
        type="primary",
        disabled=not uploaded_sessions or len(uploaded_sessions) < 2,
        key=f"{key_prefix}_run",
    ):
        try:
            frames = [
                (uploaded.name, _session_frame(uploaded))
                for uploaded in uploaded_sessions
            ]
            st.session_state[f"{key_prefix}_merge"] = build_unified_snapshot(frames)
        except Exception as exc:
            st.error(str(exc))

    result = st.session_state.get(f"{key_prefix}_merge")
    if not result:
        if uploaded_sessions and len(uploaded_sessions) < 2:
            st.warning(t["minimum_two_sessions"])
        return

    summary = result["summary"]
    snapshot = result["snapshot"]
    provenance = result["field_provenance"]
    conflicts = result["conflicts"]
    presence = result["ecu_presence"]
    catalog = result["session_catalog"]
    change_history = result["change_history"]

    row = summary.iloc[0]
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    s1.metric(t["sessions_merged"], int(row["Sessions Merged"]))
    s2.metric(t["unified_ecus"], int(row["Unified ECUs"]))
    s3.metric(t["stale_ecus"], int(row["Stale ECUs"]))
    s4.metric(t["conflicting_ecus"], int(row["ECUs with Conflicts"]))
    s5.metric(t["merge_completeness"], f"{row['Data Completeness %']:.1f}%")
    s6.metric(t["merge_quality"], f"{row['Merge Quality Score']:.1f}/100")

    if row["Merge Quality Level"] == "GOOD":
        st.success(t["merge_quality_good"])
    elif row["Merge Quality Level"] == "FAIR":
        st.info(t["merge_quality_fair"])
    elif row["Merge Quality Level"] == "POOR":
        st.warning(t["merge_quality_poor"])
    else:
        st.error(t["merge_quality_critical"])

    st.markdown(f"### {t['merge_summary']}")
    st.dataframe(summary, width="stretch", hide_index=True)

    st.markdown(f"### {t['unified_vehicle_snapshot']}")
    merge_statuses = sorted(snapshot["Merge Status"].astype(str).unique())
    selected_statuses = st.multiselect(
        t["merge_status_filter"],
        merge_statuses,
        default=merge_statuses,
        key=f"{key_prefix}_status_filter",
    )
    filtered_snapshot = snapshot[
        snapshot["Merge Status"].isin(selected_statuses)
    ]
    st.dataframe(filtered_snapshot, width="stretch", hide_index=True)

    detail_tabs = st.tabs([
        t["merge_conflicts"],
        t["field_provenance"],
        t["ecu_presence_history"],
        t["merge_session_catalog"],
        t["merge_change_history"],
    ])
    with detail_tabs[0]:
        if conflicts.empty:
            st.success(t["no_merge_conflicts"])
        else:
            st.warning(t["merge_conflict_resolution_notice"])
            st.dataframe(conflicts, width="stretch", hide_index=True)
    with detail_tabs[1]:
        st.dataframe(provenance, width="stretch", hide_index=True)
    with detail_tabs[2]:
        st.dataframe(presence, width="stretch", hide_index=True)
    with detail_tabs[3]:
        st.dataframe(catalog, width="stretch", hide_index=True)
    with detail_tabs[4]:
        st.dataframe(change_history, width="stretch", hide_index=True)

    st.warning(t["stale_ecu_notice"])

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Merge Summary", index=False)
        snapshot.to_excel(writer, sheet_name="Unified Snapshot", index=False)
        provenance.to_excel(writer, sheet_name="Field Provenance", index=False)
        conflicts.to_excel(writer, sheet_name="Merge Conflicts", index=False)
        presence.to_excel(writer, sheet_name="ECU Presence", index=False)
        catalog.to_excel(writer, sheet_name="Session Catalog", index=False)
        change_history.to_excel(writer, sheet_name="Change History", index=False)

    st.download_button(
        t["download_session_merge_excel"],
        output.getvalue(),
        "GradeX_Session_Merge_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )



def render_dynamic_report_builder(
    t: dict[str, str],
    *,
    section_frames: dict[str, list[tuple[str, pd.DataFrame]]],
    key_prefix: str,
) -> None:
    st.subheader(t["dynamic_report_builder"])
    st.caption(t["dynamic_report_builder_help"])
    st.info(t["dynamic_report_stateless_notice"])

    available = available_sections(section_frames)
    if not available:
        st.info(t["no_dynamic_report_data"])
        return

    profile_map = {
        t["report_profile_executive"]: [
            "EXECUTIVE_SUMMARY", "COMPLIANCE", "RISK_HEALTH",
            "QUALITY_DASHBOARD", "OEM_AUDIT",
        ],
        t["report_profile_engineering"]: [
            "EXECUTIVE_SUMMARY", "COMPLIANCE", "ECU_DETAILS", "DTC",
            "RISK_HEALTH", "RELEASE_CONSISTENCY", "NETWORK",
            "UPDATE_PLANNING", "CONFIGURATION_DIFF", "MULTI_SESSION",
            "RELEASE_COVERAGE", "OEM_AUDIT", "SESSION_MERGE",
        ],
        t["report_profile_audit"]: [
            "EXECUTIVE_SUMMARY", "COMPLIANCE", "DTC",
            "RELEASE_CONSISTENCY", "NETWORK", "RELEASE_COVERAGE",
            "OEM_AUDIT",
        ],
        t["report_profile_custom"]: available,
    }

    profile = st.selectbox(
        t["report_profile"],
        list(profile_map),
        key=f"{key_prefix}_profile",
    )
    profile_default = [
        section for section in profile_map[profile]
        if section in available
    ]
    selected_sections = st.multiselect(
        t["report_sections"],
        available,
        default=profile_default,
        format_func=lambda value: value.replace("_", " ").title(),
        key=f"{key_prefix}_sections",
    )

    meta_left, meta_right = st.columns(2)
    with meta_left:
        title = st.text_input(
            t["report_title"],
            value=t["default_report_title"],
            key=f"{key_prefix}_title",
        )
        prepared_by = st.text_input(
            t["prepared_by"],
            key=f"{key_prefix}_prepared_by",
        )
        project_name = st.text_input(
            t["project_department"],
            key=f"{key_prefix}_project",
        )
    with meta_right:
        subtitle = st.text_input(
            t["report_subtitle"],
            value=t["default_report_subtitle"],
            key=f"{key_prefix}_subtitle",
        )
        executive_comment = st.text_area(
            t["executive_comment"],
            height=90,
            key=f"{key_prefix}_comment",
        )
        engineering_notes = st.text_area(
            t["engineering_notes"],
            height=90,
            key=f"{key_prefix}_notes",
        )

    metadata = {
        "title": title,
        "subtitle": subtitle,
        "prepared_by": prepared_by,
        "project": project_name,
        "profile": profile,
        "executive_comment": executive_comment,
        "engineering_notes": engineering_notes,
    }

    manifest = report_manifest(selected_sections, section_frames)
    st.markdown(f"### {t['report_manifest']}")
    st.dataframe(manifest, width="stretch", hide_index=True)

    if not selected_sections:
        st.warning(t["select_report_sections"])
        return

    selected_table_count = int(manifest["Tables"].sum()) if not manifest.empty else 0
    selected_row_count = int(manifest["Total Rows"].sum()) if not manifest.empty else 0
    b1, b2, b3 = st.columns(3)
    b1.metric(t["selected_report_sections"], len(selected_sections))
    b2.metric(t["selected_report_tables"], selected_table_count)
    b3.metric(t["selected_report_rows"], selected_row_count)

    try:
        excel_bytes = build_dynamic_excel(
            metadata=metadata,
            selected_sections=selected_sections,
            section_frames=section_frames,
        )
        pdf_bytes = build_dynamic_pdf(
            metadata=metadata,
            selected_sections=selected_sections,
            section_frames=section_frames,
        )
    except Exception as exc:
        st.error(str(exc))
        return

    download_left, download_right = st.columns(2)
    with download_left:
        st.download_button(
            t["download_custom_excel"],
            excel_bytes,
            "GradeX_Custom_Report_Sprint11_4.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            key=f"{key_prefix}_excel",
        )
    with download_right:
        st.download_button(
            t["download_custom_pdf"],
            pdf_bytes,
            "GradeX_Custom_Report_Sprint11_4.pdf",
            "application/pdf",
            width="stretch",
            key=f"{key_prefix}_pdf",
        )



def render_data_quality_gate(
    t: dict[str, str],
    *,
    session_frame: pd.DataFrame,
    reference_frame: pd.DataFrame,
    dtc_frame: pd.DataFrame,
    key_prefix: str,
) -> None:
    st.subheader(t["data_quality_gate"])
    st.caption(t["data_quality_gate_help"])
    st.info(t["data_quality_stateless_notice"])

    result = evaluate_data_quality(
        session_frame,
        reference_frame,
        dtc_frame,
        rules=data_quality_rules,
    )
    st.session_state[f"{key_prefix}_quality"] = result

    summary = result["summary"]
    if summary.empty:
        st.info(t["no_data_quality_result"])
        return

    row = summary.iloc[0]
    q1, q2, q3, q4, q5, q6 = st.columns(6)
    q1.metric(t["readiness_score"], f"{row['Readiness Score']:.1f}/100")
    q2.metric(t["readiness_decision"], row["Readiness Decision"])
    q3.metric(t["unique_ecus"], int(row["Unique ECUs"]))
    q4.metric(t["missing_required_columns"], int(row["Required Columns Missing"]))
    q5.metric(t["duplicate_rate"], f"{row['Duplicate Rate %']:.1f}%")
    q6.metric(t["reference_match_rate"], f"{row['Reference Match %']:.1f}%")

    decision = row["Readiness Decision"]
    if decision == "READY":
        st.success(t["readiness_ready_message"])
    elif decision == "READY_WITH_WARNINGS":
        st.warning(t["readiness_warning_message"])
    else:
        st.error(t["readiness_not_ready_message"])

    st.markdown(f"### {t['readiness_summary']}")
    st.dataframe(summary, width="stretch", hide_index=True)

    st.markdown(f"### {t['data_quality_checklist']}")
    checklist = result["checklist"]
    st.dataframe(checklist, width="stretch", hide_index=True)

    tabs = st.tabs([
        t["field_completeness"],
        t["reference_match_details"],
        t["data_quality_findings"],
    ])
    with tabs[0]:
        st.dataframe(result["field_quality"], width="stretch", hide_index=True)
    with tabs[1]:
        reference_match = result["reference_match"]
        if reference_match.empty:
            st.info(t["no_reference_match_details"])
        else:
            st.dataframe(reference_match, width="stretch", hide_index=True)
    with tabs[2]:
        findings = result["findings"]
        if findings.empty:
            st.success(t["no_data_quality_findings"])
        else:
            st.dataframe(findings, width="stretch", hide_index=True)

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Readiness Summary", index=False)
        checklist.to_excel(writer, sheet_name="Quality Checklist", index=False)
        result["field_quality"].to_excel(writer, sheet_name="Field Quality", index=False)
        result["reference_match"].to_excel(writer, sheet_name="Reference Match", index=False)
        result["findings"].to_excel(writer, sheet_name="Findings", index=False)

    st.download_button(
        t["download_data_quality_excel"],
        output.getvalue(),
        "GradeX_Data_Quality_Readiness_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )



def render_fleet_snapshot(
    t: dict[str, str],
    *,
    target_reference_frame: pd.DataFrame,
    release_catalog_frame: pd.DataFrame,
    key_prefix: str,
) -> None:
    st.subheader(t["fleet_snapshot"])
    st.caption(t["fleet_snapshot_help"])
    st.info(t["fleet_snapshot_stateless_notice"])

    uploaded_sessions = st.file_uploader(
        t["upload_vehicle_sessions"],
        type=["session", "xml"],
        accept_multiple_files=True,
        key=f"{key_prefix}_files",
    )

    if st.button(
        t["build_fleet_snapshot"],
        type="primary",
        disabled=not uploaded_sessions or len(uploaded_sessions) < 2,
        key=f"{key_prefix}_run",
    ):
        try:
            frames = [
                (uploaded.name, _session_frame(uploaded))
                for uploaded in uploaded_sessions
            ]
            st.session_state[f"{key_prefix}_fleet"] = build_fleet_snapshot(
                frames,
                target_reference_frame,
                release_catalog_frame,
            )
        except Exception as exc:
            st.error(str(exc))

    result = st.session_state.get(f"{key_prefix}_fleet")
    if not result:
        if uploaded_sessions and len(uploaded_sessions) < 2:
            st.warning(t["minimum_two_vehicle_sessions"])
        return

    fleet_summary = result["fleet_summary"]
    vehicle_summary = result["vehicle_summary"]
    ecu_overview = result["ecu_overview"]
    field_details = result["field_details"]
    top_failing = result["top_failing_ecus"]
    ranking = result["vehicle_ranking"]

    row = fleet_summary.iloc[0]
    f1, f2, f3, f4, f5, f6 = st.columns(6)
    f1.metric(t["vehicles_analysed"], int(row["Vehicles Analysed"]))
    f2.metric(t["fleet_passed"], int(row["Passed Vehicles"]))
    f3.metric(t["fleet_conditional"], int(row["Conditional Vehicles"]))
    f4.metric(t["fleet_failed"], int(row["Failed Vehicles"]))
    f5.metric(t["average_compliance"], f"{row['Average Compliance %']:.1f}%")
    f6.metric(t["fleet_decision"], row["Fleet Decision"])

    g1, g2, g3 = st.columns(3)
    g1.metric(t["average_vehicle_quality"], f"{row['Average Vehicle Quality']:.1f}/100")
    g2.metric(t["mixed_package_vehicles"], int(row["Mixed-Package Vehicles"]))
    g3.metric(t["persistent_dtcs"], int(row["Persistent DTCs"]))

    if row["Fleet Decision"] == "PASS":
        st.success(t["fleet_pass_message"])
    elif row["Fleet Decision"] == "CONDITIONAL":
        st.warning(t["fleet_conditional_message"])
    else:
        st.error(t["fleet_fail_message"])

    st.markdown(f"### {t['fleet_summary']}")
    st.dataframe(fleet_summary, width="stretch", hide_index=True)

    st.markdown(f"### {t['vehicle_ranking']}")
    st.dataframe(ranking, width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        st.markdown(f"### {t['vehicle_decision_distribution']}")
        decision_chart = (
            vehicle_summary["Vehicle Decision"].value_counts()
            .rename_axis("Decision").reset_index(name="Vehicles")
            .set_index("Decision")
        )
        st.bar_chart(decision_chart)
    with right:
        st.markdown(f"### {t['fleet_ecu_status_distribution']}")
        status_distribution = result["status_distribution"]
        if not status_distribution.empty:
            st.bar_chart(status_distribution.set_index("ECU Status"))

    st.markdown(f"### {t['vehicle_summary_table']}")
    st.dataframe(vehicle_summary, width="stretch", hide_index=True)

    detail_tabs = st.tabs([
        t["fleet_ecu_overview"],
        t["fleet_field_details"],
        t["fleet_top_failing_ecus"],
        t["fleet_release_distribution"],
    ])
    with detail_tabs[0]:
        st.dataframe(ecu_overview, width="stretch", hide_index=True)
    with detail_tabs[1]:
        st.dataframe(field_details, width="stretch", hide_index=True)
    with detail_tabs[2]:
        if top_failing.empty:
            st.success(t["no_fleet_failures"])
        else:
            st.dataframe(top_failing, width="stretch", hide_index=True)
    with detail_tabs[3]:
        release_distribution = result["release_distribution"]
        if release_distribution.empty:
            st.info(t["no_release_distribution"])
        else:
            st.dataframe(release_distribution, width="stretch", hide_index=True)
            st.bar_chart(release_distribution.set_index("Installed Release"))

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        fleet_summary.to_excel(writer, sheet_name="Fleet Summary", index=False)
        ranking.to_excel(writer, sheet_name="Vehicle Ranking", index=False)
        vehicle_summary.to_excel(writer, sheet_name="Vehicle Summary", index=False)
        ecu_overview.to_excel(writer, sheet_name="Fleet ECU Overview", index=False)
        field_details.to_excel(writer, sheet_name="Fleet Field Details", index=False)
        top_failing.to_excel(writer, sheet_name="Top Failing ECUs", index=False)
        result["status_distribution"].to_excel(
            writer, sheet_name="Status Distribution", index=False
        )
        result["release_distribution"].to_excel(
            writer, sheet_name="Release Distribution", index=False
        )

    st.download_button(
        t["download_fleet_snapshot_excel"],
        output.getvalue(),
        "GradeX_Fleet_Snapshot_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )



def render_analysis_orchestrator(
    t: dict[str, str],
    *,
    overview_frame: pd.DataFrame,
    details_frame: pd.DataFrame,
    summary_frame: pd.DataFrame,
    dtc_frame: pd.DataFrame,
    vehicle_health_frame: pd.DataFrame,
    release_consistency_frame: pd.DataFrame,
    network_health_frame: pd.DataFrame,
    assistant_summary_frame: pd.DataFrame,
    assistant_action_plan_frame: pd.DataFrame,
    reference_frame: pd.DataFrame,
    key_prefix: str,
) -> None:
    st.subheader(t["analysis_orchestrator"])
    st.caption(t["analysis_orchestrator_help"])
    st.info(t["analysis_orchestrator_stateless_notice"])

    data_quality = evaluate_data_quality(
        summary_frame,
        reference_frame,
        dtc_frame,
        rules=data_quality_rules,
    )
    release_coverage = build_release_coverage(
        overview_frame,
        reference=reference_frame,
        release_consistency=release_consistency_frame,
    )
    oem_audit = build_oem_audit(
        overview_frame,
        details=details_frame,
        summary=summary_frame,
        vehicle_health=vehicle_health_frame,
        release_consistency=release_consistency_frame,
        network_health=network_health_frame,
        dtc_events=dtc_frame,
        release_coverage=release_coverage,
        configuration_diff=st.session_state.get("main_diff_diff_result", {}),
        update_impact_summary=st.session_state.get("impact_summary", pd.DataFrame()),
        release_path_summary=st.session_state.get("release_path_summary", pd.DataFrame()),
        rules=oem_audit_rules,
    )

    result = build_full_assessment(
        overview=overview_frame,
        details=details_frame,
        summary=summary_frame,
        dtc_events=dtc_frame,
        vehicle_health=vehicle_health_frame,
        release_consistency=release_consistency_frame,
        network_health=network_health_frame,
        assistant_summary=assistant_summary_frame,
        assistant_action_plan=assistant_action_plan_frame,
        target_reference=reference_frame,
        data_quality=data_quality,
        release_coverage=release_coverage,
        oem_audit=oem_audit,
    )
    st.session_state[f"{key_prefix}_assessment"] = result

    summary_result = result["summary"]
    row = summary_result.iloc[0]

    o1, o2, o3, o4, o5, o6 = st.columns(6)
    o1.metric(t["full_assessment_score"], f"{row['Full Assessment Score']:.1f}/100")
    o2.metric(t["full_assessment_decision"], row["Full Assessment Decision"])
    o3.metric(t["compliance_rate"], f"{row['Compliance Rate %']:.1f}%")
    o4.metric(t["vehicle_health"], f"{row['Vehicle Health']:.1f}")
    o5.metric(t["release_coverage_rate"], f"{row['Release Coverage']:.1f}%")
    o6.metric(t["audit_score"], f"{row['OEM Audit Score']:.1f}/100")

    decision = row["Full Assessment Decision"]
    if decision == "READY_FOR_SIGN_OFF":
        st.success(t["assessment_ready_message"])
    elif decision == "ENGINEERING_REVIEW":
        st.warning(t["assessment_review_message"])
    else:
        st.error(t["assessment_stop_message"])

    st.markdown(f"### {t['full_assessment_summary']}")
    st.dataframe(summary_result, width="stretch", hide_index=True)

    st.markdown(f"### {t['assessment_gates']}")
    gates = result["gates"]
    st.dataframe(gates, width="stretch", hide_index=True)
    if not gates.empty:
        st.bar_chart(gates.set_index("Gate")[["Score"]])

    st.markdown(f"### {t['open_assessment_actions']}")
    open_actions = result["open_actions"]
    if open_actions.empty:
        st.success(t["no_open_assessment_actions"])
    else:
        st.dataframe(open_actions, width="stretch", hide_index=True)

    with st.expander(t["assistant_action_plan"], expanded=False):
        if result["assistant_actions"].empty:
            st.info(t["no_assistant_actions"])
        else:
            st.dataframe(
                result["assistant_actions"],
                width="stretch",
                hide_index=True,
            )

    st.warning(t["full_assessment_disclaimer"])

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_result.to_excel(
            writer, sheet_name="Full Assessment Summary", index=False
        )
        gates.to_excel(writer, sheet_name="Assessment Gates", index=False)
        open_actions.to_excel(
            writer, sheet_name="Open Assessment Actions", index=False
        )
        result["assistant_actions"].to_excel(
            writer, sheet_name="Assistant Action Plan", index=False
        )
        data_quality["summary"].to_excel(
            writer, sheet_name="Data Readiness Evidence", index=False
        )
        release_coverage["summary"].to_excel(
            writer, sheet_name="Release Coverage Evidence", index=False
        )
        oem_audit["summary"].to_excel(
            writer, sheet_name="OEM Audit Evidence", index=False
        )

    st.download_button(
        t["download_full_assessment_excel"],
        output.getvalue(),
        "GradeX_Full_Vehicle_Assessment_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )



def render_programming_validation(
    t: dict[str, str],
    *,
    target_reference_frame: pd.DataFrame,
    release_catalog_frame: pd.DataFrame,
    key_prefix: str,
) -> None:
    st.subheader(t["programming_validation"])
    st.caption(t["programming_validation_help"])
    st.info(t["programming_validation_stateless_notice"])

    left, right = st.columns(2)
    with left:
        before_file = st.file_uploader(
            t["upload_before_programming_session"],
            type=["session", "xml"],
            key=f"{key_prefix}_before",
        )
    with right:
        after_file = st.file_uploader(
            t["upload_after_programming_session"],
            type=["session", "xml"],
            key=f"{key_prefix}_after",
        )

    if st.button(
        t["run_programming_validation"],
        type="primary",
        disabled=before_file is None or after_file is None,
        key=f"{key_prefix}_run",
    ):
        try:
            before_frame = _session_frame(before_file)
            after_frame = _session_frame(after_file)
            st.session_state[f"{key_prefix}_result"] = build_programming_validation(
                before_file.name,
                before_frame,
                after_file.name,
                after_frame,
                target_reference_frame,
                release_catalog_frame,
            )
        except Exception as exc:
            st.error(str(exc))

    result = st.session_state.get(f"{key_prefix}_result")
    if not result:
        return

    summary = result["summary"]
    row = summary.iloc[0]
    p1, p2, p3, p4, p5, p6 = st.columns(6)
    p1.metric(t["validation_score"], f"{row['Validation Score']:.1f}/100")
    p2.metric(t["validation_decision"], row["Validation Decision"])
    p3.metric(t["before_compliance"], f"{row['Before Compliance %']:.1f}%")
    p4.metric(t["after_compliance"], f"{row['After Compliance %']:.1f}%")
    p5.metric(t["resolved_ecus"], int(row["Resolved ECUs"]))
    p6.metric(t["regressed_ecus"], int(row["Regressed ECUs"]))

    q1, q2, q3 = st.columns(3)
    q1.metric(t["unresolved_ecus"], int(row["Unresolved ECUs"]))
    q2.metric(t["new_dtc_ecus"], int(row["ECUs with New DTCs"]))
    q3.metric(t["signoff_recommendation"], row["Sign-off Recommendation"])

    if row["Validation Decision"] == "PASS":
        st.success(t["programming_validation_pass"])
    elif row["Validation Decision"] == "CONDITIONAL_PASS":
        st.warning(t["programming_validation_conditional"])
    else:
        st.error(t["programming_validation_fail"])

    st.markdown(f"### {t['programming_validation_summary']}")
    st.dataframe(summary, width="stretch", hide_index=True)

    st.markdown(f"### {t['programming_validation_gates']}")
    st.dataframe(result["gates"], width="stretch", hide_index=True)

    detail_tabs = st.tabs([
        t["ecu_validation_results"],
        t["programming_findings"],
        t["programming_configuration_diff"],
        t["before_after_compliance"],
    ])
    with detail_tabs[0]:
        st.dataframe(result["ecu_validation"], width="stretch", hide_index=True)
    with detail_tabs[1]:
        if result["findings"].empty:
            st.success(t["no_programming_findings"])
        else:
            st.dataframe(result["findings"], width="stretch", hide_index=True)
    with detail_tabs[2]:
        st.dataframe(
            result["configuration_diff_ecus"],
            width="stretch",
            hide_index=True,
        )
        st.dataframe(
            result["configuration_diff_fields"],
            width="stretch",
            hide_index=True,
        )
    with detail_tabs[3]:
        before_col, after_col = st.columns(2)
        with before_col:
            st.markdown(f"#### {t['before_programming']}")
            st.dataframe(result["before_overview"], width="stretch", hide_index=True)
        with after_col:
            st.markdown(f"#### {t['after_programming']}")
            st.dataframe(result["after_overview"], width="stretch", hide_index=True)

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result["summary"].to_excel(writer, sheet_name="Validation Summary", index=False)
        result["gates"].to_excel(writer, sheet_name="Validation Gates", index=False)
        result["ecu_validation"].to_excel(writer, sheet_name="ECU Validation", index=False)
        result["findings"].to_excel(writer, sheet_name="Open Findings", index=False)
        result["configuration_diff_summary"].to_excel(writer, sheet_name="Diff Summary", index=False)
        result["configuration_diff_ecus"].to_excel(writer, sheet_name="ECU Diff", index=False)
        result["configuration_diff_fields"].to_excel(writer, sheet_name="Field Diff", index=False)
        result["before_overview"].to_excel(writer, sheet_name="Before Compliance", index=False)
        result["after_overview"].to_excel(writer, sheet_name="After Compliance", index=False)

    st.download_button(
        t["download_programming_validation_excel"],
        output.getvalue(),
        "GradeX_Pre_Post_Programming_Validation_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )



def render_corrective_action_planner(
    t: dict[str, str],
    key_prefix: str,
) -> None:
    st.subheader(t["corrective_action_planner"])
    st.caption(t["corrective_action_help"])
    st.info(t["corrective_action_stateless_notice"])

    assessment = st.session_state.get("main_orchestrator_assessment", {})
    programming = st.session_state.get("main_programming_validation_result", {})
    audit = st.session_state.get("main_oem_audit_audit", {})
    quality = st.session_state.get("main_data_quality_quality", {})

    result = build_corrective_action_plan(
        assessment_gates=assessment.get("gates", pd.DataFrame()),
        programming_gates=programming.get("gates", pd.DataFrame()),
        programming_findings=programming.get("findings", pd.DataFrame()),
        audit_findings=audit.get("findings", pd.DataFrame()),
        data_quality_findings=quality.get("findings", pd.DataFrame()),
    )
    st.session_state[f"{key_prefix}_result"] = result

    summary = result["summary"]
    row = summary.iloc[0]
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric(t["open_actions"], int(row["Open Actions"]))
    c2.metric(t["blocking_actions"], int(row["Sign-off Blocking Actions"]))
    c3.metric(t["p1_actions"], int(row["P1 Critical Actions"]))
    c4.metric(t["p2_actions"], int(row["P2 High Actions"]))
    c5.metric(t["responsible_teams"], int(row["Responsible Teams"]))
    c6.metric(t["evidence_status"], row["Sign-off Evidence Status"])

    if row["Sign-off Evidence Status"] == "READY":
        st.success(t["evidence_ready_message"])
    elif row["Sign-off Evidence Status"] == "CONDITIONAL":
        st.warning(t["evidence_conditional_message"])
    else:
        st.error(t["evidence_blocked_message"])

    st.markdown(f"### {t['corrective_action_summary']}")
    st.dataframe(summary, width="stretch", hide_index=True)

    actions = result["actions"]
    st.markdown(f"### {t['corrective_action_plan']}")
    if actions.empty:
        st.success(t["no_corrective_actions"])
    else:
        priorities = sorted(actions["Priority"].astype(str).unique())
        teams = sorted(actions["Owner Team"].astype(str).unique())
        f1, f2 = st.columns(2)
        selected_priorities = f1.multiselect(
            t["priority_filter"],
            priorities,
            default=priorities,
            key=f"{key_prefix}_priority",
        )
        selected_teams = f2.multiselect(
            t["owner_team_filter"],
            teams,
            default=teams,
            key=f"{key_prefix}_team",
        )
        filtered = actions[
            actions["Priority"].isin(selected_priorities)
            & actions["Owner Team"].isin(selected_teams)
        ]
        st.dataframe(filtered, width="stretch", hide_index=True)

    tabs = st.tabs([
        t["signoff_evidence_matrix"],
        t["team_action_summary"],
    ])
    with tabs[0]:
        st.dataframe(
            result["evidence_matrix"],
            width="stretch",
            hide_index=True,
        )
    with tabs[1]:
        if result["team_summary"].empty:
            st.info(t["no_team_summary"])
        else:
            st.dataframe(
                result["team_summary"],
                width="stretch",
                hide_index=True,
            )
            st.bar_chart(
                result["team_summary"].set_index("Owner Team")[
                    ["Open Actions", "Blocking Actions"]
                ]
            )

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Action Summary", index=False)
        actions.to_excel(writer, sheet_name="Corrective Action Plan", index=False)
        result["evidence_matrix"].to_excel(
            writer, sheet_name="Sign-off Evidence Matrix", index=False
        )
        result["team_summary"].to_excel(
            writer, sheet_name="Team Summary", index=False
        )

    st.download_button(
        t["download_corrective_action_excel"],
        output.getvalue(),
        "GradeX_Corrective_Action_Plan_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )



def render_closure_verification(
    t: dict[str, str],
    key_prefix: str,
) -> None:
    st.subheader(t["closure_verification"])
    st.caption(t["closure_verification_help"])
    st.info(t["closure_verification_stateless_notice"])

    corrective = st.session_state.get("main_corrective_action_result", {})
    actions = corrective.get("actions", pd.DataFrame())
    register = prepare_closure_register(actions)

    if register.empty:
        st.success(t["no_actions_for_closure"])
        result = evaluate_action_closure(register)
        st.session_state[f"{key_prefix}_result"] = result
        st.dataframe(result["summary"], width="stretch", hide_index=True)
        return

    editable_columns = {
        "Closure Status": st.column_config.SelectboxColumn(
            t["closure_status"],
            options=ALLOWED_CLOSURE_STATUS,
            required=True,
        ),
        "Verification Result": st.column_config.SelectboxColumn(
            t["verification_result"],
            options=ALLOWED_VERIFICATION,
            required=True,
        ),
        "Evidence Reference": st.column_config.TextColumn(
            t["evidence_reference"],
            help=t["evidence_reference_help"],
        ),
        "Reviewer Comment": st.column_config.TextColumn(
            t["reviewer_comment"],
        ),
    }

    edited = st.data_editor(
        register,
        width="stretch",
        hide_index=True,
        disabled=[
            "Action ID",
            "Priority",
            "Owner Team",
            "Gate / Finding",
            "Required Action",
            "Required Evidence",
            "Closure Criterion",
            "Sign-off Blocking",
        ],
        column_config=editable_columns,
        key=f"{key_prefix}_editor",
    )

    result = evaluate_action_closure(edited)
    st.session_state[f"{key_prefix}_result"] = result

    summary = result["summary"]
    row = summary.iloc[0]
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric(t["closure_rate"], f"{row['Closure Rate %']:.1f}%")
    k2.metric(t["verified_closed"], int(row["Verified Closed"]))
    k3.metric(t["evidence_submitted"], int(row["Evidence Submitted"]))
    k4.metric(t["open_rejected"], int(row["Open / Rejected"]))
    k5.metric(t["blocking_remaining"], int(row["Blocking Actions Remaining"]))
    k6.metric(t["final_signoff_readiness"], row["Final Sign-off Readiness"])

    readiness = row["Final Sign-off Readiness"]
    if readiness == "READY":
        st.success(t["closure_ready_message"])
    elif readiness == "CONDITIONAL":
        st.warning(t["closure_conditional_message"])
    elif readiness == "BLOCKED":
        st.error(t["closure_blocked_message"])
    else:
        st.info(t["closure_not_ready_message"])

    st.markdown(f"### {t['closure_summary']}")
    st.dataframe(summary, width="stretch", hide_index=True)

    detail_tabs = st.tabs([
        t["remaining_open_actions"],
        t["final_evidence_matrix"],
        t["closure_team_summary"],
    ])
    with detail_tabs[0]:
        if result["open_actions"].empty:
            st.success(t["all_actions_closed"])
        else:
            st.dataframe(
                result["open_actions"],
                width="stretch",
                hide_index=True,
            )
    with detail_tabs[1]:
        st.dataframe(
            result["evidence_matrix"],
            width="stretch",
            hide_index=True,
        )
    with detail_tabs[2]:
        if result["team_summary"].empty:
            st.info(t["no_team_summary"])
        else:
            st.dataframe(
                result["team_summary"],
                width="stretch",
                hide_index=True,
            )
            st.bar_chart(
                result["team_summary"].set_index("Owner Team")[
                    ["Actions", "Verified Closed", "Blocking Remaining"]
                ]
            )

    st.warning(t["closure_verification_disclaimer"])

    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Closure Summary", index=False)
        result["register"].to_excel(
            writer, sheet_name="Closure Register", index=False
        )
        result["open_actions"].to_excel(
            writer, sheet_name="Remaining Open Actions", index=False
        )
        result["evidence_matrix"].to_excel(
            writer, sheet_name="Final Evidence Matrix", index=False
        )
        result["team_summary"].to_excel(
            writer, sheet_name="Team Closure Summary", index=False
        )

    st.download_button(
        t["download_closure_verification_excel"],
        output.getvalue(),
        "GradeX_Action_Closure_Verification_Sprint11_4.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"{key_prefix}_download",
    )


def render_stateless_landing(t: dict[str, str]) -> None:
    st.subheader(t["stateless_home"])
    st.caption(t["stateless_home_help"])
    st.success(t["no_persistence_notice"])
    st.info(t["upload_to_analyze"])
    st.divider()
    landing_tabs = st.tabs([
        t["configuration_diff"],
        t["multi_session_analysis"],
        t["session_merge"],
    ])
    with landing_tabs[0]:
        render_configuration_diff(t, "landing_diff")
    with landing_tabs[1]:
        render_multi_session_analysis(t, "landing_multi")
    with landing_tabs[2]:
        render_session_merge(t, "landing_merge")


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
    render_stateless_landing(t)
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

with st.spinner("Running Sprint 11.4 stateless action closure verification and final sign-off readiness…"):
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

network_rules = load_network_rules()
update_impact_rules = load_update_impact_rules()
release_path_rules = load_release_path_rules()
release_recommendation_rules = load_release_recommendation_rules()
network_intelligence = build_network_intelligence(
    summary,
    overview,
    dependency_nodes=dependency_nodes,
    release_consistency=release_consistency,
    rules=network_rules,
)
network_graph = build_graph_analytics(
    network_intelligence["nodes"],
    network_intelligence["edges"],
)
network_timeline = build_network_timeline(
    workspace_timeseries["timeseries"],
    workspace_timeseries["transitions"],
    network_intelligence["nodes"],
)
historical_release_stats = historical_release_performance(
    workspace_timeseries["timeseries"],
    workspace_timeseries["transitions"],
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
    t["fleet_intelligence"], t["engineering_assistant"], t["ecu_network_core"],
    t["network_explorer"], t["update_impact_simulator"],
    t["release_path_planner"], t["release_recommendation"], t["details"],
    t["identifiers"], t["candidates"], t["raw"], t["comparison"],
    t["time_series_analytics"], t["configuration_diff"],
    t["multi_session_analysis"], t["advanced_search"],
    t["compliance_dashboard"], t["release_coverage_dashboard"],
    t["oem_audit_mode"], t["session_merge"], t["dynamic_report_builder"],
    t["data_quality_gate"], t["fleet_snapshot"], t["analysis_orchestrator"],
    t["programming_validation"], t["corrective_action_planner"],
    t["closure_verification"], t["report_center"]
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
    st.subheader(t["ecu_network_core"])
    st.caption(t["ecu_network_core_help"])

    network_nodes = network_intelligence["nodes"]
    network_edges = network_intelligence["edges"]
    network_matrix = network_intelligence["matrix"]
    network_violations = network_intelligence["violations"]
    network_health = network_intelligence["health"]
    network_criticality = network_intelligence["criticality"]

    if network_nodes.empty:
        st.info(t["no_network_results"])
    else:
        n1, n2, n3, n4, n5 = st.columns(5)
        avg_network_health = pd.to_numeric(
            network_health["Network Health Score"], errors="coerce"
        ).mean()
        critical_nodes = int(
            network_nodes["Criticality"].astype(str).eq("CRITICAL").sum()
        )
        violation_count = len(network_violations)
        max_impact = int(
            pd.to_numeric(network_nodes["Impact Radius"], errors="coerce")
            .fillna(0).max()
        )
        most_critical = network_criticality.iloc[0]["ECU"]

        n1.metric(t["network_health"], f"{avg_network_health:.1f}/100")
        n2.metric(t["network_nodes"], len(network_nodes))
        n3.metric(t["critical_network_ecus"], critical_nodes)
        n4.metric(t["dependency_violations"], violation_count)
        n5.metric(t["most_critical_ecu"], most_critical)

        st.markdown(f"### {t['network_health_summary']}")
        st.dataframe(network_health, width="stretch", hide_index=True)

        network_sources = sorted(
            network_nodes["Source File"].dropna().astype(str).unique()
        )
        selected_network_source = st.selectbox(
            t["vehicle_session"], network_sources, key="network_source"
        )

        scoped_nodes = network_nodes[
            network_nodes["Source File"] == selected_network_source
        ].sort_values(
            ["Criticality Score", "Risk Score"], ascending=[False, False]
        )
        scoped_edges = network_edges[
            network_edges["Source File"] == selected_network_source
        ] if not network_edges.empty else network_edges
        scoped_violations = network_violations[
            network_violations["Source File"] == selected_network_source
        ] if not network_violations.empty else network_violations
        scoped_matrix = network_matrix[
            network_matrix["Source File"] == selected_network_source
        ] if not network_matrix.empty else network_matrix

        left, right = st.columns(2)
        with left:
            st.markdown(f"### {t['critical_ecu_ranking']}")
            st.dataframe(
                scoped_nodes[
                    ["ECU", "ECU Name", "Role", "Criticality",
                     "Criticality Score", "Risk Score", "Status",
                     "Persistent DTC Count", "Impact Radius"]
                ],
                width="stretch",
                hide_index=True,
            )
        with right:
            st.markdown(f"### {t['network_edges']}")
            st.dataframe(scoped_edges, width="stretch", hide_index=True)

        st.markdown(f"### {t['dependency_violations']}")
        if scoped_violations.empty:
            st.success(t["no_dependency_violations"])
        else:
            st.dataframe(
                scoped_violations, width="stretch", hide_index=True
            )

        st.markdown(f"### {t['dependency_matrix']}")
        st.dataframe(scoped_matrix, width="stretch", hide_index=True)

        selected_network_ecu = st.selectbox(
            t["select_network_ecu"],
            sorted(scoped_nodes["ECU"].astype(str).unique()),
            key="network_ecu",
        )
        selected_node = scoped_nodes[
            scoped_nodes["ECU"] == selected_network_ecu
        ].iloc[0]
        upstream = scoped_edges[
            scoped_edges["Downstream ECU"] == selected_network_ecu
        ]["Upstream ECU"].astype(str).tolist() if not scoped_edges.empty else []
        downstream = scoped_edges[
            scoped_edges["Upstream ECU"] == selected_network_ecu
        ]["Downstream ECU"].astype(str).tolist() if not scoped_edges.empty else []

        e1, e2, e3, e4 = st.columns(4)
        e1.metric(t["ecu_role"], selected_node["Role"])
        e2.metric(t["network_criticality"], selected_node["Criticality"])
        e3.metric(t["criticality_score"], f"{selected_node['Criticality Score']:.1f}")
        e4.metric(t["impact_radius"], int(selected_node["Impact Radius"]))
        st.info(
            f"{t['upstream_ecus']}: {', '.join(upstream) or '—'}\n\n"
            f"{t['downstream_ecus']}: {', '.join(downstream) or '—'}"
        )



with tabs[14]:
    st.subheader(t["network_explorer"])
    st.caption(t["network_explorer_help"])

    explorer_nodes = network_intelligence["nodes"]
    explorer_edges = network_intelligence["edges"]
    graph_stats = network_graph["statistics"]
    graph_components = network_graph["components"]
    graph_cycles = network_graph["cycles"]
    graph_heatmap = network_graph["heatmap"]
    graph_explorer = network_graph["explorer"]

    if explorer_nodes.empty:
        st.info(t["no_network_results"])
    else:
        explorer_sources = sorted(
            explorer_nodes["Source File"].dropna().astype(str).unique()
        )
        explorer_source = st.selectbox(
            t["vehicle_session"],
            explorer_sources,
            key="network_explorer_source",
        )
        source_nodes = explorer_nodes[
            explorer_nodes["Source File"] == explorer_source
        ].copy()
        source_edges = explorer_edges[
            explorer_edges["Source File"] == explorer_source
        ].copy() if not explorer_edges.empty else explorer_edges
        source_stats = graph_stats[
            graph_stats["Source File"] == explorer_source
        ]
        source_components = graph_components[
            graph_components["Source File"] == explorer_source
        ] if not graph_components.empty else graph_components
        source_cycles = graph_cycles[
            graph_cycles["Source File"] == explorer_source
        ] if not graph_cycles.empty else graph_cycles
        source_heatmap = graph_heatmap[
            graph_heatmap["Source File"] == explorer_source
        ].copy()
        source_explorer = graph_explorer[
            graph_explorer["Source File"] == explorer_source
        ].copy()

        roles = sorted(source_nodes["Role"].dropna().astype(str).unique())
        criticalities = sorted(
            source_nodes["Criticality"].dropna().astype(str).unique()
        )
        statuses = sorted(source_nodes["Status"].dropna().astype(str).unique())

        f1, f2, f3 = st.columns(3)
        selected_roles = f1.multiselect(
            t["network_role_filter"], roles, default=roles
        )
        selected_criticalities = f2.multiselect(
            t["criticality_filter"], criticalities, default=criticalities
        )
        selected_network_status = f3.multiselect(
            t["network_status_filter"], statuses, default=statuses
        )

        filtered_network_nodes = source_nodes[
            source_nodes["Role"].isin(selected_roles)
            & source_nodes["Criticality"].isin(selected_criticalities)
            & source_nodes["Status"].isin(selected_network_status)
        ].copy()
        visible_ecus = set(filtered_network_nodes["ECU"].astype(str))
        filtered_network_edges = source_edges[
            source_edges["Upstream ECU"].astype(str).isin(visible_ecus)
            & source_edges["Downstream ECU"].astype(str).isin(visible_ecus)
        ].copy() if not source_edges.empty else source_edges

        selected_graph_ecu = st.selectbox(
            t["highlight_ecu"],
            [""] + sorted(visible_ecus),
            key="network_graph_highlight",
        )
        components.html(
            network_svg(
                filtered_network_nodes,
                filtered_network_edges,
                selected_ecu=selected_graph_ecu,
            ),
            height=680,
            scrolling=False,
        )

        if not source_stats.empty:
            stats = source_stats.iloc[0]
            s1, s2, s3, s4, s5, s6, s7 = st.columns(7)
            s1.metric(t["network_nodes"], int(stats["Node Count"]))
            s2.metric(t["network_edges_count"], int(stats["Edge Count"]))
            s3.metric(t["average_degree"], f"{stats['Average Degree']:.2f}")
            s4.metric(t["maximum_depth"], int(stats["Maximum Depth"]))
            s5.metric(t["connected_components"], int(stats["Connected Components"]))
            s6.metric(t["circular_dependencies"], int(stats["Circular Dependencies"]))
            s7.metric(t["graph_integrity"], f"{stats['Graph Integrity Score']:.1f}/100")

        left, right = st.columns(2)
        with left:
            st.markdown(f"### {t['dependency_heatmap']}")
            components.html(
                heat_bar_html(source_heatmap),
                height=min(600, 55 + len(source_heatmap.head(20)) * 45),
                scrolling=True,
            )
            st.dataframe(
                source_heatmap,
                width="stretch",
                hide_index=True,
            )
        with right:
            st.markdown(f"### {t['network_statistics']}")
            st.dataframe(source_stats, width="stretch", hide_index=True)
            st.markdown(f"### {t['connected_components']}")
            st.dataframe(
                source_components,
                width="stretch",
                hide_index=True,
            )

        st.markdown(f"### {t['circular_dependencies']}")
        if source_cycles.empty:
            st.success(t["no_circular_dependencies"])
        else:
            st.dataframe(source_cycles, width="stretch", hide_index=True)

        st.markdown(f"### {t['dependency_explorer']}")
        explorer_ecu = st.selectbox(
            t["select_network_ecu"],
            sorted(source_explorer["ECU"].astype(str).unique()),
            key="dependency_explorer_ecu",
        )
        explorer_row = source_explorer[
            source_explorer["ECU"] == explorer_ecu
        ].iloc[0]
        x1, x2, x3, x4, x5 = st.columns(5)
        x1.metric(t["ecu_role"], explorer_row["Role"])
        x2.metric(t["network_criticality"], explorer_row["Criticality"])
        x3.metric(t["risk_score"], f"{explorer_row['Risk Score']:.1f}")
        x4.metric(t["impact_radius"], int(explorer_row["Impact Radius"]))
        x5.metric(t["persistent_dtcs"], int(explorer_row["Persistent DTC Count"]))
        st.info(
            f"{t['upstream_ecus']}: {explorer_row['Parents'] or '—'}\n\n"
            f"{t['downstream_ecus']}: {explorer_row['Children'] or '—'}\n\n"
            f"{t['dependency_types']}: {explorer_row['Dependency Types'] or '—'}"
        )
        st.dataframe(
            pd.DataFrame([explorer_row]),
            width="stretch",
            hide_index=True,
        )



with tabs[15]:
    st.subheader(t["update_impact_simulator"])
    st.caption(t["update_impact_help"])
    st.warning(t["update_impact_disclaimer"])

    simulator_nodes = network_intelligence["nodes"]
    simulator_edges = network_intelligence["edges"]

    if simulator_nodes.empty:
        st.info(t["no_network_results"])
    else:
        simulator_sources = sorted(
            simulator_nodes["Source File"].dropna().astype(str).unique()
        )
        simulator_source = st.selectbox(
            t["vehicle_session"],
            simulator_sources,
            key="impact_source",
        )
        source_simulator_nodes = simulator_nodes[
            simulator_nodes["Source File"] == simulator_source
        ].copy()
        simulator_ecus = sorted(
            source_simulator_nodes["ECU"].dropna().astype(str).unique()
        )
        simulator_ecu = st.selectbox(
            t["select_update_ecu"],
            simulator_ecus,
            key="impact_ecu",
        )
        release_candidates = candidate_target_releases(
            simulator_nodes,
            simulator_source,
            simulator_ecu,
        )
        selected_ecu_row = source_simulator_nodes[
            source_simulator_nodes["ECU"] == simulator_ecu
        ].iloc[0]

        default_release = (
            str(selected_ecu_row.get("Target Release", "") or "")
            or (
                release_candidates[-1]
                if release_candidates else ""
            )
        )
        proposed_release = st.text_input(
            t["proposed_target_release"],
            value=default_release,
            key="impact_target_release",
        )
        if release_candidates:
            st.caption(
                f"{t['available_release_candidates']}: "
                + ", ".join(release_candidates)
            )

        if st.button(
            t["run_update_simulation"],
            type="primary",
            key="run_update_simulation",
        ):
            impact_results, companion_results, update_sequence = (
                simulate_update_impact(
                    simulator_nodes,
                    simulator_edges,
                    simulator_source,
                    simulator_ecu,
                    proposed_release,
                    release_consistency=release_consistency,
                    rules=update_impact_rules,
                )
            )
            impact_summary = simulation_summary(
                impact_results,
                companion_results,
                update_sequence,
                rules=update_impact_rules,
            )
            st.session_state["impact_results"] = impact_results
            st.session_state["companion_results"] = companion_results
            st.session_state["update_sequence"] = update_sequence
            st.session_state["impact_summary"] = impact_summary

        impact_results = st.session_state.get(
            "impact_results", pd.DataFrame()
        )
        companion_results = st.session_state.get(
            "companion_results", pd.DataFrame()
        )
        update_sequence = st.session_state.get(
            "update_sequence", pd.DataFrame()
        )
        impact_summary = st.session_state.get(
            "impact_summary", pd.DataFrame()
        )

        if not impact_summary.empty:
            summary_row = impact_summary.iloc[0]
            u1, u2, u3, u4, u5 = st.columns(5)
            u1.metric(
                t["overall_compatibility"],
                f"{summary_row['Overall Compatibility Score']:.1f}/100",
            )
            u2.metric(
                t["compatibility_level"],
                summary_row["Overall Compatibility Level"],
            )
            u3.metric(
                t["affected_ecus"],
                int(summary_row["Affected ECUs"]),
            )
            u4.metric(
                t["companion_updates"],
                int(summary_row["Required Companion Updates"]),
            )
            u5.metric(
                t["high_risk_ecus"],
                int(summary_row["High-Risk ECUs"]),
            )
            if summary_row["Overall Compatibility Level"] == "HIGH_RISK":
                st.error(summary_row["Overall Recommendation"])
            elif summary_row["Overall Compatibility Level"] == "CONDITIONAL":
                st.warning(summary_row["Overall Recommendation"])
            else:
                st.success(summary_row["Overall Recommendation"])

            st.markdown(f"### {t['simulation_summary']}")
            st.dataframe(
                impact_summary,
                width="stretch",
                hide_index=True,
            )

            st.markdown(f"### {t['affected_ecu_analysis']}")
            st.dataframe(
                impact_results,
                width="stretch",
                hide_index=True,
            )

            st.markdown(f"### {t['companion_update_analysis']}")
            if companion_results.empty:
                st.info(t["no_companion_ecus"])
            else:
                st.dataframe(
                    companion_results,
                    width="stretch",
                    hide_index=True,
                )

            st.markdown(f"### {t['recommended_update_sequence']}")
            if update_sequence.empty:
                st.info(t["no_update_sequence"])
            else:
                st.dataframe(
                    update_sequence,
                    width="stretch",
                    hide_index=True,
                )

            st.download_button(
                t["download_simulation_csv"],
                impact_results.to_csv(index=False).encode("utf-8"),
                "GradeX_Update_Impact_Simulation.csv",
                "text/csv",
                width="stretch",
            )
        else:
            st.info(t["run_simulation_info"])



with tabs[16]:
    st.subheader(t["release_path_planner"])
    st.caption(t["release_path_help"])
    st.warning(t["release_path_disclaimer"])

    planner_nodes = network_intelligence["nodes"]
    planner_edges = network_intelligence["edges"]

    if planner_nodes.empty:
        st.info(t["no_network_results"])
    else:
        planner_sources = sorted(
            planner_nodes["Source File"].dropna().astype(str).unique()
        )
        planner_source = st.selectbox(
            t["vehicle_session"],
            planner_sources,
            key="release_path_source",
        )
        planner_source_nodes = planner_nodes[
            planner_nodes["Source File"] == planner_source
        ].copy()
        planner_ecus = sorted(
            planner_source_nodes["ECU"].dropna().astype(str).unique()
        )
        planner_ecu = st.selectbox(
            t["select_update_ecu"],
            planner_ecus,
            key="release_path_ecu",
        )

        release_catalog = available_release_catalog(
            planner_nodes,
            planner_source,
            planner_ecu,
        )
        default_candidates = [
            item for item in release_catalog
            if item != str(
                planner_source_nodes[
                    planner_source_nodes["ECU"] == planner_ecu
                ].iloc[0].get("Installed Release", "")
            )
        ]
        scenario_releases = st.multiselect(
            t["scenario_target_releases"],
            release_catalog,
            default=default_candidates[:3],
            key="scenario_target_releases",
        )
        additional_release = st.text_input(
            t["additional_target_release"],
            key="additional_target_release",
        )
        candidate_scenarios = list(scenario_releases)
        if additional_release.strip():
            candidate_scenarios.append(additional_release.strip())

        if st.button(
            t["compare_release_scenarios"],
            type="primary",
            key="compare_release_scenarios",
            disabled=not candidate_scenarios,
        ):
            (
                scenario_comparison,
                scenario_impacts,
                scenario_companions,
                scenario_sequences,
            ) = compare_update_scenarios(
                planner_nodes,
                planner_edges,
                planner_source,
                planner_ecu,
                candidate_scenarios,
                release_consistency=release_consistency,
                update_rules=update_impact_rules,
                path_rules=release_path_rules,
            )
            path_summary = release_path_summary(scenario_comparison)
            st.session_state["scenario_comparison"] = scenario_comparison
            st.session_state["scenario_impacts"] = scenario_impacts
            st.session_state["scenario_companions"] = scenario_companions
            st.session_state["scenario_sequences"] = scenario_sequences
            st.session_state["release_path_summary"] = path_summary

        scenario_comparison = st.session_state.get(
            "scenario_comparison", pd.DataFrame()
        )
        scenario_impacts = st.session_state.get(
            "scenario_impacts", pd.DataFrame()
        )
        scenario_companions = st.session_state.get(
            "scenario_companions", pd.DataFrame()
        )
        scenario_sequences = st.session_state.get(
            "scenario_sequences", pd.DataFrame()
        )
        path_summary = st.session_state.get(
            "release_path_summary", pd.DataFrame()
        )

        if not path_summary.empty:
            recommended = path_summary.iloc[0]
            p1, p2, p3, p4, p5 = st.columns(5)
            p1.metric(
                t["recommended_target_release"],
                recommended["Recommended Target Release"],
            )
            p2.metric(t["path_type"], recommended["Path Type"])
            p3.metric(
                t["path_score"],
                f"{recommended['Path Score']:.1f}/100",
            )
            p4.metric(
                t["scenario_score"],
                f"{recommended['Scenario Score']:.1f}/100",
            )
            p5.metric(
                t["update_steps"],
                int(recommended["Update Steps"]),
            )

            if recommended["Path Type"] == "ENGINEERING_REVIEW":
                st.error(recommended["Recommendation"])
            elif recommended["Path Type"] == "STAGED":
                st.warning(recommended["Recommendation"])
            else:
                st.success(recommended["Recommendation"])

            st.markdown(f"### {t['recommended_release_path']}")
            st.info(recommended["Recommended Release Path"])
            st.caption(recommended["Path Evidence"])

            st.markdown(f"### {t['scenario_comparison']}")
            st.dataframe(
                scenario_comparison,
                width="stretch",
                hide_index=True,
            )

            chart_frame = scenario_comparison[
                ["Candidate Target Release", "Scenario Score",
                 "Overall Compatibility Score", "Path Score"]
            ].set_index("Candidate Target Release")
            st.bar_chart(chart_frame)

            selected_scenario_release = st.selectbox(
                t["inspect_scenario"],
                scenario_comparison[
                    "Candidate Target Release"
                ].astype(str).tolist(),
                key="inspect_scenario_release",
            )
            st.markdown(f"### {t['scenario_impact_details']}")
            st.dataframe(
                scenario_impacts[
                    scenario_impacts["Scenario Target Release"]
                    == selected_scenario_release
                ],
                width="stretch",
                hide_index=True,
            )
            st.markdown(f"### {t['scenario_companion_updates']}")
            st.dataframe(
                scenario_companions[
                    scenario_companions["Scenario Target Release"]
                    == selected_scenario_release
                ],
                width="stretch",
                hide_index=True,
            )
            st.markdown(f"### {t['scenario_update_sequence']}")
            st.dataframe(
                scenario_sequences[
                    scenario_sequences["Scenario Target Release"]
                    == selected_scenario_release
                ],
                width="stretch",
                hide_index=True,
            )

            st.download_button(
                t["download_scenario_comparison"],
                scenario_comparison.to_csv(index=False).encode("utf-8"),
                "GradeX_Release_Path_Scenarios.csv",
                "text/csv",
                width="stretch",
            )
        else:
            st.info(t["run_scenario_comparison_info"])

        st.divider()
        st.markdown(f"### {t['network_timeline']}")
        if network_timeline.empty:
            st.info(t["no_network_timeline"])
        else:
            timeline_vins = sorted(
                network_timeline["VIN"].dropna().astype(str).unique()
            )
            timeline_vin = st.selectbox(
                t["select_vin"],
                timeline_vins,
                key="network_timeline_vin",
            )
            scoped_timeline = network_timeline[
                network_timeline["VIN"].astype(str) == str(timeline_vin)
            ].sort_values("Date")
            st.dataframe(
                scoped_timeline,
                width="stretch",
                hide_index=True,
            )
            if len(scoped_timeline) > 1:
                timeline_chart = scoped_timeline.set_index("Date")[
                    ["Vehicle Health", "Average Risk",
                     "Release Consistency",
                     "Root ECU Criticality Score"]
                ]
                st.line_chart(timeline_chart)



with tabs[17]:
    st.subheader(t["release_recommendation"])
    st.caption(t["release_recommendation_help"])
    st.warning(t["release_recommendation_disclaimer"])

    recommendation_scenarios = st.session_state.get(
        "scenario_comparison", pd.DataFrame()
    )
    recommendation_sequences = st.session_state.get(
        "scenario_sequences", pd.DataFrame()
    )

    if recommendation_scenarios.empty:
        st.info(t["run_release_path_first"])
    else:
        recommendation_summary, recommendation_ranking = recommend_release(
            recommendation_scenarios,
            vehicle_health,
            release_consistency,
            warranty_summary,
            assistant_summary,
            overview,
            historical_release_stats,
            rules=release_recommendation_rules,
        )
        recommendation_plan = build_update_plan(
            recommendation_summary,
            recommendation_sequences,
            rules=release_recommendation_rules,
        )

        st.session_state["release_recommendation_summary"] = (
            recommendation_summary
        )
        st.session_state["release_recommendation_ranking"] = (
            recommendation_ranking
        )
        st.session_state["release_update_plan"] = recommendation_plan

        lead_recommendation = recommendation_summary.iloc[0]
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric(
            t["recommended_target_release"],
            lead_recommendation["Recommended Target Release"],
        )
        r2.metric(
            t["recommendation_score"],
            f"{lead_recommendation['Recommendation Score']:.1f}/100",
        )
        r3.metric(
            t["recommendation_decision"],
            lead_recommendation["Recommendation Decision"],
        )
        r4.metric(
            t["companion_updates"],
            int(lead_recommendation["Required Companion Updates"]),
        )
        r5.metric(
            t["historical_success_rate"],
            f"{lead_recommendation['Historical Success Rate']:.1f}%",
        )

        decision = lead_recommendation["Recommendation Decision"]
        if decision == "RECOMMENDED":
            st.success(
                f"{t['recommended_release_path']}: "
                f"{lead_recommendation['Recommended Release Path']}"
            )
        elif decision == "RECOMMENDED_WITH_CONDITIONS":
            st.warning(
                f"{t['recommended_release_path']}: "
                f"{lead_recommendation['Recommended Release Path']}"
            )
        else:
            st.error(t["engineering_review_required"])

        st.markdown(f"### {t['recommendation_summary']}")
        st.dataframe(
            recommendation_summary,
            width="stretch",
            hide_index=True,
        )

        st.markdown(f"### {t['release_recommendation_ranking']}")
        st.dataframe(
            recommendation_ranking,
            width="stretch",
            hide_index=True,
        )

        chart_data = recommendation_ranking[
            [
                "Candidate Target Release",
                "Recommendation Score",
                "Compatibility Score",
                "Historical Success Rate",
            ]
        ].set_index("Candidate Target Release")
        st.bar_chart(chart_data)

        st.markdown(f"### {t['historical_release_performance']}")
        if historical_release_stats.empty:
            st.info(t["no_historical_release_data"])
        else:
            st.dataframe(
                historical_release_stats,
                width="stretch",
                hide_index=True,
            )

        st.markdown(f"### {t['recommended_action_plan']}")
        st.dataframe(
            recommendation_plan,
            width="stretch",
            hide_index=True,
        )

        st.download_button(
            t["download_recommendation_csv"],
            recommendation_ranking.to_csv(index=False).encode("utf-8"),
            "GradeX_Release_Recommendation.csv",
            "text/csv",
            width="stretch",
        )


with tabs[18]:
    st.dataframe(filtered_details.style.map(status_style, subset=["Status"]), width="stretch", hide_index=True)
with tabs[19]:
    st.dataframe(summary, width="stretch", hide_index=True)
with tabs[20]:
    st.dataframe(candidates.sort_values(["Source File", "ECU", "Candidate Score"], ascending=[True, True, False]), width="stretch", hide_index=True)
with tabs[21]:
    st.dataframe(raw, width="stretch", hide_index=True)
with tabs[22]:
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



with tabs[23]:
    st.subheader(t["time_series_analytics"])
    st.caption(t["time_series_help"])

    ts_frame = workspace_timeseries["timeseries"]
    ts_transitions = workspace_timeseries["transitions"]
    ts_trends = workspace_timeseries["vehicle_trends"]
    ts_timeline = workspace_timeseries["timeline"]

    if ts_frame.empty:
        st.info(t["no_timeseries_data"])
    else:
        unique_vins = ts_frame["VIN"].nunique()
        multi_session_vins = int(
            ts_frame.groupby("VIN")["Session ID"].nunique().gt(1).sum()
        )
        regressions = int(
            ts_transitions.get(
                "Transition Classification", pd.Series(dtype=str)
            ).astype(str).isin(["REGRESSION", "CRITICAL_REGRESSION"]).sum()
        ) if not ts_transitions.empty else 0
        improvements = int(
            ts_transitions.get(
                "Transition Classification", pd.Series(dtype=str)
            ).astype(str).isin(["IMPROVEMENT", "STRONG_IMPROVEMENT"]).sum()
        ) if not ts_transitions.empty else 0

        t1, t2, t3, t4, t5 = st.columns(5)
        t1.metric(t["tracked_vins"], unique_vins)
        t2.metric(t["multi_session_vins"], multi_session_vins)
        t3.metric(t["saved_analyses"], len(ts_frame))
        t4.metric(t["detected_regressions"], regressions)
        t5.metric(t["detected_improvements"], improvements)

        available_vins = sorted(ts_frame["VIN"].dropna().astype(str).unique())
        selected_ts_vin = st.selectbox(
            t["select_vin"], available_vins, key="timeseries_vin"
        )
        vin_history = ts_frame[
            ts_frame["VIN"].astype(str) == str(selected_ts_vin)
        ].sort_values(["Analysis Date", "Session ID"])
        vin_transitions = (
            ts_transitions[
                ts_transitions["VIN"].astype(str) == str(selected_ts_vin)
            ].sort_values("Current Date")
            if not ts_transitions.empty else pd.DataFrame()
        )
        vin_timeline = ts_timeline[
            ts_timeline["VIN"].astype(str) == str(selected_ts_vin)
        ].sort_values("Date")

        if len(vin_history) < 2:
            st.warning(t["single_session_vin"])
        else:
            first = vin_history.iloc[0]
            latest = vin_history.iloc[-1]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric(
                t["vehicle_health_change"],
                f"{latest['Vehicle Health'] - first['Vehicle Health']:+.1f}",
                delta=f"{latest['Vehicle Health']:.1f}",
            )
            c2.metric(
                t["risk_change"],
                f"{latest['Average Risk'] - first['Average Risk']:+.1f}",
                delta=f"{latest['Average Risk']:.1f}",
                delta_color="inverse",
            )
            c3.metric(
                t["compliance_change"],
                f"{latest['Compliance Rate'] - first['Compliance Rate']:+.1f}",
                delta=f"{latest['Compliance Rate']:.1f}%",
            )
            c4.metric(
                t["consistency_change"],
                f"{latest['Release Consistency'] - first['Release Consistency']:+.1f}",
                delta=f"{latest['Release Consistency']:.1f}%",
            )

            chart_data = vin_history.set_index("Analysis Date")[
                ["Vehicle Health", "Compliance Rate", "Release Consistency"]
            ]
            st.markdown(f"### {t['health_compliance_trend']}")
            st.line_chart(chart_data)

            risk_chart = vin_history.set_index("Analysis Date")[["Average Risk"]]
            st.markdown(f"### {t['risk_trend']}")
            st.line_chart(risk_chart)

        st.markdown(f"### {t['vehicle_timeline']}")
        st.dataframe(vin_timeline, width="stretch", hide_index=True)

        st.markdown(f"### {t['transition_analysis']}")
        if vin_transitions.empty:
            st.info(t["no_transitions"])
        else:
            transition_filter = st.multiselect(
                t["transition_classification"],
                sorted(
                    vin_transitions["Transition Classification"]
                    .dropna().astype(str).unique()
                ),
                default=sorted(
                    vin_transitions["Transition Classification"]
                    .dropna().astype(str).unique()
                ),
                key="transition_filter",
            )
            st.dataframe(
                vin_transitions[
                    vin_transitions["Transition Classification"].isin(
                        transition_filter
                    )
                ],
                width="stretch",
                hide_index=True,
            )

        with st.expander(t["all_vehicle_trends"]):
            st.dataframe(ts_trends, width="stretch", hide_index=True)

        with st.expander(t["all_saved_timeseries"]):
            st.dataframe(ts_frame, width="stretch", hide_index=True)


with tabs[24]:
    render_configuration_diff(t, "main_diff")


session_merge_report = st.session_state.get("main_merge_merge", {})
session_merge_summary_report = session_merge_report.get("summary", pd.DataFrame()) if session_merge_report else pd.DataFrame()
session_merge_snapshot_report = session_merge_report.get("snapshot", pd.DataFrame()) if session_merge_report else pd.DataFrame()
session_merge_provenance_report = session_merge_report.get("field_provenance", pd.DataFrame()) if session_merge_report else pd.DataFrame()
session_merge_conflicts_report = session_merge_report.get("conflicts", pd.DataFrame()) if session_merge_report else pd.DataFrame()
session_merge_presence_report = session_merge_report.get("ecu_presence", pd.DataFrame()) if session_merge_report else pd.DataFrame()
session_merge_catalog_report = session_merge_report.get("session_catalog", pd.DataFrame()) if session_merge_report else pd.DataFrame()
session_merge_history_report = session_merge_report.get("change_history", pd.DataFrame()) if session_merge_report else pd.DataFrame()

oem_audit_report = st.session_state.get("main_oem_audit_audit", {})
oem_audit_summary_report = oem_audit_report.get("summary", pd.DataFrame()) if oem_audit_report else pd.DataFrame()
oem_audit_checklist_report = oem_audit_report.get("checklist", pd.DataFrame()) if oem_audit_report else pd.DataFrame()
oem_audit_findings_report = oem_audit_report.get("findings", pd.DataFrame()) if oem_audit_report else pd.DataFrame()
oem_audit_area_summary_report = oem_audit_report.get("area_summary", pd.DataFrame()) if oem_audit_report else pd.DataFrame()

release_coverage_report = st.session_state.get("main_release_coverage_coverage", {})
release_coverage_summary_report = release_coverage_report.get("summary", pd.DataFrame()) if release_coverage_report else pd.DataFrame()
release_coverage_ecus_report = release_coverage_report.get("ecu_coverage", pd.DataFrame()) if release_coverage_report else pd.DataFrame()
release_coverage_installed_report = release_coverage_report.get("installed_distribution", pd.DataFrame()) if release_coverage_report else pd.DataFrame()
release_coverage_target_report = release_coverage_report.get("target_distribution", pd.DataFrame()) if release_coverage_report else pd.DataFrame()
release_coverage_by_target_report = release_coverage_report.get("coverage_by_target", pd.DataFrame()) if release_coverage_report else pd.DataFrame()
release_coverage_legacy_report = release_coverage_report.get("legacy_candidates", pd.DataFrame()) if release_coverage_report else pd.DataFrame()
release_coverage_unknown_report = release_coverage_report.get("unknown_releases", pd.DataFrame()) if release_coverage_report else pd.DataFrame()
release_reference_coverage_report = release_coverage_report.get("reference_coverage", pd.DataFrame()) if release_coverage_report else pd.DataFrame()
release_session_trend_report = release_coverage_report.get("session_release_trend", pd.DataFrame()) if release_coverage_report else pd.DataFrame()

compliance_dashboard_report = st.session_state.get("main_dashboard_dashboard", {})
compliance_dashboard_summary_report = compliance_dashboard_report.get("summary", pd.DataFrame()) if compliance_dashboard_report else pd.DataFrame()
compliance_dashboard_status_report = compliance_dashboard_report.get("status_distribution", pd.DataFrame()) if compliance_dashboard_report else pd.DataFrame()
compliance_dashboard_risk_report = compliance_dashboard_report.get("risk_distribution", pd.DataFrame()) if compliance_dashboard_report else pd.DataFrame()
compliance_dashboard_failing_report = compliance_dashboard_report.get("top_failing_ecus", pd.DataFrame()) if compliance_dashboard_report else pd.DataFrame()
compliance_dashboard_release_report = compliance_dashboard_report.get("release_distribution", pd.DataFrame()) if compliance_dashboard_report else pd.DataFrame()
compliance_dashboard_trend_report = compliance_dashboard_report.get("transition_trend", pd.DataFrame()) if compliance_dashboard_report else pd.DataFrame()

advanced_search_results_report = st.session_state.get("main_search_results", pd.DataFrame())
advanced_search_summary_report = st.session_state.get("main_search_summary", pd.DataFrame())

multi_session_result_report = st.session_state.get("main_multi_result", {})
multi_session_catalog_report = multi_session_result_report.get("catalog", pd.DataFrame()) if multi_session_result_report else pd.DataFrame()
multi_session_transition_summary_report = multi_session_result_report.get("transition_summary", pd.DataFrame()) if multi_session_result_report else pd.DataFrame()
multi_session_transition_ecus_report = multi_session_result_report.get("transition_ecus", pd.DataFrame()) if multi_session_result_report else pd.DataFrame()
multi_session_transition_fields_report = multi_session_result_report.get("transition_fields", pd.DataFrame()) if multi_session_result_report else pd.DataFrame()
multi_session_ecu_timeline_report = multi_session_result_report.get("ecu_timeline", pd.DataFrame()) if multi_session_result_report else pd.DataFrame()
multi_session_change_history_report = multi_session_result_report.get("change_history", pd.DataFrame()) if multi_session_result_report else pd.DataFrame()
multi_session_vehicle_trend_report = multi_session_result_report.get("vehicle_trend", pd.DataFrame()) if multi_session_result_report else pd.DataFrame()

configuration_diff_result_report = st.session_state.get("main_diff_diff_result", {})
configuration_diff_summary_report = (
    configuration_diff_result_report.get("summary", pd.DataFrame())
    if configuration_diff_result_report else pd.DataFrame()
)
configuration_diff_ecu_report = (
    configuration_diff_result_report.get("ecu_diff", pd.DataFrame())
    if configuration_diff_result_report else pd.DataFrame()
)
configuration_diff_fields_report = (
    configuration_diff_result_report.get("field_diff", pd.DataFrame())
    if configuration_diff_result_report else pd.DataFrame()
)

impact_results_report = st.session_state.get("impact_results", pd.DataFrame())
companion_results_report = st.session_state.get("companion_results", pd.DataFrame())
update_sequence_report = st.session_state.get("update_sequence", pd.DataFrame())
impact_summary_report = st.session_state.get("impact_summary", pd.DataFrame())

scenario_comparison_report = st.session_state.get("scenario_comparison", pd.DataFrame())
scenario_impacts_report = st.session_state.get("scenario_impacts", pd.DataFrame())
scenario_companions_report = st.session_state.get("scenario_companions", pd.DataFrame())
scenario_sequences_report = st.session_state.get("scenario_sequences", pd.DataFrame())
release_path_summary_report = st.session_state.get("release_path_summary", pd.DataFrame())

release_recommendation_summary_report = st.session_state.get("release_recommendation_summary", pd.DataFrame())
release_recommendation_ranking_report = st.session_state.get("release_recommendation_ranking", pd.DataFrame())
release_update_plan_report = st.session_state.get("release_update_plan", pd.DataFrame())

with tabs[25]:
    render_multi_session_analysis(t, "main_multi")

with tabs[26]:
    render_advanced_search(
        t,
        overview_frame=overview,
        details_frame=details,
        summary_frame=summary,
        dtc_frame=dtc_events,
        key_prefix="main_search",
    )

with tabs[27]:
    render_compliance_dashboard(
        t,
        overview_frame=overview,
        release_consistency_frame=release_consistency,
        vehicle_health_frame=vehicle_health,
        network_health_frame=network_intelligence["health"],
        dtc_frame=dtc_events,
        key_prefix="main_dashboard",
    )

with tabs[28]:
    render_release_coverage_dashboard(
        t,
        overview_frame=overview,
        reference_frame=target_reference,
        release_consistency_frame=release_consistency,
        key_prefix="main_release_coverage",
    )

with tabs[29]:
    render_oem_audit(
        t,
        overview_frame=overview,
        details_frame=details,
        summary_frame=summary,
        vehicle_health_frame=vehicle_health,
        release_consistency_frame=release_consistency,
        network_health_frame=network_intelligence["health"],
        dtc_frame=dtc_events,
        reference_frame=target_reference,
        key_prefix="main_oem_audit",
    )

with tabs[30]:
    render_session_merge(t, "main_merge")

dynamic_report_sections = {
    "EXECUTIVE_SUMMARY": [
        ("Vehicle Health", vehicle_health),
        ("Engineering Assistant Summary", assistant_summary),
        ("Vehicle Decisions", vehicle_decisions),
    ],
    "COMPLIANCE": [
        ("Compliance Overview", overview),
        ("Detailed Compliance", details),
        ("Session Summary", summary),
    ],
    "ECU_DETAILS": [
        ("Raw ECU Data", raw),
        ("Reference Candidates", candidates),
        ("ECU Identifiers", summary),
    ],
    "DTC": [
        ("DTC Summary", dtc_summary),
        ("DTC Events", dtc_events),
    ],
    "RISK_HEALTH": [
        ("Vehicle Health", vehicle_health),
        ("Risk Breakdown", risk_breakdown),
        ("Decision Actions", decision_actions),
    ],
    "RELEASE_CONSISTENCY": [
        ("Release Consistency", release_consistency),
        ("Consistency Fields", consistency_fields),
        ("ECU Consistency", ecu_consistency),
    ],
    "NETWORK": [
        ("Network Nodes", network_intelligence["nodes"]),
        ("Network Edges", network_intelligence["edges"]),
        ("Network Health", network_intelligence["health"]),
        ("Network Violations", network_intelligence["violations"]),
        ("Network Statistics", network_graph["statistics"]),
    ],
    "UPDATE_PLANNING": [
        ("Update Impact Summary", impact_summary_report),
        ("Update Impact Results", impact_results_report),
        ("Companion ECU Updates", companion_results_report),
        ("Update Sequence", update_sequence_report),
        ("Release Path Summary", release_path_summary_report),
        ("Release Scenario Comparison", scenario_comparison_report),
        ("Release Recommendation", release_recommendation_summary_report),
        ("Recommended Update Plan", release_update_plan_report),
    ],
    "CONFIGURATION_DIFF": [
        ("Configuration Diff Summary", configuration_diff_summary_report),
        ("ECU Differences", configuration_diff_ecu_report),
        ("Field Differences", configuration_diff_fields_report),
    ],
    "MULTI_SESSION": [
        ("Multi-Session Catalog", multi_session_catalog_report),
        ("Transition Summary", multi_session_transition_summary_report),
        ("Transition ECU Differences", multi_session_transition_ecus_report),
        ("Transition Field Differences", multi_session_transition_fields_report),
        ("ECU Timeline", multi_session_ecu_timeline_report),
        ("ECU Change History", multi_session_change_history_report),
        ("Vehicle Session Trend", multi_session_vehicle_trend_report),
    ],
    "ADVANCED_SEARCH": [
        ("Advanced Search Summary", advanced_search_summary_report),
        ("Advanced Search Results", advanced_search_results_report),
    ],
    "QUALITY_DASHBOARD": [
        ("Compliance Dashboard", compliance_dashboard_summary_report),
        ("Compliance Distribution", compliance_dashboard_status_report),
        ("Risk Distribution", compliance_dashboard_risk_report),
        ("Top Failing ECUs", compliance_dashboard_failing_report),
        ("Quality Trend", compliance_dashboard_trend_report),
    ],
    "RELEASE_COVERAGE": [
        ("Release Coverage Summary", release_coverage_summary_report),
        ("ECU Release Coverage", release_coverage_ecus_report),
        ("Coverage by Target", release_coverage_by_target_report),
        ("Legacy Candidates", release_coverage_legacy_report),
        ("Unknown Releases", release_coverage_unknown_report),
        ("Reference Coverage", release_reference_coverage_report),
    ],
    "OEM_AUDIT": [
        ("OEM Audit Summary", oem_audit_summary_report),
        ("OEM Audit Checklist", oem_audit_checklist_report),
        ("Open Audit Findings", oem_audit_findings_report),
        ("Audit Area Summary", oem_audit_area_summary_report),
    ],
    "SESSION_MERGE": [
        ("Session Merge Summary", session_merge_summary_report),
        ("Unified Vehicle Snapshot", session_merge_snapshot_report),
        ("Field Provenance", session_merge_provenance_report),
        ("Merge Conflicts", session_merge_conflicts_report),
        ("ECU Presence", session_merge_presence_report),
        ("Merged Session Catalog", session_merge_catalog_report),
        ("Merged Change History", session_merge_history_report),
    ],
    "DATA_QUALITY": [
        ("Readiness Summary", st.session_state.get("main_data_quality_quality", {}).get("summary", pd.DataFrame())),
        ("Data Quality Checklist", st.session_state.get("main_data_quality_quality", {}).get("checklist", pd.DataFrame())),
        ("Field Quality", st.session_state.get("main_data_quality_quality", {}).get("field_quality", pd.DataFrame())),
        ("Reference Match", st.session_state.get("main_data_quality_quality", {}).get("reference_match", pd.DataFrame())),
        ("Data Quality Findings", st.session_state.get("main_data_quality_quality", {}).get("findings", pd.DataFrame())),
    ],
    "FLEET_SNAPSHOT": [
        ("Fleet Summary", st.session_state.get("main_fleet_snapshot_fleet", {}).get("fleet_summary", pd.DataFrame())),
        ("Vehicle Ranking", st.session_state.get("main_fleet_snapshot_fleet", {}).get("vehicle_ranking", pd.DataFrame())),
        ("Vehicle Summary", st.session_state.get("main_fleet_snapshot_fleet", {}).get("vehicle_summary", pd.DataFrame())),
        ("Fleet ECU Overview", st.session_state.get("main_fleet_snapshot_fleet", {}).get("ecu_overview", pd.DataFrame())),
        ("Fleet Field Details", st.session_state.get("main_fleet_snapshot_fleet", {}).get("field_details", pd.DataFrame())),
        ("Top Failing ECUs", st.session_state.get("main_fleet_snapshot_fleet", {}).get("top_failing_ecus", pd.DataFrame())),
    ],
    "FULL_ASSESSMENT": [
        ("Full Assessment Summary", st.session_state.get("main_orchestrator_assessment", {}).get("summary", pd.DataFrame())),
        ("Assessment Gates", st.session_state.get("main_orchestrator_assessment", {}).get("gates", pd.DataFrame())),
        ("Open Assessment Actions", st.session_state.get("main_orchestrator_assessment", {}).get("open_actions", pd.DataFrame())),
        ("Assistant Actions", st.session_state.get("main_orchestrator_assessment", {}).get("assistant_actions", pd.DataFrame())),
    ],
    "PROGRAMMING_VALIDATION": [
        ("Programming Validation Summary", st.session_state.get("main_programming_validation_result", {}).get("summary", pd.DataFrame())),
        ("Programming Validation Gates", st.session_state.get("main_programming_validation_result", {}).get("gates", pd.DataFrame())),
        ("ECU Validation Results", st.session_state.get("main_programming_validation_result", {}).get("ecu_validation", pd.DataFrame())),
        ("Programming Findings", st.session_state.get("main_programming_validation_result", {}).get("findings", pd.DataFrame())),
        ("Programming Configuration Diff", st.session_state.get("main_programming_validation_result", {}).get("configuration_diff_ecus", pd.DataFrame())),
    ],
    "CORRECTIVE_ACTIONS": [
        ("Corrective Action Summary", st.session_state.get("main_corrective_action_result", {}).get("summary", pd.DataFrame())),
        ("Corrective Action Plan", st.session_state.get("main_corrective_action_result", {}).get("actions", pd.DataFrame())),
        ("Sign-off Evidence Matrix", st.session_state.get("main_corrective_action_result", {}).get("evidence_matrix", pd.DataFrame())),
        ("Team Action Summary", st.session_state.get("main_corrective_action_result", {}).get("team_summary", pd.DataFrame())),
    ],
    "CLOSURE_VERIFICATION": [
        ("Closure Summary", st.session_state.get("main_closure_verification_result", {}).get("summary", pd.DataFrame())),
        ("Closure Register", st.session_state.get("main_closure_verification_result", {}).get("register", pd.DataFrame())),
        ("Remaining Open Actions", st.session_state.get("main_closure_verification_result", {}).get("open_actions", pd.DataFrame())),
        ("Final Evidence Matrix", st.session_state.get("main_closure_verification_result", {}).get("evidence_matrix", pd.DataFrame())),
        ("Team Closure Summary", st.session_state.get("main_closure_verification_result", {}).get("team_summary", pd.DataFrame())),
    ],
}

with tabs[31]:
    render_dynamic_report_builder(
        t,
        section_frames=dynamic_report_sections,
        key_prefix="main_dynamic_report",
    )

with tabs[32]:
    render_data_quality_gate(
        t,
        session_frame=raw,
        reference_frame=target_reference,
        dtc_frame=dtc_events,
        key_prefix="main_data_quality",
    )

with tabs[33]:
    render_fleet_snapshot(
        t,
        target_reference_frame=target_reference,
        release_catalog_frame=release_catalog,
        key_prefix="main_fleet_snapshot",
    )

with tabs[34]:
    render_analysis_orchestrator(
        t,
        overview_frame=overview,
        details_frame=details,
        summary_frame=summary,
        dtc_frame=dtc_events,
        vehicle_health_frame=vehicle_health,
        release_consistency_frame=release_consistency,
        network_health_frame=network_intelligence["health"],
        assistant_summary_frame=assistant_summary,
        assistant_action_plan_frame=assistant_action_plan,
        reference_frame=target_reference,
        key_prefix="main_orchestrator",
    )

with tabs[35]:
    render_programming_validation(
        t,
        target_reference_frame=target_reference,
        release_catalog_frame=release_catalog,
        key_prefix="main_programming_validation",
    )

with tabs[36]:
    render_corrective_action_planner(t, "main_corrective_action")

with tabs[37]:
    render_closure_verification(t, "main_closure_verification")

with tabs[38]:
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
            workspace_timeseries=workspace_timeseries["timeseries"],
            timeseries_transitions=workspace_timeseries["transitions"],
            vehicle_trend_summary=workspace_timeseries["vehicle_trends"],
            timeline_events=workspace_timeseries["timeline"],
            timeseries_rules=timeseries_rules,
            network_nodes=network_intelligence["nodes"],
            network_edges=network_intelligence["edges"],
            dependency_matrix=network_intelligence["matrix"],
            network_violations=network_intelligence["violations"],
            network_health=network_intelligence["health"],
            network_criticality=network_intelligence["criticality"],
            network_rules=network_rules,
            network_statistics=network_graph["statistics"],
            network_components=network_graph["components"],
            network_cycles=network_graph["cycles"],
            network_heatmap=network_graph["heatmap"],
            network_explorer=network_graph["explorer"],
            update_impact_summary=impact_summary_report,
            update_impact_results=impact_results_report,
            companion_updates=companion_results_report,
            update_sequence=update_sequence_report,
            update_impact_rules=update_impact_rules,
            release_path_summary=release_path_summary_report,
            release_scenario_comparison=scenario_comparison_report,
            release_scenario_impacts=scenario_impacts_report,
            release_scenario_companions=scenario_companions_report,
            release_scenario_sequences=scenario_sequences_report,
            network_timeline=network_timeline,
            release_path_rules=release_path_rules,
            release_recommendation_summary=release_recommendation_summary_report,
            release_recommendation_ranking=release_recommendation_ranking_report,
            historical_release_performance=historical_release_stats,
            release_update_plan=release_update_plan_report,
            release_recommendation_rules=release_recommendation_rules,
            configuration_diff_summary=configuration_diff_summary_report,
            configuration_diff_ecus=configuration_diff_ecu_report,
            configuration_diff_fields=configuration_diff_fields_report,
            multi_session_catalog=multi_session_catalog_report,
            multi_session_transition_summary=multi_session_transition_summary_report,
            multi_session_transition_ecus=multi_session_transition_ecus_report,
            multi_session_transition_fields=multi_session_transition_fields_report,
            multi_session_ecu_timeline=multi_session_ecu_timeline_report,
            multi_session_change_history=multi_session_change_history_report,
            multi_session_vehicle_trend=multi_session_vehicle_trend_report,
            advanced_search_summary=advanced_search_summary_report,
            advanced_search_results=advanced_search_results_report,
            compliance_dashboard_summary=compliance_dashboard_summary_report,
            compliance_dashboard_status=compliance_dashboard_status_report,
            compliance_dashboard_risk=compliance_dashboard_risk_report,
            compliance_dashboard_failing=compliance_dashboard_failing_report,
            compliance_dashboard_release=compliance_dashboard_release_report,
            compliance_dashboard_trend=compliance_dashboard_trend_report,
            release_coverage_summary=release_coverage_summary_report,
            release_coverage_ecus=release_coverage_ecus_report,
            release_coverage_installed=release_coverage_installed_report,
            release_coverage_target=release_coverage_target_report,
            release_coverage_by_target=release_coverage_by_target_report,
            release_coverage_legacy=release_coverage_legacy_report,
            release_coverage_unknown=release_coverage_unknown_report,
            release_reference_coverage=release_reference_coverage_report,
            release_session_trend=release_session_trend_report,
            oem_audit_summary=oem_audit_summary_report,
            oem_audit_checklist=oem_audit_checklist_report,
            oem_audit_findings=oem_audit_findings_report,
            oem_audit_area_summary=oem_audit_area_summary_report,
            oem_audit_rules=oem_audit_rules,
            session_merge_summary=session_merge_summary_report,
            session_merge_snapshot=session_merge_snapshot_report,
            session_merge_provenance=session_merge_provenance_report,
            session_merge_conflicts=session_merge_conflicts_report,
            session_merge_presence=session_merge_presence_report,
            session_merge_catalog=session_merge_catalog_report,
            session_merge_history=session_merge_history_report,
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
            workspace_timeseries=workspace_timeseries["timeseries"],
            timeseries_transitions=workspace_timeseries["transitions"],
            vehicle_trend_summary=workspace_timeseries["vehicle_trends"],
            timeline_events=workspace_timeseries["timeline"],
            network_nodes=network_intelligence["nodes"],
            network_edges=network_intelligence["edges"],
            network_violations=network_intelligence["violations"],
            network_health=network_intelligence["health"],
            network_criticality=network_intelligence["criticality"],
            network_statistics=network_graph["statistics"],
            network_components=network_graph["components"],
            network_cycles=network_graph["cycles"],
            network_heatmap=network_graph["heatmap"],
            update_impact_summary=impact_summary_report,
            update_impact_results=impact_results_report,
            companion_updates=companion_results_report,
            update_sequence=update_sequence_report,
            release_path_summary=release_path_summary_report,
            release_scenario_comparison=scenario_comparison_report,
            release_scenario_sequences=scenario_sequences_report,
            network_timeline=network_timeline,
            release_recommendation_summary=release_recommendation_summary_report,
            release_recommendation_ranking=release_recommendation_ranking_report,
            historical_release_performance=historical_release_stats,
            release_update_plan=release_update_plan_report,
            configuration_diff_summary=configuration_diff_summary_report,
            configuration_diff_ecus=configuration_diff_ecu_report,
            configuration_diff_fields=configuration_diff_fields_report,
            multi_session_catalog=multi_session_catalog_report,
            multi_session_transition_summary=multi_session_transition_summary_report,
            multi_session_transition_ecus=multi_session_transition_ecus_report,
            multi_session_transition_fields=multi_session_transition_fields_report,
            multi_session_ecu_timeline=multi_session_ecu_timeline_report,
            multi_session_change_history=multi_session_change_history_report,
            multi_session_vehicle_trend=multi_session_vehicle_trend_report,
            advanced_search_summary=advanced_search_summary_report,
            advanced_search_results=advanced_search_results_report,
            compliance_dashboard_summary=compliance_dashboard_summary_report,
            compliance_dashboard_status=compliance_dashboard_status_report,
            compliance_dashboard_risk=compliance_dashboard_risk_report,
            compliance_dashboard_failing=compliance_dashboard_failing_report,
            compliance_dashboard_release=compliance_dashboard_release_report,
            compliance_dashboard_trend=compliance_dashboard_trend_report,
            release_coverage_summary=release_coverage_summary_report,
            release_coverage_ecus=release_coverage_ecus_report,
            release_coverage_installed=release_coverage_installed_report,
            release_coverage_target=release_coverage_target_report,
            release_coverage_by_target=release_coverage_by_target_report,
            release_coverage_legacy=release_coverage_legacy_report,
            release_coverage_unknown=release_coverage_unknown_report,
            release_reference_coverage=release_reference_coverage_report,
            release_session_trend=release_session_trend_report,
            oem_audit_summary=oem_audit_summary_report,
            oem_audit_checklist=oem_audit_checklist_report,
            oem_audit_findings=oem_audit_findings_report,
            oem_audit_area_summary=oem_audit_area_summary_report,
            oem_audit_rules=oem_audit_rules,
            session_merge_summary=session_merge_summary_report,
            session_merge_snapshot=session_merge_snapshot_report,
            session_merge_provenance=session_merge_provenance_report,
            session_merge_conflicts=session_merge_conflicts_report,
            session_merge_presence=session_merge_presence_report,
            session_merge_catalog=session_merge_catalog_report,
            session_merge_history=session_merge_history_report,
        )

        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                t["download_excel"], excel, "GradeX_Configuration_Intelligence_Report_Sprint11_4.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary", width="stretch"
            )
        with d2:
            st.download_button(
                t["download_pdf"], pdf, "GradeX_Configuration_Intelligence_Report_Sprint11_4.pdf",
                "application/pdf", width="stretch"
            )

        st.success(t["reports_ready"])

