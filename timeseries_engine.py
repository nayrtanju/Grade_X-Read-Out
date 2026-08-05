from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("timeseries_rules.json")


def load_timeseries_rules(path: str | Path | None = None) -> dict[str, Any]:
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


def _dt(value: Any) -> pd.Timestamp:
    if value in (None, ""):
        return pd.NaT
    try:
        return pd.to_datetime(value, utc=True)
    except Exception:
        return pd.NaT


def build_workspace_timeseries(
    sessions: list[dict[str, Any]],
    projects: list[dict[str, Any]] | None = None,
    vehicles: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    projects = projects or []
    vehicles = vehicles or []
    project_lookup = {item.get("id"): item.get("name", "") for item in projects}
    vehicle_lookup = {item.get("id"): item for item in vehicles}

    rows: list[dict[str, Any]] = []
    for session in sessions:
        metadata = session.get("metadata", {}) or {}
        vehicle = vehicle_lookup.get(session.get("vehicle_id"), {})
        rows.append({
            "Project ID": session.get("project_id", ""),
            "Project": project_lookup.get(session.get("project_id"), ""),
            "Vehicle ID": session.get("vehicle_id", ""),
            "Vehicle Name": vehicle.get("display_name", ""),
            "VIN": session.get("vin", ""),
            "Session ID": session.get("id", ""),
            "Analysis Date": _dt(session.get("analysis_date")),
            "Selected Release": session.get("selected_release", ""),
            "Reference File": session.get("reference_file", ""),
            "Engineer": session.get("engineer", ""),
            "Session Notes": session.get("notes", ""),
            "ECU Count": int(_num(metadata.get("ecu_count", 0))),
            "Compliance Rate": _num(metadata.get("compliance_rate", 0)),
            "Average Risk": _num(metadata.get("average_risk", 0)),
            "Vehicle Health": _num(metadata.get("vehicle_health", 0)),
            "Release Consistency": _num(metadata.get("release_consistency", 0)),
            "Warranty Recommendation": metadata.get("warranty_recommendation", ""),
            "Root ECU": metadata.get("root_ecu", ""),
            "Root Cause Confidence": _num(metadata.get("root_cause_confidence", 0)),
            "Assistant Status": metadata.get("assistant_status", ""),
            "Open Findings": int(_num(metadata.get("open_findings", 0))),
            "Persistent DTCs": int(_num(metadata.get("persistent_dtcs", 0))),
            "Mixed Package": bool(metadata.get("mixed_package", False)),
        })

    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows)
    return frame.sort_values(
        ["VIN", "Analysis Date", "Session ID"]
    ).reset_index(drop=True)


def _delta_score(previous: pd.Series, current: pd.Series, rules: Mapping[str, Any]) -> tuple[float, list[str]]:
    weights = rules["weights"]
    reasons: list[str] = []
    score = 0.0

    health_delta = _num(current["Vehicle Health"]) - _num(previous["Vehicle Health"])
    score += weights["vehicle_health"] * health_delta
    if abs(health_delta) >= rules["thresholds"]["significant_health_change"]:
        reasons.append(f"Vehicle Health changed by {health_delta:+.1f}")

    compliance_delta = _num(current["Compliance Rate"]) - _num(previous["Compliance Rate"])
    score += weights["compliance_rate"] * compliance_delta
    if abs(compliance_delta) >= rules["thresholds"]["significant_compliance_change"]:
        reasons.append(f"Compliance changed by {compliance_delta:+.1f} percentage points")

    consistency_delta = _num(current["Release Consistency"]) - _num(previous["Release Consistency"])
    score += weights["release_consistency"] * consistency_delta
    if abs(consistency_delta) >= rules["thresholds"]["significant_consistency_change"]:
        reasons.append(f"Release Consistency changed by {consistency_delta:+.1f}")

    risk_delta = _num(current["Average Risk"]) - _num(previous["Average Risk"])
    score += weights["average_risk"] * (-risk_delta)
    if abs(risk_delta) >= rules["thresholds"]["significant_risk_change"]:
        reasons.append(f"Average Risk changed by {risk_delta:+.1f}")

    findings_delta = _num(current["Open Findings"]) - _num(previous["Open Findings"])
    score += weights["open_findings"] * (-10.0 * findings_delta)
    if findings_delta != 0:
        reasons.append(f"Open Findings changed by {int(findings_delta):+d}")

    dtc_delta = _num(current["Persistent DTCs"]) - _num(previous["Persistent DTCs"])
    score += weights["persistent_dtcs"] * (-10.0 * dtc_delta)
    if dtc_delta != 0:
        reasons.append(f"Persistent DTCs changed by {int(dtc_delta):+d}")

    return round(score, 1), reasons


def classify_transition(score: float, rules: Mapping[str, Any]) -> str:
    thresholds = rules["thresholds"]
    if score <= thresholds["critical_regression_score"]:
        return "CRITICAL_REGRESSION"
    if score < 0:
        return "REGRESSION"
    if score >= thresholds["strong_improvement_score"]:
        return "STRONG_IMPROVEMENT"
    if score > 0:
        return "IMPROVEMENT"
    return "STABLE"


