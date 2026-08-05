from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("consistency_rules.json")


def load_consistency_rules(path: str | Path | None = None) -> dict[str, Any]:
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


def _release_family(value: str) -> str:
    text = _text(value).upper()
    if not text:
        return ""
    patterns = [
        r"(MY\d{2}(?:\.\d+)?)",
        r"(PTO\d+)",
        r"(BF\d+)",
        r"(SOP)",
    ]
    parts = []
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            parts.append(match.group(1))
    return " | ".join(parts) if parts else text


def _level(score: float, thresholds: Mapping[str, float]) -> str:
    if score >= thresholds["consistent"]:
        return "CONSISTENT"
    if score >= thresholds["mostly_consistent"]:
        return "MOSTLY_CONSISTENT"
    if score >= thresholds["mixed_package"]:
        return "MIXED_PACKAGE"
    return "INCONSISTENT"


def _field_breakdown(
    details: pd.DataFrame,
    source_file: str,
    field: str,
    rules: Mapping[str, Any],
) -> dict[str, Any]:
    scoped = details[
        (details["Source File"].astype(str) == str(source_file))
        & (details["Field"].astype(str) == str(field))
    ]
    if scoped.empty:
        return {
            "Field": field,
            "Applicable ECUs": 0,
            "Weighted Score %": None,
            "Matches": 0,
            "Partial Matches": 0,
            "Mismatches": 0,
            "Missing": 0,
        }

    status_scores = rules["status_scores"]
    scored = []
    for status in scoped["Status"].astype(str):
        value = status_scores.get(status)
        if value is not None:
            scored.append(float(value))

    weighted_score = sum(scored) / len(scored) * 100 if scored else None
    return {
        "Field": field,
        "Applicable ECUs": len(scored),
        "Weighted Score %": round(weighted_score, 1) if weighted_score is not None else None,
        "Matches": int((scoped["Status"].astype(str) == "MATCH").sum()),
        "Partial Matches": int((scoped["Status"].astype(str) == "PART_MATCH").sum()),
        "Mismatches": int((scoped["Status"].astype(str) == "MISMATCH").sum()),
        "Missing": int((scoped["Status"].astype(str) == "MISSING").sum()),
    }


