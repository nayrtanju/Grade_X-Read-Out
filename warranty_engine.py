from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("warranty_rules.json")


def load_warranty_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    with rules_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def enhanced_vehicle_health(
    overview: pd.DataFrame,
    change_log: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_warranty_rules())
    if overview is None or overview.empty:
        return pd.DataFrame()

    weights = rules["weights"]
    thresholds = rules["thresholds"]
    rows: list[dict[str, Any]] = []

    for (source_file, vin), group in overview.groupby(["Source File", "VIN"], dropna=False):
        risks = pd.to_numeric(group.get("Risk Score", 0), errors="coerce").fillna(0)
        average_risk = float(risks.mean()) if len(risks) else 0.0
        maximum_risk = float(risks.max()) if len(risks) else 0.0
        persistent_dtcs = int(
            pd.to_numeric(group.get("Persistent DTC Count", 0), errors="coerce").fillna(0).sum()
        )
        critical_ecus = int((group.get("Risk Level", "").astype(str) == "CRITICAL").sum())
        high_ecus = int((group.get("Risk Level", "").astype(str) == "HIGH").sum())
        compliant_ecus = int((group.get("Status", "").astype(str) == "COMPLIANT").sum())
        compliance_rate = compliant_ecus / len(group) * 100 if len(group) else 0.0

        regressions = 0
        if change_log is not None and not change_log.empty:
            if {"Current Session", "Regression"}.issubset(change_log.columns):
                regressions = int(
                    change_log[
                        (change_log["Current Session"].astype(str) == str(source_file))
                        & change_log["Regression"].fillna(False).astype(bool)
                    ].shape[0]
                )

        penalty = (
            weights["average_risk"] * average_risk
            + weights["maximum_risk"] * maximum_risk
            + weights["persistent_dtc_penalty"] * persistent_dtcs
            + weights["critical_ecu_penalty"] * critical_ecus
            + weights["high_ecu_penalty"] * high_ecus
            + weights["regression_penalty"] * regressions
        )
        bonus = weights["compliance_bonus"] * (compliance_rate / 100.0)
        health_score = max(0.0, min(100.0, 100.0 - penalty + bonus))

        if health_score >= thresholds["good_health"]:
            health_level = "GOOD"
        elif health_score >= thresholds["fair_health"]:
            health_level = "FAIR"
        elif health_score >= thresholds["poor_health"]:
            health_level = "POOR"
        else:
            health_level = "CRITICAL"

        lead = group.sort_values(
            ["Risk Score", "Decision Confidence %"],
            ascending=[False, False],
        ).iloc[0]

        rows.append({
            "Source File": source_file,
            "VIN": vin,
            "ECUs": len(group),
            "Compliance Rate %": round(compliance_rate, 1),
            "Average Risk Score": round(average_risk, 1),
            "Maximum Risk Score": round(maximum_risk, 1),
            "Persistent DTCs": persistent_dtcs,
            "Critical ECUs": critical_ecus,
            "High-Risk ECUs": high_ecus,
            "Regressions": regressions,
            "Vehicle Health Score": round(health_score, 1),
            "Vehicle Health Level": health_level,
            "Lead ECU": lead.get("ECU", ""),
            "Lead Decision": lead.get("Decision", ""),
            "Lead Root Cause": lead.get("Primary Root Cause", ""),
        })

    return pd.DataFrame(rows).sort_values(
        ["Vehicle Health Score", "Maximum Risk Score"],
        ascending=[True, False],
    ).reset_index(drop=True)


