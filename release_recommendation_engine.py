from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from update_impact_engine import release_family


DEFAULT_RULES_PATH = Path(__file__).with_name("release_recommendation_rules.json")


def load_release_recommendation_rules(path: str | Path | None = None) -> dict[str, Any]:
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


def historical_release_performance(
    workspace_timeseries: pd.DataFrame,
    transitions: pd.DataFrame,
) -> pd.DataFrame:
    if workspace_timeseries is None or workspace_timeseries.empty:
        return pd.DataFrame()

    transition_lookup = {}
    if transitions is not None and not transitions.empty:
        transition_lookup = {
            str(row.get("Current Session", "")): row
            for _, row in transitions.iterrows()
        }

    rows = []
    for release, group in workspace_timeseries.groupby("Selected Release", dropna=False):
        classifications = []
        for session_id in group["Session ID"].astype(str):
            transition = transition_lookup.get(session_id)
            if transition is not None:
                classifications.append(str(transition.get("Transition Classification", "")))

        improvements = sum(item in {"IMPROVEMENT", "STRONG_IMPROVEMENT"} for item in classifications)
        regressions = sum(item in {"REGRESSION", "CRITICAL_REGRESSION"} for item in classifications)
        evaluated = improvements + regressions
        success_rate = improvements / evaluated * 100 if evaluated else 50.0

        rows.append({
            "Release": release,
            "Release Family": release_family(release),
            "Historical Samples": len(group),
            "Evaluated Transitions": evaluated,
            "Improvements": improvements,
            "Regressions": regressions,
            "Historical Success Rate": round(success_rate, 1),
            "Average Vehicle Health": round(
                pd.to_numeric(group["Vehicle Health"], errors="coerce").mean(), 1
            ),
            "Average Risk": round(
                pd.to_numeric(group["Average Risk"], errors="coerce").mean(), 1
            ),
            "Average Release Consistency": round(
                pd.to_numeric(group["Release Consistency"], errors="coerce").mean(), 1
            ),
        })
    return pd.DataFrame(rows).sort_values(
        ["Historical Success Rate", "Average Vehicle Health"],
        ascending=[False, False],
    ).reset_index(drop=True)


