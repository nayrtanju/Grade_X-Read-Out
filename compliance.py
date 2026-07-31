from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from frs_database import FIELDS
from utils import compact, ecu_base, identifier_parts, text

ACTUAL_TO_REFERENCE = {
    "Bootloader": FIELDS["Bootloader"],
    "Calibration SW": FIELDS["Calibration SW"],
    "Part Number": FIELDS["Part Number"],
    "Application SW": FIELDS["Application SW"],
    "Basic SW": FIELDS["Basic SW"],
    "Software Number": FIELDS["Software Number"],
    "Hardware Number": FIELDS["Hardware Number"],
}

CRITICAL_FIELDS = {"Calibration SW", "Application SW", "Software Number", "Hardware Number"}


@dataclass(frozen=True)
class CandidateResult:
    index: int
    score: int
    exact: int
    part: int
    mismatch: int
    missing: int
    checks: int
    confidence: int


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
        if ar and er and (ar == er or er.endswith(ar.zfill(len(er))) or ar.endswith(er.zfill(len(ar)))):
            return "MATCH", "Part number and available revision match"
        return "PART_MATCH", "Part number matches; revision granularity differs"
    return "MISMATCH", "Part number differs"


def _evaluate_candidate(ecu_row: pd.Series, ref_row: pd.Series, idx: int) -> CandidateResult:
    exact = part = mismatch = missing = checks = 0
    weighted = 0
    max_weight = 0
    for actual_col, ref_col in ACTUAL_TO_REFERENCE.items():
        status, _ = compare_identifier(ecu_row.get(actual_col, ""), ref_row.get(ref_col, ""))
        if status == "NOT_APPLICABLE":
            continue
        checks += 1
        weight = 3 if actual_col in CRITICAL_FIELDS else 1
        max_weight += weight * 3
        if status == "MATCH":
            exact += 1
            weighted += weight * 3
        elif status == "PART_MATCH":
            part += 1
            weighted += weight * 2
        elif status == "MISSING":
            missing += 1
        else:
            mismatch += 1
            weighted -= weight * 2
    confidence = max(0, min(100, round((weighted / max_weight) * 100))) if max_weight else 0
    score = weighted - mismatch * 2 - missing
    return CandidateResult(idx, score, exact, part, mismatch, missing, checks, confidence)


def _best_candidate(ecu: pd.Series, candidates: pd.DataFrame) -> CandidateResult | None:
    if candidates.empty:
        return None
    results = [_evaluate_candidate(ecu, ref, int(idx)) for idx, ref in candidates.iterrows()]
    return max(results, key=lambda r: (r.score, r.exact, r.part, -r.mismatch, -r.missing))


def _release_relation(installed_rank: tuple[int, ...], target_rank: tuple[int, ...]) -> str:
    if not installed_rank or not target_rank:
        return "UNKNOWN"
    if installed_rank == target_rank:
        return "TARGET"
    return "OLDER" if installed_rank < target_rank else "NEWER"


def _overall_status(
    target_statuses: dict[str, str],
    installed_match: pd.Series | None,
    target_ref: pd.Series,
) -> tuple[str, str]:
    considered = [s for s in target_statuses.values() if s != "NOT_APPLICABLE"]
    critical = [target_statuses.get(field) for field in CRITICAL_FIELDS if target_statuses.get(field) not in (None, "NOT_APPLICABLE")]

    if considered and all(s == "MATCH" for s in considered):
        return "COMPLIANT", "All applicable identifiers match the selected target release"

    if installed_match is not None:
        relation = _release_relation(
            tuple(installed_match.get("Release Rank", ())),
            tuple(target_ref.get("Release Rank", ())),
        )
        same_sheet = text(installed_match.get("Reference Sheet")) == text(target_ref.get("Reference Sheet"))
        same_my = text(installed_match.get("Model Year")) == text(target_ref.get("Model Year"))
        if not same_sheet and relation == "OLDER" and same_my:
            return "UPDATE_AVAILABLE", "Installed identifiers match an older release; selected target is newer"
        if not same_sheet and (not same_my or relation == "NEWER"):
            return "WRONG_RELEASE", "Installed identifiers match a different model-year or non-target release"

    if any(s == "MISMATCH" for s in critical):
        return "MISMATCH", "One or more critical SW/HW identifiers differ from the target"
    if any(s == "MISSING" for s in considered):
        return "REVIEW", "Required identifiers are missing; automatic decision is incomplete"
    if any(s == "PART_MATCH" for s in considered):
        return "PARTIAL_MATCH", "Part numbers match, but revision granularity prevents full confirmation"
    if any(s == "MISMATCH" for s in considered):
        return "MISMATCH", "One or more identifiers differ from the target"
    return "REVIEW", "The available data is insufficient for a definitive decision"


