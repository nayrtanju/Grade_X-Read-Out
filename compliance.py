from __future__ import annotations
import pandas as pd
from frs_database import FIELDS
from utils import compact, ecu_base, identifier_parts, text

ACTUAL_TO_REFERENCE = {
    "Bootloader": FIELDS["Bootloader"], "Calibration SW": FIELDS["Calibration SW"],
    "Part Number": FIELDS["Part Number"], "Application SW": FIELDS["Application SW"],
    "Basic SW": FIELDS["Basic SW"], "Software Number": FIELDS["Software Number"],
    "Hardware Number": FIELDS["Hardware Number"],
}


def compare_identifier(actual: str, expected: str) -> tuple[str, str]:
    a, e = text(actual), text(expected)
    if not e:
        return "NOT_APPLICABLE", "No reference value"
    if not a:
        return "MISSING", "Identifier not read from vehicle"
    if compact(a) == compact(e):
        return "MATCH", "Exact identifier match"
    ap, an, ar = identifier_parts(a)
    ep, en, er = identifier_parts(e)
    if an and en and an == en and (not ap or not ep or ap == ep):
        if ar and er and (ar == er or er.endswith(ar.zfill(len(er)))):
            return "MATCH", "Part number and available revision match"
        return "PART_MATCH", "Part number matches; revision granularity differs"
    return "MISMATCH", "Part number differs"


def _candidate_score(ecu_row: pd.Series, ref_row: pd.Series) -> tuple[int, int, int]:
    match = partial = mismatch = 0
    for actual_col, ref_col in ACTUAL_TO_REFERENCE.items():
        status, _ = compare_identifier(ecu_row.get(actual_col, ""), ref_row.get(ref_col, ""))
        if status == "MATCH": match += 3
        elif status == "PART_MATCH": partial += 1
        elif status == "MISMATCH": mismatch += 1
    return match + partial - mismatch * 2, match, -mismatch


def validate(summary: pd.DataFrame, reference: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    overview, details, candidates_out = [], [], []
    for _, ecu in summary.iterrows():
        base = ecu_base(ecu.get("ECU ID", "") or ecu.get("ECU Name", ""))
        candidates = reference[reference["ECU Base"] == base].copy()
        if candidates.empty:
            overview.append({"Source File": ecu["Source File"], "VIN": ecu["VIN"], "ECU": ecu["ECU ID"],
                             "Matched Variant": "", "Installed Release": "", "Target Release": "",
                             "Status": "NO_REFERENCE", "Matches": 0, "Checks": 0, "Mismatches": 0})
            continue
        scored = []
        for idx, ref in candidates.iterrows():
            score = _candidate_score(ecu, ref)
            scored.append((score, idx))
            candidates_out.append({"Source File": ecu["Source File"], "ECU": ecu["ECU ID"],
                                   "Candidate Variant": ref["ECU Variant"], "Target Release": ref["SW Version"],
                                   "Candidate Score": score[0]})
        _, best_idx = max(scored, key=lambda x: x[0])
        ref = reference.loc[best_idx]
        statuses = []
        for actual_col, ref_col in ACTUAL_TO_REFERENCE.items():
            status, reason = compare_identifier(ecu.get(actual_col, ""), ref.get(ref_col, ""))
            statuses.append(status)
            details.append({"Source File": ecu["Source File"], "VIN": ecu["VIN"], "ECU": ecu["ECU ID"],
                            "Matched Variant": ref["ECU Variant"], "Target Release": ref["SW Version"],
                            "Field": actual_col, "Actual": ecu.get(actual_col, ""), "Expected": ref.get(ref_col, ""),
                            "Status": status, "Reason": reason})
        considered = [s for s in statuses if s != "NOT_APPLICABLE"]
        if any(s == "MISMATCH" for s in considered): overall = "MISMATCH"
        elif any(s == "MISSING" for s in considered): overall = "REVIEW"
        elif any(s == "PART_MATCH" for s in considered): overall = "PART_MATCH"
        elif considered and all(s == "MATCH" for s in considered): overall = "COMPLIANT"
        else: overall = "REVIEW"
        overview.append({"Source File": ecu["Source File"], "VIN": ecu["VIN"], "ECU": ecu["ECU ID"],
                         "Matched Variant": ref["ECU Variant"], "Installed Release": "",
                         "Target Release": ref["SW Version"], "Status": overall,
                         "Matches": sum(s == "MATCH" for s in considered), "Checks": len(considered),
                         "Mismatches": sum(s == "MISMATCH" for s in considered)})
    return pd.DataFrame(overview), pd.DataFrame(details), pd.DataFrame(candidates_out)
