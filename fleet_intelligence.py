from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("fleet_rules.json")


def load_fleet_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    with rules_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _safe_num(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _split_codes(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def fleet_kpis(
    overview: pd.DataFrame,
    vehicle_health: pd.DataFrame,
    release_consistency: pd.DataFrame,
    warranty_summary: pd.DataFrame,
    vehicle_root_causes: pd.DataFrame,
) -> pd.DataFrame:
    vehicles = overview["Source File"].nunique() if not overview.empty else 0
    vins = overview["VIN"].nunique() if not overview.empty else 0
    ecus = len(overview)
    avg_risk = pd.to_numeric(overview.get("Risk Score", pd.Series(dtype=float)), errors="coerce").mean()
    avg_health = pd.to_numeric(vehicle_health.get("Vehicle Health Score", pd.Series(dtype=float)), errors="coerce").mean()
    avg_consistency = pd.to_numeric(release_consistency.get("Release Consistency Score", pd.Series(dtype=float)), errors="coerce").mean()
    critical = int(overview.get("Risk Level", pd.Series(dtype=str)).astype(str).eq("CRITICAL").sum())
    persistent = int(pd.to_numeric(overview.get("Persistent DTC Count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    escalations = int(warranty_summary.get("Warranty Recommendation", pd.Series(dtype=str)).astype(str).eq("ENGINEERING_ESCALATION").sum())
    mixed_packages = int(release_consistency.get("Mixed Package Detected", pd.Series(dtype=bool)).fillna(False).sum())
    root_conf = pd.to_numeric(vehicle_root_causes.get("Root Cause Confidence %", pd.Series(dtype=float)), errors="coerce").mean()

    return pd.DataFrame([{
        "Vehicles / Sessions": vehicles,
        "Unique VINs": vins,
        "ECU Assessments": ecus,
        "Average Risk Score": round(avg_risk, 1) if pd.notna(avg_risk) else 0.0,
        "Average Vehicle Health": round(avg_health, 1) if pd.notna(avg_health) else 0.0,
        "Average Release Consistency": round(avg_consistency, 1) if pd.notna(avg_consistency) else 0.0,
        "Critical-Risk ECUs": critical,
        "Persistent DTCs": persistent,
        "Mixed Packages": mixed_packages,
        "Engineering Escalations": escalations,
        "Average Root-Cause Confidence": round(root_conf, 1) if pd.notna(root_conf) else 0.0,
    }])


def problematic_ecu_ranking(
    overview: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_fleet_rules())
    if overview is None or overview.empty:
        return pd.DataFrame()

    rows = []
    severity = rules["severity_weights"]
    for ecu, group in overview.groupby("ECU", dropna=False):
        status = group.get("Status", pd.Series(dtype=str)).astype(str)
        weighted = sum(severity.get(item, 3) for item in status)
        problem_count = int(status.ne("COMPLIANT").sum())
        persistent = int(pd.to_numeric(group.get("Persistent DTC Count", 0), errors="coerce").fillna(0).sum())
        avg_risk = pd.to_numeric(group.get("Risk Score", 0), errors="coerce").mean()
        critical = int(group.get("Risk Level", pd.Series(dtype=str)).astype(str).eq("CRITICAL").sum())
        vehicles = group["Source File"].nunique()
        problem_rate = problem_count / len(group) * 100 if len(group) else 0.0
        score = weighted + persistent * 4 + critical * 3 + (_safe_num(avg_risk) / 20)
        rows.append({
            "ECU": ecu,
            "Vehicles Seen": vehicles,
            "Assessments": len(group),
            "Problem Count": problem_count,
            "Problem Rate %": round(problem_rate, 1),
            "Average Risk Score": round(_safe_num(avg_risk), 1),
            "Critical Findings": critical,
            "Persistent DTCs": persistent,
            "Fleet Problem Score": round(score, 1),
            "Most Common Status": status.mode().iloc[0] if not status.mode().empty else "",
        })
    return pd.DataFrame(rows).sort_values(
        ["Fleet Problem Score", "Problem Rate %", "Assessments"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def dtc_ranking(dtc_summary: pd.DataFrame) -> pd.DataFrame:
    if dtc_summary is None or dtc_summary.empty:
        return pd.DataFrame()
    rows = []
    for (dtc, failure_type), group in dtc_summary.groupby(["DTC", "Failure Type"], dropna=False):
        rows.append({
            "DTC": dtc,
            "Failure Type": failure_type,
            "Affected ECUs": group["ECU"].nunique(),
            "Affected Vehicles": group["Mapped Session"].nunique(),
            "Occurrences": int(pd.to_numeric(group["Occurrences"], errors="coerce").fillna(0).sum()),
            "Persistent Records": int(group["Persistence"].astype(str).isin(["REAPPEARED_AFTER_CLEAR", "REPEATED"]).sum()),
            "Highest Severity": (
                "HIGH" if group["Severity"].astype(str).eq("HIGH").any()
                else "MEDIUM" if group["Severity"].astype(str).eq("MEDIUM").any()
                else "LOW"
            ),
            "ECUs": ", ".join(sorted(group["ECU"].dropna().astype(str).unique())),
        })
    return pd.DataFrame(rows).sort_values(
        ["Persistent Records", "Occurrences", "Affected Vehicles"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def release_pattern_ranking(
    release_consistency: pd.DataFrame,
    ecu_consistency: pd.DataFrame,
) -> pd.DataFrame:
    if release_consistency is None or release_consistency.empty:
        return pd.DataFrame()
    rows = []
    for family, group in release_consistency.groupby("Dominant Installed Release Family", dropna=False):
        scoped_ecus = (
            ecu_consistency[ecu_consistency["Source File"].isin(group["Source File"])]
            if ecu_consistency is not None and not ecu_consistency.empty else pd.DataFrame()
        )
        rows.append({
            "Installed Release Family": family,
            "Vehicles": group["Source File"].nunique(),
            "Average Consistency Score": round(pd.to_numeric(group["Release Consistency Score"], errors="coerce").mean(), 1),
            "Mixed Packages": int(group["Mixed Package Detected"].fillna(False).sum()),
            "Variant Reviews": int(group["Variant Review Required"].fillna(False).sum()),
            "Critical Package Mismatches": int(pd.to_numeric(group["Critical Package Mismatches"], errors="coerce").fillna(0).sum()),
            "ECU Outliers": int(scoped_ecus.get("Package Role", pd.Series(dtype=str)).astype(str).eq("OUTLIER").sum()) if not scoped_ecus.empty else 0,
        })
    return pd.DataFrame(rows).sort_values(
        ["Average Consistency Score", "Mixed Packages"],
        ascending=[True, False],
    ).reset_index(drop=True)


def root_ecu_ranking(vehicle_root_causes: pd.DataFrame) -> pd.DataFrame:
    if vehicle_root_causes is None or vehicle_root_causes.empty:
        return pd.DataFrame()
    rows = []
    for ecu, group in vehicle_root_causes.groupby("Most Probable Root ECU", dropna=False):
        rows.append({
            "Root ECU": ecu,
            "Vehicles": len(group),
            "Average Confidence %": round(pd.to_numeric(group["Root Cause Confidence %"], errors="coerce").mean(), 1),
            "Average Root Cause Score": round(pd.to_numeric(group["Root Cause Score"], errors="coerce").mean(), 1),
            "Average Impact Radius": round(pd.to_numeric(group["Impact Radius"], errors="coerce").mean(), 1),
            "Most Common Role": group["Root ECU Role"].mode().iloc[0] if not group["Root ECU Role"].mode().empty else "",
            "Common Root Action": group["Recommended Root Action"].mode().iloc[0] if not group["Recommended Root Action"].mode().empty else "",
        })
    return pd.DataFrame(rows).sort_values(
        ["Vehicles", "Average Confidence %"],
        ascending=[False, False],
    ).reset_index(drop=True)


def warranty_pattern_ranking(
    warranty_summary: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_fleet_rules())
    if warranty_summary is None or warranty_summary.empty:
        return pd.DataFrame()
    rows = []
    priority = rules["warranty_priority"]
    for recommendation, group in warranty_summary.groupby("Warranty Recommendation", dropna=False):
        rows.append({
            "Warranty Recommendation": recommendation,
            "Vehicles": len(group),
            "Priority": priority.get(str(recommendation), 0),
            "Average Vehicle Health": round(pd.to_numeric(group["Vehicle Health Score"], errors="coerce").mean(), 1),
            "Average Lead Risk": round(pd.to_numeric(group["Lead Risk Score"], errors="coerce").mean(), 1),
            "Most Common Next Step": group["Required Next Step"].mode().iloc[0] if not group["Required Next Step"].mode().empty else "",
        })
    return pd.DataFrame(rows).sort_values(
        ["Priority", "Vehicles"],
        ascending=[False, False],
    ).reset_index(drop=True)


def fleet_alerts(
    fleet_kpi: pd.DataFrame,
    problematic_ecus: pd.DataFrame,
    release_patterns: pd.DataFrame,
    warranty_patterns: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_fleet_rules())
    if fleet_kpi is None or fleet_kpi.empty:
        return pd.DataFrame()
    thresholds = rules["trend_thresholds"]
    kpi = fleet_kpi.iloc[0]
    alerts = []

    if _safe_num(kpi.get("Average Vehicle Health")) < thresholds["low_vehicle_health_percent"]:
        alerts.append(("CRITICAL", "Fleet Vehicle Health is below threshold", f"{kpi.get('Average Vehicle Health')}%"))
    if _safe_num(kpi.get("Average Release Consistency")) < thresholds["low_consistency_percent"]:
        alerts.append(("HIGH", "Fleet release consistency is below threshold", f"{kpi.get('Average Release Consistency')}%"))
    if not problematic_ecus.empty:
        lead = problematic_ecus.iloc[0]
        if _safe_num(lead.get("Problem Rate %")) >= thresholds["high_problem_rate_percent"]:
            alerts.append(("HIGH", f"High problem rate for ECU {lead.get('ECU')}", f"{lead.get('Problem Rate %')}%"))
    if int(kpi.get("Engineering Escalations", 0)) > 0:
        alerts.append(("HIGH", "Engineering escalations are present", str(kpi.get("Engineering Escalations"))))
    if int(kpi.get("Mixed Packages", 0)) > 0:
        alerts.append(("MEDIUM", "Mixed software packages detected", str(kpi.get("Mixed Packages"))))
    if not warranty_patterns.empty and warranty_patterns.iloc[0]["Priority"] >= 5:
        alerts.append(("HIGH", "High-priority warranty pattern detected", str(warranty_patterns.iloc[0]["Warranty Recommendation"])))

    return pd.DataFrame(alerts, columns=["Alert Level", "Alert", "Evidence"])


def build_fleet_intelligence(
    overview: pd.DataFrame,
    vehicle_health: pd.DataFrame,
    release_consistency: pd.DataFrame,
    ecu_consistency: pd.DataFrame,
    warranty_summary: pd.DataFrame,
    vehicle_root_causes: pd.DataFrame,
    dtc_summary: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    rules = dict(rules or load_fleet_rules())
    kpis = fleet_kpis(
        overview, vehicle_health, release_consistency,
        warranty_summary, vehicle_root_causes,
    )
    problematic = problematic_ecu_ranking(overview, rules)
    dtcs = dtc_ranking(dtc_summary)
    releases = release_pattern_ranking(release_consistency, ecu_consistency)
    roots = root_ecu_ranking(vehicle_root_causes)
    warranties = warranty_pattern_ranking(warranty_summary, rules)
    alerts = fleet_alerts(kpis, problematic, releases, warranties, rules)
    return {
        "kpis": kpis,
        "problematic_ecus": problematic,
        "dtc_ranking": dtcs,
        "release_patterns": releases,
        "root_ecus": roots,
        "warranty_patterns": warranties,
        "alerts": alerts,
    }