def _warranty_recommendation(
    vehicle_group: pd.DataFrame,
    health_row: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> tuple[str, list[str]]:
    thresholds = rules["thresholds"]
    reasons: list[str] = []

    decisions = set(vehicle_group.get("Decision", pd.Series(dtype=str)).astype(str))
    statuses = set(vehicle_group.get("Status", pd.Series(dtype=str)).astype(str))
    mismatch_fields = " ".join(
        vehicle_group.get("Mismatch Fields", pd.Series(dtype=str)).fillna("").astype(str)
    )
    persistent = int(
        pd.to_numeric(vehicle_group.get("Persistent DTC Count", 0), errors="coerce")
        .fillna(0).sum()
    )
    critical_ecus = int(health_row.get("Critical ECUs", 0) or 0)
    health_score = _number(health_row.get("Vehicle Health Score", 0))
    max_risk = _number(health_row.get("Maximum Risk Score", 0))
    max_conf = _number(
        pd.to_numeric(
            vehicle_group.get("Decision Confidence %", 0),
            errors="coerce",
        ).max()
    )

    hardware_evidence = (
        "Hardware Number" in mismatch_fields
        or "Part Number" in mismatch_fields
        or "HARDWARE" in " ".join(decisions)
    )
    software_evidence = any(
        token in " ".join(decisions)
        for token in ("REFLASH", "SOFTWARE", "CALIBRATION", "PACKAGE")
    )

    if critical_ecus >= thresholds["escalation_critical_ecus"]:
        reasons.append(f"{critical_ecus} ECUs are classified as critical risk.")
        return "ENGINEERING_ESCALATION", reasons

    if hardware_evidence:
        reasons.append("Hardware or part-number compatibility evidence is present.")
        if persistent > 0 and max_conf >= thresholds["replacement_review_confidence"]:
            reasons.append("A persistent DTC is present with high decision confidence.")
            return "REPLACEMENT_REVIEW", reasons
        return "HARDWARE_VERIFICATION_REQUIRED", reasons

    if software_evidence or statuses.intersection({"WRONG_RELEASE", "UPDATE_AVAILABLE"}):
        reasons.append("The evidence indicates a software or package-selection deviation.")
        if persistent > 0:
            reasons.append("The DTC must be rechecked after the software configuration is corrected.")
        return "SOFTWARE_CORRECTION_FIRST", reasons

    if persistent > 0:
        reasons.append("Persistent diagnostic faults remain without decisive hardware evidence.")
        return "FURTHER_DIAGNOSTIC_REQUIRED", reasons

    if (
        health_score < thresholds["poor_health"]
        or max_risk >= thresholds["critical_risk_score"]
        or statuses.intersection({"MISMATCH", "REVIEW", "NO_REFERENCE"})
    ):
        reasons.append("The configuration or evidence quality is insufficient for a warranty decision.")
        return "FURTHER_DIAGNOSTIC_REQUIRED", reasons

    reasons.append("No critical software, hardware or persistent diagnostic evidence was detected.")
    return "NO_WARRANTY_ACTION", reasons


def warranty_triage_summary(
    overview: pd.DataFrame,
    vehicle_health: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_warranty_rules())
    if overview is None or overview.empty or vehicle_health is None or vehicle_health.empty:
        return pd.DataFrame()

    recommendations = rules["recommendations"]
    rows: list[dict[str, Any]] = []

    for _, health in vehicle_health.iterrows():
        source_file = health["Source File"]
        vin = health["VIN"]
        group = overview[
            (overview["Source File"].astype(str) == str(source_file))
            & (overview["VIN"].astype(str) == str(vin))
        ]
        code, reasons = _warranty_recommendation(group, health, rules)
        config = recommendations[code]

        lead = group.sort_values(
            ["Risk Score", "Decision Confidence %"],
            ascending=[False, False],
        ).iloc[0]

        rows.append({
            "Source File": source_file,
            "VIN": vin,
            "Vehicle Health Score": health["Vehicle Health Score"],
            "Vehicle Health Level": health["Vehicle Health Level"],
            "Warranty Recommendation": code,
            "Warranty Recommendation Label": config["label"],
            "Warranty Priority": config["priority"],
            "Warranty Rationale": " | ".join(reasons),
            "Required Next Step": config["required_next_step"],
            "Lead ECU": lead.get("ECU", ""),
            "Lead Decision": lead.get("Decision", ""),
            "Lead Decision Confidence %": lead.get("Decision Confidence %", 0),
            "Lead Risk Score": lead.get("Risk Score", 0),
            "Lead Root Cause": lead.get("Primary Root Cause", ""),
            "Disclaimer": rules["disclaimer"],
        })

    return pd.DataFrame(rows).sort_values(
        ["Warranty Priority", "Vehicle Health Score"],
        ascending=[False, True],
    ).reset_index(drop=True)


def ecu_warranty_triage(
    overview: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_warranty_rules())
    if overview is None or overview.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for _, row in overview.iterrows():
        single = pd.DataFrame([row])
        health = pd.DataFrame([{
            "Source File": row.get("Source File", ""),
            "VIN": row.get("VIN", ""),
            "Vehicle Health Score": max(0, 100 - _number(row.get("Risk Score", 0))),
            "Critical ECUs": int(str(row.get("Risk Level", "")) == "CRITICAL"),
            "Maximum Risk Score": _number(row.get("Risk Score", 0)),
        }])
        code, reasons = _warranty_recommendation(single, health.iloc[0], rules)
        config = rules["recommendations"][code]
        rows.append({
            "Source File": row.get("Source File", ""),
            "VIN": row.get("VIN", ""),
            "ECU": row.get("ECU", ""),
            "Status": row.get("Status", ""),
            "Risk Score": row.get("Risk Score", 0),
            "Risk Level": row.get("Risk Level", ""),
            "Decision": row.get("Decision", ""),
            "Decision Confidence %": row.get("Decision Confidence %", 0),
            "Warranty Recommendation": code,
            "Warranty Recommendation Label": config["label"],
            "Warranty Priority": config["priority"],
            "Warranty Rationale": " | ".join(reasons),
            "Required Next Step": config["required_next_step"],
        })
    return pd.DataFrame(rows)