def build_transition_log(
    timeseries: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_timeseries_rules())
    if timeseries is None or timeseries.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for vin, group in timeseries.groupby("VIN", dropna=False):
        group = group.sort_values(["Analysis Date", "Session ID"]).reset_index(drop=True)
        for index in range(1, len(group)):
            previous = group.iloc[index - 1]
            current = group.iloc[index]
            score, reasons = _delta_score(previous, current, rules)

            warranty_previous = str(previous.get("Warranty Recommendation", "") or "")
            warranty_current = str(current.get("Warranty Recommendation", "") or "")
            warranty_delta = (
                rules["warranty_rank"].get(warranty_current, 0)
                - rules["warranty_rank"].get(warranty_previous, 0)
            )
            if warranty_delta > 0:
                score -= 5.0 * warranty_delta
                reasons.append(
                    f"Warranty recommendation escalated from {warranty_previous or 'N/A'} "
                    f"to {warranty_current or 'N/A'}"
                )
            elif warranty_delta < 0:
                score += 5.0 * abs(warranty_delta)
                reasons.append(
                    f"Warranty recommendation improved from {warranty_previous or 'N/A'} "
                    f"to {warranty_current or 'N/A'}"
                )

            previous_status = str(previous.get("Assistant Status", "") or "")
            current_status = str(current.get("Assistant Status", "") or "")
            status_delta = (
                rules["state_rank"].get(current_status, 0)
                - rules["state_rank"].get(previous_status, 0)
            )
            if status_delta > 0:
                score += 5.0 * status_delta
                reasons.append(
                    f"Assistant Status improved from {previous_status or 'N/A'} "
                    f"to {current_status or 'N/A'}"
                )
            elif status_delta < 0:
                score -= 5.0 * abs(status_delta)
                reasons.append(
                    f"Assistant Status deteriorated from {previous_status or 'N/A'} "
                    f"to {current_status or 'N/A'}"
                )

            root_changed = str(previous.get("Root ECU", "")) != str(current.get("Root ECU", ""))
            if root_changed:
                reasons.append(
                    f"Probable Root ECU changed from {previous.get('Root ECU', '') or 'N/A'} "
                    f"to {current.get('Root ECU', '') or 'N/A'}"
                )

            release_changed = str(previous.get("Selected Release", "")) != str(current.get("Selected Release", ""))
            if release_changed:
                reasons.append(
                    f"Selected Release changed from {previous.get('Selected Release', '') or 'N/A'} "
                    f"to {current.get('Selected Release', '') or 'N/A'}"
                )

            rows.append({
                "VIN": vin,
                "Project": current.get("Project", ""),
                "Previous Session": previous.get("Session ID", ""),
                "Current Session": current.get("Session ID", ""),
                "Previous Date": previous.get("Analysis Date"),
                "Current Date": current.get("Analysis Date"),
                "Transition Score": round(score, 1),
                "Transition Classification": classify_transition(score, rules),
                "Vehicle Health Delta": round(
                    _num(current.get("Vehicle Health")) - _num(previous.get("Vehicle Health")), 1
                ),
                "Average Risk Delta": round(
                    _num(current.get("Average Risk")) - _num(previous.get("Average Risk")), 1
                ),
                "Compliance Delta": round(
                    _num(current.get("Compliance Rate")) - _num(previous.get("Compliance Rate")), 1
                ),
                "Consistency Delta": round(
                    _num(current.get("Release Consistency")) - _num(previous.get("Release Consistency")), 1
                ),
                "Open Findings Delta": int(
                    _num(current.get("Open Findings")) - _num(previous.get("Open Findings"))
                ),
                "Persistent DTC Delta": int(
                    _num(current.get("Persistent DTCs")) - _num(previous.get("Persistent DTCs"))
                ),
                "Warranty Previous": warranty_previous,
                "Warranty Current": warranty_current,
                "Root ECU Previous": previous.get("Root ECU", ""),
                "Root ECU Current": current.get("Root ECU", ""),
                "Root ECU Changed": root_changed,
                "Selected Release Previous": previous.get("Selected Release", ""),
                "Selected Release Current": current.get("Selected Release", ""),
                "Selected Release Changed": release_changed,
                "Transition Evidence": " | ".join(reasons) if reasons else "No significant change detected",
            })

    return pd.DataFrame(rows).sort_values(
        ["VIN", "Current Date"]
    ).reset_index(drop=True)


