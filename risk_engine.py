from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("risk_rules.json")


def load_risk_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    with rules_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def risk_level(score: float, thresholds: Mapping[str, float]) -> str:
    if score <= thresholds["low"]:
        return "LOW"
    if score <= thresholds["medium"]:
        return "MEDIUM"
    if score <= thresholds["high"]:
        return "HIGH"
    return "CRITICAL"


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _detail_mismatch_fields(details: pd.DataFrame, source_file: str, ecu: str) -> set[str]:
    if details is None or details.empty:
        return set()
    required = {"Source File", "ECU", "Field", "Status"}
    if not required.issubset(details.columns):
        return set()

    scoped = details[
        (details["Source File"].astype(str) == str(source_file))
        & (details["ECU"].astype(str) == str(ecu))
        & (details["Status"].astype(str).isin(["MISMATCH", "PART_MATCH"]))
    ]
    return set(scoped["Field"].astype(str))


def _add_factor(
    factors: list[dict[str, Any]],
    code: str,
    label: str,
    points: float,
    evidence: str = "",
) -> None:
    if points <= 0:
        return
    factors.append({
        "Factor Code": code,
        "Factor": label,
        "Points": round(float(points), 1),
        "Evidence": evidence,
    })


def assess_ecu_risk(
    row: Mapping[str, Any],
    details: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
    history_regression: bool = False,
) -> dict[str, Any]:
    rules = dict(rules or load_risk_rules())
    factors: list[dict[str, Any]] = []

    status = str(row.get("Status", "") or "")
    status_points = float(rules["status_scores"].get(status, 50))
    _add_factor(
        factors,
        f"STATUS_{status or 'UNKNOWN'}",
        f"Compliance status: {status or 'UNKNOWN'}",
        status_points,
        str(row.get("Decision Reason", "") or ""),
    )

    persistent_dtc_count = int(_safe_number(row.get("Persistent DTC Count", 0)))
    dtc_severity = str(row.get("DTC Severity", "") or "").upper()
    if persistent_dtc_count > 0:
        _add_factor(
            factors,
            "PERSISTENT_DTC",
            "Persistent diagnostic trouble code",
            rules["factors"]["persistent_dtc"],
            str(row.get("DTC Codes", "") or ""),
        )
    if dtc_severity == "HIGH":
        _add_factor(
            factors,
            "HIGH_DTC_SEVERITY",
            "High-severity DTC",
            rules["factors"]["high_severity_dtc"],
            str(row.get("DTC Codes", "") or ""),
        )
    elif dtc_severity == "MEDIUM":
        _add_factor(
            factors,
            "MEDIUM_DTC_SEVERITY",
            "Medium-severity DTC",
            rules["factors"]["medium_severity_dtc"],
            str(row.get("DTC Codes", "") or ""),
        )

    mismatch_fields = _detail_mismatch_fields(
        details if details is not None else pd.DataFrame(),
        str(row.get("Source File", "") or ""),
        str(row.get("ECU", "") or ""),
    )

    field_rules = {
        "Hardware Number": ("HARDWARE_MISMATCH", "Hardware mismatch", "hardware_mismatch"),
        "Application SW": ("APPLICATION_MISMATCH", "Application software mismatch", "application_mismatch"),
        "Calibration SW": ("CALIBRATION_MISMATCH", "Calibration software mismatch", "calibration_mismatch"),
        "Basic SW": ("BASIC_SW_MISMATCH", "Basic software mismatch", "basic_software_mismatch"),
        "Bootloader": ("BOOTLOADER_MISMATCH", "Bootloader mismatch", "bootloader_mismatch"),
        "Software Number": ("SOFTWARE_NUMBER_MISMATCH", "Software-number mismatch", "software_number_mismatch"),
        "Part Number": ("PART_NUMBER_MISMATCH", "Part-number mismatch", "part_number_mismatch"),
    }
    for field, (code, label, rule_key) in field_rules.items():
        if field in mismatch_fields:
            _add_factor(factors, code, label, rules["factors"][rule_key], field)

    confidence = _safe_number(row.get("Confidence %", 100), 100)
    confidence_thresholds = rules["confidence_thresholds"]
    if confidence < confidence_thresholds["very_low"]:
        _add_factor(
            factors,
            "VERY_LOW_CONFIDENCE",
            "Very low matching confidence",
            rules["factors"]["very_low_confidence"],
            f"{confidence:.1f}%",
        )
    elif confidence < confidence_thresholds["low"]:
        _add_factor(
            factors,
            "LOW_CONFIDENCE",
            "Low matching confidence",
            rules["factors"]["low_confidence"],
            f"{confidence:.1f}%",
        )

    if history_regression:
        _add_factor(
            factors,
            "HISTORY_REGRESSION",
            "Historical regression detected",
            rules["factors"]["history_regression"],
            "A previously healthier ECU state deteriorated.",
        )

    raw_score = sum(float(item["Points"]) for item in factors)
    score = min(float(rules["score_cap"]), raw_score)
    level = risk_level(score, rules["thresholds"])
    contributors = sorted(factors, key=lambda item: item["Points"], reverse=True)

    return {
        "Risk Score": round(score, 1),
        "Risk Level": level,
        "Risk Factor Count": len(contributors),
        "Top Contributors": "; ".join(
            f"{item['Factor']} (+{item['Points']:g})" for item in contributors[:4]
        ),
        "Risk Explanation": " | ".join(
            f"+{item['Points']:g} {item['Factor']}"
            + (f" [{item['Evidence']}]" if item["Evidence"] else "")
            for item in contributors
        ),
        "Risk Breakdown": contributors,
    }


