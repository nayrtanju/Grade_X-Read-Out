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


def _first(frame: pd.DataFrame | None, column: str, default: Any = "") -> Any:
    if frame is None or frame.empty or column not in frame.columns:
        return default
    return frame.iloc[0].get(column, default)


def build_full_assessment(
    *,
    overview: pd.DataFrame,
    details: pd.DataFrame,
    summary: pd.DataFrame,
    dtc_events: pd.DataFrame,
    vehicle_health: pd.DataFrame,
    release_consistency: pd.DataFrame,
    network_health: pd.DataFrame,
    assistant_summary: pd.DataFrame,
    assistant_action_plan: pd.DataFrame,
    target_reference: pd.DataFrame,
    data_quality: dict[str, pd.DataFrame] | None = None,
    release_coverage: dict[str, pd.DataFrame] | None = None,
    oem_audit: dict[str, pd.DataFrame] | None = None,
) -> dict[str, pd.DataFrame]:
    data_quality = data_quality or {}
    release_coverage = release_coverage or {}
    oem_audit = oem_audit or {}

    total_ecus = len(overview)
    statuses = overview.get("Status", pd.Series(dtype=str)).astype(str)
    compliant = int(statuses.eq("COMPLIANT").sum())
    mismatch = int(statuses.eq("MISMATCH").sum())
    wrong_release = int(statuses.eq("WRONG_RELEASE").sum())
    missing = int(statuses.isin(["MISSING", "NO_REFERENCE"]).sum())
    compliance_rate = compliant / total_ecus * 100 if total_ecus else 0.0

    persistent_dtcs = int(
        pd.to_numeric(
            overview.get("Persistent DTC Count", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0).sum()
    )
    risk_scores = pd.to_numeric(
        overview.get("Risk Score", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0)
    critical_risk = int((risk_scores >= 75).sum())
    average_risk = float(risk_scores.mean()) if len(risk_scores) else 0.0

    data_quality_summary = data_quality.get("summary", pd.DataFrame())
    readiness_score = _num(_first(data_quality_summary, "Readiness Score", 0))
    readiness_decision = str(
        _first(data_quality_summary, "Readiness Decision", "NOT_EVALUATED")
    )

    coverage_summary = release_coverage.get("summary", pd.DataFrame())
    release_coverage_rate = _num(
        _first(coverage_summary, "Release Coverage %", 0)
    )
    coverage_level = str(
        _first(coverage_summary, "Coverage Level", "NOT_EVALUATED")
    )

    audit_summary = oem_audit.get("summary", pd.DataFrame())
    audit_score = _num(_first(audit_summary, "Audit Score", 0))
    audit_decision = str(
        _first(audit_summary, "Audit Decision", "NOT_EVALUATED")
    )

    vehicle_health_score = _num(
        _first(vehicle_health, "Vehicle Health Score", 0)
    )
    release_consistency_score = _num(
        _first(release_consistency, "Release Consistency Score", 0)
    )
    mixed_package = bool(
        _first(release_consistency, "Mixed Package Detected", False)
    )
    network_health_score = _num(
        _first(network_health, "Network Health Score", 0)
    )
    network_level = str(
        _first(network_health, "Network Health Level", "")
    )
    executive_status = str(
        _first(assistant_summary, "Executive Vehicle Status", "")
    )

    assessment_score = (
        compliance_rate * 0.22
        + vehicle_health_score * 0.18
        + release_consistency_score * 0.12
        + network_health_score * 0.12
        + release_coverage_rate * 0.12
        + readiness_score * 0.12
        + audit_score * 0.12
    )
    penalties = (
        min(20.0, persistent_dtcs * 4.0)
        + min(15.0, wrong_release * 4.0)
        + min(12.0, critical_risk * 3.0)
        + (8.0 if mixed_package else 0.0)
    )
    assessment_score = max(0.0, min(100.0, assessment_score - penalties))

    hard_fail = (
        readiness_decision == "NOT_READY"
        or audit_decision == "FAIL"
        or persistent_dtcs > 0
        or wrong_release > 0
    )
    if hard_fail:
        decision = "STOP_AND_CORRECT"
    elif assessment_score >= 90 and mismatch == 0 and missing == 0:
        decision = "READY_FOR_SIGN_OFF"
    elif assessment_score >= 70:
        decision = "ENGINEERING_REVIEW"
    else:
        decision = "STOP_AND_CORRECT"

    summary_frame = pd.DataFrame([{
        "VIN": _first(summary, "VIN", ""),
        "Source Files": int(
            summary.get("Source File", pd.Series(dtype=str))
            .dropna().astype(str).nunique()
        ),
        "Total ECUs": total_ecus,
        "Compliant ECUs": compliant,
        "Compliance Rate %": round(compliance_rate, 1),
        "Mismatch ECUs": mismatch,
        "Wrong Release ECUs": wrong_release,
        "Missing / No Reference ECUs": missing,
        "Critical-Risk ECUs": critical_risk,
        "Average Risk": round(average_risk, 1),
        "Persistent DTCs": persistent_dtcs,
        "DTC Event Rows": len(dtc_events),
        "Data Readiness Score": round(readiness_score, 1),
        "Data Readiness Decision": readiness_decision,
        "Vehicle Health": round(vehicle_health_score, 1),
        "Release Consistency": round(release_consistency_score, 1),
        "Mixed Package": mixed_package,
        "Release Coverage": round(release_coverage_rate, 1),
        "Coverage Level": coverage_level,
        "Network Health": round(network_health_score, 1),
        "Network Level": network_level,
        "OEM Audit Score": round(audit_score, 1),
        "OEM Audit Decision": audit_decision,
        "Executive Status": executive_status,
        "Full Assessment Score": round(assessment_score, 1),
        "Full Assessment Decision": decision,
    }])

    gates = pd.DataFrame([
        {
            "Gate": "INPUT_DATA",
            "Status": (
                "PASS" if readiness_decision == "READY"
                else "WARNING" if readiness_decision == "READY_WITH_WARNINGS"
                else "FAIL"
            ),
            "Score": readiness_score,
            "Evidence": readiness_decision,
            "Required Action": (
                "No action."
                if readiness_decision == "READY"
                else "Review data-quality findings."
                if readiness_decision == "READY_WITH_WARNINGS"
                else "Correct input data before engineering analysis."
            ),
        },
        {
            "Gate": "SOFTWARE_COMPLIANCE",
            "Status": (
                "PASS" if compliance_rate >= 95 and wrong_release == 0
                else "WARNING" if compliance_rate >= 80 and wrong_release == 0
                else "FAIL"
            ),
            "Score": round(compliance_rate, 1),
            "Evidence": (
                f"{compliant}/{total_ecus} compliant; "
                f"{mismatch} mismatch; {wrong_release} wrong release"
            ),
            "Required Action": (
                "Resolve non-compliant ECU software records."
                if compliant != total_ecus else "No action."
            ),
        },
        {
            "Gate": "DIAGNOSTICS",
            "Status": "PASS" if persistent_dtcs == 0 else "FAIL",
            "Score": max(0.0, 100.0 - persistent_dtcs * 25),
            "Evidence": f"{persistent_dtcs} persistent DTC(s)",
            "Required Action": (
                "Diagnose and clear persistent DTCs."
                if persistent_dtcs else "No action."
            ),
        },
        {
            "Gate": "RELEASE_PACKAGE",
            "Status": (
                "PASS"
                if release_coverage_rate >= 90
                and release_consistency_score >= 90
                and not mixed_package
                else "WARNING"
                if release_coverage_rate >= 75
                and release_consistency_score >= 75
                else "FAIL"
            ),
            "Score": round(
                (release_coverage_rate + release_consistency_score) / 2, 1
            ),
            "Evidence": (
                f"Coverage {release_coverage_rate:.1f}%; "
                f"consistency {release_consistency_score:.1f}%; "
                f"mixed package {mixed_package}"
            ),
            "Required Action": (
                "Align ECU software to an approved coherent release package."
                if mixed_package or release_coverage_rate < 90
                else "No action."
            ),
        },
        {
            "Gate": "NETWORK",
            "Status": (
                "PASS" if network_health_score >= 85
                else "WARNING" if network_health_score >= 65
                else "FAIL"
            ),
            "Score": round(network_health_score, 1),
            "Evidence": f"{network_level or 'N/A'}",
            "Required Action": (
                "Review network violations and dependency risks."
                if network_health_score < 85 else "No action."
            ),
        },
        {
            "Gate": "OEM_AUDIT",
            "Status": (
                "PASS" if audit_decision == "PASS"
                else "WARNING" if audit_decision == "CONDITIONAL_PASS"
                else "FAIL"
            ),
            "Score": round(audit_score, 1),
            "Evidence": audit_decision,
            "Required Action": (
                "Close audit findings and repeat the audit."
                if audit_decision != "PASS" else "No action."
            ),
        },
    ])

    gate_priority = {"FAIL": 1, "WARNING": 2, "PASS": 3}
    open_actions = gates[gates["Status"].ne("PASS")].copy()
    if not open_actions.empty:
        open_actions["_priority"] = (
            open_actions["Status"].map(gate_priority).fillna(9)
        )
        open_actions = open_actions.sort_values(
            ["_priority", "Gate"]
        ).drop(columns="_priority").reset_index(drop=True)

    if assistant_action_plan is not None and not assistant_action_plan.empty:
        assistant_actions = assistant_action_plan.copy()
    else:
        assistant_actions = pd.DataFrame()

    return {
        "summary": summary_frame,
        "gates": gates,
        "open_actions": open_actions,
        "assistant_actions": assistant_actions,
    }