def analyze_release_consistency(
    overview: pd.DataFrame,
    details: pd.DataFrame,
    summary: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rules = dict(rules or load_consistency_rules())
    if overview is None or overview.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    vehicle_rows = []
    field_rows = []
    ecu_rows = []

    field_weights = rules["field_weights"]
    package_rules = rules["package_rules"]

    for (source_file, vin), group in overview.groupby(["Source File", "VIN"], dropna=False):
        field_results = []
        for field, weight in field_weights.items():
            result = _field_breakdown(details, source_file, field, rules)
            result.update({
                "Source File": source_file,
                "VIN": vin,
                "Weight": weight,
            })
            field_results.append(result)
            field_rows.append(result)

        applicable = [
            item for item in field_results
            if item["Weighted Score %"] is not None and item["Applicable ECUs"] > 0
        ]
        total_weight = sum(float(item["Weight"]) for item in applicable)
        consistency_score = (
            sum(float(item["Weight"]) * float(item["Weighted Score %"]) for item in applicable)
            / total_weight
            if total_weight > 0 else 0.0
        )

        installed_release_counts = Counter(
            _release_family(value)
            for value in group.get("Installed Release", pd.Series(dtype=str))
            if _release_family(value)
        )
        target_release_counts = Counter(
            _release_family(value)
            for value in group.get("Target Release", pd.Series(dtype=str))
            if _release_family(value)
        )
        dominant_installed = installed_release_counts.most_common(1)[0][0] if installed_release_counts else ""
        dominant_target = target_release_counts.most_common(1)[0][0] if target_release_counts else ""

        off_family = 0
        for value in group.get("Installed Release", pd.Series(dtype=str)):
            family = _release_family(value)
            if family and dominant_installed and family != dominant_installed:
                off_family += 1
        mixed_ratio = off_family / len(group) if len(group) else 0.0

        critical_fields = set(package_rules["critical_mismatch_fields"])
        critical_mismatches = details[
            (details["Source File"].astype(str) == str(source_file))
            & (details["Field"].astype(str).isin(critical_fields))
            & (details["Status"].astype(str) == "MISMATCH")
        ]
        hardware_mismatches = details[
            (details["Source File"].astype(str) == str(source_file))
            & (details["Field"].astype(str).isin(["Hardware Number", "Part Number"]))
            & (details["Status"].astype(str) == "MISMATCH")
        ]

        mixed_package = (
            len(group) >= package_rules["minimum_ecus_for_package_detection"]
            and (
                mixed_ratio >= package_rules["mixed_release_ratio"]
                or not critical_mismatches.empty
            )
        )
        variant_review = (
            package_rules["hardware_mismatch_triggers_variant_review"]
            and not hardware_mismatches.empty
        )

        level = _level(consistency_score, rules["thresholds"])
        if mixed_package and level in {"CONSISTENT", "MOSTLY_CONSISTENT"}:
            level = "MIXED_PACKAGE"

        complete_fields = sum(
            1 for item in applicable
            if item["Missing"] == 0 and item["Applicable ECUs"] > 0
        )
        confidence_cfg = rules["confidence"]
        confidence = float(confidence_cfg["base"])
        if applicable and complete_fields == len(applicable):
            confidence += confidence_cfg["complete_data_bonus"]
        if dominant_target:
            confidence += confidence_cfg["target_release_bonus"]
        if len(group) >= 10:
            confidence += confidence_cfg["large_sample_bonus"]
        if mixed_package or variant_review:
            confidence += confidence_cfg["mixed_evidence_bonus"]
        confidence = min(float(confidence_cfg["cap"]), confidence)

        findings = []
        if mixed_package:
            findings.append("Mixed software package evidence detected")
        if variant_review:
            findings.append("Hardware/part-number variant review required")
        if critical_mismatches.empty:
            findings.append("No critical application/calibration/basic SW/bootloader mismatch")
        else:
            findings.append(f"{len(critical_mismatches)} critical field mismatch(es)")
        if mixed_ratio > 0:
            findings.append(f"{mixed_ratio * 100:.1f}% of ECUs differ from the dominant installed release family")
        if not findings:
            findings.append("No significant package-consistency finding")

        vehicle_rows.append({
            "Source File": source_file,
            "VIN": vin,
            "ECUs": len(group),
            "Release Consistency Score": round(consistency_score, 1),
            "Release Consistency Level": level,
            "Consistency Confidence %": round(confidence, 1),
            "Dominant Installed Release Family": dominant_installed,
            "Dominant Target Release Family": dominant_target,
            "Mixed Release Ratio %": round(mixed_ratio * 100, 1),
            "Mixed Package Detected": bool(mixed_package),
            "Variant Review Required": bool(variant_review),
            "Critical Package Mismatches": len(critical_mismatches),
            "Hardware/Part Mismatches": len(hardware_mismatches),
            "Consistency Findings": " | ".join(findings),
        })

        scoped_summary = summary[
            summary["Source File"].astype(str) == str(source_file)
        ].copy()
        scoped_overview = group.copy()
        for _, ecu_row in scoped_overview.iterrows():
            ecu = _text(ecu_row.get("ECU"))
            ecu_details = details[
                (details["Source File"].astype(str) == str(source_file))
                & (details["ECU"].astype(str) == ecu)
            ]
            critical_count = int(
                (
                    ecu_details["Field"].astype(str).isin(critical_fields)
                    & (ecu_details["Status"].astype(str) == "MISMATCH")
                ).sum()
            )
            total_mismatch = int((ecu_details["Status"].astype(str) == "MISMATCH").sum())
            installed_family = _release_family(_text(ecu_row.get("Installed Release")))
            family_match = (
                bool(installed_family)
                and bool(dominant_installed)
                and installed_family == dominant_installed
            )
            ecu_score = max(
                0.0,
                100.0
                - 25.0 * critical_count
                - 10.0 * max(0, total_mismatch - critical_count)
                - (15.0 if installed_family and not family_match else 0.0),
            )
            ecu_rows.append({
                "Source File": source_file,
                "VIN": vin,
                "ECU": ecu,
                "Status": ecu_row.get("Status", ""),
                "Installed Release": ecu_row.get("Installed Release", ""),
                "Installed Release Family": installed_family,
                "Dominant Release Family Match": family_match,
                "Critical Field Mismatches": critical_count,
                "Total Field Mismatches": total_mismatch,
                "ECU Consistency Score": round(ecu_score, 1),
                "Package Role": (
                    "OUTLIER"
                    if installed_family and dominant_installed and not family_match
                    else "DOMINANT_FAMILY"
                ),
            })

    vehicle = pd.DataFrame(vehicle_rows).sort_values(
        ["Release Consistency Score", "Mixed Package Detected"],
        ascending=[True, False],
    ).reset_index(drop=True)
    field = pd.DataFrame(field_rows)
    ecu = pd.DataFrame(ecu_rows).sort_values(
        ["Source File", "ECU Consistency Score", "ECU"],
        ascending=[True, True, True],
    ).reset_index(drop=True)
    return vehicle, field, ecu
