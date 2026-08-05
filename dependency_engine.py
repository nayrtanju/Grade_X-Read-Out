from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("dependency_rules.json")


def load_dependency_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    with rules_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^A-Z0-9]+", str(value or "").upper())
        if token
    }


def classify_ecu_role(
    ecu_id: str,
    ecu_name: str = "",
    rules: Mapping[str, Any] | None = None,
) -> str:
    rules = dict(rules or load_dependency_rules())
    haystack = f"{ecu_id} {ecu_name}".upper()
    token_set = _tokens(haystack)

    best_role = "OTHER"
    best_score = 0
    for role, config in rules["node_roles"].items():
        if role == "OTHER":
            continue
        for alias in config.get("aliases", []):
            alias_upper = alias.upper()
            score = 0
            if alias_upper in token_set:
                score = 3
            elif alias_upper in haystack:
                score = 2
            elif any(token.startswith(alias_upper) or alias_upper.startswith(token) for token in token_set):
                score = 1
            if score > best_score:
                best_role = role
                best_score = score
    return best_role


def build_dependency_edges(
    summary: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_dependency_rules())
    if summary is None or summary.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for source_file, group in summary.groupby("Source File", dropna=False):
        nodes = []
        for _, row in group.iterrows():
            ecu_id = str(row.get("ECU ID", "") or "")
            ecu_name = str(row.get("ECU Name", "") or "")
            role = classify_ecu_role(ecu_id, ecu_name, rules)
            nodes.append({
                "Source File": source_file,
                "VIN": row.get("VIN", ""),
                "ECU": ecu_id,
                "ECU Name": ecu_name,
                "Role": role,
                "Importance": float(rules["node_roles"][role]["importance"]),
                "Role Description": rules["node_roles"][role]["description"],
            })

        node_frame = pd.DataFrame(nodes)
        role_to_ecus = defaultdict(list)
        for _, node in node_frame.iterrows():
            role_to_ecus[node["Role"]].append(node["ECU"])

        for upstream_role, downstream_role in rules["dependencies"]:
            for upstream in role_to_ecus.get(upstream_role, []):
                for downstream in role_to_ecus.get(downstream_role, []):
                    if upstream == downstream:
                        continue
                    rows.append({
                        "Source File": source_file,
                        "VIN": node_frame.iloc[0].get("VIN", "") if not node_frame.empty else "",
                        "Upstream ECU": upstream,
                        "Upstream Role": upstream_role,
                        "Downstream ECU": downstream,
                        "Downstream Role": downstream_role,
                        "Dependency Type": "LOGICAL_CONFIGURATION_DEPENDENCY",
                    })

        # Retain isolated nodes in a dedicated self-free node inventory later.
    return pd.DataFrame(rows)


def dependency_node_summary(
    summary: pd.DataFrame,
    edges: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    rules = dict(rules or load_dependency_rules())
    if summary is None or summary.empty:
        return pd.DataFrame()

    output: list[dict[str, Any]] = []
    for _, row in summary.iterrows():
        source_file = row.get("Source File", "")
        ecu = str(row.get("ECU ID", "") or "")
        role = classify_ecu_role(ecu, str(row.get("ECU Name", "") or ""), rules)
        scoped = edges[edges["Source File"] == source_file] if not edges.empty else pd.DataFrame()
        direct_downstream = (
            scoped[scoped["Upstream ECU"] == ecu]["Downstream ECU"].astype(str).unique().tolist()
            if not scoped.empty else []
        )
        direct_upstream = (
            scoped[scoped["Downstream ECU"] == ecu]["Upstream ECU"].astype(str).unique().tolist()
            if not scoped.empty else []
        )
        impact_nodes = downstream_closure(scoped, ecu)
        output.append({
            "Source File": source_file,
            "VIN": row.get("VIN", ""),
            "ECU": ecu,
            "ECU Name": row.get("ECU Name", ""),
            "Role": role,
            "Importance": float(rules["node_roles"][role]["importance"]),
            "Direct Upstream Count": len(direct_upstream),
            "Direct Upstream ECUs": ", ".join(direct_upstream),
            "Direct Downstream Count": len(direct_downstream),
            "Direct Downstream ECUs": ", ".join(direct_downstream),
            "Impact Radius": len(impact_nodes),
            "Impacted ECUs": ", ".join(sorted(impact_nodes)),
        })
    return pd.DataFrame(output)


def downstream_closure(edges: pd.DataFrame, root_ecu: str) -> set[str]:
    if edges is None or edges.empty:
        return set()
    adjacency = defaultdict(set)
    for _, edge in edges.iterrows():
        adjacency[str(edge["Upstream ECU"])].add(str(edge["Downstream ECU"]))

    visited: set[str] = set()
    queue = deque(adjacency.get(str(root_ecu), set()))
    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        queue.extend(adjacency.get(node, set()) - visited)
    return visited


def build_dependency_analysis(
    summary: pd.DataFrame,
    rules: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rules = dict(rules or load_dependency_rules())
    edges = build_dependency_edges(summary, rules)
    nodes = dependency_node_summary(summary, edges, rules)
    return nodes, edges
