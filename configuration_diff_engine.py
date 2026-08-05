from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("configuration_diff_rules.json")
KEY_COLUMN = "ECU"


def load_diff_rules(path: str | Path | None = None) -> dict[str, Any]:
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


def _release_family(value: Any) -> str:
    text = _text(value).upper()
    match = re.search(r"(MY\s*\d{2}(?:\.\d+)?)", text)
    return match.group(1).replace(" ", "") if match else text


def normalize_session(frame: pd.DataFrame, label: str = "Session") -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = pd.DataFrame()
    result[KEY_COLUMN] = frame.get("ECU ID", pd.Series(dtype=str)).map(_text)
    result["ECU Name"] = frame.get("ECU Name", pd.Series(dtype=str)).map(_text)
    for field in (
        "VIN", "Hardware Number", "Part Number", "Application SW",
        "Calibration SW", "Basic SW", "Software Number", "Bootloader",
    ):
        result[field] = frame.get(field, pd.Series(dtype=str)).map(_text)
    result["Installed Release"] = ""
    result["Target Release"] = ""
    result["Release Family"] = ""
    result["Source Label"] = label
    return result[result[KEY_COLUMN].ne("")].drop_duplicates(KEY_COLUMN, keep="last")


def normalize_reference(
    frame: pd.DataFrame,
    label: str = "Reference",
    release_name: str = "",
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = pd.DataFrame()
    result[KEY_COLUMN] = frame.get("ECU Variant", pd.Series(dtype=str)).map(_text)
    result["ECU Name"] = result[KEY_COLUMN]
    result["VIN"] = ""
    for field in (
        "Hardware Number", "Part Number", "Application SW",
        "Calibration SW", "Basic SW", "Software Number", "Bootloader",
    ):
        result[field] = frame.get(field, pd.Series(dtype=str)).map(_text)
    ref_series = frame.get("Reference Sheet", pd.Series(dtype=str)).map(_text)
    result["Installed Release"] = ""
    result["Target Release"] = (
        ref_series.where(ref_series.ne(""), release_name)
        if len(ref_series) == len(result)
        else release_name
    )
    result["Release Family"] = result["Target Release"].map(_release_family)
    result["Source Label"] = label
    return result[result[KEY_COLUMN].ne("")].drop_duplicates(KEY_COLUMN, keep="last")


def _severity_rank(severity: str, rules: Mapping[str, Any]) -> int:
    order = rules["severity_order"]
    try:
        return len(order) - order.index(severity)
    except ValueError:
        return 0


def compare_configurations(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    left_label: str = "A",
    right_label: str = "B",
    ignore_fields: Iterable[str] | None = None,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    rules = dict(rules or load_diff_rules())
    ignore = set(ignore_fields or [])
    configured_fields = [
        field for field in rules["fields"]
        if field not in ignore
    ]
    if left is None:
        left = pd.DataFrame()
    if right is None:
        right = pd.DataFrame()

    left_map = {
        _text(row.get(KEY_COLUMN)): row
        for _, row in left.iterrows()
        if _text(row.get(KEY_COLUMN))
    }
    right_map = {
        _text(row.get(KEY_COLUMN)): row
        for _, row in right.iterrows()
        if _text(row.get(KEY_COLUMN))
    }
    all_ecus = sorted(set(left_map) | set(right_map))

    ecu_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []

    for ecu in all_ecus:
        lrow = left_map.get(ecu)
        rrow = right_map.get(ecu)
        if lrow is None:
            status = "ADDED"
            changed_fields = ["ECU Presence"]
            highest = rules["presence_severity"]["ADDED"]
        elif rrow is None:
            status = "REMOVED"
            changed_fields = ["ECU Presence"]
            highest = rules["presence_severity"]["REMOVED"]
        else:
            changed_fields = []
            highest = "NONE"
            for field in configured_fields:
                before = _text(lrow.get(field, ""))
                after = _text(rrow.get(field, ""))
                if before == after:
                    continue
                changed_fields.append(field)
                config = rules["fields"][field]
                severity = config["severity"]
                if _severity_rank(severity, rules) > _severity_rank(highest, rules):
                    highest = severity
                field_rows.append({
                    "ECU": ecu,
                    "Field": field,
                    "Category": config["category"],
                    "Severity": severity,
                    f"{left_label} Value": before,
                    f"{right_label} Value": after,
                    "Change Type": (
                        "VALUE_ADDED" if not before and after else
                        "VALUE_REMOVED" if before and not after else
                        "VALUE_CHANGED"
                    ),
                })
            status = "MODIFIED" if changed_fields else "UNCHANGED"

        if status in {"ADDED", "REMOVED"}:
            field_rows.append({
                "ECU": ecu,
                "Field": "ECU Presence",
                "Category": "PRESENCE",
                "Severity": highest,
                f"{left_label} Value": "PRESENT" if lrow is not None else "MISSING",
                f"{right_label} Value": "PRESENT" if rrow is not None else "MISSING",
                "Change Type": status,
            })

        categories = sorted({
            row["Category"] for row in field_rows
            if row["ECU"] == ecu
        })
        ecu_rows.append({
            "ECU": ecu,
            "ECU Name A": _text(lrow.get("ECU Name", "")) if lrow is not None else "",
            "ECU Name B": _text(rrow.get("ECU Name", "")) if rrow is not None else "",
            "Diff Status": status,
            "Highest Severity": highest,
            "Changed Field Count": len(changed_fields),
            "Changed Fields": ", ".join(changed_fields),
            "Changed Categories": ", ".join(categories),
            "Software Changed": "SOFTWARE" in categories,
            "Hardware Changed": "HARDWARE" in categories,
            "Release Changed": "RELEASE" in categories,
            "Identity Changed": "IDENTITY" in categories,
        })

    ecu_diff = pd.DataFrame(ecu_rows)
    field_diff = pd.DataFrame(field_rows)

    if not ecu_diff.empty:
        status_rank = {name: i for i, name in enumerate(rules["status_order"])}
        severity_rank = {
            name: i for i, name in enumerate(rules["severity_order"])
        }
        ecu_diff["_status"] = ecu_diff["Diff Status"].map(status_rank).fillna(999)
        ecu_diff["_severity"] = ecu_diff["Highest Severity"].map(severity_rank).fillna(999)
        ecu_diff = ecu_diff.sort_values(
            ["_status", "_severity", "ECU"]
        ).drop(columns=["_status", "_severity"]).reset_index(drop=True)

    summary_counts = (
        ecu_diff["Diff Status"].value_counts().to_dict()
        if not ecu_diff.empty else {}
    )
    severity_counts = (
        field_diff["Severity"].value_counts().to_dict()
        if not field_diff.empty else {}
    )
    category_counts = (
        field_diff["Category"].value_counts().to_dict()
        if not field_diff.empty else {}
    )
    summary = pd.DataFrame([{
        "Left Configuration": left_label,
        "Right Configuration": right_label,
        "Total ECUs": len(ecu_diff),
        "Added ECUs": int(summary_counts.get("ADDED", 0)),
        "Removed ECUs": int(summary_counts.get("REMOVED", 0)),
        "Modified ECUs": int(summary_counts.get("MODIFIED", 0)),
        "Unchanged ECUs": int(summary_counts.get("UNCHANGED", 0)),
        "Total Field Differences": len(field_diff),
        "Critical Differences": int(severity_counts.get("CRITICAL", 0)),
        "Major Differences": int(severity_counts.get("MAJOR", 0)),
        "Minor Differences": int(severity_counts.get("MINOR", 0)),
        "Informational Differences": int(severity_counts.get("INFORMATIONAL", 0)),
        "Software Differences": int(category_counts.get("SOFTWARE", 0)),
        "Hardware Differences": int(category_counts.get("HARDWARE", 0)),
        "Release Differences": int(category_counts.get("RELEASE", 0)),
        "Identity Differences": int(category_counts.get("IDENTITY", 0)),
        "Overall Assessment": (
            "CRITICAL_CHANGE"
            if severity_counts.get("CRITICAL", 0) else
            "MAJOR_CHANGE"
            if severity_counts.get("MAJOR", 0) else
            "MINOR_CHANGE"
            if field_diff is not None and not field_diff.empty else
            "NO_CHANGE"
        ),
    }])

    categories = {}
    for category in ("SOFTWARE", "HARDWARE", "RELEASE", "IDENTITY", "PRESENCE"):
        categories[category.lower()] = (
            field_diff[field_diff["Category"] == category].copy()
            if not field_diff.empty else pd.DataFrame()
        )

    return {
        "summary": summary,
        "ecu_diff": ecu_diff,
        "field_diff": field_diff,
        **categories,
        "added_removed": (
            ecu_diff[ecu_diff["Diff Status"].isin(["ADDED", "REMOVED"])].copy()
            if not ecu_diff.empty else pd.DataFrame()
        ),
    }
