from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("assistant_rules.json")


def load_assistant_rules(path: str | Path | None = None) -> dict[str, Any]:
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


def _executive_status(health_score: float, rules: Mapping[str, Any]) -> tuple[str, str]:
    for key in ("CRITICAL", "POOR", "FAIR", "GOOD"):
        config = rules["executive_status"][key]
        if health_score <= float(config["max_health"]):
            return config["label"], config["message"]
    return "GOOD", rules["executive_status"]["GOOD"]["message"]


def _decision_confidence(
    root_confidence: float,
    avg_decision_confidence: float,
    consistency_confidence: float,
    data_completeness: float,
    has_fleet_pattern: bool,
    persistent_dtcs: int,
    rules: Mapping[str, Any],
) -> float:
    cfg = rules["confidence"]
    confidence = float(cfg["base"])
    confidence += cfg["root_cause_weight"] * root_confidence
    confidence += cfg["decision_weight"] * avg_decision_confidence
    confidence += cfg["consistency_weight"] * consistency_confidence
    confidence += cfg["data_completeness_weight"] * data_completeness
    if has_fleet_pattern:
        confidence += cfg["fleet_pattern_bonus"]
    if persistent_dtcs > 0:
        confidence += cfg["persistent_dtc_bonus"]
    return min(float(cfg["cap"]), confidence)


def build_action_plan(
    findings: pd.DataFrame,
    source_file: str,
) -> pd.DataFrame:
    scoped = findings[findings["Source File"].astype(str) == str(source_file)].copy()
    if scoped.empty:
        return pd.DataFrame()

    rows = []
    seen = set()
    phase_map = {
        "ROOT_CAUSE": "VERIFY_EVIDENCE",
        "DIAGNOSTIC": "VERIFY_EVIDENCE",
        "CONFIGURATION": "CORRECT_CONFIGURATION",
        "PACKAGE_CONSISTENCY": "CORRECT_CONFIGURATION",
        "WARRANTY_TRIAGE": "ENGINEERING_REVIEW",
        "VEHICLE_HEALTH": "REPEAT_DIAGNOSTIC",
        "GENERAL": "DOCUMENT_AND_CLOSE",
    }
    phase_order = {
        "VERIFY_EVIDENCE": 1,
        "CORRECT_CONFIGURATION": 2,
        "REPEAT_DIAGNOSTIC": 3,
        "ENGINEERING_REVIEW": 4,
        "DOCUMENT_AND_CLOSE": 5,
    }
    for _, row in scoped.iterrows():
        action = str(row.get("Recommended Action", "") or "").strip()
        if not action or action in seen:
            continue
        seen.add(action)
        phase = phase_map.get(str(row.get("Category", "")), "VERIFY_EVIDENCE")
        rows.append({
            "Source File": source_file,
            "VIN": row.get("VIN", ""),
            "Phase": phase,
            "Phase Order": phase_order[phase],
            "Priority": row.get("Severity", ""),
            "ECU": row.get("ECU", ""),
            "Action": action,
            "Reason": row.get("Finding Title", ""),
            "Evidence": row.get("Evidence", ""),
        })
    return pd.DataFrame(rows).sort_values(
        ["Phase Order", "Priority", "ECU"],
        ascending=[True, False, True],
    ).reset_index(drop=True)