def validate(
    summary: pd.DataFrame,
    target_reference: pd.DataFrame,
    release_catalog: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Validate vehicle identifiers against a selected target release.

    release_catalog may contain all release sheets. It is used to infer the installed
    release and to distinguish UPDATE_AVAILABLE / WRONG_RELEASE from a generic mismatch.
    """
    catalog = release_catalog if release_catalog is not None and not release_catalog.empty else target_reference
    overview: list[dict] = []
    details: list[dict] = []
    candidates_out: list[dict] = []

    for _, ecu in summary.iterrows():
        base = ecu_base(ecu.get("ECU ID", "") or ecu.get("ECU Name", ""))
        target_candidates = target_reference[target_reference["ECU Base"] == base].copy()
        all_candidates = catalog[catalog["ECU Base"] == base].copy()

        if target_candidates.empty:
            overview.append({
                "Source File": ecu.get("Source File", ""), "VIN": ecu.get("VIN", ""), "ECU": ecu.get("ECU ID", ""),
                "Matched Variant": "", "Installed Release": "", "Target Release": "", "Status": "NO_REFERENCE",
                "Decision Reason": "No ECU reference exists in the selected target release", "Confidence %": 0,
                "Matches": 0, "Partial Matches": 0, "Checks": 0, "Mismatches": 0, "Missing": 0,
            })
            continue

        for idx, ref in target_candidates.iterrows():
            result = _evaluate_candidate(ecu, ref, int(idx))
            candidates_out.append({
                "Source File": ecu.get("Source File", ""), "ECU": ecu.get("ECU ID", ""),
                "Candidate Variant": ref.get("ECU Variant", ""), "Target Release": ref.get("SW Version", ""),
                "Reference Sheet": ref.get("Reference Sheet", ""), "Candidate Score": result.score,
                "Confidence %": result.confidence, "Matches": result.exact, "Partial Matches": result.part,
                "Mismatches": result.mismatch, "Missing": result.missing,
            })

        best_target_result = _best_candidate(ecu, target_candidates)
        assert best_target_result is not None
        target_ref = target_reference.loc[best_target_result.index]

        best_installed_result = _best_candidate(ecu, all_candidates)
        installed_ref: pd.Series | None = None
        # Only infer an installed release when the match is sufficiently strong and not dominated by mismatches.
        if best_installed_result and best_installed_result.confidence >= 55 and best_installed_result.mismatch <= 1:
            installed_ref = catalog.loc[best_installed_result.index]

        target_statuses: dict[str, str] = {}
        for actual_col, ref_col in ACTUAL_TO_REFERENCE.items():
            status, reason = compare_identifier(ecu.get(actual_col, ""), target_ref.get(ref_col, ""))
            target_statuses[actual_col] = status
            details.append({
                "Source File": ecu.get("Source File", ""), "VIN": ecu.get("VIN", ""), "ECU": ecu.get("ECU ID", ""),
                "Matched Variant": target_ref.get("ECU Variant", ""), "Installed Release": installed_ref.get("SW Version", "") if installed_ref is not None else "",
                "Target Release": target_ref.get("SW Version", ""), "Field": actual_col,
                "Actual": ecu.get(actual_col, ""), "Expected": target_ref.get(ref_col, ""),
                "Status": status, "Reason": reason,
            })

        overall, decision_reason = _overall_status(target_statuses, installed_ref, target_ref)
        considered = [s for s in target_statuses.values() if s != "NOT_APPLICABLE"]
        overview.append({
            "Source File": ecu.get("Source File", ""), "VIN": ecu.get("VIN", ""), "ECU": ecu.get("ECU ID", ""),
            "Matched Variant": target_ref.get("ECU Variant", ""),
            "Installed Release": installed_ref.get("SW Version", "") if installed_ref is not None else "",
            "Target Release": target_ref.get("SW Version", ""), "Status": overall,
            "Decision Reason": decision_reason, "Confidence %": best_target_result.confidence,
            "Matches": sum(s == "MATCH" for s in considered),
            "Partial Matches": sum(s == "PART_MATCH" for s in considered),
            "Checks": len(considered), "Mismatches": sum(s == "MISMATCH" for s in considered),
            "Missing": sum(s == "MISSING" for s in considered),
        })

    return pd.DataFrame(overview), pd.DataFrame(details), pd.DataFrame(candidates_out)
