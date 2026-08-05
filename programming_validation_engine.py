from __future__ import annotations

from typing import Any

import pandas as pd

from compliance import validate
from configuration_diff_engine import compare_configurations, normalize_session


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


def _vin(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty or "VIN" not in frame.columns:
        return ""
    values = frame["VIN"].dropna().astype(str).str.strip()
    values = values[values.ne("")]
    return values.iloc[0] if not values.empty else ""


def build_programming_validation(
    before_name: str,
    before_frame: pd.DataFrame,
    after_name: str,
    after_frame: pd.DataFrame,
    target_reference: pd.DataFrame,
    release_catalog: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    before_overview, before_details, _ = validate(
        before_frame, target_reference, release_catalog
    )
    after_overview, after_details, _ = validate(
        after_frame, target_reference, release_catalog
    )

    diff = compare_configurations(
        normalize_session(before_frame, before_name),
        normalize_session(after_frame, after_name),
        left_label=before_name,
        right_label=after_name,
        ignore_fields=["VIN"],
    )

    before_status = (
        before_overview.set_index("ECU")["Status"].astype(str).to_dict()
        if not before_overview.empty and "ECU" in before_overview.columns
        else {}
    )
    after_status = (
        after_overview.set_index("ECU")["Status"].astype(str).to_dict()
        if not after_overview.empty and "ECU" in after_overview.columns
        else {}
    )
    before_dtc = (
        before_frame.groupby("ECU ID")["DTC Count"].sum().to_dict()
        if "ECU ID" in before_frame.columns and "DTC Count" in before_frame.columns
        else {}
    )
    after_dtc = (
        after_frame.groupby("ECU ID")["DTC Count"].sum().to_dict()
        if "ECU ID" in after_frame.columns and "DTC Count" in after_frame.columns
        else {}
    )

    ecus = sorted(set(before_status) | set(after_status) | set(before_dtc) | set(after_dtc))
    rows = []
    for ecu in ecus:
        b_status = before_status.get(ecu, "NOT_AVAILABLE")
        a_status = after_status.get(ecu, "NOT_AVAILABLE")
        b_dtc = int(_num(before_dtc.get(ecu, 0)))
        a_dtc = int(_num(after_dtc.get(ecu, 0)))
        if b_status != "COMPLIANT" and a_status == "COMPLIANT":
            outcome = "RESOLVED"
        elif b_status == "COMPLIANT" and a_status != "COMPLIANT":
            outcome = "REGRESSION"
        elif b_status != "COMPLIANT" and a_status != "COMPLIANT":
            outcome = "NOT_RESOLVED"
        else:
            outcome = "UNCHANGED_PASS"

        dtc_outcome = (
            "NEW_DTC" if a_dtc > b_dtc
            else "DTC_REDUCED" if a_dtc < b_dtc
            else "UNCHANGED"
        )
        rows.append({
            "ECU": ecu,
            "Before Status": b_status,
            "After Status": a_status,
            "Programming Outcome": outcome,
            "Before DTC Count": b_dtc,
            "After DTC Count": a_dtc,
            "DTC Outcome": dtc_outcome,
        })
    ecu_validation = pd.DataFrame(rows)

    before_total = len(before_overview)
    after_total = len(after_overview)
    before_compliant = int(
        before_overview.get("Status", pd.Series(dtype=str)).astype(str)
        .eq("COMPLIANT").sum()
    )
    after_compliant = int(
        after_overview.get("Status", pd.Series(dtype=str)).astype(str)
        .eq("COMPLIANT").sum()
    )
    before_rate = before_compliant / before_total * 100 if before_total else 0.0
    after_rate = after_compliant / after_total * 100 if after_total else 0.0

    resolved = int(ecu_validation["Programming Outcome"].eq("RESOLVED").sum())
    regressions = int(ecu_validation["Programming Outcome"].eq("REGRESSION").sum())
    unresolved = int(ecu_validation["Programming Outcome"].eq("NOT_RESOLVED").sum())
    new_dtcs = int(ecu_validation["DTC Outcome"].eq("NEW_DTC").sum())
    removed_ecus = int(
        diff["summary"].iloc[0].get("Removed ECUs", 0)
        if not diff["summary"].empty else 0
    )
    critical_differences = int(
        diff["summary"].iloc[0].get("Critical Differences", 0)
        if not diff["summary"].empty else 0
    )

    score = (
        after_rate * 0.60
        + max(0.0, 100.0 - regressions * 20.0) * 0.15
        + max(0.0, 100.0 - unresolved * 10.0) * 0.10
        + max(0.0, 100.0 - new_dtcs * 20.0) * 0.10
        + max(0.0, 100.0 - removed_ecus * 25.0) * 0.05
    )
    score -= min(20.0, critical_differences * 4.0)
    score = max(0.0, min(100.0, score))

    hard_fail = regressions > 0 or new_dtcs > 0 or removed_ecus > 0
    decision = (
        "PASS"
        if score >= 90 and not hard_fail and unresolved == 0
        else "CONDITIONAL_PASS"
        if score >= 70 and not hard_fail
        else "FAIL"
    )

    summary = pd.DataFrame([{
        "Before Session": before_name,
        "After Session": after_name,
        "VIN Before": _vin(before_frame),
        "VIN After": _vin(after_frame),
        "Before Compliance %": round(before_rate, 1),
        "After Compliance %": round(after_rate, 1),
        "Compliance Improvement %": round(after_rate - before_rate, 1),
        "Resolved ECUs": resolved,
        "Unresolved ECUs": unresolved,
        "Regressed ECUs": regressions,
        "ECUs with New DTCs": new_dtcs,
        "Removed ECUs": removed_ecus,
        "Critical Configuration Differences": critical_differences,
        "Validation Score": round(score, 1),
        "Validation Decision": decision,
        "Sign-off Recommendation": (
            "READY_FOR_SIGN_OFF"
            if decision == "PASS"
            else "SIGN_OFF_AFTER_CONDITIONS"
            if decision == "CONDITIONAL_PASS"
            else "DO_NOT_SIGN_OFF"
        ),
    }])

    findings = ecu_validation[
        ecu_validation["Programming Outcome"].isin(["REGRESSION", "NOT_RESOLVED"])
        | ecu_validation["DTC Outcome"].eq("NEW_DTC")
    ].copy()
    if not findings.empty:
        findings["Required Action"] = findings.apply(
            lambda row: (
                "Diagnose new DTC and verify programming package."
                if row["DTC Outcome"] == "NEW_DTC"
                else "Restore or correct regressed ECU configuration."
                if row["Programming Outcome"] == "REGRESSION"
                else "Resolve remaining non-compliant ECU fields."
            ),
            axis=1,
        )

    gates = pd.DataFrame([
        {
            "Gate": "VIN_CONSISTENCY",
            "Status": "PASS" if _vin(before_frame) == _vin(after_frame) and _vin(before_frame) else "FAIL",
            "Evidence": f"{_vin(before_frame)} → {_vin(after_frame)}",
        },
        {
            "Gate": "COMPLIANCE_IMPROVEMENT",
            "Status": "PASS" if after_rate >= before_rate else "FAIL",
            "Evidence": f"{before_rate:.1f}% → {after_rate:.1f}%",
        },
        {
            "Gate": "NO_REGRESSION",
            "Status": "PASS" if regressions == 0 else "FAIL",
            "Evidence": f"{regressions} regressed ECU(s)",
        },
        {
            "Gate": "NO_NEW_DTC",
            "Status": "PASS" if new_dtcs == 0 else "FAIL",
            "Evidence": f"{new_dtcs} ECU(s) with increased DTC count",
        },
        {
            "Gate": "NO_REMOVED_ECU",
            "Status": "PASS" if removed_ecus == 0 else "FAIL",
            "Evidence": f"{removed_ecus} removed ECU(s)",
        },
        {
            "Gate": "TARGET_COMPLIANCE",
            "Status": "PASS" if after_rate >= 95 else "WARNING" if after_rate >= 80 else "FAIL",
            "Evidence": f"After-programming compliance {after_rate:.1f}%",
        },
    ])

    return {
        "summary": summary,
        "gates": gates,
        "ecu_validation": ecu_validation,
        "findings": findings,
        "configuration_diff_summary": diff["summary"],
        "configuration_diff_ecus": diff["ecu_diff"],
        "configuration_diff_fields": diff["field_diff"],
        "before_overview": before_overview,
        "after_overview": after_overview,
        "before_details": before_details,
        "after_details": after_details,
    }
