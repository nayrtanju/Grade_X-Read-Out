from __future__ import annotations

from typing import Any

import pandas as pd

from compliance import validate


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


def _first_text(frame: pd.DataFrame, column: str) -> str:
    if frame is None or frame.empty or column not in frame.columns:
        return ""
    values = frame[column].dropna().astype(str).str.strip()
    values = values[values.ne("")]
    return values.iloc[0] if not values.empty else ""


def analyze_vehicle(
    session_name: str,
    session_frame: pd.DataFrame,
    target_reference: pd.DataFrame,
    release_catalog: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    summary = session_frame.copy()
    overview, details, candidates = validate(
        summary,
        target_reference,
        release_catalog,
    )

    if overview.empty:
        vehicle_summary = pd.DataFrame([{
            "Session File": session_name,
            "VIN": _first_text(summary, "VIN"),
            "ECU Count": int(summary.get("ECU ID", pd.Series(dtype=str)).nunique()),
            "Compliant ECUs": 0,
            "Compliance Rate %": 0.0,
            "Mismatch ECUs": 0,
            "Wrong Release ECUs": 0,
            "Missing / No Reference ECUs": 0,
            "Critical ECU Deviations": 0,
            "Persistent DTC Count": int(
                pd.to_numeric(
                    summary.get("DTC Count", pd.Series(dtype=float)),
                    errors="coerce",
                ).fillna(0).sum()
            ),
            "Unique Installed Releases": 0,
            "Unique Target Releases": 0,
            "Mixed Release Package": False,
            "Vehicle Quality Score": 0.0,
            "Vehicle Decision": "NOT_READY",
        }])
        return {
            "summary": vehicle_summary,
            "overview": overview,
            "details": details,
            "candidates": candidates,
        }

    statuses = overview["Status"].astype(str)
    total = len(overview)
    compliant = int(statuses.eq("COMPLIANT").sum())
    mismatch = int(statuses.eq("MISMATCH").sum())
    wrong_release = int(statuses.eq("WRONG_RELEASE").sum())
    missing = int(statuses.isin(["MISSING", "NO_REFERENCE"]).sum())
    compliance_rate = compliant / total * 100 if total else 0.0

    mismatch_fields = 0
    critical_field_deviations = 0
    if not details.empty:
        bad = details["Status"].astype(str).isin(["MISMATCH", "MISSING"])
        mismatch_fields = int(bad.sum())
        critical_mask = details["Field"].astype(str).isin([
            "Hardware Number",
            "Application SW",
            "Bootloader",
        ])
        critical_field_deviations = int((bad & critical_mask).sum())

    persistent_dtcs = int(
        pd.to_numeric(
            summary.get("DTC Count", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0).sum()
    )

    installed_releases = (
        overview["Installed Release"].dropna().astype(str).str.strip()
        if "Installed Release" in overview.columns else pd.Series(dtype=str)
    )
    installed_releases = installed_releases[installed_releases.ne("")]
    target_releases = (
        overview["Target Release"].dropna().astype(str).str.strip()
        if "Target Release" in overview.columns else pd.Series(dtype=str)
    )
    target_releases = target_releases[target_releases.ne("")]

    unique_installed = installed_releases.nunique()
    unique_target = target_releases.nunique()
    mixed_package = unique_installed > 1

    quality_score = (
        compliance_rate * 0.65
        + max(0.0, 100.0 - mismatch_fields * 4) * 0.15
        + max(0.0, 100.0 - persistent_dtcs * 10) * 0.10
        + (100.0 if not mixed_package else 50.0) * 0.10
    )
    if critical_field_deviations:
        quality_score -= min(25.0, critical_field_deviations * 5)
    quality_score = max(0.0, min(100.0, quality_score))

    decision = (
        "PASS"
        if quality_score >= 90 and wrong_release == 0 and critical_field_deviations == 0
        else "CONDITIONAL"
        if quality_score >= 70 and critical_field_deviations == 0
        else "FAIL"
    )

    vehicle_summary = pd.DataFrame([{
        "Session File": session_name,
        "VIN": _first_text(summary, "VIN"),
        "ECU Count": total,
        "Compliant ECUs": compliant,
        "Compliance Rate %": round(compliance_rate, 1),
        "Mismatch ECUs": mismatch,
        "Wrong Release ECUs": wrong_release,
        "Missing / No Reference ECUs": missing,
        "Critical ECU Deviations": critical_field_deviations,
        "Persistent DTC Count": persistent_dtcs,
        "Unique Installed Releases": unique_installed,
        "Unique Target Releases": unique_target,
        "Mixed Release Package": mixed_package,
        "Vehicle Quality Score": round(quality_score, 1),
        "Vehicle Decision": decision,
    }])

    return {
        "summary": vehicle_summary,
        "overview": overview,
        "details": details,
        "candidates": candidates,
    }


def build_fleet_snapshot(
    session_frames: list[tuple[str, pd.DataFrame]],
    target_reference: pd.DataFrame,
    release_catalog: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    vehicle_summaries = []
    overview_frames = []
    detail_frames = []
    candidate_frames = []

    for session_name, frame in session_frames:
        result = analyze_vehicle(
            session_name,
            frame,
            target_reference,
            release_catalog,
        )
        vehicle_summaries.append(result["summary"])

        for key, target in (
            ("overview", overview_frames),
            ("details", detail_frames),
            ("candidates", candidate_frames),
        ):
            data = result[key].copy()
            if not data.empty:
                data.insert(0, "Vehicle Session", session_name)
                target.append(data)

    vehicles = (
        pd.concat(vehicle_summaries, ignore_index=True)
        if vehicle_summaries else pd.DataFrame()
    )
    overview = (
        pd.concat(overview_frames, ignore_index=True)
        if overview_frames else pd.DataFrame()
    )
    details = (
        pd.concat(detail_frames, ignore_index=True)
        if detail_frames else pd.DataFrame()
    )
    candidates = (
        pd.concat(candidate_frames, ignore_index=True)
        if candidate_frames else pd.DataFrame()
    )

    if vehicles.empty:
        empty = pd.DataFrame()
        return {
            "fleet_summary": empty,
            "vehicle_summary": empty,
            "ecu_overview": empty,
            "field_details": empty,
            "candidate_details": empty,
            "status_distribution": empty,
            "top_failing_ecus": empty,
            "release_distribution": empty,
            "vehicle_ranking": empty,
        }

    total_vehicles = len(vehicles)
    pass_count = int(vehicles["Vehicle Decision"].eq("PASS").sum())
    conditional_count = int(vehicles["Vehicle Decision"].eq("CONDITIONAL").sum())
    fail_count = int(vehicles["Vehicle Decision"].eq("FAIL").sum())
    average_compliance = _num(vehicles["Compliance Rate %"].mean())
    average_quality = _num(vehicles["Vehicle Quality Score"].mean())
    mixed_count = int(vehicles["Mixed Release Package"].fillna(False).sum())
    persistent_dtcs = int(
        pd.to_numeric(vehicles["Persistent DTC Count"], errors="coerce")
        .fillna(0).sum()
    )

    fleet_decision = (
        "PASS"
        if fail_count == 0 and conditional_count == 0 and average_quality >= 90
        else "CONDITIONAL"
        if fail_count == 0 and average_quality >= 70
        else "FAIL"
    )

    fleet_summary = pd.DataFrame([{
        "Vehicles Analysed": total_vehicles,
        "Passed Vehicles": pass_count,
        "Conditional Vehicles": conditional_count,
        "Failed Vehicles": fail_count,
        "Average Compliance %": round(average_compliance, 1),
        "Average Vehicle Quality": round(average_quality, 1),
        "Mixed-Package Vehicles": mixed_count,
        "Persistent DTCs": persistent_dtcs,
        "Fleet Decision": fleet_decision,
    }])

    status_distribution = (
        overview["Status"].astype(str)
        .value_counts()
        .rename_axis("ECU Status")
        .reset_index(name="Count")
        if not overview.empty else pd.DataFrame()
    )

    top_failing = pd.DataFrame()
    if not overview.empty:
        failing = overview[
            ~overview["Status"].astype(str).eq("COMPLIANT")
        ].copy()
        if not failing.empty:
            failing["Failure Priority"] = failing["Status"].map({
                "WRONG_RELEASE": 1,
                "MISMATCH": 2,
                "MISSING": 3,
                "NO_REFERENCE": 4,
            }).fillna(5)
            top_failing = failing.sort_values(
                ["Failure Priority", "Vehicle Session", "ECU"]
            ).drop(columns=["Failure Priority"]).head(100).reset_index(drop=True)

    release_distribution = pd.DataFrame()
    if not overview.empty and "Installed Release" in overview.columns:
        release_distribution = (
            overview["Installed Release"].astype(str).str.strip()
            .replace("", "UNKNOWN")
            .value_counts()
            .rename_axis("Installed Release")
            .reset_index(name="ECU Count")
        )

    ranking = vehicles.sort_values(
        ["Vehicle Quality Score", "Compliance Rate %", "Wrong Release ECUs"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    ranking.insert(0, "Fleet Rank", range(1, len(ranking) + 1))

    return {
        "fleet_summary": fleet_summary,
        "vehicle_summary": vehicles,
        "ecu_overview": overview,
        "field_details": details,
        "candidate_details": candidates,
        "status_distribution": status_distribution,
        "top_failing_ecus": top_failing,
        "release_distribution": release_distribution,
        "vehicle_ranking": ranking,
    }