def build_engineering_assistant(
    overview: pd.DataFrame,
    vehicle_health: pd.DataFrame,
    warranty_summary: pd.DataFrame,
    vehicle_root_causes: pd.DataFrame,
    release_consistency: pd.DataFrame,
    engineering_findings: pd.DataFrame,
    fleet_intelligence: Mapping[str, pd.DataFrame] | None = None,
    rules: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rules = dict(rules or load_assistant_rules())
    if overview is None or overview.empty:
        return pd.DataFrame(), pd.DataFrame()

    summaries = []
    action_frames = []
    fleet_problematic = (
        fleet_intelligence.get("problematic_ecus", pd.DataFrame())
        if fleet_intelligence else pd.DataFrame()
    )

    for (source_file, vin), group in overview.groupby(["Source File", "VIN"], dropna=False):
        health = vehicle_health[
            (vehicle_health["Source File"].astype(str) == str(source_file))
            & (vehicle_health["VIN"].astype(str) == str(vin))
        ]
        warranty = warranty_summary[
            (warranty_summary["Source File"].astype(str) == str(source_file))
            & (warranty_summary["VIN"].astype(str) == str(vin))
        ]
        root = vehicle_root_causes[
            (vehicle_root_causes["Source File"].astype(str) == str(source_file))
            & (vehicle_root_causes["VIN"].astype(str) == str(vin))
        ]
        consistency = release_consistency[
            (release_consistency["Source File"].astype(str) == str(source_file))
            & (release_consistency["VIN"].astype(str) == str(vin))
        ]
        findings = engineering_findings[
            engineering_findings["Source File"].astype(str) == str(source_file)
        ]

        health_row = health.iloc[0] if not health.empty else pd.Series(dtype=object)
        warranty_row = warranty.iloc[0] if not warranty.empty else pd.Series(dtype=object)
        root_row = root.iloc[0] if not root.empty else pd.Series(dtype=object)
        consistency_row = consistency.iloc[0] if not consistency.empty else pd.Series(dtype=object)

        health_score = _num(health_row.get("Vehicle Health Score", 0))
        status, status_message = _executive_status(health_score, rules)
        avg_decision_conf = pd.to_numeric(
            group.get("Decision Confidence %", pd.Series(dtype=float)),
            errors="coerce",
        ).mean()
        root_conf = _num(root_row.get("Root Cause Confidence %", 0))
        consistency_conf = _num(consistency_row.get("Consistency Confidence %", 0))
        data_completeness = 100.0 - min(
            100.0,
            pd.to_numeric(group.get("Missing", pd.Series(dtype=float)), errors="coerce")
            .fillna(0).mean() * 10,
        )
        persistent_dtcs = int(
            pd.to_numeric(group.get("Persistent DTC Count", 0), errors="coerce")
            .fillna(0).sum()
        )
        root_ecu = str(root_row.get("Most Probable Root ECU", "") or "")
        has_fleet_pattern = (
            not fleet_problematic.empty
            and root_ecu
            and root_ecu in set(fleet_problematic.head(10)["ECU"].astype(str))
        )
        confidence = _decision_confidence(
            root_conf,
            _num(avg_decision_conf),
            consistency_conf,
            data_completeness,
            has_fleet_pattern,
            persistent_dtcs,
            rules,
        )

        critical_findings = int(findings["Severity"].isin(["CRITICAL", "HIGH"]).sum())
        top_finding = findings.iloc[0] if not findings.empty else pd.Series(dtype=object)
        root_action = str(root_row.get("Recommended Root Action", "") or "")
        warranty_next = str(warranty_row.get("Required Next Step", "") or "")
        overall_action = root_action or warranty_next or str(top_finding.get("Recommended Action", ""))

        executive_summary = (
            f"Vehicle status is {status}. Vehicle Health is {health_score:.1f}/100. "
            f"{critical_findings} high or critical engineering findings were identified. "
            f"The most probable root ECU is {root_ecu or 'not determined'} "
            f"with {root_conf:.1f}% root-cause confidence. "
            f"Release consistency is {_num(consistency_row.get('Release Consistency Score', 0)):.1f}/100 "
            f"and warranty triage is {warranty_row.get('Warranty Recommendation Label', 'not available')}."
        )

        assistant_message = (
            f"Observed: {top_finding.get('Finding Title', 'No dominant finding')}. "
            f"Most probable cause: {root_row.get('Primary Vehicle Root Cause', 'Insufficient evidence')}. "
            f"Recommended first action: {overall_action or 'Complete manual engineering review'}. "
            f"Assistant confidence: {confidence:.1f}%."
        )

        management_summary = (
            f"Status={status}; Vehicle Health={health_score:.1f}/100; "
            f"Release Consistency={_num(consistency_row.get('Release Consistency Score', 0)):.1f}/100; "
            f"Root ECU={root_ecu or 'N/A'}; "
            f"Warranty={warranty_row.get('Warranty Recommendation', 'N/A')}; "
            f"Required Action={overall_action or 'Manual review'}."
        )

        summaries.append({
            "Source File": source_file,
            "VIN": vin,
            "Executive Vehicle Status": status,
            "Executive Status Message": status_message,
            "Vehicle Health Score": health_score,
            "Release Consistency Score": _num(consistency_row.get("Release Consistency Score", 0)),
            "Mixed Package Detected": bool(consistency_row.get("Mixed Package Detected", False)),
            "Most Probable Root ECU": root_ecu,
            "Root Cause Confidence %": root_conf,
            "Warranty Recommendation": warranty_row.get("Warranty Recommendation", ""),
            "Assistant Confidence %": round(confidence, 1),
            "Critical Findings": critical_findings,
            "Primary Finding": top_finding.get("Finding Title", ""),
            "Primary Root Cause": root_row.get("Primary Vehicle Root Cause", ""),
            "Required First Action": overall_action,
            "Executive Summary": executive_summary,
            "Engineering Assistant Message": assistant_message,
            "Management Summary": management_summary,
            "Disclaimers": " | ".join(rules["disclaimers"]),
        })

        action_plan = build_action_plan(engineering_findings, source_file)
        if not action_plan.empty:
            action_frames.append(action_plan)

    return (
        pd.DataFrame(summaries).sort_values(
            ["Vehicle Health Score", "Assistant Confidence %"],
            ascending=[True, False],
        ).reset_index(drop=True),
        pd.concat(action_frames, ignore_index=True) if action_frames else pd.DataFrame(),
    )
