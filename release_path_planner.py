from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from update_impact_engine import (
    release_family,
    release_numeric,
    simulate_update_impact,
    simulation_summary,
)


DEFAULT_RULES_PATH = Path(__file__).with_name("release_path_rules.json")


def load_release_path_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    with rules_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def _release_sort_key(value: str) -> tuple[float, str]:
    numeric = release_numeric(value)
    return (numeric if numeric is not None else 9999.0, value)


def ordered_releases(values: Iterable[Any]) -> list[str]:
    releases = {
        str(value).strip()
        for value in values
        if str(value or "").strip()
    }
    return sorted(releases, key=_release_sort_key)


def available_release_catalog(
    nodes: pd.DataFrame,
    source_file: str,
    selected_ecu: str,
) -> list[str]:
    if nodes is None or nodes.empty:
        return []
    scoped = nodes[nodes["Source File"].astype(str) == str(source_file)]
    selected = scoped[scoped["ECU"].astype(str) == str(selected_ecu)]
    values: list[Any] = []
    for column in ("Installed Release", "Target Release"):
        if column in scoped.columns:
            values.extend(scoped[column].dropna().tolist())
        if not selected.empty and column in selected.columns:
            values.append(selected.iloc[0].get(column, ""))
    return ordered_releases(values)


def derive_release_path(
    current_release: str,
    target_release: str,
    catalog: list[str],
    overall_compatibility_score: float,
    mixed_package: bool,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rules = dict(rules or load_release_path_rules())
    current_num = release_numeric(current_release)
    target_num = release_numeric(target_release)
    current_family = release_family(current_release)
    target_family = release_family(target_release)

    evidence: list[str] = []
    penalty = 0.0
    path: list[str] = [current_release] if current_release else []

    if not target_release:
        return {
            "Path Type": "ENGINEERING_REVIEW",
            "Path": current_release or "UNKNOWN",
            "Path Score": 0.0,
            "Intermediate Release": "",
            "Evidence": "Target release is missing",
            "Recommendation": rules["recommendations"]["ENGINEERING_REVIEW"],
        }

    if current_release == target_release:
        path = [current_release]
        evidence.append("Current and target releases are identical")
        path_type = "DIRECT"
    elif current_num is None or target_num is None:
        path.extend([target_release])
        penalty += rules["path_penalties"]["missing_intermediate_release"]
        evidence.append("Release numbering could not be resolved")
        path_type = "ENGINEERING_REVIEW"
    else:
        gap = round(target_num - current_num, 2)
        intermediate_candidates = [
            release
            for release in catalog
            if release_numeric(release) is not None
            and current_num < release_numeric(release) < target_num
        ]
        if gap <= rules["path_thresholds"]["direct_minor_gap_max"]:
            path.append(target_release)
            path_type = "DIRECT"
            evidence.append(f"Minor release gap: {gap:+.1f}")
        elif intermediate_candidates:
            intermediate = intermediate_candidates[-1]
            path.extend([intermediate, target_release])
            path_type = "STAGED"
            evidence.append(f"Intermediate release available: {intermediate}")
        elif gap <= rules["path_thresholds"]["direct_major_gap_max"]:
            path.append(target_release)
            path_type = "DIRECT"
            evidence.append(f"Direct path inferred for release gap {gap:+.1f}")
        else:
            path.append(target_release)
            path_type = "ENGINEERING_REVIEW"
            penalty += rules["path_penalties"]["major_year_jump"]
            evidence.append(f"Large release gap without approved intermediate path: {gap:+.1f}")

    if current_family and target_family and current_family.split(".")[0] != target_family.split(".")[0]:
        penalty += rules["path_penalties"]["major_year_jump"]
        evidence.append(f"Model-year family changes from {current_family} to {target_family}")
        path_type = "ENGINEERING_REVIEW"

    if mixed_package:
        penalty += rules["path_penalties"]["mixed_package"]
        evidence.append("Mixed-package condition is active")

    if overall_compatibility_score < rules["path_thresholds"]["conditional_score"]:
        penalty += rules["path_penalties"]["high_risk_scenario"]
        evidence.append("Scenario compatibility is below the conditional threshold")
        path_type = "ENGINEERING_REVIEW"

    path_score = max(0.0, min(100.0, overall_compatibility_score - penalty))
    if path_type == "DIRECT" and path_score < rules["path_thresholds"]["safe_score"]:
        path_type = "ENGINEERING_REVIEW"
    elif path_type == "STAGED" and path_score < rules["path_thresholds"]["conditional_score"]:
        path_type = "ENGINEERING_REVIEW"

    intermediate_release = path[1] if len(path) == 3 else ""
    return {
        "Path Type": path_type,
        "Path": " → ".join([item for item in path if item]),
        "Path Score": round(path_score, 1),
        "Intermediate Release": intermediate_release,
        "Evidence": " | ".join(evidence) if evidence else "No path issue detected",
        "Recommendation": rules["recommendations"][path_type],
    }


def compare_update_scenarios(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    source_file: str,
    selected_ecu: str,
    candidate_releases: list[str],
    release_consistency: pd.DataFrame | None = None,
    update_rules: Mapping[str, Any] | None = None,
    path_rules: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    path_rules = dict(path_rules or load_release_path_rules())
    scoped = nodes[
        (nodes["Source File"].astype(str) == str(source_file))
        & (nodes["ECU"].astype(str) == str(selected_ecu))
    ]
    if scoped.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    selected = scoped.iloc[0]
    current_release = str(selected.get("Installed Release", "") or "")
    mixed_package = False
    if release_consistency is not None and not release_consistency.empty:
        match = release_consistency[
            release_consistency["Source File"].astype(str) == str(source_file)
        ]
        if not match.empty:
            mixed_package = bool(match.iloc[0].get("Mixed Package Detected", False))

    catalog = available_release_catalog(nodes, source_file, selected_ecu)
    scenario_rows = []
    impact_frames = []
    companion_frames = []
    sequence_frames = []

    weights = path_rules["scenario_weights"]

    for target_release in ordered_releases(candidate_releases):
        impact, companions, sequence = simulate_update_impact(
            nodes,
            edges,
            source_file,
            selected_ecu,
            target_release,
            release_consistency=release_consistency,
            rules=update_rules,
        )
        summary = simulation_summary(
            impact,
            companions,
            sequence,
            rules=update_rules,
        )
        if summary.empty:
            continue

        summary_row = summary.iloc[0]
        compatibility = _num(summary_row.get("Overall Compatibility Score", 0))
        required_updates = int(_num(summary_row.get("Required Companion Updates", 0)))
        high_risk = int(_num(summary_row.get("High-Risk ECUs", 0)))
        sequence_length = int(_num(summary_row.get("Recommended Update Steps", 0)))
        current_num = release_numeric(current_release)
        target_num = release_numeric(target_release)
        gap = abs(target_num - current_num) if current_num is not None and target_num is not None else 0.0

        path = derive_release_path(
            current_release,
            target_release,
            catalog,
            compatibility,
            mixed_package,
            rules=path_rules,
        )

        scenario_score = (
            weights["compatibility"] * compatibility
            + weights["required_updates"] * max(0, 100 - required_updates * 15)
            + weights["high_risk_ecus"] * max(0, 100 - high_risk * 25)
            + weights["sequence_length"] * max(0, 100 - sequence_length * 8)
            + weights["release_gap"] * max(0, 100 - gap * 40)
        )
        scenario_score = min(scenario_score, path["Path Score"])

        scenario_rows.append({
            "Source File": source_file,
            "VIN": selected.get("VIN", ""),
            "Selected ECU": selected_ecu,
            "Current Release": current_release,
            "Candidate Target Release": target_release,
            "Overall Compatibility Score": compatibility,
            "Compatibility Level": summary_row.get("Overall Compatibility Level", ""),
            "Affected ECUs": int(_num(summary_row.get("Affected ECUs", 0))),
            "Required Companion Updates": required_updates,
            "High-Risk ECUs": high_risk,
            "Update Steps": sequence_length,
            "Path Type": path["Path Type"],
            "Release Path": path["Path"],
            "Intermediate Release": path["Intermediate Release"],
            "Path Score": path["Path Score"],
            "Scenario Score": round(scenario_score, 1),
            "Path Evidence": path["Evidence"],
            "Recommendation": path["Recommendation"],
        })

        if not impact.empty:
            frame = impact.copy()
            frame["Scenario Target Release"] = target_release
            impact_frames.append(frame)
        if not companions.empty:
            frame = companions.copy()
            frame["Scenario Target Release"] = target_release
            companion_frames.append(frame)
        if not sequence.empty:
            frame = sequence.copy()
            frame["Scenario Target Release"] = target_release
            sequence_frames.append(frame)

    scenarios = pd.DataFrame(scenario_rows)
    if not scenarios.empty:
        scenarios = scenarios.sort_values(
            ["Scenario Score", "Overall Compatibility Score", "Required Companion Updates"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
        scenarios["Scenario Rank"] = range(1, len(scenarios) + 1)
        scenarios["Recommended Scenario"] = scenarios["Scenario Rank"].eq(1)

    return (
        scenarios,
        pd.concat(impact_frames, ignore_index=True) if impact_frames else pd.DataFrame(),
        pd.concat(companion_frames, ignore_index=True) if companion_frames else pd.DataFrame(),
        pd.concat(sequence_frames, ignore_index=True) if sequence_frames else pd.DataFrame(),
    )


def build_network_timeline(
    workspace_timeseries: pd.DataFrame,
    timeseries_transitions: pd.DataFrame,
    network_nodes: pd.DataFrame,
) -> pd.DataFrame:
    if workspace_timeseries is None or workspace_timeseries.empty:
        return pd.DataFrame()

    criticality_lookup: dict[str, dict[str, Any]] = {}
    if network_nodes is not None and not network_nodes.empty:
        for _, row in network_nodes.iterrows():
            criticality_lookup[str(row.get("ECU", ""))] = {
                "Role": row.get("Role", ""),
                "Criticality": row.get("Criticality", ""),
                "Criticality Score": row.get("Criticality Score", 0),
            }

    transition_lookup = {}
    if timeseries_transitions is not None and not timeseries_transitions.empty:
        transition_lookup = {
            str(row.get("Current Session", "")): row
            for _, row in timeseries_transitions.iterrows()
        }

    rows = []
    for _, session in workspace_timeseries.sort_values(
        ["VIN", "Analysis Date", "Session ID"]
    ).iterrows():
        session_id = str(session.get("Session ID", ""))
        transition = transition_lookup.get(session_id)
        root_ecu = str(session.get("Root ECU", "") or "")
        root_info = criticality_lookup.get(root_ecu, {})
        event_types = ["ANALYSIS"]
        event_details = ["Saved analysis"]

        if transition is not None:
            classification = str(transition.get("Transition Classification", ""))
            event_types.append(classification)
            event_details.append(str(transition.get("Transition Evidence", "")))
            if bool(transition.get("Selected Release Changed", False)):
                event_types.append("RELEASE_CHANGE")
                event_details.append(
                    f"{transition.get('Selected Release Previous', '')} → "
                    f"{transition.get('Selected Release Current', '')}"
                )
            if bool(transition.get("Root ECU Changed", False)):
                event_types.append("ROOT_ECU_CHANGE")
                event_details.append(
                    f"{transition.get('Root ECU Previous', '')} → "
                    f"{transition.get('Root ECU Current', '')}"
                )

        rows.append({
            "VIN": session.get("VIN", ""),
            "Date": session.get("Analysis Date"),
            "Session ID": session_id,
            "Project": session.get("Project", ""),
            "Selected Release": session.get("Selected Release", ""),
            "Vehicle Health": session.get("Vehicle Health", 0),
            "Average Risk": session.get("Average Risk", 0),
            "Release Consistency": session.get("Release Consistency", 0),
            "Root ECU": root_ecu,
            "Root ECU Role": root_info.get("Role", ""),
            "Root ECU Criticality": root_info.get("Criticality", ""),
            "Root ECU Criticality Score": root_info.get("Criticality Score", 0),
            "Network Event Types": " | ".join(event_types),
            "Network Event Details": " | ".join(event_details),
        })
    return pd.DataFrame(rows)


def release_path_summary(scenarios: pd.DataFrame) -> pd.DataFrame:
    if scenarios is None or scenarios.empty:
        return pd.DataFrame()
    recommended = scenarios.sort_values("Scenario Rank").iloc[0]
    return pd.DataFrame([{
        "Source File": recommended.get("Source File", ""),
        "VIN": recommended.get("VIN", ""),
        "Selected ECU": recommended.get("Selected ECU", ""),
        "Current Release": recommended.get("Current Release", ""),
        "Recommended Target Release": recommended.get("Candidate Target Release", ""),
        "Recommended Release Path": recommended.get("Release Path", ""),
        "Path Type": recommended.get("Path Type", ""),
        "Path Score": recommended.get("Path Score", 0),
        "Scenario Score": recommended.get("Scenario Score", 0),
        "Required Companion Updates": recommended.get("Required Companion Updates", 0),
        "High-Risk ECUs": recommended.get("High-Risk ECUs", 0),
        "Update Steps": recommended.get("Update Steps", 0),
        "Recommendation": recommended.get("Recommendation", ""),
        "Path Evidence": recommended.get("Path Evidence", ""),
    }])
