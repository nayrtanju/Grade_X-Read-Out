from __future__ import annotations

import html
import math
from typing import Any

import pandas as pd


NODE_COLORS = {
    "CRITICAL": "#d62728",
    "MAJOR": "#ff7f0e",
    "NORMAL": "#1f77b4",
    "LOW": "#7f7f7f",
}


def network_svg(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    selected_ecu: str = "",
    width: int = 1000,
    height: int = 650,
) -> str:
    if nodes is None or nodes.empty:
        return "<div>No network data.</div>"

    node_rows = nodes.reset_index(drop=True)
    count = len(node_rows)
    cx, cy = width / 2, height / 2
    radius = max(120, min(width, height) * 0.36)

    positions: dict[str, tuple[float, float]] = {}
    gateway = node_rows[node_rows["Role"].astype(str) == "GATEWAY"]
    remaining = node_rows
    if not gateway.empty:
        gateway_ecu = str(gateway.iloc[0]["ECU"])
        positions[gateway_ecu] = (cx, cy)
        remaining = node_rows[node_rows["ECU"].astype(str) != gateway_ecu]

    ring_count = len(remaining)
    for index, (_, row) in enumerate(remaining.iterrows()):
        angle = (2 * math.pi * index / max(ring_count, 1)) - math.pi / 2
        positions[str(row["ECU"])] = (
            cx + radius * math.cos(angle),
            cy + radius * math.sin(angle),
        )

    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        'xmlns="http://www.w3.org/2000/svg">',
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" '
        'refX="9" refY="3" orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L0,6 L9,3 z" fill="#888"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#fafafa" rx="12"/>',
    ]

    if edges is not None and not edges.empty:
        for _, edge in edges.iterrows():
            source = str(edge["Upstream ECU"])
            target = str(edge["Downstream ECU"])
            if source not in positions or target not in positions:
                continue
            x1, y1 = positions[source]
            x2, y2 = positions[target]
            parts.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                'stroke="#999" stroke-width="1.5" marker-end="url(#arrow)" opacity="0.75"/>'
            )

    for _, row in node_rows.iterrows():
        ecu = str(row["ECU"])
        x, y = positions[ecu]
        criticality = str(row.get("Criticality", "LOW"))
        fill = NODE_COLORS.get(criticality, "#7f7f7f")
        selected = ecu == selected_ecu
        radius_node = 31 if selected else 25
        stroke = "#111" if selected else "#fff"
        stroke_width = 4 if selected else 2
        label = html.escape(ecu)
        role = html.escape(str(row.get("Role", "")))
        title = html.escape(
            f"{ecu} | {role} | Criticality {row.get('Criticality Score', 0)} | "
            f"Risk {row.get('Risk Score', 0)}"
        )
        parts.extend([
            f'<g><title>{title}</title>',
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius_node}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{stroke_width}"/>',
            f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" '
            'font-size="10" font-family="Arial" fill="white">'
            f'{label[:16]}</text>',
            f'<text x="{x:.1f}" y="{y + radius_node + 15:.1f}" text-anchor="middle" '
            'font-size="9" font-family="Arial" fill="#333">'
            f'{role}</text></g>',
        ])

    parts.append("</svg>")
    return "".join(parts)


def heat_bar_html(heatmap: pd.DataFrame, limit: int = 20) -> str:
    if heatmap is None or heatmap.empty:
        return "<div>No heatmap data.</div>"
    rows = heatmap.head(limit)
    parts = ['<div style="font-family:Arial,sans-serif">']
    for _, row in rows.iterrows():
        score = float(row.get("Network Heat Score", 0))
        parts.append(
            '<div style="margin:8px 0">'
            f'<div style="display:flex;justify-content:space-between">'
            f'<span>{html.escape(str(row.get("ECU", "")))}</span>'
            f'<strong>{score:.1f}</strong></div>'
            '<div style="height:12px;background:#eee;border-radius:6px;overflow:hidden">'
            f'<div style="height:100%;width:{score:.1f}%;background:'
            f'linear-gradient(90deg,#2ca02c,#ffbf00,#d62728)"></div></div></div>'
        )
    parts.append("</div>")
    return "".join(parts)
