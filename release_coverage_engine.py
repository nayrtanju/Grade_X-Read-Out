from __future__ import annotations

import re
from typing import Any

import pandas as pd


def _text(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def _release_number(value: Any) -> float | None:
    text = _text(value).upper()
    match = re.search(r"MY\s*(\d{2})(?:\.(\d+))?", text)
    if not match:
        return None
    return int(match.group(1)) + int(match.group(2) or 0) / 10.0


def _release_family(value: Any) -> str:
    text = _text(value).upper()
    match = re.search(r"(MY\s*\d{2}(?:\.\d+)?)", text)
    return match.group(1).replace(" ", "") if match else text


def build_release_coverage(
    overview: pd.DataFrame,
    reference: pd.DataFrame | None = None,
    release_consistency: pd.DataFrame | None = None,
    multi_session_result: dict[str, pd.DataFrame] | None = None,
) -> dict[str, pd.DataFrame]:
    overview = overview.copy() if overview is not None else pd.DataFrame()
    reference = reference.copy() if reference is not None else pd.DataFrame()
    multi_session_result = multi_session_result or {}

    if overview.empty:
        empty = pd.DataFrame()
        return {
            "summary": empty,
            "ecu_coverage": empty,
            "installed_distribution": empty,
            "target_distribution": empty,
            "coverage_by_target": empty,
            "legacy_candidates": empty,
            "unknown_releases": empty,
            "reference_coverage": empty,
            "session_release_trend": empty,
        }

    for column in ("Installed Release", "Target Release", "Status", "ECU", "ECU Name"):
        if column not in overview.columns:
            overview[column] = ""

    overview["Installed Release"] = overview["Installed Release"].map(_text)
    overview["Target Release"] = overview["Target Release"].map(_text)
    overview["Installed Release Family"] = overview["Installed Release"].map(_release_family)
    overview["Target Release Family"] = overview["Target Release"].map(_release_family)
    overview["Installed Release Number"] = overview["Installed Release"].map(_release_number)
    overview["Target Release Number"] = overview["Target Release"].map(_release_number)

    def coverage_state(row: pd.Series) -> str:
        installed = _text(row["Installed Release"])
        target = _text(row["Target Release"])
        status = _text(row["Status"])
        if not installed:
            return "UNKNOWN_INSTALLED"
        if not target:
            return "UNKNOWN_TARGET"
        if status == "COMPLIANT" or installed == target:
            return "TARGET_LEVEL"
        installed_num = row["Installed Release Number"]
        target_num = row["Target Release Number"]
        if installed_num is not None and target_num is not None:
            if installed_num < target_num:
                return "BELOW_TARGET"
            if installed_num > target_num:
                return "ABOVE_TARGET"
        return "DIFFERENT_RELEASE"

    overview["Coverage State"] = overview.apply(coverage_state, axis=1)
    overview["Release Gap"] = overview.apply(
        lambda row: (
            round(float(row["Target Release Number"]) - float(row["Installed Release Number"]), 1)
            if pd.notna(row["Target Release Number"]) and pd.notna(row["Installed Release Number"])
            else pd.NA
        ),
        axis=1,
    )
    overview["Obsolescence Candidate"] = overview["Coverage State"].isin(
        ["BELOW_TARGET", "UNKNOWN_INSTALLED"]
    )

    total = len(overview)
    target_level = int(overview["Coverage State"].eq("TARGET_LEVEL").sum())
    below_target = int(overview["Coverage State"].eq("BELOW_TARGET").sum())
    above_target = int(overview["Coverage State"].eq("ABOVE_TARGET").sum())
    unknown = int(
        overview["Coverage State"].isin(["UNKNOWN_INSTALLED", "UNKNOWN_TARGET"]).sum()
    )
    different = int(overview["Coverage State"].eq("DIFFERENT_RELEASE").sum())
    coverage_rate = target_level / total * 100 if total else 0.0

    mixed_package = False
    consistency_score = 0.0
    if release_consistency is not None and not release_consistency.empty:
        mixed_package = bool(
            release_consistency.iloc[0].get("Mixed Package Detected", False)
        )
        try:
            consistency_score = float(
                release_consistency.iloc[0].get("Release Consistency Score", 0)
            )
        except (TypeError, ValueError):
            consistency_score = 0.0

    installed_known = overview[
        overview["Installed Release"].astype(str).str.strip().ne("")
    ]
    unique_installed = installed_known["Installed Release"].nunique()
    unique_targets = overview[
        overview["Target Release"].astype(str).str.strip().ne("")
    ]["Target Release"].nunique()

    summary = pd.DataFrame([{
        "Total ECUs": total,
        "Target-Level ECUs": target_level,
        "Release Coverage %": round(coverage_rate, 1),
        "Below-Target ECUs": below_target,
        "Above-Target ECUs": above_target,
        "Different Release ECUs": different,
        "Unknown Release ECUs": unknown,
        "Obsolescence Candidates": int(overview["Obsolescence Candidate"].sum()),
        "Unique Installed Releases": unique_installed,
        "Unique Target Releases": unique_targets,
        "Release Consistency %": round(consistency_score, 1),
        "Mixed Package": mixed_package,
        "Coverage Level": (
            "GOOD" if coverage_rate >= 90 and not mixed_package
            else "FAIR" if coverage_rate >= 75
            else "POOR" if coverage_rate >= 50
            else "CRITICAL"
        ),
    }])

    installed_distribution = (
        overview["Installed Release"].replace("", "UNKNOWN")
        .value_counts()
        .rename_axis("Installed Release")
        .reset_index(name="ECU Count")
    )
    installed_distribution["Share %"] = (
        installed_distribution["ECU Count"] / total * 100
    ).round(1)

    target_distribution = (
        overview["Target Release"].replace("", "UNKNOWN")
        .value_counts()
        .rename_axis("Target Release")
        .reset_index(name="ECU Count")
    )
    target_distribution["Share %"] = (
        target_distribution["ECU Count"] / total * 100
    ).round(1)

    coverage_by_target = (
        overview.groupby("Target Release", dropna=False)
        .agg(
            ECU_Count=("ECU", "count"),
            Target_Level=("Coverage State", lambda values: int((values == "TARGET_LEVEL").sum())),
            Below_Target=("Coverage State", lambda values: int((values == "BELOW_TARGET").sum())),
            Unknown=("Coverage State", lambda values: int(values.isin(["UNKNOWN_INSTALLED", "UNKNOWN_TARGET"]).sum())),
        )
        .reset_index()
        .rename(columns={"Target Release": "Target Release"})
    )
    coverage_by_target["Target Release"] = coverage_by_target["Target Release"].replace("", "UNKNOWN")
    coverage_by_target["Coverage %"] = (
        coverage_by_target["Target_Level"] / coverage_by_target["ECU_Count"] * 100
    ).round(1)

    preferred_columns = [
        "Source File", "VIN", "ECU", "ECU Name", "Status",
        "Installed Release", "Target Release", "Installed Release Family",
        "Target Release Family", "Release Gap", "Coverage State",
        "Obsolescence Candidate", "Risk Score", "Risk Level",
        "Persistent DTC Count",
    ]
    ecu_coverage = overview[
        [column for column in preferred_columns if column in overview.columns]
    ].copy()

    legacy_candidates = ecu_coverage[
        ecu_coverage["Coverage State"].isin(["BELOW_TARGET", "UNKNOWN_INSTALLED"])
    ].copy()
    if "Release Gap" in legacy_candidates.columns:
        legacy_candidates = legacy_candidates.sort_values(
            ["Release Gap", "ECU"],
            ascending=[False, True],
            na_position="last",
        )

    unknown_releases = ecu_coverage[
        ecu_coverage["Coverage State"].isin(["UNKNOWN_INSTALLED", "UNKNOWN_TARGET"])
    ].copy()

    reference_coverage = pd.DataFrame()
    if reference is not None and not reference.empty:
        ref = reference.copy()
        ecu_col = "ECU Variant" if "ECU Variant" in ref.columns else "ECU"
        release_col = "SW Version" if "SW Version" in ref.columns else "Target Release"
        if ecu_col in ref.columns:
            reference_coverage = pd.DataFrame({
                "Reference ECU": ref[ecu_col].map(_text),
                "Reference Release": (
                    ref[release_col].map(_text)
                    if release_col in ref.columns else ""
                ),
            })
            installed_ecus = set(overview["ECU"].map(_text))
            reference_coverage["Present in Session"] = (
                reference_coverage["Reference ECU"].isin(installed_ecus)
            )
            reference_coverage["Coverage Status"] = reference_coverage[
                "Present in Session"
            ].map({True: "PRESENT", False: "MISSING_FROM_SESSION"})

    session_release_trend = pd.DataFrame()
    timeline = multi_session_result.get("ecu_timeline", pd.DataFrame())
    if timeline is not None and not timeline.empty:
        release_columns = [
            column for column in ("Installed Release", "Application SW", "Software Number")
            if column in timeline.columns
        ]
        if release_columns:
            release_source = release_columns[0]
            trend = timeline.copy()
            trend["Release Value"] = trend[release_source].map(_text).replace("", "UNKNOWN")
            session_release_trend = (
                trend.groupby(["Session File", "Session Date", "Release Value"], dropna=False)
                .size()
                .reset_index(name="ECU Count")
                .sort_values(["Session Date", "Session File", "ECU Count"], ascending=[True, True, False])
            )

    return {
        "summary": summary,
        "ecu_coverage": ecu_coverage,
        "installed_distribution": installed_distribution,
        "target_distribution": target_distribution,
        "coverage_by_target": coverage_by_target,
        "legacy_candidates": legacy_candidates,
        "unknown_releases": unknown_releases,
        "reference_coverage": reference_coverage,
        "session_release_trend": session_release_trend,
    }