def apply_risk_assessment(
    overview: pd.DataFrame,
    details: pd.DataFrame | None = None,
    change_log: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rules = dict(rules or load_risk_rules())
    if overview is None or overview.empty:
        return pd.DataFrame(), pd.DataFrame()

    regression_keys: set[tuple[str, str]] = set()
    if change_log is not None and not change_log.empty:
        required = {"Current Session", "ECU", "Regression"}
        if required.issubset(change_log.columns):
            reg = change_log[change_log["Regression"].fillna(False).astype(bool)]
            regression_keys = set(zip(reg["Current Session"].astype(str), reg["ECU"].astype(str)))

    assessed_rows = []
    breakdown_rows = []
    for _, row in overview.iterrows():
        key = (str(row.get("Source File", "")), str(row.get("ECU", "")))
        assessment = assess_ecu_risk(
            row,
            details=details,
            rules=rules,
            history_regression=key in regression_keys,
        )
        enriched = row.to_dict()
        for column in (
            "Risk Score",
            "Risk Level",
            "Risk Factor Count",
            "Top Contributors",
            "Risk Explanation",
        ):
            enriched[column] = assessment[column]
        assessed_rows.append(enriched)

        for position, factor in enumerate(assessment["Risk Breakdown"], start=1):
            breakdown_rows.append({
                "Source File": row.get("Source File", ""),
                "VIN": row.get("VIN", ""),
                "ECU": row.get("ECU", ""),
                "Risk Score": assessment["Risk Score"],
                "Risk Level": assessment["Risk Level"],
                "Rank": position,
                **factor,
            })

    risk_overview = pd.DataFrame(assessed_rows)
    breakdown = pd.DataFrame(breakdown_rows)
    return risk_overview, breakdown


def vehicle_health_summary(risk_overview: pd.DataFrame) -> pd.DataFrame:
    if risk_overview is None or risk_overview.empty:
        return pd.DataFrame()

    rows = []
    for (source_file, vin), group in risk_overview.groupby(["Source File", "VIN"], dropna=False):
        risk = pd.to_numeric(group["Risk Score"], errors="coerce").fillna(0)
        avg_risk = float(risk.mean()) if len(risk) else 0.0
        max_risk = float(risk.max()) if len(risk) else 0.0
        critical_count = int((group["Risk Level"].astype(str) == "CRITICAL").sum())
        high_count = int((group["Risk Level"].astype(str) == "HIGH").sum())

        health_score = max(0.0, 100.0 - (0.65 * avg_risk + 0.35 * max_risk))
        if health_score >= 85:
            health_level = "GOOD"
        elif health_score >= 70:
            health_level = "FAIR"
        elif health_score >= 50:
            health_level = "POOR"
        else:
            health_level = "CRITICAL"

        highest = group.sort_values("Risk Score", ascending=False).iloc[0]
        rows.append({
            "Source File": source_file,
            "VIN": vin,
            "ECUs": len(group),
            "Average Risk Score": round(avg_risk, 1),
            "Maximum Risk Score": round(max_risk, 1),
            "Critical ECUs": critical_count,
            "High-Risk ECUs": high_count,
            "Vehicle Health Score": round(health_score, 1),
            "Vehicle Health Level": health_level,
            "Highest-Risk ECU": highest.get("ECU", ""),
            "Highest-Risk Contributors": highest.get("Top Contributors", ""),
        })

    return pd.DataFrame(rows).sort_values(
        ["Vehicle Health Score", "Maximum Risk Score"],
        ascending=[True, False],
    ).reset_index(drop=True)
