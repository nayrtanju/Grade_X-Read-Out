from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("data_quality_rules.json")


def load_data_quality_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    with rules_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _text(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def _pct(numerator: float, denominator: float) -> float:
    return round(numerator / denominator * 100, 1) if denominator else 0.0


def evaluate_data_quality(
    session_frame: pd.DataFrame,
    reference_frame: pd.DataFrame | None = None,
    dtc_frame: pd.DataFrame | None = None,
    *,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    rules = dict(rules or load_data_quality_rules())
    session = session_frame.copy() if session_frame is not None else pd.DataFrame()
    reference = reference_frame.copy() if reference_frame is not None else pd.DataFrame()
    dtc = dtc_frame.copy() if dtc_frame is not None else pd.DataFrame()

    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    required_session_fields = rules["required_session_fields"]
    missing_columns = [field for field in required_session_fields if field not in session.columns]
    schema_score = _pct(
        len(required_session_fields) - len(missing_columns),
        len(required_session_fields),
    )
    checks.append({
        "Check ID": "SESSION_SCHEMA",
        "Area": "Schema",
        "Check": "Required session columns",
        "Status": "PASS" if not missing_columns else "FAIL",
        "Score": schema_score,
        "Evidence": (
            "All required session columns are present."
            if not missing_columns
            else "Missing columns: " + ", ".join(missing_columns)
        ),
    })
    for column in missing_columns:
        findings.append({
            "Severity": "CRITICAL",
            "Area": "Schema",
            "Field": column,
            "Finding": "Required session column is missing.",
            "Required Action": "Correct parser input or session export and upload the file again.",
        })

    row_count = len(session)
    ecu_count = (
        session["ECU ID"].astype(str).str.strip().replace("", pd.NA).dropna().nunique()
        if "ECU ID" in session.columns else 0
    )
    minimum_ecus = int(rules["thresholds"]["minimum_ecu_count"])
    checks.append({
        "Check ID": "PARSER_COVERAGE",
        "Area": "Parser",
        "Check": "Parsed ECU coverage",
        "Status": "PASS" if ecu_count >= minimum_ecus else "WARNING",
        "Score": min(100.0, _pct(ecu_count, max(minimum_ecus, 1))),
        "Evidence": f"{row_count} rows and {ecu_count} unique ECU(s) parsed.",
    })
    if ecu_count < minimum_ecus:
        findings.append({
            "Severity": "MAJOR",
            "Area": "Parser",
            "Field": "ECU Count",
            "Finding": f"Only {ecu_count} unique ECU(s) were parsed.",
            "Required Action": "Confirm that the session file is complete and uses a supported Grade-X export format.",
        })

    critical_fields = [f for f in rules["critical_fields"] if f in session.columns]
    critical_cells = len(session) * len(critical_fields)
    missing_critical = 0
    field_quality_rows = []
    for field in required_session_fields:
        if field not in session.columns:
            field_quality_rows.append({
                "Field": field,
                "Present": False,
                "Populated Rows": 0,
                "Missing Rows": len(session),
                "Completeness %": 0.0,
                "Critical": field in rules["critical_fields"],
            })
            continue
        values = session[field].map(_text)
        populated = int(values.ne("").sum())
        missing = int(values.eq("").sum())
        completeness = _pct(populated, len(session))
        field_quality_rows.append({
            "Field": field,
            "Present": True,
            "Populated Rows": populated,
            "Missing Rows": missing,
            "Completeness %": completeness,
            "Critical": field in rules["critical_fields"],
        })
        if field in rules["critical_fields"]:
            missing_critical += missing

    critical_missing_rate = _pct(missing_critical, critical_cells)
    max_missing_critical = float(rules["thresholds"]["maximum_missing_critical_rate"])
    critical_status = (
        "PASS" if critical_missing_rate <= max_missing_critical
        else "FAIL" if critical_missing_rate > max_missing_critical * 2
        else "WARNING"
    )
    checks.append({
        "Check ID": "CRITICAL_FIELD_COMPLETENESS",
        "Area": "Completeness",
        "Check": "Critical ECU field completeness",
        "Status": critical_status,
        "Score": max(0.0, 100.0 - critical_missing_rate),
        "Evidence": f"Critical-field missing rate: {critical_missing_rate:.1f}%.",
    })

    if "ECU ID" in session.columns:
        ecu_values = session["ECU ID"].map(_text)
        duplicate_mask = ecu_values.ne("") & ecu_values.duplicated(keep=False)
        duplicate_rows = int(duplicate_mask.sum())
        duplicate_ecus = int(ecu_values[duplicate_mask].nunique())
    else:
        duplicate_rows = duplicate_ecus = 0
    duplicate_rate = _pct(duplicate_rows, len(session))
    max_duplicate_rate = float(rules["thresholds"]["maximum_duplicate_rate"])
    duplicate_status = (
        "PASS" if duplicate_rate <= max_duplicate_rate
        else "FAIL" if duplicate_rate > max_duplicate_rate * 3
        else "WARNING"
    )
    checks.append({
        "Check ID": "DUPLICATE_CONTROL",
        "Area": "Uniqueness",
        "Check": "Duplicate ECU records",
        "Status": duplicate_status,
        "Score": max(0.0, 100.0 - duplicate_rate * 5),
        "Evidence": f"{duplicate_rows} duplicate row(s) across {duplicate_ecus} ECU(s).",
    })
    if duplicate_rows:
        findings.append({
            "Severity": "MAJOR",
            "Area": "Uniqueness",
            "Field": "ECU ID",
            "Finding": f"{duplicate_rows} duplicate ECU row(s) detected.",
            "Required Action": "Review repeated ECU blocks and confirm which record is authoritative.",
        })

    vin_values = (
        session["VIN"].map(_text)
        if "VIN" in session.columns else pd.Series(dtype=str)
    )
    unique_vins = sorted({vin for vin in vin_values if vin})
    valid_vins = [vin for vin in unique_vins if len(vin) == 17 and vin.isalnum()]
    vin_status = (
        "PASS" if len(unique_vins) == 1 and len(valid_vins) == 1
        else "FAIL" if len(unique_vins) > 1
        else "WARNING"
    )
    vin_score = 100.0 if vin_status == "PASS" else 0.0 if vin_status == "FAIL" else 60.0
    checks.append({
        "Check ID": "VIN_INTEGRITY",
        "Area": "Identity",
        "Check": "VIN presence and consistency",
        "Status": vin_status,
        "Score": vin_score,
        "Evidence": f"Resolved VIN values: {', '.join(unique_vins) if unique_vins else 'none'}.",
    })

    reference_match_rate = 0.0
    reference_status = "NOT_AVAILABLE"
    reference_rows = []
    if not reference.empty and "ECU ID" in session.columns:
        reference_key = "ECU Variant" if "ECU Variant" in reference.columns else "ECU"
        if reference_key in reference.columns:
            session_ecus = {value for value in session["ECU ID"].map(_text) if value}
            reference_ecus = {value for value in reference[reference_key].map(_text) if value}
            matched = session_ecus & reference_ecus
            unmatched_session = session_ecus - reference_ecus
            missing_session = reference_ecus - session_ecus
            reference_match_rate = _pct(len(matched), len(session_ecus))
            minimum_match = float(rules["thresholds"]["minimum_reference_match_rate"])
            reference_status = (
                "PASS" if reference_match_rate >= minimum_match
                else "FAIL" if reference_match_rate < minimum_match * 0.75
                else "WARNING"
            )
            for ecu in sorted(session_ecus | reference_ecus):
                reference_rows.append({
                    "ECU": ecu,
                    "In Session": ecu in session_ecus,
                    "In Reference": ecu in reference_ecus,
                    "Match Status": (
                        "MATCHED" if ecu in matched
                        else "SESSION_ONLY" if ecu in unmatched_session
                        else "REFERENCE_ONLY"
                    ),
                })
    checks.append({
        "Check ID": "REFERENCE_MATCH",
        "Area": "Reference",
        "Check": "Session-to-reference ECU match",
        "Status": reference_status,
        "Score": reference_match_rate if reference_status != "NOT_AVAILABLE" else 50.0,
        "Evidence": (
            f"Reference match rate: {reference_match_rate:.1f}%."
            if reference_status != "NOT_AVAILABLE"
            else "No usable reference ECU key was available."
        ),
    })

    dtc_rows = len(dtc)
    checks.append({
        "Check ID": "DTC_INPUT",
        "Area": "Diagnostics",
        "Check": "DTC input availability",
        "Status": "PASS" if dtc_rows > 0 else "NOT_AVAILABLE",
        "Score": 100.0 if dtc_rows > 0 else 50.0,
        "Evidence": f"{dtc_rows} DTC row(s) available.",
    })

    checklist = pd.DataFrame(checks)
    weights = rules["weights"]
    weighted = 0.0
    total_weight = 0.0
    weight_map = {
        "SESSION_SCHEMA": "schema_completeness",
        "CRITICAL_FIELD_COMPLETENESS": "critical_field_completeness",
        "DUPLICATE_CONTROL": "duplicate_control",
        "VIN_INTEGRITY": "vin_integrity",
        "REFERENCE_MATCH": "reference_match",
        "PARSER_COVERAGE": "parser_coverage",
    }
    for _, row in checklist.iterrows():
        weight_key = weight_map.get(str(row["Check ID"]))
        if not weight_key:
            continue
        weight = float(weights[weight_key])
        weighted += weight * float(row["Score"])
        total_weight += weight
    quality_score = weighted / total_weight if total_weight else 0.0

    failed = int(checklist["Status"].eq("FAIL").sum())
    warnings = int(checklist["Status"].eq("WARNING").sum())
    if failed:
        readiness = "NOT_READY"
    elif quality_score >= float(rules["thresholds"]["ready"]) and warnings == 0:
        readiness = "READY"
    elif quality_score >= float(rules["thresholds"]["ready_with_warnings"]):
        readiness = "READY_WITH_WARNINGS"
    else:
        readiness = "NOT_READY"

    summary = pd.DataFrame([{
        "Readiness Score": round(quality_score, 1),
        "Readiness Decision": readiness,
        "Session Rows": len(session),
        "Unique ECUs": ecu_count,
        "Required Columns Missing": len(missing_columns),
        "Critical Missing Rate %": critical_missing_rate,
        "Duplicate Rate %": duplicate_rate,
        "Resolved VIN Count": len(unique_vins),
        "Reference Match %": reference_match_rate,
        "DTC Rows": dtc_rows,
        "Passed Checks": int(checklist["Status"].eq("PASS").sum()),
        "Warning Checks": warnings,
        "Failed Checks": failed,
        "Unavailable Checks": int(checklist["Status"].eq("NOT_AVAILABLE").sum()),
        "Recommendation": (
            "PROCEED_WITH_ANALYSIS"
            if readiness == "READY"
            else "PROCEED_AND_REVIEW_WARNINGS"
            if readiness == "READY_WITH_WARNINGS"
            else "CORRECT_INPUT_DATA_BEFORE_ANALYSIS"
        ),
        "Disclaimer": rules["disclaimer"],
    }])

    findings_frame = pd.DataFrame(findings)
    if findings_frame.empty:
        findings_frame = pd.DataFrame(columns=[
            "Severity", "Area", "Field", "Finding", "Required Action"
        ])

    return {
        "summary": summary,
        "checklist": checklist,
        "field_quality": pd.DataFrame(field_quality_rows),
        "reference_match": pd.DataFrame(reference_rows),
        "findings": findings_frame,
    }
