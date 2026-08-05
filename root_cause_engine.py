from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from dependency_engine import downstream_closure, load_dependency_rules


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _urgency_score(value: str) -> float:
    return {
        "LOW": 0.0,
        "MEDIUM": 0.35,
        "HIGH": 0.70,
        "CRITICAL": 1.0,
    }.get(str(value or "").upper(), 0.25)


def _status_flag(status: str, target: str) -> float:
    return 1.0 if str(status or "").upper() == target else 0.0


def rank_root_ecus(
    overview: pd.DataFrame,
    dependency_nodes: pd.DataFrame,
    dependency_edges: pd.DataFrame,
    change_log: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rules = dict(rules or load_dependency_rules())
    if overview is None or overview.empty:
        return pd.DataFrame(), pd.DataFrame()

    weights = rules["root_cause_weights"]
    confidence_rules = rules["confidence"]
    ranking_rows: list[dict[str, Any]] = []
    vehicle_rows: list[dict[str, Any]] = []

    node_lookup = {}
    if dependency_nodes is not None and not dependency_nodes.empty:
        node_lookup = {
            (str(row["Source File"]), str(row["ECU"])): row
            for _, row in dependency_nodes.iterrows()
        }

    regression_keys: set[tuple[str, str]] = set()
    if change_log is not None and not change_log.empty:
        required = {"Current Session", "ECU", "Regression"}
        if required.issubset(change_log.columns):
            reg = change_log[change_log["Regression"].fillna(False).astype(bool)]
            regression_keys = set(
                zip(reg["Current Session"].astype(str), reg["ECU"].astype(str))
            )

    for (source_file, vin), group in overview.groupby(["Source File", "VIN"], dropna=False):
        scoped_edges = (
            dependency_edges[dependency_edges["Source File"].astype(str) == str(source_file)]
            if dependency_edges is not None and not dependency_edges.empty
            else pd.DataFrame()
        )

        candidate_rows = []
        ecu_count = max(len(group), 1)
        for _, row in group.iterrows():
            ecu = str(row.get("ECU", "") or "")
            node = node_lookup.get((str(source_file), ecu), {})
            risk_norm = min(1.0, _number(row.get("Risk Score", 0)) / 100.0)
            persistent_norm = min(1.0, _number(row.get("Persistent DTC Count", 0)) / 2.0)
            importance = _number(
                node.get("Importance", 0.45) if hasattr(node, "get") else 0.45,
                0.45,
            )
            impacted = downstream_closure(scoped_edges, ecu)
            impact_norm = min(1.0, len(impacted) / max(ecu_count - 1, 1))
            regression = 1.0 if (str(source_file), ecu) in regression_keys else 0.0
            status = str(row.get("Status", "") or "")
            urgency_norm = _urgency_score(str(row.get("Decision Urgency", "") or ""))

            score = 100.0 * (
                weights["risk_score"] * risk_norm
                + weights["persistent_dtc"] * persistent_norm
                + weights["wrong_release"] * _status_flag(status, "WRONG_RELEASE")
                + weights["mismatch"] * _status_flag(status, "MISMATCH")
                + weights["regression"] * regression
                + weights["importance"] * importance
                + weights["downstream_impact"] * impact_norm
                + weights["high_decision_urgency"] * urgency_norm
            )

            evidence = []
            if risk_norm >= 0.6:
                evidence.append(f"High ECU risk ({_number(row.get('Risk Score', 0)):.0f}/100)")
            if persistent_norm > 0:
                evidence.append(
                    f"Persistent DTC evidence ({int(_number(row.get('Persistent DTC Count', 0)))})"
                )
            if status in {"WRONG_RELEASE", "MISMATCH"}:
                evidence.append(f"Critical configuration status: {status}")
            if regression:
                evidence.append("Historical regression detected")
            if impact_norm > 0:
                evidence.append(f"Potential downstream impact on {len(impacted)} ECU(s)")
            if importance >= 0.8:
                evidence.append("High-importance ECU role")
            if not evidence:
                evidence.append("Limited direct root-cause evidence")

            candidate_rows.append({
                "Source File": source_file,
                "VIN": vin,
                "ECU": ecu,
                "ECU Role": node.get("Role", "OTHER") if hasattr(node, "get") else "OTHER",
                "Root Cause Score": round(score, 1),
                "Risk Score": _number(row.get("Risk Score", 0)),
                "Status": status,
                "Decision": row.get("Decision", ""),
                "Decision Urgency": row.get("Decision Urgency", ""),
                "Persistent DTC Count": int(_number(row.get("Persistent DTC Count", 0))),
                "Importance": round(importance, 2),
                "Impact Radius": len(impacted),
                "Impacted ECUs": ", ".join(sorted(impacted)),
                "Regression Evidence": bool(regression),
                "Root Cause Evidence": " | ".join(evidence),
                "Primary Root Cause Hypothesis": row.get("Primary Root Cause", ""),
                "Recommended Actions": row.get("Recommended Actions", ""),
            })

        ranked = pd.DataFrame(candidate_rows).sort_values(
            ["Root Cause Score", "Risk Score", "Impact Radius"],
            ascending=[False, False, False],
        ).reset_index(drop=True)
        if ranked.empty:
            continue

        ranked["Root Cause Rank"] = range(1, len(ranked) + 1)
        total_positive = float(ranked["Root Cause Score"].clip(lower=0).sum())
        lead_score = float(ranked.iloc[0]["Root Cause Score"])
        dominance = lead_score / total_positive if total_positive > 0 else 0.0
        evidence_count = len(
            [
                item
                for item in str(ranked.iloc[0]["Root Cause Evidence"]).split(" | ")
                if item and "Limited" not in item
            ]
        )
        dependency_bonus = (
            confidence_rules["dependency_bonus"]
            if int(ranked.iloc[0]["Impact Radius"]) > 0
            else 0
        )
        confidence = (
            confidence_rules["base"]
            + confidence_rules["dominance_weight"] * dominance
            + confidence_rules["evidence_bonus"] * min(evidence_count, 3)
            + dependency_bonus
        )
        confidence = min(float(confidence_rules["cap"]), confidence)

        lead = ranked.iloc[0]
        runner_up = ranked.iloc[1] if len(ranked) > 1 else None
        gap = (
            float(lead["Root Cause Score"]) - float(runner_up["Root Cause Score"])
            if runner_up is not None
            else float(lead["Root Cause Score"])
        )

        vehicle_rows.append({
            "Source File": source_file,
            "VIN": vin,
            "Most Probable Root ECU": lead["ECU"],
            "Root ECU Role": lead["ECU Role"],
            "Root Cause Confidence %": round(confidence, 1),
            "Root Cause Score": lead["Root Cause Score"],
            "Runner-Up ECU": runner_up["ECU"] if runner_up is not None else "",
            "Runner-Up Score": runner_up["Root Cause Score"] if runner_up is not None else 0,
            "Score Gap": round(gap, 1),
            "Impact Radius": lead["Impact Radius"],
            "Potentially Affected ECUs": lead["Impacted ECUs"],
            "Primary Vehicle Root Cause": lead["Primary Root Cause Hypothesis"],
            "Root Cause Evidence": lead["Root Cause Evidence"],
            "Recommended Root Action": str(lead["Recommended Actions"]).split(" | ")[0],
        })

        ranking_rows.extend(ranked.to_dict("records"))

    return pd.DataFrame(vehicle_rows), pd.DataFrame(ranking_rows)


def root_cause_path_summary(
    vehicle_root_causes: pd.DataFrame,
    dependency_edges: pd.DataFrame,
) -> pd.DataFrame:
    if vehicle_root_causes is None or vehicle_root_causes.empty:
        return pd.DataFrame()

    rows = []
    for _, root in vehicle_root_causes.iterrows():
        source_file = root["Source File"]
        root_ecu = root["Most Probable Root ECU"]
        scoped = (
            dependency_edges[dependency_edges["Source File"] == source_file]
            if dependency_edges is not None and not dependency_edges.empty
            else pd.DataFrame()
        )
        impacted = downstream_closure(scoped, root_ecu)
        if not impacted:
            rows.append({
                "Source File": source_file,
                "VIN": root["VIN"],
                "Root ECU": root_ecu,
                "Affected ECU": "",
                "Relationship": "NO_MAPPED_DOWNSTREAM_DEPENDENCY",
                "Root Cause Confidence %": root["Root Cause Confidence %"],
            })
        else:
            for affected in sorted(impacted):
                rows.append({
                    "Source File": source_file,
                    "VIN": root["VIN"],
                    "Root ECU": root_ecu,
                    "Affected ECU": affected,
                    "Relationship": "POTENTIAL_DOWNSTREAM_IMPACT",
                    "Root Cause Confidence %": root["Root Cause Confidence %"],
                })
    return pd.DataFrame(rows)
