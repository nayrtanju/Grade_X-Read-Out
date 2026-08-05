from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("ecu_network_rules.json")


def load_network_rules(path: str | Path | None = None) -> dict[str, Any]:
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


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^A-Z0-9]+", value.upper()) if token}


def classify_role(ecu: str, ecu_name: str, rules: Mapping[str, Any]) -> str:
    haystack = f"{ecu} {ecu_name}".upper()
    tokens = _tokens(haystack)
    best_role = "OTHER"
    best_score = 0
    for role, config in rules["roles"].items():
        if role == "OTHER":
            continue
        for alias in config.get("aliases", []):
            alias = alias.upper()
            score = 3 if alias in tokens else 2 if alias in haystack else 0
            if score > best_score:
                best_role = role
                best_score = score
    return best_role


def build_network_nodes(
    summary: pd.DataFrame,
    overview: pd.DataFrame,
    dependency_nodes: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_network_rules())
    if summary is None or summary.empty:
        return pd.DataFrame()

    overview_lookup = {
        (str(row.get("Source File", "")), str(row.get("ECU", ""))): row
        for _, row in overview.iterrows()
    } if overview is not None and not overview.empty else {}

    dependency_lookup = {
        (str(row.get("Source File", "")), str(row.get("ECU", ""))): row
        for _, row in dependency_nodes.iterrows()
    } if dependency_nodes is not None and not dependency_nodes.empty else {}

    rows = []
    for _, item in summary.iterrows():
        source = str(item.get("Source File", ""))
        ecu = str(item.get("ECU ID", ""))
        name = str(item.get("ECU Name", "") or "")
        role = classify_role(ecu, name, rules)
        overview_row = overview_lookup.get((source, ecu), {})
        dep_row = dependency_lookup.get((source, ecu), {})
        risk = _num(overview_row.get("Risk Score", 0) if hasattr(overview_row, "get") else 0)
        persistent = int(_num(overview_row.get("Persistent DTC Count", 0) if hasattr(overview_row, "get") else 0))
        base = _num(rules["roles"][role]["base_criticality"])
        impact = int(_num(dep_row.get("Impact Radius", 0) if hasattr(dep_row, "get") else 0))
        criticality_score = min(100.0, base * 0.65 + min(30, impact * 4) + min(20, risk * 0.20))
        thresholds = rules["criticality_thresholds"]
        if criticality_score >= thresholds["CRITICAL"]:
            criticality = "CRITICAL"
        elif criticality_score >= thresholds["MAJOR"]:
            criticality = "MAJOR"
        elif criticality_score >= thresholds["NORMAL"]:
            criticality = "NORMAL"
        else:
            criticality = "LOW"

        rows.append({
            "Source File": source,
            "VIN": item.get("VIN", ""),
            "ECU": ecu,
            "ECU Name": name,
            "Role": role,
            "Status": overview_row.get("Status", "") if hasattr(overview_row, "get") else "",
            "Risk Score": risk,
            "Risk Level": overview_row.get("Risk Level", "") if hasattr(overview_row, "get") else "",
            "Persistent DTC Count": persistent,
            "Installed Release": overview_row.get("Installed Release", "") if hasattr(overview_row, "get") else "",
            "Target Release": overview_row.get("Target Release", "") if hasattr(overview_row, "get") else "",
            "Impact Radius": impact,
            "Criticality Score": round(criticality_score, 1),
            "Criticality": criticality,
        })
    return pd.DataFrame(rows)


def build_network_edges(nodes: pd.DataFrame, rules: Mapping[str, Any] | None = None) -> pd.DataFrame:
    rules = dict(rules or load_network_rules())
    if nodes is None or nodes.empty:
        return pd.DataFrame()

    rows = []
    for source, group in nodes.groupby("Source File", dropna=False):
        role_map: dict[str, list[str]] = defaultdict(list)
        vin = group.iloc[0].get("VIN", "")
        for _, row in group.iterrows():
            role_map[str(row["Role"])].append(str(row["ECU"]))

        for upstream_role, downstream_role, dep_type in rules["dependencies"]:
            for upstream in role_map.get(upstream_role, []):
                for downstream in role_map.get(downstream_role, []):
                    if upstream != downstream:
                        rows.append({
                            "Source File": source,
                            "VIN": vin,
                            "Upstream ECU": upstream,
                            "Upstream Role": upstream_role,
                            "Downstream ECU": downstream,
                            "Downstream Role": downstream_role,
                            "Dependency Type": dep_type,
                        })
    return pd.DataFrame(rows)