def recommend_release(
    scenario_comparison: pd.DataFrame,
    vehicle_health: pd.DataFrame,
    release_consistency: pd.DataFrame,
    warranty_summary: pd.DataFrame,
    assistant_summary: pd.DataFrame,
    overview: pd.DataFrame,
    historical_performance: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rules = dict(rules or load_release_recommendation_rules())
    if scenario_comparison is None or scenario_comparison.empty:
        return pd.DataFrame(), pd.DataFrame()

    weights = rules["weights"]
    penalties_cfg = rules["penalties"]

    health = _num(
        vehicle_health.iloc[0].get("Vehicle Health Score", 0)
        if vehicle_health is not None and not vehicle_health.empty else 0
    )
    consistency = _num(
        release_consistency.iloc[0].get("Release Consistency Score", 0)
        if release_consistency is not None and not release_consistency.empty else 0
    )
    mixed = bool(
        release_consistency.iloc[0].get("Mixed Package Detected", False)
        if release_consistency is not None and not release_consistency.empty else False
    )
    warranty = str(
        warranty_summary.iloc[0].get("Warranty Recommendation", "")
        if warranty_summary is not None and not warranty_summary.empty else ""
    )
    assistant_status = str(
        assistant_summary.iloc[0].get("Executive Vehicle Status", "")
        if assistant_summary is not None and not assistant_summary.empty else ""
    )
    persistent_dtcs = int(
        pd.to_numeric(
            overview.get("Persistent DTC Count", pd.Series(dtype=float)),
            errors="coerce",
        ).fillna(0).sum()
    ) if overview is not None and not overview.empty else 0

    history_lookup = {
        str(row["Release"]): row
        for _, row in historical_performance.iterrows()
    } if historical_performance is not None and not historical_performance.empty else {}

    rows = []
    for _, scenario in scenario_comparison.iterrows():
        target = str(scenario.get("Candidate Target Release", ""))
        history = history_lookup.get(target, {})
        historical_success = _num(
            history.get("Historical Success Rate", 50)
            if hasattr(history, "get") else 50
        )
        samples = int(
            _num(history.get("Historical Samples", 0) if hasattr(history, "get") else 0)
        )
        companion_updates = int(_num(scenario.get("Required Companion Updates", 0)))
        high_risk_ecus = int(_num(scenario.get("High-Risk ECUs", 0)))

        score = (
            weights["scenario_score"] * _num(scenario.get("Scenario Score", 0))
            + weights["compatibility_score"] * _num(scenario.get("Overall Compatibility Score", 0))
            + weights["path_score"] * _num(scenario.get("Path Score", 0))
            + weights["vehicle_health"] * health
            + weights["release_consistency"] * consistency
            + weights["historical_success"] * historical_success
            + weights["companion_burden"] * max(0, 100 - companion_updates * 15)
            + weights["high_risk_burden"] * max(0, 100 - high_risk_ecus * 25)
        )

        penalty = 0.0
        evidence = []
        if mixed:
            penalty += penalties_cfg["mixed_package"]
            evidence.append("Mixed software package is currently detected")
        if persistent_dtcs > 0:
            penalty += penalties_cfg["persistent_dtc"]
            evidence.append(f"{persistent_dtcs} persistent DTC(s) are present")
        if warranty == "ENGINEERING_ESCALATION":
            penalty += penalties_cfg["engineering_escalation"]
            evidence.append("Warranty triage requires engineering escalation")
        if assistant_status == "CRITICAL":
            penalty += penalties_cfg["critical_vehicle_status"]
            evidence.append("Executive vehicle status is CRITICAL")
        if not target:
            penalty += penalties_cfg["unknown_release"]
            evidence.append("Candidate release is missing")
        current_family = release_family(scenario.get("Current Release", ""))
        target_family = release_family(target)
        if current_family and target_family and current_family.split(".")[0] != target_family.split(".")[0]:
            penalty += penalties_cfg["cross_model_year"]
            evidence.append("Candidate crosses model-year release family")
        if samples < rules["thresholds"]["minimum_history_samples"]:
            evidence.append("Historical evidence is limited")

        final_score = max(0.0, min(100.0, score - penalty))
        if final_score >= rules["thresholds"]["recommended"]:
            decision = "RECOMMENDED"
        elif final_score >= rules["thresholds"]["recommended_with_conditions"]:
            decision = "RECOMMENDED_WITH_CONDITIONS"
        else:
            decision = "ENGINEERING_REVIEW_REQUIRED"

        rows.append({
            "Source File": scenario.get("Source File", ""),
            "VIN": scenario.get("VIN", ""),
            "Selected ECU": scenario.get("Selected ECU", ""),
            "Current Release": scenario.get("Current Release", ""),
            "Candidate Target Release": target,
            "Release Path": scenario.get("Release Path", ""),
            "Path Type": scenario.get("Path Type", ""),
            "Scenario Score": scenario.get("Scenario Score", 0),
            "Compatibility Score": scenario.get("Overall Compatibility Score", 0),
            "Path Score": scenario.get("Path Score", 0),
            "Historical Samples": samples,
            "Historical Success Rate": historical_success,
            "Required Companion Updates": companion_updates,
            "High-Risk ECUs": high_risk_ecus,
            "Recommendation Score": round(final_score, 1),
            "Recommendation Decision": decision,
            "Recommendation Evidence": " | ".join(evidence) if evidence else "No additional penalty evidence",
        })

    ranking = pd.DataFrame(rows).sort_values(
        ["Recommendation Score", "Compatibility Score", "Historical Success Rate"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    ranking["Recommendation Rank"] = range(1, len(ranking) + 1)
    ranking["Recommended Release"] = ranking["Recommendation Rank"].eq(1)

    lead = ranking.iloc[0]
    summary = pd.DataFrame([{
        "Source File": lead.get("Source File", ""),
        "VIN": lead.get("VIN", ""),
        "Selected ECU": lead.get("Selected ECU", ""),
        "Current Release": lead.get("Current Release", ""),
        "Recommended Target Release": lead.get("Candidate Target Release", ""),
        "Recommended Release Path": lead.get("Release Path", ""),
        "Recommendation Score": lead.get("Recommendation Score", 0),
        "Recommendation Decision": lead.get("Recommendation Decision", ""),
        "Required Companion Updates": lead.get("Required Companion Updates", 0),
        "High-Risk ECUs": lead.get("High-Risk ECUs", 0),
        "Historical Success Rate": lead.get("Historical Success Rate", 0),
        "Recommendation Evidence": lead.get("Recommendation Evidence", ""),
        "Disclaimer": rules["disclaimer"],
    }])
    return summary, ranking


def build_update_plan(
    recommendation_summary: pd.DataFrame,
    scenario_sequences: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_release_recommendation_rules())
    if recommendation_summary is None or recommendation_summary.empty:
        return pd.DataFrame()

    summary = recommendation_summary.iloc[0]
    target = str(summary.get("Recommended Target Release", ""))
    selected_sequence = (
        scenario_sequences[
            scenario_sequences["Scenario Target Release"].astype(str) == target
        ].copy()
        if scenario_sequences is not None and not scenario_sequences.empty
        else pd.DataFrame()
    )

    rows = [
        {
            "Phase Order": 1,
            "Phase": "PRE_CHECK",
            "ECU": summary.get("Selected ECU", ""),
            "Action": "Confirm battery support, diagnostic communication and current vehicle configuration.",
            "Verification": "Stable voltage, complete vehicle scan and saved pre-programming report.",
        },
        {
            "Phase Order": 2,
            "Phase": "PACKAGE_CONFIRMATION",
            "ECU": summary.get("Selected ECU", ""),
            "Action": f"Confirm the approved software package and release path for {target}.",
            "Verification": "OEM release approval and programming instructions are available.",
        },
    ]

    if not selected_sequence.empty:
        for _, step in selected_sequence.sort_values("Update Step").iterrows():
            rows.append({
                "Phase Order": 2 + int(step.get("Update Step", 0)),
                "Phase": "PROGRAMMING",
                "ECU": step.get("Affected ECU", ""),
                "Action": step.get("Sequence Action", ""),
                "Verification": "Programming completed without error; ECU communication restored.",
            })
        next_order = max(row["Phase Order"] for row in rows) + 1
    else:
        next_order = 3
        rows.append({
            "Phase Order": next_order,
            "Phase": "PROGRAMMING",
            "ECU": summary.get("Selected ECU", ""),
            "Action": f"Program the selected ECU using the approved package for {target}.",
            "Verification": "Programming completed without error.",
        })
        next_order += 1

    rows.extend([
        {
            "Phase Order": next_order,
            "Phase": "POST_PROGRAMMING_VALIDATION",
            "ECU": "VEHICLE",
            "Action": "Clear DTCs, cycle ignition, repeat Grade-X readout and compare against the approved reference.",
            "Verification": "No new persistent DTC, compliant release package and restored network health.",
        },
        {
            "Phase Order": next_order + 1,
            "Phase": "ENGINEERING_SIGN_OFF",
            "ECU": "VEHICLE",
            "Action": "Review residual deviations and close or escalate the engineering case.",
            "Verification": "Report approved and decision documented.",
        },
    ])

    result = pd.DataFrame(rows)
    result.insert(0, "VIN", summary.get("VIN", ""))
    result.insert(0, "Source File", summary.get("Source File", ""))
    result["Recommended Target Release"] = target
    result["Recommendation Decision"] = summary.get("Recommendation Decision", "")
    return result
