from __future__ import annotations

from typing import Any, Mapping

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


def _add(
    findings: list[dict[str, Any]],
    source_file: str,
    vin: str,
    category: str,
    severity: str,
    title: str,
    finding: str,
    evidence: str,
    action: str,
    ecu: str = "",
) -> None:
    findings.append({
        "Source File": source_file,
        "VIN": vin,
        "ECU": ecu,
        "Category": category,
        "Severity": severity,
        "Finding Title": title,
        "Engineering Finding": finding,
        "Evidence": evidence,
        "Recommended Action": action,
    })


def generate_engineering_findings(
    overview: pd.DataFrame,
    vehicle_health: pd.DataFrame,
    warranty_summary: pd.DataFrame,
    vehicle_root_causes: pd.DataFrame,
    release_consistency: pd.DataFrame,
    fleet_alerts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if overview is None or overview.empty:
        return pd.DataFrame()

    findings: list[dict[str, Any]] = []

    for (source_file, vin), group in overview.groupby(["Source File", "VIN"], dropna=False):
        health = vehicle_health[
            (vehicle_health["Source File"].astype(str) == str(source_file))
            & (vehicle_health["VIN"].astype(str) == str(vin))
        ]
        warranty = warranty_summary[
            (warranty_summary["Source File"].astype(str) == str(source_file))
            & (warranty_summary["VIN"].astype(str) == str(vin))
        ]
        root = vehicle_root_causes[
            (vehicle_root_causes["Source File"].astype(str) == str(source_file))
            & (vehicle_root_causes["VIN"].astype(str) == str(vin))
        ]
        consistency = release_consistency[
            (release_consistency["Source File"].astype(str) == str(source_file))
            & (release_consistency["VIN"].astype(str) == str(vin))
        ]

        health_row = health.iloc[0] if not health.empty else pd.Series(dtype=object)
        warranty_row = warranty.iloc[0] if not warranty.empty else pd.Series(dtype=object)
        root_row = root.iloc[0] if not root.empty else pd.Series(dtype=object)
        consistency_row = consistency.iloc[0] if not consistency.empty else pd.Series(dtype=object)

        health_score = _num(health_row.get("Vehicle Health Score", 0))
        health_level = str(health_row.get("Vehicle Health Level", "UNKNOWN"))
        if health_level in {"CRITICAL", "POOR"}:
            severity = "CRITICAL" if health_level == "CRITICAL" else "HIGH"
            _add(
                findings, source_file, vin, "VEHICLE_HEALTH", severity,
                "Low vehicle health",
                f"Vehicle Health is {health_score:.1f}/100 and classified as {health_level}.",
                f"Average risk={health_row.get('Average Risk Score', '')}; "
                f"critical ECUs={health_row.get('Critical ECUs', '')}; "
                f"persistent DTCs={health_row.get('Persistent DTCs', '')}.",
                "Complete the critical ECU actions, repeat Grade-X readout and recalculate Vehicle Health.",
            )

        status = group.get("Status", pd.Series(dtype=str)).astype(str)
        critical_group = group[status.isin(["MISMATCH", "WRONG_RELEASE"])]
        for _, row in critical_group.iterrows():
            _add(
                findings, source_file, vin, "CONFIGURATION", "HIGH",
                f"Critical configuration deviation on {row.get('ECU', '')}",
                f"{row.get('ECU', '')} is classified as {row.get('Status', '')}.",
                str(row.get("Decision Reason", "")),
                str(row.get("Recommended Actions", "")).split(" | ")[0],
                str(row.get("ECU", "")),
            )

        persistent_group = group[
            pd.to_numeric(group.get("Persistent DTC Count", 0), errors="coerce")
            .fillna(0).gt(0)
        ]
        for _, row in persistent_group.iterrows():
            _add(
                findings, source_file, vin, "DIAGNOSTIC", "HIGH",
                f"Persistent DTC on {row.get('ECU', '')}",
                f"{row.get('ECU', '')} contains persistent diagnostic evidence.",
                f"DTCs={row.get('DTC Codes', '')}; severity={row.get('DTC Severity', '')}.",
                "Follow the OEM DTC test plan, record enabling conditions and repeat after corrective action.",
                str(row.get("ECU", "")),
            )

        if not root.empty:
            confidence = _num(root_row.get("Root Cause Confidence %", 0))
            severity = "HIGH" if confidence >= 70 else "MEDIUM"
            _add(
                findings, source_file, vin, "ROOT_CAUSE", severity,
                f"Probable root ECU: {root_row.get('Most Probable Root ECU', '')}",
                f"The most probable root ECU is {root_row.get('Most Probable Root ECU', '')} "
                f"with {confidence:.1f}% confidence.",
                str(root_row.get("Root Cause Evidence", "")),
                str(root_row.get("Recommended Root Action", "")),
                str(root_row.get("Most Probable Root ECU", "")),
            )

        if not consistency.empty and bool(consistency_row.get("Mixed Package Detected", False)):
            _add(
                findings, source_file, vin, "PACKAGE_CONSISTENCY", "HIGH",
                "Mixed software package detected",
                f"Release consistency is {_num(consistency_row.get('Release Consistency Score', 0)):.1f}/100.",
                str(consistency_row.get("Consistency Findings", "")),
                "Verify the complete approved vehicle package and correct outlier ECU software levels.",
            )

        recommendation = str(warranty_row.get("Warranty Recommendation", ""))
        if recommendation:
            severity = (
                "CRITICAL" if recommendation == "ENGINEERING_ESCALATION"
                else "HIGH" if recommendation in {"REPLACEMENT_REVIEW", "HARDWARE_VERIFICATION_REQUIRED"}
                else "MEDIUM"
            )
            _add(
                findings, source_file, vin, "WARRANTY_TRIAGE", severity,
                f"Warranty triage: {warranty_row.get('Warranty Recommendation Label', recommendation)}",
                str(warranty_row.get("Warranty Rationale", "")),
                str(warranty_row.get("Lead Root Cause", "")),
                str(warranty_row.get("Required Next Step", "")),
                str(warranty_row.get("Lead ECU", "")),
            )

        if critical_group.empty and persistent_group.empty and health_level in {"GOOD", "FAIR"}:
            _add(
                findings, source_file, vin, "GENERAL", "INFO",
                "No critical vehicle-level finding",
                "No critical release deviation or persistent diagnostic fault was identified.",
                f"Vehicle Health={health_score:.1f}/100.",
                "Retain the report and continue normal monitoring.",
            )

    result = pd.DataFrame(findings)
    if result.empty:
        return result

    priority = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
    result["_Priority"] = result["Severity"].map(priority).fillna(0)
    result = result.sort_values(
        ["Source File", "_Priority", "Category", "ECU"],
        ascending=[True, False, True, True],
    ).drop(columns="_Priority").reset_index(drop=True)
    return result