def vehicle_trend_summary(
    timeseries: pd.DataFrame,
    transitions: pd.DataFrame,
) -> pd.DataFrame:
    if timeseries is None or timeseries.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for vin, group in timeseries.groupby("VIN", dropna=False):
        group = group.sort_values(["Analysis Date", "Session ID"]).reset_index(drop=True)
        first = group.iloc[0]
        latest = group.iloc[-1]
        scoped_transitions = (
            transitions[transitions["VIN"].astype(str) == str(vin)]
            if transitions is not None and not transitions.empty else pd.DataFrame()
        )
        latest_transition = (
            scoped_transitions.sort_values("Current Date").iloc[-1]
            if not scoped_transitions.empty else pd.Series(dtype=object)
        )
        rows.append({
            "VIN": vin,
            "Vehicle Name": latest.get("Vehicle Name", ""),
            "Projects": ", ".join(sorted(group["Project"].dropna().astype(str).unique())),
            "Sessions": len(group),
            "First Analysis": first.get("Analysis Date"),
            "Latest Analysis": latest.get("Analysis Date"),
            "Latest Release": latest.get("Selected Release", ""),
            "Latest Vehicle Health": latest.get("Vehicle Health", 0),
            "Health Change Since First": round(
                _num(latest.get("Vehicle Health")) - _num(first.get("Vehicle Health")), 1
            ),
            "Latest Average Risk": latest.get("Average Risk", 0),
            "Risk Change Since First": round(
                _num(latest.get("Average Risk")) - _num(first.get("Average Risk")), 1
            ),
            "Latest Compliance %": latest.get("Compliance Rate", 0),
            "Compliance Change Since First": round(
                _num(latest.get("Compliance Rate")) - _num(first.get("Compliance Rate")), 1
            ),
            "Latest Release Consistency": latest.get("Release Consistency", 0),
            "Consistency Change Since First": round(
                _num(latest.get("Release Consistency")) - _num(first.get("Release Consistency")), 1
            ),
            "Latest Warranty": latest.get("Warranty Recommendation", ""),
            "Latest Root ECU": latest.get("Root ECU", ""),
            "Latest Assistant Status": latest.get("Assistant Status", ""),
            "Latest Transition": latest_transition.get("Transition Classification", "BASELINE"),
            "Latest Transition Score": latest_transition.get("Transition Score", 0),
            "Regressions": int(
                scoped_transitions.get(
                    "Transition Classification", pd.Series(dtype=str)
                ).astype(str).isin(["REGRESSION", "CRITICAL_REGRESSION"]).sum()
            ) if not scoped_transitions.empty else 0,
            "Improvements": int(
                scoped_transitions.get(
                    "Transition Classification", pd.Series(dtype=str)
                ).astype(str).isin(["IMPROVEMENT", "STRONG_IMPROVEMENT"]).sum()
            ) if not scoped_transitions.empty else 0,
        })
    return pd.DataFrame(rows).sort_values(
        ["Regressions", "Latest Vehicle Health"],
        ascending=[False, True],
    ).reset_index(drop=True)


def build_timeline_events(
    timeseries: pd.DataFrame,
    transitions: pd.DataFrame,
) -> pd.DataFrame:
    if timeseries is None or timeseries.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    transition_lookup = {}
    if transitions is not None and not transitions.empty:
        transition_lookup = {
            str(row["Current Session"]): row
            for _, row in transitions.iterrows()
        }

    for _, session in timeseries.iterrows():
        transition = transition_lookup.get(str(session["Session ID"]))
        rows.append({
            "VIN": session.get("VIN", ""),
            "Date": session.get("Analysis Date"),
            "Session ID": session.get("Session ID", ""),
            "Project": session.get("Project", ""),
            "Event Type": (
                transition.get("Transition Classification", "")
                if transition is not None else "BASELINE"
            ),
            "Selected Release": session.get("Selected Release", ""),
            "Vehicle Health": session.get("Vehicle Health", 0),
            "Average Risk": session.get("Average Risk", 0),
            "Compliance Rate": session.get("Compliance Rate", 0),
            "Release Consistency": session.get("Release Consistency", 0),
            "Warranty Recommendation": session.get("Warranty Recommendation", ""),
            "Root ECU": session.get("Root ECU", ""),
            "Persistent DTCs": session.get("Persistent DTCs", 0),
            "Open Findings": session.get("Open Findings", 0),
            "Event Summary": (
                transition.get("Transition Evidence", "")
                if transition is not None
                else "Initial saved analysis for this VIN"
            ),
        })
    return pd.DataFrame(rows).sort_values(
        ["VIN", "Date", "Session ID"]
    ).reset_index(drop=True)


def build_timeseries_intelligence(
    sessions: list[dict[str, Any]],
    projects: list[dict[str, Any]] | None = None,
    vehicles: list[dict[str, Any]] | None = None,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    rules = dict(rules or load_timeseries_rules())
    timeseries = build_workspace_timeseries(sessions, projects, vehicles)
    transitions = build_transition_log(timeseries, rules)
    trends = vehicle_trend_summary(timeseries, transitions)
    timeline = build_timeline_events(timeseries, transitions)
    return {
        "timeseries": timeseries,
        "transitions": transitions,
        "vehicle_trends": trends,
        "timeline": timeline,
    }