def build_dependency_matrix(nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    if nodes is None or nodes.empty:
        return pd.DataFrame()
    matrices = []
    for source, group in nodes.groupby("Source File", dropna=False):
        ecus = sorted(group["ECU"].astype(str).unique())
        matrix = pd.DataFrame(0, index=ecus, columns=ecus, dtype=int)
        scoped = edges[edges["Source File"].astype(str) == str(source)] if edges is not None and not edges.empty else pd.DataFrame()
        for _, edge in scoped.iterrows():
            upstream = str(edge["Upstream ECU"])
            downstream = str(edge["Downstream ECU"])
            if upstream in matrix.index and downstream in matrix.columns:
                matrix.loc[upstream, downstream] = 1
        matrix.insert(0, "ECU", matrix.index)
        matrix.insert(0, "Source File", source)
        matrices.append(matrix.reset_index(drop=True))
    return pd.concat(matrices, ignore_index=True) if matrices else pd.DataFrame()


def _closure(edges: pd.DataFrame, root: str) -> set[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for _, row in edges.iterrows():
        adjacency[str(row["Upstream ECU"])].add(str(row["Downstream ECU"]))
    visited: set[str] = set()
    queue = deque(adjacency.get(root, set()))
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        queue.extend(adjacency.get(node, set()) - visited)
    return visited


def detect_dependency_violations(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    release_consistency: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_network_rules())
    if nodes is None or nodes.empty:
        return pd.DataFrame()

    consistency_lookup = {
        str(row["Source File"]): row
        for _, row in release_consistency.iterrows()
    } if release_consistency is not None and not release_consistency.empty else {}

    rows = []
    for source, scoped_nodes in nodes.groupby("Source File", dropna=False):
        node_lookup = {str(row["ECU"]): row for _, row in scoped_nodes.iterrows()}
        scoped_edges = edges[edges["Source File"].astype(str) == str(source)] if edges is not None and not edges.empty else pd.DataFrame()
        mixed = bool(consistency_lookup.get(str(source), {}).get("Mixed Package Detected", False)) if hasattr(consistency_lookup.get(str(source), {}), "get") else False
        for _, edge in scoped_edges.iterrows():
            upstream = node_lookup.get(str(edge["Upstream ECU"]))
            downstream = node_lookup.get(str(edge["Downstream ECU"]))
            if upstream is None or downstream is None:
                continue

            evidence = []
            penalty = 0
            upstream_status = str(upstream.get("Status", ""))
            downstream_status = str(downstream.get("Status", ""))
            if upstream_status == "WRONG_RELEASE":
                penalty += rules["violation_rules"]["upstream_wrong_release"]
                evidence.append("Upstream ECU has WRONG_RELEASE")
            elif upstream_status == "MISMATCH":
                penalty += rules["violation_rules"]["upstream_mismatch"]
                evidence.append("Upstream ECU has MISMATCH")
            if downstream_status in {"MISMATCH", "WRONG_RELEASE"}:
                penalty += rules["violation_rules"]["downstream_mismatch"]
                evidence.append("Downstream ECU has a critical configuration deviation")
            if mixed:
                penalty += rules["violation_rules"]["mixed_package"]
                evidence.append("Vehicle mixed-package condition is active")
            if int(upstream.get("Persistent DTC Count", 0) or 0) > 0:
                penalty += rules["violation_rules"]["persistent_network_dtc"]
                evidence.append("Upstream ECU contains persistent DTC evidence")

            if penalty > 0:
                rows.append({
                    "Source File": source,
                    "VIN": upstream.get("VIN", ""),
                    "Upstream ECU": upstream.get("ECU", ""),
                    "Downstream ECU": downstream.get("ECU", ""),
                    "Dependency Type": edge.get("Dependency Type", ""),
                    "Violation Score": min(100, penalty),
                    "Violation Severity": "CRITICAL" if penalty >= 50 else "HIGH" if penalty >= 30 else "MEDIUM",
                    "Violation Evidence": " | ".join(evidence),
                    "Potential Propagation": ", ".join(sorted(_closure(scoped_edges, str(upstream.get("ECU", ""))))),
                })
    return pd.DataFrame(rows).sort_values(
        ["Violation Score", "Upstream ECU"], ascending=[False, True]
    ).reset_index(drop=True) if rows else pd.DataFrame()


def network_health_summary(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    violations: pd.DataFrame,
    release_consistency: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_network_rules())
    if nodes is None or nodes.empty:
        return pd.DataFrame()

    consistency_lookup = {
        str(row["Source File"]): row
        for _, row in release_consistency.iterrows()
    } if release_consistency is not None and not release_consistency.empty else {}

    rows = []
    weights = rules["network_health_weights"]
    for source, group in nodes.groupby("Source File", dropna=False):
        status = group["Status"].astype(str)
        node_compliance = (status.eq("COMPLIANT").sum() / len(group) * 100) if len(group) else 0
        scoped_violations = (
            violations[violations["Source File"].astype(str) == str(source)]
            if violations is not None and not violations.empty else pd.DataFrame()
        )
        dependency_integrity = max(
            0.0, 100.0 - pd.to_numeric(
                scoped_violations.get("Violation Score", pd.Series(dtype=float)),
                errors="coerce",
            ).fillna(0).sum() / max(len(group), 1)
        )
        consistency = _num(
            consistency_lookup.get(str(source), {}).get("Release Consistency Score", 0)
            if hasattr(consistency_lookup.get(str(source), {}), "get") else 0
        )
        persistent = pd.to_numeric(group["Persistent DTC Count"], errors="coerce").fillna(0).sum()
        diagnostic_health = max(0.0, 100.0 - persistent * 15.0)
        critical_nodes = group[group["Criticality"].isin(["CRITICAL", "MAJOR"])]
        critical_node_health = (
            max(0.0, 100.0 - pd.to_numeric(critical_nodes["Risk Score"], errors="coerce").fillna(0).mean())
            if not critical_nodes.empty else 100.0
        )
        score = (
            weights["node_compliance"] * node_compliance
            + weights["dependency_integrity"] * dependency_integrity
            + weights["release_consistency"] * consistency
            + weights["diagnostic_health"] * diagnostic_health
            + weights["critical_node_health"] * critical_node_health
        )
        level = "GOOD" if score >= 85 else "FAIR" if score >= 70 else "POOR" if score >= 50 else "CRITICAL"
        lead = group.sort_values(
            ["Criticality Score", "Risk Score"], ascending=[False, False]
        ).iloc[0]
        rows.append({
            "Source File": source,
            "VIN": group.iloc[0].get("VIN", ""),
            "Network Nodes": len(group),
            "Network Edges": len(edges[edges["Source File"].astype(str) == str(source)]) if edges is not None and not edges.empty else 0,
            "Dependency Violations": len(scoped_violations),
            "Node Compliance %": round(node_compliance, 1),
            "Dependency Integrity %": round(dependency_integrity, 1),
            "Release Consistency %": round(consistency, 1),
            "Diagnostic Health %": round(diagnostic_health, 1),
            "Critical Node Health %": round(critical_node_health, 1),
            "Network Health Score": round(score, 1),
            "Network Health Level": level,
            "Most Critical ECU": lead.get("ECU", ""),
            "Most Critical ECU Score": lead.get("Criticality Score", 0),
        })
    return pd.DataFrame(rows).sort_values(
        ["Network Health Score", "Dependency Violations"],
        ascending=[True, False],
    ).reset_index(drop=True)


def build_network_intelligence(
    summary: pd.DataFrame,
    overview: pd.DataFrame,
    dependency_nodes: pd.DataFrame | None = None,
    release_consistency: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, pd.DataFrame]:
    rules = dict(rules or load_network_rules())
    nodes = build_network_nodes(summary, overview, dependency_nodes, rules)
    edges = build_network_edges(nodes, rules)
    matrix = build_dependency_matrix(nodes, edges)
    violations = detect_dependency_violations(nodes, edges, release_consistency, rules)
    health = network_health_summary(nodes, edges, violations, release_consistency, rules)
    criticality = nodes.sort_values(
        ["Criticality Score", "Risk Score"], ascending=[False, False]
    ).reset_index(drop=True)
    return {
        "nodes": nodes,
        "edges": edges,
        "matrix": matrix,
        "violations": violations,
        "health": health,
        "criticality": criticality,
    }
