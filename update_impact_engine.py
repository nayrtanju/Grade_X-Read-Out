from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("update_impact_rules.json")


def load_update_impact_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    with rules_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _text(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


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


def release_family(value: Any) -> str:
    text = _text(value).upper()
    if not text:
        return ""
    match = re.search(r"(MY\d{2}(?:\.\d+)?)", text)
    if match:
        return match.group(1)
    match = re.search(r"(PTO\d+)", text)
    if match:
        return match.group(1)
    return text


def release_numeric(value: Any) -> float | None:
    family = release_family(value)
    match = re.search(r"MY(\d{2})(?:\.(\d+))?", family)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    return major + minor / 10.0


def release_gap(current: Any, target: Any) -> float:
    current_value = release_numeric(current)
    target_value = release_numeric(target)
    if current_value is None or target_value is None:
        return 0.0
    return round(target_value - current_value, 2)


def build_adjacency(edges: pd.DataFrame) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    if edges is None or edges.empty:
        return adjacency
    for _, edge in edges.iterrows():
        adjacency[str(edge["Upstream ECU"])].add(str(edge["Downstream ECU"]))
    return adjacency


def downstream_depths(edges: pd.DataFrame, root_ecu: str) -> dict[str, int]:
    adjacency = build_adjacency(edges)
    depths: dict[str, int] = {}
    queue = deque([(str(root_ecu), 0)])
    while queue:
        node, depth = queue.popleft()
        for child in adjacency.get(node, set()):
            next_depth = depth + 1
            if child not in depths or next_depth < depths[child]:
                depths[child] = next_depth
                queue.append((child, next_depth))
    return depths


def candidate_target_releases(
    nodes: pd.DataFrame,
    source_file: str,
    selected_ecu: str,
) -> list[str]:
    if nodes is None or nodes.empty:
        return []
    scoped = nodes[
        nodes["Source File"].astype(str) == str(source_file)
    ]
    selected = scoped[scoped["ECU"].astype(str) == str(selected_ecu)]
    candidates = set()
    if not selected.empty:
        for column in ("Installed Release", "Target Release"):
            value = _text(selected.iloc[0].get(column, ""))
            if value:
                candidates.add(value)
    for value in scoped.get("Target Release", pd.Series(dtype=str)).dropna().astype(str):
        if value.strip():
            candidates.add(value.strip())
    return sorted(candidates)


def _compatibility_level(score: float, rules: Mapping[str, Any]) -> str:
    thresholds = rules["compatibility_thresholds"]
    if score >= thresholds["SAFE"]:
        return "SAFE"
    if score >= thresholds["CONDITIONAL"]:
        return "CONDITIONAL"
    return "HIGH_RISK"


def simulate_update_impact(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    source_file: str,
    selected_ecu: str,
    target_release: str,
    release_consistency: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rules = dict(rules or load_update_impact_rules())
    scoped_nodes = nodes[
        nodes["Source File"].astype(str) == str(source_file)
    ].copy()
    scoped_edges = edges[
        edges["Source File"].astype(str) == str(source_file)
    ].copy() if edges is not None and not edges.empty else pd.DataFrame()

    selected_rows = scoped_nodes[
        scoped_nodes["ECU"].astype(str) == str(selected_ecu)
    ]
    if selected_rows.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    selected = selected_rows.iloc[0]
    depths = downstream_depths(scoped_edges, selected_ecu)
    affected_ecus = {selected_ecu, *depths.keys()}
    affected = scoped_nodes[
        scoped_nodes["ECU"].astype(str).isin(affected_ecus)
    ].copy()

    mixed_package = False
    if release_consistency is not None and not release_consistency.empty:
        match = release_consistency[
            release_consistency["Source File"].astype(str) == str(source_file)
        ]
        if not match.empty:
            mixed_package = bool(match.iloc[0].get("Mixed Package Detected", False))

    current_family = release_family(selected.get("Installed Release", ""))
    target_family = release_family(target_release)
    family_change = bool(current_family and target_family and current_family != target_family)
    target_unknown = not bool(target_family)

    result_rows = []
    companion_rows = []

    for _, row in affected.iterrows():
        ecu = str(row["ECU"])
        depth = 0 if ecu == selected_ecu else depths.get(ecu, 99)
        direct = depth == 1
        status = str(row.get("Status", ""))
        criticality = str(row.get("Criticality", ""))
        current_release = _text(row.get("Installed Release", ""))
        node_target = _text(row.get("Target Release", ""))
        node_family = release_family(current_release)
        node_target_family = release_family(node_target)
        gap = release_gap(current_release, target_release)

        penalty = 0.0
        evidence = []
        if status == "WRONG_RELEASE":
            penalty += rules["penalties"]["wrong_release"]
            evidence.append("ECU currently has WRONG_RELEASE")
        elif status == "MISMATCH":
            penalty += rules["penalties"]["mismatch"]
            evidence.append("ECU currently has MISMATCH")

        if mixed_package:
            penalty += rules["penalties"]["mixed_package"]
            evidence.append("Vehicle has mixed-package evidence")

        persistent = int(_num(row.get("Persistent DTC Count", 0)))
        if persistent > 0:
            penalty += rules["penalties"]["persistent_dtc"]
            evidence.append(f"Persistent DTC count: {persistent}")

        if criticality == "CRITICAL":
            penalty += rules["penalties"]["critical_ecu"]
            evidence.append("Critical network ECU")
        elif criticality == "MAJOR":
            penalty += rules["penalties"]["major_ecu"]
            evidence.append("Major network ECU")

        if direct:
            penalty += rules["penalties"]["direct_dependency"]
            evidence.append("Direct downstream dependency")
        elif depth > 1 and depth < 99:
            penalty += rules["penalties"]["indirect_dependency"]
            evidence.append(f"Indirect dependency at depth {depth}")

        if family_change and ecu == selected_ecu:
            penalty += rules["penalties"]["release_family_change"]
            evidence.append(
                f"Selected ECU release family changes from {current_family} to {target_family}"
            )

        if target_unknown:
            penalty += rules["penalties"]["unknown_target_release"]
            evidence.append("Target release family is unknown")

        compatibility = max(0.0, min(100.0, 100.0 - penalty))
        level = _compatibility_level(compatibility, rules)

        requires_update = ecu == selected_ecu
        reason = "Selected ECU update"
        if ecu != selected_ecu:
            companion_rules = rules["companion_update_rules"]
            if status in {"WRONG_RELEASE", "MISMATCH"}:
                requires_update = True
                reason = f"Current configuration status is {status}"
            elif criticality == "CRITICAL" and direct:
                requires_update = True
                reason = "Direct critical downstream dependency"
            elif (
                node_family
                and target_family
                and node_family != target_family
                and companion_rules["different_release_family_requires_update"]
            ):
                requires_update = True
                reason = "Installed release family differs from proposed package"
            elif direct and companion_rules["direct_downstream_requires_review"]:
                reason = "Direct downstream ECU requires compatibility review"
            else:
                reason = "No automatic companion update requirement"

        action = (
            "UPDATE_REQUIRED" if requires_update
            else "COMPATIBILITY_REVIEW" if direct
            else "NO_AUTOMATIC_UPDATE"
        )

        result_rows.append({
            "Source File": source_file,
            "VIN": row.get("VIN", ""),
            "Selected ECU": selected_ecu,
            "Proposed Target Release": target_release,
            "Affected ECU": ecu,
            "Role": row.get("Role", ""),
            "Dependency Depth": depth,
            "Direct Dependency": direct,
            "Current Release": current_release,
            "Current Release Family": node_family,
            "Reference Target Release": node_target,
            "Reference Target Family": node_target_family,
            "Proposed Release Gap": gap,
            "Status": status,
            "Criticality": criticality,
            "Risk Score": row.get("Risk Score", 0),
            "Persistent DTC Count": persistent,
            "Compatibility Score": round(compatibility, 1),
            "Compatibility Level": level,
            "Required Action": action,
            "Impact Evidence": " | ".join(evidence) if evidence else "No significant impact evidence",
        })

        if ecu != selected_ecu:
            companion_rows.append({
                "Source File": source_file,
                "VIN": row.get("VIN", ""),
                "Selected ECU": selected_ecu,
                "Companion ECU": ecu,
                "Role": row.get("Role", ""),
                "Dependency Depth": depth,
                "Current Release": current_release,
                "Proposed Package": target_release,
                "Companion Update Required": requires_update,
                "Companion Decision": action,
                "Decision Reason": reason,
                "Compatibility Score": round(compatibility, 1),
                "Compatibility Level": level,
            })

    impact = pd.DataFrame(result_rows).sort_values(
        ["Dependency Depth", "Compatibility Score", "Affected ECU"],
        ascending=[True, True, True],
    ).reset_index(drop=True)
    companions = pd.DataFrame(companion_rows).sort_values(
        ["Companion Update Required", "Dependency Depth", "Compatibility Score"],
        ascending=[False, True, True],
    ).reset_index(drop=True)

    required = impact[impact["Required Action"] == "UPDATE_REQUIRED"].copy()
    role_order = {
        role: index
        for index, role in enumerate(rules["sequence_role_order"], start=1)
    }
    if not required.empty:
        required["Role Order"] = required["Role"].map(role_order).fillna(999)
        required["Sequence Priority"] = (
            required["Dependency Depth"] * 100
            + required["Role Order"]
        )
        sequence = required.sort_values(
            ["Sequence Priority", "Compatibility Score", "Affected ECU"]
        ).reset_index(drop=True)
        sequence["Update Step"] = range(1, len(sequence) + 1)
        sequence["Sequence Action"] = sequence.apply(
            lambda row: (
                f"Program {row['Affected ECU']} to the approved release compatible "
                f"with {target_release}, then verify communication and DTC status."
            ),
            axis=1,
        )
        sequence = sequence[
            [
                "Source File", "VIN", "Update Step", "Affected ECU", "Role",
                "Dependency Depth", "Current Release", "Proposed Target Release",
                "Compatibility Score", "Compatibility Level", "Sequence Action",
            ]
        ]
    else:
        sequence = pd.DataFrame()

    return impact, companions, sequence


def simulation_summary(
    impact: pd.DataFrame,
    companions: pd.DataFrame,
    sequence: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_update_impact_rules())
    if impact is None or impact.empty:
        return pd.DataFrame()

    lead = impact.iloc[0]
    required_updates = int(
        impact["Required Action"].astype(str).eq("UPDATE_REQUIRED").sum()
    )
    reviews = int(
        impact["Required Action"].astype(str).eq("COMPATIBILITY_REVIEW").sum()
    )
    high_risk = int(
        impact["Compatibility Level"].astype(str).eq("HIGH_RISK").sum()
    )
    average_score = pd.to_numeric(
        impact["Compatibility Score"], errors="coerce"
    ).mean()
    overall_score = float(
        pd.to_numeric(impact["Compatibility Score"], errors="coerce").min()
    )
    overall_level = _compatibility_level(overall_score, rules)

    return pd.DataFrame([{
        "Source File": lead.get("Source File", ""),
        "VIN": lead.get("VIN", ""),
        "Selected ECU": lead.get("Selected ECU", ""),
        "Proposed Target Release": lead.get("Proposed Target Release", ""),
        "Affected ECUs": len(impact),
        "Required Companion Updates": max(0, required_updates - 1),
        "Compatibility Reviews": reviews,
        "High-Risk ECUs": high_risk,
        "Average Compatibility Score": round(float(average_score), 1),
        "Overall Compatibility Score": round(overall_score, 1),
        "Overall Compatibility Level": overall_level,
        "Recommended Update Steps": len(sequence),
        "Overall Recommendation": (
            "DO_NOT_PROCEED_WITHOUT_ENGINEERING_REVIEW"
            if overall_level == "HIGH_RISK"
            else "PROCEED_WITH_CONDITIONS"
            if overall_level == "CONDITIONAL"
            else "PROCEED_USING_APPROVED_PROGRAMMING_INSTRUCTIONS"
        ),
        "Disclaimer": rules["disclaimer"],
    }])
