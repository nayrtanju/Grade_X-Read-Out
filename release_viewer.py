from __future__ import annotations

import pandas as pd

from compliance import ACTUAL_TO_REFERENCE, CRITICAL_FIELDS, compare_identifier
from utils import ecu_base, text


def release_timeline(ecu_row: pd.Series, catalog: pd.DataFrame) -> pd.DataFrame:
    """Score every historical reference variant for one vehicle ECU."""
    base = ecu_base(ecu_row.get("ECU ID", "") or ecu_row.get("ECU Name", ""))
    candidates = catalog[catalog.get("ECU Base", pd.Series(dtype=str)) == base].copy()
    rows: list[dict] = []
    for _, ref in candidates.iterrows():
        matches = partial = mismatches = missing = checks = 0
        weighted = 0
        maximum = 0
        for actual_col, reference_col in ACTUAL_TO_REFERENCE.items():
            status, _ = compare_identifier(ecu_row.get(actual_col, ""), ref.get(reference_col, ""))
            if status == "NOT_APPLICABLE":
                continue
            checks += 1
            weight = 3 if actual_col in CRITICAL_FIELDS else 1
            maximum += weight * 3
            if status == "MATCH":
                matches += 1
                weighted += weight * 3
            elif status == "PART_MATCH":
                partial += 1
                weighted += weight * 2
            elif status == "MISSING":
                missing += 1
            else:
                mismatches += 1
                weighted -= weight * 2
        confidence = max(0, min(100, round(weighted / maximum * 100))) if maximum else 0
        rows.append({
            "Reference Sheet": ref.get("Reference Sheet", ""),
            "Model Year": ref.get("Model Year", ""),
            "Release": ref.get("SW Version", ""),
            "ECU Variant": ref.get("ECU Variant", ""),
            "Confidence %": confidence,
            "Matches": matches,
            "Partial Matches": partial,
            "Mismatches": mismatches,
            "Missing": missing,
            "Checks": checks,
            "Release Rank": ref.get("Release Rank", ()),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.drop_duplicates(subset=["Reference Sheet", "Release", "ECU Variant"], keep="first")
    return out.sort_values(
        ["Confidence %", "Mismatches", "Matches", "Release Rank"],
        ascending=[False, True, False, False],
    ).reset_index(drop=True)


def field_comparison(ecu_row: pd.Series, reference_row: pd.Series) -> pd.DataFrame:
    rows = []
    for actual_col, reference_col in ACTUAL_TO_REFERENCE.items():
        status, reason = compare_identifier(ecu_row.get(actual_col, ""), reference_row.get(reference_col, ""))
        rows.append({
            "Field": actual_col,
            "Installed": text(ecu_row.get(actual_col, "")),
            "Expected": text(reference_row.get(reference_col, "")),
            "Status": status,
            "Reason": reason,
        })
    return pd.DataFrame(rows)


def target_variants(ecu_row: pd.Series, target_reference: pd.DataFrame) -> pd.DataFrame:
    base = ecu_base(ecu_row.get("ECU ID", "") or ecu_row.get("ECU Name", ""))
    return target_reference[target_reference.get("ECU Base", pd.Series(dtype=str)) == base].copy().reset_index(drop=True)


def release_detail_rows(summary: pd.DataFrame, overview: pd.DataFrame, details: pd.DataFrame) -> pd.DataFrame:
    """Flatten ECU/release information for the Excel Release Details sheet."""
    if overview.empty:
        return pd.DataFrame()
    key_cols = ["Source File", "ECU"]
    rows = []
    for _, ov in overview.iterrows():
        ecu_match = summary[(summary["Source File"] == ov.get("Source File", "")) & (summary["ECU ID"] == ov.get("ECU", ""))]
        ecu = ecu_match.iloc[0] if not ecu_match.empty else pd.Series(dtype=object)
        field_rows = details[(details["Source File"] == ov.get("Source File", "")) & (details["ECU"] == ov.get("ECU", ""))]
        mismatch_fields = ", ".join(field_rows.loc[field_rows["Status"].isin(["MISMATCH", "MISSING"]), "Field"].astype(str))
        rows.append({
            "Source File": ov.get("Source File", ""),
            "VIN": ov.get("VIN", ""),
            "ECU": ov.get("ECU", ""),
            "ECU Name": ecu.get("ECU Name", ""),
            "Matched Variant": ov.get("Matched Variant", ""),
            "Installed Release": ov.get("Installed Release", ""),
            "Target Release": ov.get("Target Release", ""),
            "Status": ov.get("Status", ""),
            "Confidence %": ov.get("Confidence %", 0),
            "Decision Reason": ov.get("Decision Reason", ""),
            "Mismatch / Missing Fields": mismatch_fields,
            "Hardware Number": ecu.get("Hardware Number", ""),
            "Application SW": ecu.get("Application SW", ""),
            "Calibration SW": ecu.get("Calibration SW", ""),
            "Part Number": ecu.get("Part Number", ""),
            "Basic SW": ecu.get("Basic SW", ""),
            "Software Number": ecu.get("Software Number", ""),
            "Bootloader": ecu.get("Bootloader", ""),
        })
    return pd.DataFrame(rows)
