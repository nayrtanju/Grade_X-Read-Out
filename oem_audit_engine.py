from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("oem_audit_rules.json")


def load_oem_audit_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    with rules_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def _status(pass_condition: bool, fail_condition: bool = False) -> str:
    if fail_condition:
        return "FAIL"
    return "PASS" if pass_condition else "WARNING"


def build_oem_audit(
    overview: pd.DataFrame,
    details: pd.DataFrame | None = None,
    summary: pd.DataFrame | None = None,
    vehicle_health: pd.DataFrame | None = None,
    release_consistency: pd.DataFrame | None = None,
    network_health: pd.DataFrame | None = None,
    dtc_events: pd.DataFrame | None = None,
    release_coverage: dict[str, pd.DataFrame] | None = None,
    configuration_diff: dict[str, pd.DataFrame] | None = None,
    update_impact_summary: pd.DataFrame | None = None,
    release_path_summary: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    rules = dict(rules or load_oem_audit_rules())
    overview = overview.copy() if overview is not None else pd.DataFrame()
    details = details.copy() if details is not None else pd.DataFrame()
    summary = summary.copy() if summary is not None else pd.DataFrame()
    release_coverage = release_coverage or {}
    configuration_diff = configuration_diff or {}

    checks: list[dict[str, Any]] = []

    statuses = (
        overview.get("Status", pd.Series(dtype=str)).astype(str)
        if not overview.empty else pd.Series(dtype=str)
    )
    total_ecus = len(overview)
    compliant = int(statuses.eq("COMPLIANT").sum())
    software_failures = int(statuses.isin(["MISMATCH", "WRONG_RELEASE", "MISSING"]).sum())
    software_rate = compliant / total_ecus * 100 if total_ecus else 0.0
    checks.append({
        "Check ID": "SOFTWARE_COMPLIANCE",
        "Audit Area": "Software",
        "Check": "Application / Basic / Calibration software compliance",
        "Status": _status(software_rate >= 95, software_failures > 0 and software_rate < 80),
        "Score": round(software_rate, 1),
        "Evidence": f"{compliant}/{total_ecus} ECUs compliant; {software_failures} deviation(s)",
        "Required Action": "Resolve software mismatches and wrong-release ECUs." if software_failures else "No action.",
    })

    hardware_columns = [
        column for column in ("Hardware Number", "Part Number")
        if column in details.columns
    ]
    hardware_failures = 0
    if not details.empty and "Status" in details.columns and hardware_columns:
        hardware_mask = details.get("Field", pd.Series(dtype=str)).astype(str).isin(hardware_columns)
        hardware_failures = int(
            details.loc[hardware_mask, "Status"].astype(str)
            .isin(["MISMATCH", "MISSING", "WRONG_RELEASE"]).sum()
        )
        hardware_available = int(hardware_mask.sum())
    else:
        hardware_available = 0
    hardware_status = (
        "NOT_AVAILABLE" if hardware_available == 0
        else "FAIL" if hardware_failures > 0
        else "PASS"
    )
    checks.append({
        "Check ID": "HARDWARE_COMPATIBILITY",
        "Audit Area": "Hardware",
        "Check": "Hardware and part-number compatibility",
        "Status": hardware_status,
        "Score": 50.0 if hardware_status == "NOT_AVAILABLE" else 0.0 if hardware_failures else 100.0,
        "Evidence": (
            "No field-level hardware result available."
            if hardware_available == 0
            else f"{hardware_failures} hardware deviation(s) across {hardware_available} evaluated record(s)"
        ),
        "Required Action": "Verify ECU hardware against the approved reference." if hardware_status != "PASS" else "No action.",
    })

    bootloader_failures = 0
    calibration_failures = 0
    if not details.empty and "Field" in details.columns and "Status" in details.columns:
        bootloader_mask = details["Field"].astype(str).str.contains("Boot", case=False, na=False)
        calibration_mask = details["Field"].astype(str).str.contains("Calib", case=False, na=False)
        bootloader_failures = int(
            details.loc[bootloader_mask, "Status"].astype(str)
            .isin(["MISMATCH", "MISSING", "WRONG_RELEASE"]).sum()
        )
        calibration_failures = int(
            details.loc[calibration_mask, "Status"].astype(str)
            .isin(["MISMATCH", "MISSING", "WRONG_RELEASE"]).sum()
        )
        bootloader_available = int(bootloader_mask.sum())
        calibration_available = int(calibration_mask.sum())
    else:
        bootloader_available = calibration_available = 0

    for check_id, area, label, available, failures in (
        ("BOOTLOADER_INTEGRITY", "Software", "Bootloader integrity", bootloader_available, bootloader_failures),
        ("CALIBRATION_INTEGRITY", "Software", "Calibration integrity", calibration_available, calibration_failures),
    ):
        check_status = (
            "NOT_AVAILABLE" if available == 0
            else "FAIL" if failures > 0
            else "PASS"
        )
        checks.append({
            "Check ID": check_id,
            "Audit Area": area,
            "Check": label,
            "Status": check_status,
            "Score": 50.0 if check_status == "NOT_AVAILABLE" else 0.0 if failures else 100.0,
            "Evidence": (
                "No field-level result available."
                if available == 0 else f"{failures} deviation(s) across {available} evaluated record(s)"
            ),
            "Required Action": f"Review {label.lower()} against the approved reference." if check_status != "PASS" else "No action.",
        })

    coverage_summary = release_coverage.get("summary", pd.DataFrame())
    if coverage_summary is not None and not coverage_summary.empty:
        coverage_row = coverage_summary.iloc[0]
        coverage_rate = _num(coverage_row.get("Release Coverage %", 0))
        unknown = int(_num(coverage_row.get("Unknown Release ECUs", 0)))
        coverage_status = _status(
            coverage_rate >= 90 and unknown == 0,
            coverage_rate < 70 or unknown > 0,
        )
        coverage_evidence = (
            f"Coverage {coverage_rate:.1f}%; "
            f"{int(_num(coverage_row.get('Below-Target ECUs', 0)))} below target; "
            f"{unknown} unknown"
        )
    else:
        coverage_rate = 0.0
        coverage_status = "NOT_AVAILABLE"
        coverage_evidence = "Release Coverage dashboard has not been evaluated."
    checks.append({
        "Check ID": "RELEASE_COVERAGE",
        "Audit Area": "Release",
        "Check": "Installed-versus-target release coverage",
        "Status": coverage_status,
        "Score": coverage_rate if coverage_status != "NOT_AVAILABLE" else 50.0,
        "Evidence": coverage_evidence,
        "Required Action": "Resolve below-target and unknown release records." if coverage_status != "PASS" else "No action.",
    })

    consistency_score = 0.0
    mixed_package = False
    if release_consistency is not None and not release_consistency.empty:
        consistency_score = _num(release_consistency.iloc[0].get("Release Consistency Score", 0))
        mixed_package = bool(release_consistency.iloc[0].get("Mixed Package Detected", False))
        consistency_status = _status(
            consistency_score >= 90 and not mixed_package,
            consistency_score < 70 or mixed_package,
        )
    else:
        consistency_status = "NOT_AVAILABLE"
    checks.append({
        "Check ID": "RELEASE_CONSISTENCY",
        "Audit Area": "Release",
        "Check": "Release consistency and mixed-package control",
        "Status": consistency_status,
        "Score": consistency_score if consistency_status != "NOT_AVAILABLE" else 50.0,
        "Evidence": f"Consistency {consistency_score:.1f}%; mixed package: {mixed_package}",
        "Required Action": "Align all ECUs to an approved coherent release package." if consistency_status != "PASS" else "No action.",
    })

    persistent_dtcs = int(
        pd.to_numeric(
            overview.get("Persistent DTC Count", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0).sum()
    )
    dtc_count = len(dtc_events) if dtc_events is not None else 0
    dtc_status = "PASS" if persistent_dtcs == 0 else "FAIL"
    checks.append({
        "Check ID": "PERSISTENT_DTC",
        "Audit Area": "Diagnostics",
        "Check": "Persistent DTC and post-programming diagnostic integrity",
        "Status": dtc_status,
        "Score": max(0.0, 100.0 - persistent_dtcs * 25),
        "Evidence": f"{persistent_dtcs} persistent DTC(s); {dtc_count} DTC event record(s)",
        "Required Action": "Diagnose and resolve persistent DTCs before audit closure." if persistent_dtcs else "No action.",
    })

    network_score = 0.0
    network_level = ""
    if network_health is not None and not network_health.empty:
        network_score = _num(network_health.iloc[0].get("Network Health Score", 0))
        network_level = str(network_health.iloc[0].get("Network Health Level", ""))
        network_status = _status(network_score >= 85, network_score < 60)
    else:
        network_status = "NOT_AVAILABLE"
    checks.append({
        "Check ID": "NETWORK_HEALTH",
        "Audit Area": "Network",
        "Check": "ECU dependency and network health",
        "Status": network_status,
        "Score": network_score if network_status != "NOT_AVAILABLE" else 50.0,
        "Evidence": f"Network Health {network_score:.1f}; level {network_level or 'N/A'}",
        "Required Action": "Review critical dependency violations and disconnected ECUs." if network_status != "PASS" else "No action.",
    })

    diff_summary = configuration_diff.get("summary", pd.DataFrame())
    if diff_summary is not None and not diff_summary.empty:
        diff_row = diff_summary.iloc[0]
        critical_diff = int(_num(diff_row.get("Critical Differences", 0)))
        removed = int(_num(diff_row.get("Removed ECUs", 0)))
        modified = int(_num(diff_row.get("Modified ECUs", 0)))
        diff_status = _status(critical_diff == 0 and removed == 0, critical_diff > 0 or removed > 0)
        diff_score = max(0.0, 100.0 - critical_diff * 20 - removed * 25 - modified * 3)
        diff_evidence = f"{critical_diff} critical difference(s); {removed} removed ECU(s); {modified} modified ECU(s)"
    else:
        diff_status = "NOT_AVAILABLE"
        diff_score = 50.0
        diff_evidence = "Configuration Diff has not been run."
    checks.append({
        "Check ID": "CONFIGURATION_DIFF",
        "Audit Area": "Configuration",
        "Check": "Configuration delta and unauthorized change control",
        "Status": diff_status,
        "Score": diff_score,
        "Evidence": diff_evidence,
        "Required Action": "Review critical, removed and modified configuration records." if diff_status != "PASS" else "No action.",
    })

    path_type = ""
    path_score = 0.0
    if release_path_summary is not None and not release_path_summary.empty:
        path_type = str(release_path_summary.iloc[0].get("Path Type", ""))
        path_score = _num(release_path_summary.iloc[0].get("Path Score", 0))
        path_status = (
            "PASS" if path_type == "DIRECT" and path_score >= 85
            else "WARNING" if path_type == "STAGED" and path_score >= 65
            else "FAIL"
        )
    elif update_impact_summary is not None and not update_impact_summary.empty:
        level = str(update_impact_summary.iloc[0].get("Overall Compatibility Level", ""))
        path_score = _num(update_impact_summary.iloc[0].get("Overall Compatibility Score", 0))
        path_status = "PASS" if level == "SAFE" else "WARNING" if level == "CONDITIONAL" else "FAIL"
        path_type = level
    else:
        path_status = "NOT_AVAILABLE"
    checks.append({
        "Check ID": "UPDATE_PATH",
        "Audit Area": "Programming",
        "Check": "Approved update path and companion ECU planning",
        "Status": path_status,
        "Score": path_score if path_status != "NOT_AVAILABLE" else 50.0,
        "Evidence": f"Path/compatibility type: {path_type or 'N/A'}; score {path_score:.1f}",
        "Required Action": "Confirm official programming path and companion ECU requirements." if path_status != "PASS" else "No action.",
    })

    vins = (
        summary.get("VIN", pd.Series(dtype=str)).dropna().astype(str).str.strip()
        if summary is not None and not summary.empty else pd.Series(dtype=str)
    )
    unique_vins = [vin for vin in vins.unique() if vin]
    vin_status = "PASS" if len(unique_vins) == 1 and len(unique_vins[0]) == 17 else "WARNING"
    if not unique_vins:
        vin_status = "NOT_AVAILABLE"
    checks.append({
        "Check ID": "VIN_INTEGRITY",
        "Audit Area": "Identity",
        "Check": "VIN presence and consistency",
        "Status": vin_status,
        "Score": 100.0 if vin_status == "PASS" else 50.0,
        "Evidence": f"Resolved VINs: {', '.join(unique_vins) if unique_vins else 'none'}",
        "Required Action": "Verify the 17-character vehicle VIN and consistency across ECUs." if vin_status != "PASS" else "No action.",
    })

    checklist = pd.DataFrame(checks)
    weights = rules["weights"]
    status_scores = rules["status_scores"]
    weighted_total = 0.0
    weight_sum = 0.0
    for _, row in checklist.iterrows():
        weight = float(weights.get(str(row["Check ID"]), 0))
        normalized = min(
            float(row["Score"]),
            float(status_scores.get(str(row["Status"]), row["Score"])),
        )
        weighted_total += weight * normalized
        weight_sum += weight
    audit_score = weighted_total / weight_sum if weight_sum else 0.0

    mandatory_failed = checklist[
        checklist["Check ID"].isin(rules["mandatory_fail_checks"])
        & checklist["Status"].eq("FAIL")
    ]
    critical_failures = len(mandatory_failed)
    warnings = int(checklist["Status"].eq("WARNING").sum())
    unavailable = int(checklist["Status"].eq("NOT_AVAILABLE").sum())

    if critical_failures:
        audit_decision = "FAIL"
    elif audit_score >= rules["decision_thresholds"]["PASS"] and warnings == 0:
        audit_decision = "PASS"
    elif audit_score >= rules["decision_thresholds"]["CONDITIONAL_PASS"]:
        audit_decision = "CONDITIONAL_PASS"
    else:
        audit_decision = "FAIL"

    vehicle_health_score = 0.0
    if vehicle_health is not None and not vehicle_health.empty:
        vehicle_health_score = _num(vehicle_health.iloc[0].get("Vehicle Health Score", 0))

    audit_summary = pd.DataFrame([{
        "VIN": unique_vins[0] if len(unique_vins) == 1 else "",
        "Audit Score": round(audit_score, 1),
        "Audit Decision": audit_decision,
        "Checks": len(checklist),
        "Passed Checks": int(checklist["Status"].eq("PASS").sum()),
        "Warning Checks": warnings,
        "Failed Checks": int(checklist["Status"].eq("FAIL").sum()),
        "Unavailable Checks": unavailable,
        "Mandatory Failures": critical_failures,
        "Software Compliance %": round(software_rate, 1),
        "Release Coverage %": round(coverage_rate, 1),
        "Release Consistency %": round(consistency_score, 1),
        "Vehicle Health": round(vehicle_health_score, 1),
        "Network Health": round(network_score, 1),
        "Persistent DTCs": persistent_dtcs,
        "Mixed Package": mixed_package,
        "Closure Recommendation": (
            "AUDIT_CLOSED"
            if audit_decision == "PASS"
            else "CLOSE_AFTER_CONDITIONS"
            if audit_decision == "CONDITIONAL_PASS"
            else "CORRECT_AND_REPEAT_AUDIT"
        ),
        "Disclaimer": rules["disclaimer"],
    }])

    findings = checklist[checklist["Status"].ne("PASS")].copy()
    findings["Finding Priority"] = findings["Status"].map({
        "FAIL": 1, "WARNING": 2, "NOT_AVAILABLE": 3
    }).fillna(4)
    findings = findings.sort_values(
        ["Finding Priority", "Audit Area", "Check"]
    ).drop(columns=["Finding Priority"]).reset_index(drop=True)

    area_summary = (
        checklist.groupby("Audit Area", dropna=False)
        .agg(
            Checks=("Check ID", "count"),
            Passed=("Status", lambda values: int((values == "PASS").sum())),
            Warnings=("Status", lambda values: int((values == "WARNING").sum())),
            Failed=("Status", lambda values: int((values == "FAIL").sum())),
            Average_Score=("Score", "mean"),
        )
        .reset_index()
        .rename(columns={"Average_Score": "Average Score"})
    )
    area_summary["Average Score"] = area_summary["Average Score"].round(1)

    return {
        "summary": audit_summary,
        "checklist": checklist,
        "findings": findings,
        "area_summary": area_summary,
    }
