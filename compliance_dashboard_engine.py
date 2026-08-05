from __future__ import annotations

from typing import Any

import pandas as pd


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_compliance_dashboard(
    overview: pd.DataFrame,
    release_consistency: pd.DataFrame | None = None,
    vehicle_health: pd.DataFrame | None = None,
    network_health: pd.DataFrame | None = None,
    dtc_events: pd.DataFrame | None = None,
    diff_result: dict[str, pd.DataFrame] | None = None,
    multi_session_result: dict[str, pd.DataFrame] | None = None,
) -> dict[str, pd.DataFrame]:
    overview = overview.copy() if overview is not None else pd.DataFrame()
    diff_result = diff_result or {}
    multi_session_result = multi_session_result or {}

    total_ecus = len(overview)
    status_counts = (
        overview["Status"].astype(str).value_counts().to_dict()
        if not overview.empty and "Status" in overview.columns else {}
    )
    compliant = int(status_counts.get("COMPLIANT", 0))
    mismatch = int(status_counts.get("MISMATCH", 0))
    wrong_release = int(status_counts.get("WRONG_RELEASE", 0))
    missing = int(status_counts.get("MISSING", 0))
    compliance_rate = compliant / total_ecus * 100 if total_ecus else 0.0

    risk_values = pd.to_numeric(
        overview.get("Risk Score", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0)
    critical_risk = int((risk_values >= 75).sum())
    high_risk = int(((risk_values >= 50) & (risk_values < 75)).sum())
    average_risk = float(risk_values.mean()) if len(risk_values) else 0.0

    persistent_dtcs = int(
        pd.to_numeric(
            overview.get("Persistent DTC Count", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0).sum()
    )
    dtc_count = len(dtc_events) if dtc_events is not None else 0

    consistency_score = 0.0
    mixed_package = False
    if release_consistency is not None and not release_consistency.empty:
        consistency_score = _num(
            release_consistency.iloc[0].get("Release Consistency Score", 0)
        )
        mixed_package = bool(
            release_consistency.iloc[0].get("Mixed Package Detected", False)
        )

    vehicle_health_score = 0.0
    if vehicle_health is not None and not vehicle_health.empty:
        vehicle_health_score = _num(
            vehicle_health.iloc[0].get("Vehicle Health Score", 0)
        )

    network_health_score = 0.0
    network_level = ""
    if network_health is not None and not network_health.empty:
        network_health_score = _num(
            network_health.iloc[0].get("Network Health Score", 0)
        )
        network_level = str(
            network_health.iloc[0].get("Network Health Level", "")
        )

    diff_summary = diff_result.get("summary", pd.DataFrame())
    modified_ecus = added_ecus = removed_ecus = critical_differences = 0
    if diff_summary is not None and not diff_summary.empty:
        row = diff_summary.iloc[0]
        modified_ecus = int(_num(row.get("Modified ECUs", 0)))
        added_ecus = int(_num(row.get("Added ECUs", 0)))
        removed_ecus = int(_num(row.get("Removed ECUs", 0)))
        critical_differences = int(_num(row.get("Critical Differences", 0)))

    transition_summary = multi_session_result.get(
        "transition_summary", pd.DataFrame()
    )
    critical_transitions = 0
    major_transitions = 0
    if transition_summary is not None and not transition_summary.empty:
        assessments = transition_summary.get(
            "Overall Assessment", pd.Series(dtype=str)
        ).astype(str)
        critical_transitions = int(assessments.eq("CRITICAL_CHANGE").sum())
        major_transitions = int(assessments.eq("MAJOR_CHANGE").sum())

    overall_score = (
        compliance_rate * 0.35
        + consistency_score * 0.20
        + vehicle_health_score * 0.20
        + network_health_score * 0.15
        + max(0.0, 100.0 - average_risk) * 0.10
    )
    penalties = (
        min(20, persistent_dtcs * 4)
        + (10 if mixed_package else 0)
        + min(15, critical_differences * 3)
        + min(15, critical_transitions * 5)
    )
    overall_score = max(0.0, min(100.0, overall_score - penalties))
    overall_level = (
        "GOOD" if overall_score >= 85
        else "FAIR" if overall_score >= 70
        else "POOR" if overall_score >= 50
        else "CRITICAL"
    )

    summary = pd.DataFrame([{
        "Total ECUs": total_ecus,
        "Compliant ECUs": compliant,
        "Compliance Rate %": round(compliance_rate, 1),
        "Mismatch ECUs": mismatch,
        "Wrong Release ECUs": wrong_release,
        "Missing ECUs": missing,
        "Critical-Risk ECUs": critical_risk,
        "High-Risk ECUs": high_risk,
        "Average Risk": round(average_risk, 1),
        "Persistent DTCs": persistent_dtcs,
        "DTC Events": dtc_count,
        "Release Consistency %": round(consistency_score, 1),
        "Mixed Package": mixed_package,
        "Vehicle Health": round(vehicle_health_score, 1),
        "Network Health": round(network_health_score, 1),
        "Network Level": network_level,
        "Modified ECUs": modified_ecus,
        "Added ECUs": added_ecus,
        "Removed ECUs": removed_ecus,
        "Critical Differences": critical_differences,
        "Critical Transitions": critical_transitions,
        "Major Transitions": major_transitions,
        "Overall Quality Score": round(overall_score, 1),
        "Overall Quality Level": overall_level,
    }])

    status_distribution = pd.DataFrame([
        {"Status": key, "Count": int(value)}
        for key, value in sorted(status_counts.items())
    ])

    risk_distribution = pd.DataFrame([
        {"Risk Band": "CRITICAL", "Count": critical_risk},
        {"Risk Band": "HIGH", "Count": high_risk},
        {
            "Risk Band": "MEDIUM",
            "Count": int(((risk_values >= 25) & (risk_values < 50)).sum()),
        },
        {"Risk Band": "LOW", "Count": int((risk_values < 25).sum())},
    ])

    top_failing = pd.DataFrame()
    if not overview.empty:
        top_failing = overview.copy()
        top_failing["_risk"] = risk_values
        top_failing = top_failing[
            top_failing.get("Status", pd.Series(dtype=str)).astype(str)
            .ne("COMPLIANT")
            | top_failing["_risk"].gt(0)
        ].sort_values(
            ["_risk", "Persistent DTC Count"],
            ascending=[False, False],
        ).drop(columns=["_risk"]).head(25).reset_index(drop=True)

    release_distribution = pd.DataFrame()
    release_column = next(
        (
            column for column in
            ("Installed Release", "Target Release", "Reference Sheet")
            if column in overview.columns
        ),
        None,
    )
    if release_column:
        release_distribution = (
            overview[release_column].astype(str)
            .replace("", "UNKNOWN")
            .value_counts()
            .rename_axis("Release")
            .reset_index(name="ECU Count")
        )

    transition_trend = multi_session_result.get(
        "vehicle_trend", pd.DataFrame()
    ).copy()

    return {
        "summary": summary,
        "status_distribution": status_distribution,
        "risk_distribution": risk_distribution,
        "top_failing_ecus": top_failing,
        "release_distribution": release_distribution,
        "transition_trend": transition_trend,
    }
