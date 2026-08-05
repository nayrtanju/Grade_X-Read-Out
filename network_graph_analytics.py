from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

import pandas as pd


def _source_edges(edges: pd.DataFrame, source_file: str) -> pd.DataFrame:
    if edges is None or edges.empty:
        return pd.DataFrame()
    return edges[edges["Source File"].astype(str) == str(source_file)].copy()


def graph_statistics(nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    if nodes is None or nodes.empty:
        return pd.DataFrame()
    rows = []
    for source, group in nodes.groupby("Source File", dropna=False):
        scoped = _source_edges(edges, source)
        node_ids = set(group["ECU"].astype(str))
        indegree = {node: 0 for node in node_ids}
        outdegree = {node: 0 for node in node_ids}
        undirected: dict[str, set[str]] = defaultdict(set)
        for _, edge in scoped.iterrows():
            upstream = str(edge["Upstream ECU"])
            downstream = str(edge["Downstream ECU"])
            if upstream in node_ids and downstream in node_ids:
                outdegree[upstream] += 1
                indegree[downstream] += 1
                undirected[upstream].add(downstream)
                undirected[downstream].add(upstream)

        degree_values = [indegree[n] + outdegree[n] for n in node_ids]
        leaf_nodes = [n for n in node_ids if outdegree[n] == 0 and indegree[n] > 0]
        disconnected = [n for n in node_ids if indegree[n] == 0 and outdegree[n] == 0]
        roots = [n for n in node_ids if indegree[n] == 0 and outdegree[n] > 0]

        components = connected_components(node_ids, undirected)
        cycles = find_cycles(scoped)
        max_depth = maximum_depth(scoped, roots)
        possible_edges = max(len(node_ids) * (len(node_ids) - 1), 1)
        density = len(scoped) / possible_edges * 100
        integrity = max(
            0.0,
            100.0
            - len(disconnected) * 8.0
            - len(cycles) * 15.0
            - max(0, len(components) - 1) * 10.0,
        )

        rows.append({
            "Source File": source,
            "VIN": group.iloc[0].get("VIN", ""),
            "Node Count": len(node_ids),
            "Edge Count": len(scoped),
            "Average Degree": round(sum(degree_values) / len(node_ids), 2) if node_ids else 0,
            "Graph Density %": round(density, 2),
            "Maximum Depth": max_depth,
            "Root Nodes": len(roots),
            "Leaf Nodes": len(leaf_nodes),
            "Disconnected Nodes": len(disconnected),
            "Connected Components": len(components),
            "Circular Dependencies": len(cycles),
            "Graph Integrity Score": round(integrity, 1),
            "Graph Integrity Level": (
                "GOOD" if integrity >= 85 else
                "FAIR" if integrity >= 70 else
                "POOR" if integrity >= 50 else
                "CRITICAL"
            ),
        })
    return pd.DataFrame(rows)


def connected_components(
    nodes: set[str],
    adjacency: dict[str, set[str]],
) -> list[set[str]]:
    remaining = set(nodes)
    components: list[set[str]] = []
    while remaining:
        start = next(iter(remaining))
        component = set()
        queue = deque([start])
        while queue:
            node = queue.popleft()
            if node in component:
                continue
            component.add(node)
            queue.extend(adjacency.get(node, set()) - component)
        remaining -= component
        components.append(component)
    return components


def component_table(nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    if nodes is None or nodes.empty:
        return pd.DataFrame()
    rows = []
    for source, group in nodes.groupby("Source File", dropna=False):
        node_ids = set(group["ECU"].astype(str))
        adjacency: dict[str, set[str]] = defaultdict(set)
        scoped = _source_edges(edges, source)
        for _, edge in scoped.iterrows():
            a = str(edge["Upstream ECU"])
            b = str(edge["Downstream ECU"])
            adjacency[a].add(b)
            adjacency[b].add(a)
        for index, component in enumerate(connected_components(node_ids, adjacency), start=1):
            rows.append({
                "Source File": source,
                "VIN": group.iloc[0].get("VIN", ""),
                "Component ID": index,
                "Node Count": len(component),
                "ECUs": ", ".join(sorted(component)),
                "Is Isolated": len(component) == 1 and not adjacency.get(next(iter(component)), set()),
            })
    return pd.DataFrame(rows)


def find_cycles(edges: pd.DataFrame) -> list[list[str]]:
    if edges is None or edges.empty:
        return []
    adjacency: dict[str, set[str]] = defaultdict(set)
    for _, edge in edges.iterrows():
        adjacency[str(edge["Upstream ECU"])].add(str(edge["Downstream ECU"]))

    visited: set[str] = set()
    stack: set[str] = set()
    path: list[str] = []
    cycles: list[list[str]] = []
    signatures: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        visited.add(node)
        stack.add(node)
        path.append(node)
        for neighbour in adjacency.get(node, set()):
            if neighbour not in visited:
                visit(neighbour)
            elif neighbour in stack:
                start = path.index(neighbour)
                cycle = path[start:] + [neighbour]
                core = cycle[:-1]
                rotations = [tuple(core[i:] + core[:i]) for i in range(len(core))]
                signature = min(rotations) if rotations else tuple()
                if signature not in signatures:
                    signatures.add(signature)
                    cycles.append(cycle)
        path.pop()
        stack.remove(node)

    for node in set(adjacency) | {n for values in adjacency.values() for n in values}:
        if node not in visited:
            visit(node)
    return cycles


def cycle_table(edges: pd.DataFrame) -> pd.DataFrame:
    if edges is None or edges.empty:
        return pd.DataFrame()
    rows = []
    for source, scoped in edges.groupby("Source File", dropna=False):
        for index, cycle in enumerate(find_cycles(scoped), start=1):
            rows.append({
                "Source File": source,
                "Cycle ID": index,
                "Cycle Length": max(0, len(cycle) - 1),
                "Cycle Path": " → ".join(cycle),
                "Severity": "CRITICAL" if len(cycle) > 4 else "HIGH",
            })
    return pd.DataFrame(rows)


def maximum_depth(edges: pd.DataFrame, roots: list[str]) -> int:
    if edges is None or edges.empty:
        return 0
    adjacency: dict[str, set[str]] = defaultdict(set)
    for _, edge in edges.iterrows():
        adjacency[str(edge["Upstream ECU"])].add(str(edge["Downstream ECU"]))
    max_depth = 0
    for root in roots:
        queue = deque([(root, 0)])
        best: dict[str, int] = {root: 0}
        while queue:
            node, depth = queue.popleft()
            max_depth = max(max_depth, depth)
            for child in adjacency.get(node, set()):
                next_depth = depth + 1
                if next_depth > best.get(child, -1) and next_depth <= len(adjacency) + 1:
                    best[child] = next_depth
                    queue.append((child, next_depth))
    return max_depth


def node_heatmap(nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    if nodes is None or nodes.empty:
        return pd.DataFrame()
    rows = []
    for source, group in nodes.groupby("Source File", dropna=False):
        scoped = _source_edges(edges, source)
        for _, node in group.iterrows():
            ecu = str(node["ECU"])
            indegree = int((scoped["Downstream ECU"].astype(str) == ecu).sum()) if not scoped.empty else 0
            outdegree = int((scoped["Upstream ECU"].astype(str) == ecu).sum()) if not scoped.empty else 0
            heat = (
                float(node.get("Criticality Score", 0)) * 0.45
                + float(node.get("Risk Score", 0)) * 0.25
                + min(100, int(node.get("Impact Radius", 0)) * 12) * 0.20
                + min(100, (indegree + outdegree) * 12) * 0.10
            )
            rows.append({
                "Source File": source,
                "VIN": node.get("VIN", ""),
                "ECU": ecu,
                "Role": node.get("Role", ""),
                "Criticality": node.get("Criticality", ""),
                "Criticality Score": node.get("Criticality Score", 0),
                "Risk Score": node.get("Risk Score", 0),
                "Impact Radius": node.get("Impact Radius", 0),
                "In Degree": indegree,
                "Out Degree": outdegree,
                "Network Heat Score": round(min(100, heat), 1),
            })
    return pd.DataFrame(rows).sort_values(
        ["Network Heat Score", "Criticality Score"], ascending=[False, False]
    ).reset_index(drop=True)


def explorer_rows(nodes: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    if nodes is None or nodes.empty:
        return pd.DataFrame()
    rows = []
    for source, group in nodes.groupby("Source File", dropna=False):
        scoped = _source_edges(edges, source)
        for _, node in group.iterrows():
            ecu = str(node["ECU"])
            parents = scoped[scoped["Downstream ECU"].astype(str) == ecu]
            children = scoped[scoped["Upstream ECU"].astype(str) == ecu]
            rows.append({
                "Source File": source,
                "VIN": node.get("VIN", ""),
                "ECU": ecu,
                "ECU Name": node.get("ECU Name", ""),
                "Role": node.get("Role", ""),
                "Criticality": node.get("Criticality", ""),
                "Criticality Score": node.get("Criticality Score", 0),
                "Risk Score": node.get("Risk Score", 0),
                "Status": node.get("Status", ""),
                "Installed Release": node.get("Installed Release", ""),
                "Target Release": node.get("Target Release", ""),
                "Persistent DTC Count": node.get("Persistent DTC Count", 0),
                "Impact Radius": node.get("Impact Radius", 0),
                "Parent Count": len(parents),
                "Parents": ", ".join(parents["Upstream ECU"].astype(str)),
                "Child Count": len(children),
                "Children": ", ".join(children["Downstream ECU"].astype(str)),
                "Dependency Types": ", ".join(
                    sorted(set(
                        parents.get("Dependency Type", pd.Series(dtype=str)).astype(str).tolist()
                        + children.get("Dependency Type", pd.Series(dtype=str)).astype(str).tolist()
                    ))
                ),
            })
    return pd.DataFrame(rows)


def build_graph_analytics(nodes: pd.DataFrame, edges: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "statistics": graph_statistics(nodes, edges),
        "components": component_table(nodes, edges),
        "cycles": cycle_table(edges),
        "heatmap": node_heatmap(nodes, edges),
        "explorer": explorer_rows(nodes, edges),
    }
