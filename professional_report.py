
from __future__ import annotations

import io
from datetime import datetime
from typing import Mapping, Sequence

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

STATUS_COLORS = {
    "COMPLIANT": colors.HexColor("#C6EFCE"),
    "MATCH": colors.HexColor("#C6EFCE"),
    "UPDATE_AVAILABLE": colors.HexColor("#FFF2CC"),
    "PARTIAL_MATCH": colors.HexColor("#FFEB9C"),
    "PART_MATCH": colors.HexColor("#FFEB9C"),
    "REVIEW": colors.HexColor("#FCE4D6"),
    "MISSING": colors.HexColor("#FCE4D6"),
    "MISMATCH": colors.HexColor("#FFC7CE"),
    "WRONG_RELEASE": colors.HexColor("#F4B084"),
    "NO_REFERENCE": colors.HexColor("#D9E1F2"),
    "NOT_APPLICABLE": colors.HexColor("#E7E6E6"),
    "HIGH": colors.HexColor("#FFC7CE"),
    "MEDIUM": colors.HexColor("#FFF2CC"),
    "LOW": colors.HexColor("#D9EAF7"),
    "HIGH": colors.HexColor("#FFC7CE"),
    "CRITICAL": colors.HexColor("#F4B084"),
}

PRIMARY = colors.HexColor("#1F4E78")
SECONDARY = colors.HexColor("#44546A")
LIGHT = colors.HexColor("#F4F7FA")
BORDER = colors.HexColor("#CBD5E1")


def _safe(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def _paragraph(value, style):
    return Paragraph(_safe(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), style)


def _status_count(overview: pd.DataFrame, status: str) -> int:
    return int((overview.get("Status", pd.Series(dtype=str)).astype(str) == status).sum())


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.line(15 * mm, 13 * mm, doc.pagesize[0] - 15 * mm, 13 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(SECONDARY)
    canvas.drawString(15 * mm, 8 * mm, "Grade-X Software Configuration Intelligence Platform")
    canvas.drawRightString(doc.pagesize[0] - 15 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _doc_template(buffer: io.BytesIO) -> BaseDocTemplate:
    doc = BaseDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=18 * mm,
        title="Grade-X Software Compliance Report",
        author="Grade-X Software Configuration Intelligence Platform",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_footer)])
    return doc


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="GXTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=22, leading=26, textColor=PRIMARY, alignment=TA_LEFT, spaceAfter=10
    ))
    styles.add(ParagraphStyle(
        name="GXSubtitle", parent=styles["Normal"], fontSize=11, leading=15,
        textColor=SECONDARY, spaceAfter=14
    ))
    styles.add(ParagraphStyle(
        name="GXH1", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=15, leading=18, textColor=PRIMARY, spaceBefore=5, spaceAfter=8
    ))
    styles.add(ParagraphStyle(
        name="GXH2", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=11, leading=14, textColor=SECONDARY, spaceBefore=4, spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        name="GXBody", parent=styles["BodyText"], fontSize=8.5, leading=11,
        textColor=colors.HexColor("#1F2937")
    ))
    styles.add(ParagraphStyle(
        name="GXSmall", parent=styles["BodyText"], fontSize=7.2, leading=9,
        textColor=colors.HexColor("#334155")
    ))
    styles.add(ParagraphStyle(
        name="GXMetric", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=17, leading=20, alignment=TA_CENTER, textColor=PRIMARY
    ))
    styles.add(ParagraphStyle(
        name="GXMetricLabel", parent=styles["Normal"], fontSize=8,
        alignment=TA_CENTER, textColor=SECONDARY
    ))
    return styles


def _table(data, col_widths=None, header=True, status_column=None, repeat_rows=1):
    table = Table(data, colWidths=col_widths, repeatRows=repeat_rows if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        commands += [
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    if status_column is not None:
        for row_index in range(1 if header else 0, len(data)):
            status = _safe(data[row_index][status_column])
            fill = STATUS_COLORS.get(status)
            if fill:
                commands.append(("BACKGROUND", (0, row_index), (-1, row_index), fill))
    table.setStyle(TableStyle(commands))
    return table


def _df_table(df: pd.DataFrame, styles, columns: Sequence[str] | None = None, max_rows: int | None = None,
              status_col: str | None = None, widths=None):
    if columns is not None:
        visible = [c for c in columns if c in df.columns]
        df = df[visible]
    if max_rows is not None:
        df = df.head(max_rows)
    headers = [_paragraph(c, styles["GXSmall"]) for c in df.columns]
    rows = []
    for _, row in df.iterrows():
        rows.append([_paragraph(row.get(c, ""), styles["GXSmall"]) for c in df.columns])
    status_index = list(df.columns).index(status_col) if status_col and status_col in df.columns else None
    return _table([headers] + rows, col_widths=widths, status_column=status_index)


def build_pdf_report(
    overview: pd.DataFrame,
    details: pd.DataFrame,
    summary: pd.DataFrame,
    release_sheet: str,
    metadata: Mapping[str, str] | None = None,
    logo_bytes: bytes | None = None,
    selected_files: Sequence[str] | None = None,
    dtc_summary: pd.DataFrame | None = None,
    dtc_events: pd.DataFrame | None = None,
    risk_breakdown: pd.DataFrame | None = None,
    vehicle_health: pd.DataFrame | None = None,
    decision_actions: pd.DataFrame | None = None,
    vehicle_decisions: pd.DataFrame | None = None,
    warranty_summary: pd.DataFrame | None = None,
    engineering_summaries: pd.DataFrame | None = None,
    dependency_nodes: pd.DataFrame | None = None,
    dependency_edges: pd.DataFrame | None = None,
    vehicle_root_causes: pd.DataFrame | None = None,
    root_cause_ranking: pd.DataFrame | None = None,
    release_consistency: pd.DataFrame | None = None,
    consistency_fields: pd.DataFrame | None = None,
    ecu_consistency: pd.DataFrame | None = None,
    fleet_kpis: pd.DataFrame | None = None,
    fleet_problematic_ecus: pd.DataFrame | None = None,
    fleet_dtc_ranking: pd.DataFrame | None = None,
    fleet_release_patterns: pd.DataFrame | None = None,
    fleet_root_ecus: pd.DataFrame | None = None,
    fleet_warranty_patterns: pd.DataFrame | None = None,
    fleet_alerts: pd.DataFrame | None = None,
    engineering_findings: pd.DataFrame | None = None,
    assistant_summary: pd.DataFrame | None = None,
    assistant_action_plan: pd.DataFrame | None = None,
) -> bytes:
    metadata = dict(metadata or {})
    if selected_files:
        overview = overview[overview["Source File"].isin(selected_files)].copy()
        details = details[details["Source File"].isin(selected_files)].copy()
        summary = summary[summary["Source File"].isin(selected_files)].copy()
        if dtc_summary is not None and not dtc_summary.empty and "Mapped Session" in dtc_summary.columns:
            dtc_summary = dtc_summary[dtc_summary["Mapped Session"].isin(selected_files)].copy()
        if dtc_events is not None and not dtc_events.empty and "Mapped Session" in dtc_events.columns:
            dtc_events = dtc_events[dtc_events["Mapped Session"].isin(selected_files)].copy()
        if decision_actions is not None and not decision_actions.empty and "Source File" in decision_actions.columns:
            decision_actions = decision_actions[
                decision_actions["Source File"].isin(selected_files)
            ].copy()
        if vehicle_decisions is not None and not vehicle_decisions.empty and "Source File" in vehicle_decisions.columns:
            vehicle_decisions = vehicle_decisions[
                vehicle_decisions["Source File"].isin(selected_files)
            ].copy()
        if warranty_summary is not None and not warranty_summary.empty and "Source File" in warranty_summary.columns:
            warranty_summary = warranty_summary[
                warranty_summary["Source File"].isin(selected_files)
            ].copy()
        if engineering_summaries is not None and not engineering_summaries.empty and "Source File" in engineering_summaries.columns:
            engineering_summaries = engineering_summaries[
                engineering_summaries["Source File"].isin(selected_files)
            ].copy()
        if dependency_nodes is not None and not dependency_nodes.empty and "Source File" in dependency_nodes.columns:
            dependency_nodes = dependency_nodes[
                dependency_nodes["Source File"].isin(selected_files)
            ].copy()
        if dependency_edges is not None and not dependency_edges.empty and "Source File" in dependency_edges.columns:
            dependency_edges = dependency_edges[
                dependency_edges["Source File"].isin(selected_files)
            ].copy()
        if vehicle_root_causes is not None and not vehicle_root_causes.empty and "Source File" in vehicle_root_causes.columns:
            vehicle_root_causes = vehicle_root_causes[
                vehicle_root_causes["Source File"].isin(selected_files)
            ].copy()
        if root_cause_ranking is not None and not root_cause_ranking.empty and "Source File" in root_cause_ranking.columns:
            root_cause_ranking = root_cause_ranking[
                root_cause_ranking["Source File"].isin(selected_files)
            ].copy()
        if release_consistency is not None and not release_consistency.empty and "Source File" in release_consistency.columns:
            release_consistency = release_consistency[
                release_consistency["Source File"].isin(selected_files)
            ].copy()
        if consistency_fields is not None and not consistency_fields.empty and "Source File" in consistency_fields.columns:
            consistency_fields = consistency_fields[
                consistency_fields["Source File"].isin(selected_files)
            ].copy()
        if ecu_consistency is not None and not ecu_consistency.empty and "Source File" in ecu_consistency.columns:
            ecu_consistency = ecu_consistency[
                ecu_consistency["Source File"].isin(selected_files)
            ].copy()

    buffer = io.BytesIO()
    doc = _doc_template(buffer)
    styles = _styles()
    story = []

    # Cover
    if logo_bytes:
        try:
            logo = Image(io.BytesIO(logo_bytes), width=42 * mm, height=18 * mm, kind="proportional")
            story.append(logo)
            story.append(Spacer(1, 5 * mm))
        except Exception:
            pass

    story.append(Paragraph(metadata.get("report_title") or "Grade-X Software Compliance Report", styles["GXTitle"]))
    story.append(Paragraph(
        metadata.get("report_subtitle") or "ECU software and hardware compliance assessment",
        styles["GXSubtitle"],
    ))

    info_rows = [
        ["Target release", release_sheet],
        ["Prepared by", metadata.get("prepared_by", "")],
        ["Department / Project", metadata.get("project", "")],
        ["Report date", metadata.get("report_date", datetime.now().strftime("%Y-%m-%d %H:%M"))],
        ["Reference file", metadata.get("reference_file", "")],
        ["Vehicle/session count", str(overview["Source File"].nunique() if "Source File" in overview else 0)],
    ]
    story.append(_table(
        [[_paragraph("Report information", styles["GXBody"]), ""]] +
        [[_paragraph(a, styles["GXSmall"]), _paragraph(b, styles["GXSmall"])] for a, b in info_rows],
        col_widths=[45 * mm, 120 * mm],
        header=True,
    ))
    story.append(Spacer(1, 7 * mm))

    total = len(overview)
    compliant = _status_count(overview, "COMPLIANT")
    critical = int(overview.get("Status", pd.Series(dtype=str)).isin(["MISMATCH", "WRONG_RELEASE"]).sum())
    updates = _status_count(overview, "UPDATE_AVAILABLE")
    persistent_dtcs = int(pd.to_numeric(
        overview.get("Persistent DTC Count", pd.Series(dtype=float)), errors="coerce"
    ).fillna(0).sum())
    avg_conf = pd.to_numeric(overview.get("Confidence %", pd.Series(dtype=float)), errors="coerce").mean()
    rate = compliant / total * 100 if total else 0

    metrics = [
        ("ECUs checked", total),
        ("Compliance rate", f"{rate:.1f}%"),
        ("Critical findings", critical),
        ("Updates available", updates),
        ("Persistent DTCs", persistent_dtcs),
    ]
    metric_cells = []
    for label, value in metrics:
        metric_cells.append([
            _paragraph(value, styles["GXMetric"]),
            _paragraph(label, styles["GXMetricLabel"]),
        ])
    metric_table = Table([metric_cells], colWidths=[49 * mm] * len(metric_cells))
    metric_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(metric_table)
    story.append(Spacer(1, 6 * mm))

    if metadata.get("executive_comment"):
        story.append(Paragraph("Executive comment", styles["GXH1"]))
        story.append(Paragraph(metadata["executive_comment"], styles["GXBody"]))
    if metadata.get("generated_fleet_summary"):
        story.append(Paragraph("Automatic fleet summary", styles["GXH1"]))
        story.append(Paragraph(metadata["generated_fleet_summary"], styles["GXBody"]))
    if metadata.get("generated_executive_summary"):
        story.append(Paragraph("Automatic executive summary", styles["GXH1"]))
        story.append(Paragraph(metadata["generated_executive_summary"], styles["GXBody"]))

    story.append(PageBreak())

    # Executive summary
    story.append(Paragraph("Executive Summary", styles["GXH1"]))
    status_order = [
        "COMPLIANT", "UPDATE_AVAILABLE", "PARTIAL_MATCH", "REVIEW",
        "MISMATCH", "WRONG_RELEASE", "NO_REFERENCE"
    ]
    status_rows = [["Status", "Count", "Share"]]
    status_series = overview.get("Status", pd.Series(dtype=str)).astype(str)
    for status in status_order:
        count = int((status_series == status).sum())
        status_rows.append([status, count, f"{count / total * 100:.1f}%" if total else "0.0%"])
    story.append(_table(
        [[_paragraph(v, styles["GXSmall"]) for v in row] for row in status_rows],
        col_widths=[65 * mm, 30 * mm, 35 * mm],
        status_column=0,
    ))
    story.append(Spacer(1, 6 * mm))

    vehicle_columns = [
        "Source File", "VIN", "ECUs", "Compliant", "Update Available",
        "Mismatch", "Wrong Release", "Review", "Compliance Rate %"
    ]
    if "Source File" in overview:
        vehicle_rows = []
        for source, group in overview.groupby("Source File", dropna=False):
            s = group["Status"].astype(str)
            vin = group.get("VIN", pd.Series(dtype=str)).dropna()
            vehicle_rows.append({
                "Source File": source,
                "VIN": vin.iloc[0] if not vin.empty else "",
                "ECUs": len(group),
                "Compliant": int((s == "COMPLIANT").sum()),
                "Update Available": int((s == "UPDATE_AVAILABLE").sum()),
                "Mismatch": int((s == "MISMATCH").sum()),
                "Wrong Release": int((s == "WRONG_RELEASE").sum()),
                "Review": int(s.isin(["REVIEW", "PARTIAL_MATCH"]).sum()),
                "Compliance Rate %": round((s == "COMPLIANT").sum() / len(group) * 100, 1) if len(group) else 0,
            })
        vehicle_df = pd.DataFrame(vehicle_rows)
        story.append(Paragraph("Vehicle Summary", styles["GXH2"]))
        story.append(_df_table(vehicle_df, styles, columns=vehicle_columns, widths=[
            48*mm, 35*mm, 16*mm, 20*mm, 24*mm, 19*mm, 23*mm, 17*mm, 25*mm
        ]))
        story.append(Spacer(1, 6 * mm))

    # Priority actions
    critical_df = overview[
        overview.get("Status", pd.Series(dtype=str)).isin(
            ["MISMATCH", "WRONG_RELEASE", "UPDATE_AVAILABLE", "REVIEW", "PARTIAL_MATCH"]
        )
    ].copy()
    if not critical_df.empty:
        critical_df["Priority"] = critical_df["Status"].map({
            "MISMATCH": "1 - Critical",
            "WRONG_RELEASE": "1 - Critical",
            "UPDATE_AVAILABLE": "2 - Planned",
            "REVIEW": "3 - Review",
            "PARTIAL_MATCH": "3 - Review",
        })
        story.append(Paragraph("Priority Actions", styles["GXH2"]))
        story.append(_df_table(
            critical_df.sort_values(["Priority", "Source File", "ECU"]),
            styles,
            columns=["Priority", "Source File", "VIN", "ECU", "Status", "Installed Release",
                     "Target Release", "Confidence %", "Decision Reason"],
            max_rows=40,
            status_col="Status",
            widths=[22*mm, 42*mm, 31*mm, 21*mm, 29*mm, 34*mm, 34*mm, 20*mm, 70*mm],
        ))
    else:
        story.append(Paragraph("No open compliance actions were identified.", styles["GXBody"]))

    if dtc_summary is not None and not dtc_summary.empty:
        story.append(PageBreak())
        story.append(Paragraph("Diagnostic Trouble Codes", styles["GXH1"]))
        story.append(_df_table(
            dtc_summary,
            styles,
            columns=["Mapped Session", "ECU", "DTC", "Failure Type", "Category",
                     "Occurrences", "Read Cycles", "Seen After Clear", "Persistence", "Severity"],
            status_col="Severity",
            widths=[45*mm, 25*mm, 22*mm, 22*mm, 38*mm, 20*mm, 20*mm, 26*mm, 45*mm, 22*mm],
        ))

    if assistant_summary is not None and not assistant_summary.empty:
        story.append(PageBreak())
        story.append(Paragraph("Engineering Assistant & Executive Summary", styles["GXH1"]))
        story.append(_df_table(
            assistant_summary,
            styles,
            columns=["Source File", "VIN", "Executive Vehicle Status",
                     "Vehicle Health Score", "Release Consistency Score",
                     "Most Probable Root ECU", "Root Cause Confidence %",
                     "Warranty Recommendation", "Assistant Confidence %",
                     "Critical Findings", "Primary Finding",
                     "Primary Root Cause", "Required First Action"],
        ))

    if engineering_findings is not None and not engineering_findings.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Engineering Findings", styles["GXH2"]))
        story.append(_df_table(
            engineering_findings.head(60),
            styles,
            columns=["Source File", "VIN", "ECU", "Category", "Severity",
                     "Finding Title", "Engineering Finding", "Evidence",
                     "Recommended Action"],
            status_col="Severity",
        ))

    if assistant_action_plan is not None and not assistant_action_plan.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Phased Action Plan", styles["GXH2"]))
        story.append(_df_table(
            assistant_action_plan.head(60),
            styles,
            columns=["Source File", "VIN", "Phase", "Phase Order", "Priority",
                     "ECU", "Action", "Reason", "Evidence"],
            status_col="Priority",
        ))

    if fleet_kpis is not None and not fleet_kpis.empty:
        story.append(PageBreak())
        story.append(Paragraph("Fleet Intelligence Overview", styles["GXH1"]))
        story.append(_df_table(
            fleet_kpis,
            styles,
            columns=list(fleet_kpis.columns),
        ))

    if fleet_alerts is not None and not fleet_alerts.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Fleet Alerts", styles["GXH2"]))
        story.append(_df_table(
            fleet_alerts,
            styles,
            columns=["Alert Level", "Alert", "Evidence"],
            status_col="Alert Level",
            widths=[25*mm, 110*mm, 65*mm],
        ))

    if fleet_problematic_ecus is not None and not fleet_problematic_ecus.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Top Problematic ECUs", styles["GXH2"]))
        story.append(_df_table(
            fleet_problematic_ecus.head(15),
            styles,
            columns=["ECU", "Vehicles Seen", "Assessments", "Problem Count",
                     "Problem Rate %", "Average Risk Score", "Critical Findings",
                     "Persistent DTCs", "Fleet Problem Score", "Most Common Status"],
        ))

    if fleet_dtc_ranking is not None and not fleet_dtc_ranking.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Top DTC Patterns", styles["GXH2"]))
        story.append(_df_table(
            fleet_dtc_ranking.head(15),
            styles,
            columns=["DTC", "Failure Type", "Affected ECUs", "Affected Vehicles",
                     "Occurrences", "Persistent Records", "Highest Severity", "ECUs"],
        ))

    if fleet_release_patterns is not None and not fleet_release_patterns.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Release Patterns", styles["GXH2"]))
        story.append(_df_table(
            fleet_release_patterns.head(15),
            styles,
            columns=list(fleet_release_patterns.columns),
        ))

    if fleet_root_ecus is not None and not fleet_root_ecus.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Root ECU Patterns", styles["GXH2"]))
        story.append(_df_table(
            fleet_root_ecus.head(15),
            styles,
            columns=list(fleet_root_ecus.columns),
        ))

    if fleet_warranty_patterns is not None and not fleet_warranty_patterns.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Warranty Patterns", styles["GXH2"]))
        story.append(_df_table(
            fleet_warranty_patterns.head(15),
            styles,
            columns=list(fleet_warranty_patterns.columns),
        ))

    if release_consistency is not None and not release_consistency.empty:
        story.append(PageBreak())
        story.append(Paragraph("Release Consistency & Mixed Package Analysis", styles["GXH1"]))
        story.append(_df_table(
            release_consistency,
            styles,
            columns=["Source File", "VIN", "ECUs", "Release Consistency Score",
                     "Release Consistency Level", "Consistency Confidence %",
                     "Dominant Installed Release Family", "Dominant Target Release Family",
                     "Mixed Release Ratio %", "Mixed Package Detected",
                     "Variant Review Required", "Critical Package Mismatches",
                     "Hardware/Part Mismatches", "Consistency Findings"],
            widths=[36*mm, 27*mm, 12*mm, 23*mm, 26*mm, 22*mm, 38*mm,
                    38*mm, 20*mm, 22*mm, 22*mm, 20*mm, 20*mm, 65*mm],
        ))

    if consistency_fields is not None and not consistency_fields.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Field Consistency", styles["GXH2"]))
        story.append(_df_table(
            consistency_fields,
            styles,
            columns=["Source File", "VIN", "Field", "Weight", "Applicable ECUs",
                     "Weighted Score %", "Matches", "Partial Matches",
                     "Mismatches", "Missing"],
            widths=[38*mm, 27*mm, 33*mm, 17*mm, 20*mm, 23*mm,
                    17*mm, 22*mm, 18*mm, 16*mm],
        ))

    if ecu_consistency is not None and not ecu_consistency.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("ECU Package Consistency", styles["GXH2"]))
        top_outliers = ecu_consistency.sort_values(
            ["Source File", "ECU Consistency Score", "ECU"]
        ).groupby("Source File", dropna=False).head(20)
        story.append(_df_table(
            top_outliers,
            styles,
            columns=["Source File", "VIN", "ECU", "Status", "Installed Release",
                     "Installed Release Family", "Dominant Release Family Match",
                     "Critical Field Mismatches", "Total Field Mismatches",
                     "ECU Consistency Score", "Package Role"],
            widths=[36*mm, 27*mm, 19*mm, 24*mm, 38*mm, 37*mm, 24*mm,
                    22*mm, 20*mm, 22*mm, 24*mm],
        ))

    if vehicle_root_causes is not None and not vehicle_root_causes.empty:
        story.append(PageBreak())
        story.append(Paragraph("ECU Dependency & Root Cause Analysis", styles["GXH1"]))
        story.append(_df_table(
            vehicle_root_causes,
            styles,
            columns=["Source File", "VIN", "Most Probable Root ECU",
                     "Root ECU Role", "Root Cause Confidence %",
                     "Root Cause Score", "Runner-Up ECU", "Score Gap",
                     "Impact Radius", "Potentially Affected ECUs",
                     "Primary Vehicle Root Cause", "Recommended Root Action"],
            widths=[38*mm, 27*mm, 27*mm, 27*mm, 23*mm, 19*mm, 22*mm,
                    16*mm, 18*mm, 55*mm, 67*mm, 58*mm],
        ))

    if root_cause_ranking is not None and not root_cause_ranking.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Root Cause Candidate Ranking", styles["GXH2"]))
        top_candidates = root_cause_ranking.sort_values(
            ["Source File", "Root Cause Rank"]
        ).groupby("Source File", dropna=False).head(10)
        story.append(_df_table(
            top_candidates,
            styles,
            columns=["Source File", "VIN", "Root Cause Rank", "ECU", "ECU Role",
                     "Root Cause Score", "Risk Score", "Status",
                     "Persistent DTC Count", "Importance", "Impact Radius",
                     "Root Cause Evidence"],
            widths=[37*mm, 27*mm, 17*mm, 20*mm, 28*mm, 20*mm, 17*mm,
                    24*mm, 20*mm, 16*mm, 17*mm, 75*mm],
        ))

    if dependency_nodes is not None and not dependency_nodes.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Dependency Impact Summary", styles["GXH2"]))
        top_nodes = dependency_nodes.sort_values(
            ["Impact Radius", "Importance"], ascending=[False, False]
        ).head(30)
        story.append(_df_table(
            top_nodes,
            styles,
            columns=["Source File", "VIN", "ECU", "Role", "Importance",
                     "Direct Upstream Count", "Direct Downstream Count",
                     "Impact Radius", "Impacted ECUs"],
            widths=[38*mm, 27*mm, 20*mm, 29*mm, 17*mm, 22*mm, 25*mm,
                    18*mm, 82*mm],
        ))

    if warranty_summary is not None and not warranty_summary.empty:
        story.append(PageBreak())
        story.append(Paragraph("Vehicle Health & Warranty Triage", styles["GXH1"]))
        story.append(_df_table(
            warranty_summary,
            styles,
            columns=["Source File", "VIN", "Vehicle Health Score",
                     "Vehicle Health Level", "Warranty Recommendation Label",
                     "Warranty Priority", "Warranty Rationale",
                     "Required Next Step", "Lead ECU", "Lead Risk Score",
                     "Lead Root Cause"],
            widths=[38*mm, 28*mm, 22*mm, 22*mm, 37*mm, 18*mm, 62*mm,
                    66*mm, 18*mm, 18*mm, 60*mm],
        ))

    if engineering_summaries is not None and not engineering_summaries.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Automatic Engineering Summaries", styles["GXH2"]))
        for _, summary_row in engineering_summaries.iterrows():
            story.append(KeepTogether([
                Paragraph(
                    f"Vehicle / Session: {_safe(summary_row.get('Source File', ''))}",
                    styles["GXH2"],
                ),
                Paragraph(
                    _safe(summary_row.get("Combined Engineering Summary", "")),
                    styles["GXBody"],
                ),
                Spacer(1, 4 * mm),
            ]))

    if vehicle_decisions is not None and not vehicle_decisions.empty:
        story.append(PageBreak())
        story.append(Paragraph("Engineering Decision Summary", styles["GXH1"]))
        story.append(_df_table(
            vehicle_decisions,
            styles,
            columns=["Source File", "VIN", "ECUs", "High/Critical Decisions",
                     "Manual Reviews", "Lead ECU", "Overall Decision",
                     "Overall Urgency", "Decision Confidence %",
                     "Primary Root Cause", "Recommended Next Step"],
            status_col="Overall Urgency",
            widths=[39*mm, 29*mm, 13*mm, 24*mm, 20*mm, 20*mm, 38*mm,
                    22*mm, 23*mm, 60*mm, 62*mm],
        ))

    if decision_actions is not None and not decision_actions.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Priority Recommended Actions", styles["GXH2"]))
        top_actions = decision_actions.sort_values(
            ["Decision Urgency", "Risk Score", "Action Priority"],
            ascending=[False, False, True],
        ).head(50)
        story.append(_df_table(
            top_actions,
            styles,
            columns=["Source File", "VIN", "ECU", "Decision", "Decision Urgency",
                     "Decision Confidence %", "Risk Score", "Risk Level",
                     "Action Priority", "Recommended Action",
                     "Primary Root Cause"],
            status_col="Decision Urgency",
            widths=[36*mm, 27*mm, 18*mm, 38*mm, 22*mm, 22*mm, 17*mm,
                    18*mm, 17*mm, 65*mm, 65*mm],
        ))

    if vehicle_health is not None and not vehicle_health.empty:
        story.append(PageBreak())
        story.append(Paragraph("Vehicle Health & Risk Summary", styles["GXH1"]))
        story.append(_df_table(
            vehicle_health,
            styles,
            columns=["Source File", "VIN", "ECUs", "Average Risk Score", "Maximum Risk Score",
                     "Critical ECUs", "High-Risk ECUs", "Vehicle Health Score",
                     "Vehicle Health Level", "Highest-Risk ECU", "Highest-Risk Contributors"],
            widths=[42*mm, 30*mm, 14*mm, 24*mm, 24*mm, 20*mm, 22*mm, 25*mm, 25*mm, 25*mm, 55*mm],
        ))

    if risk_breakdown is not None and not risk_breakdown.empty:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Top Risk Contributors", styles["GXH2"]))
        top_risk = risk_breakdown.sort_values(
            ["Risk Score", "Rank"], ascending=[False, True]
        ).head(40)
        story.append(_df_table(
            top_risk,
            styles,
            columns=["Source File", "VIN", "ECU", "Risk Score", "Risk Level",
                     "Rank", "Factor", "Points", "Evidence"],
            status_col="Risk Level",
            widths=[40*mm, 30*mm, 20*mm, 20*mm, 20*mm, 12*mm, 40*mm, 16*mm, 65*mm],
        ))

    story.append(PageBreak())

    # ECU details by vehicle
    detail_lookup = details.copy()
    for source, group in overview.groupby("Source File", dropna=False):
        story.append(Paragraph(f"Vehicle / Session: {_safe(source)}", styles["GXH1"]))
        vin_series = group.get("VIN", pd.Series(dtype=str)).dropna()
        vin = vin_series.iloc[0] if not vin_series.empty else ""
        story.append(Paragraph(f"VIN: {_safe(vin)} | Target release: {_safe(release_sheet)}", styles["GXSubtitle"]))

        story.append(_df_table(
            group.sort_values(["Status", "ECU"]),
            styles,
            columns=["ECU", "Status", "Matched Variant", "Installed Release", "Target Release",
                     "Confidence %", "Risk Score", "Risk Level", "Decision", "Decision Urgency",
                     "Decision Confidence %", "Primary Root Cause",
                     "External DTC Count", "Persistent DTC Count", "DTC Codes",
                     "Matches", "Partial Matches", "Mismatches", "Missing", "Decision Reason"],
            status_col="Status",
            widths=[18*mm, 25*mm, 35*mm, 31*mm, 31*mm, 18*mm, 18*mm, 20*mm, 40*mm,
                    13*mm, 17*mm, 15*mm, 13*mm, 55*mm],
        ))
        story.append(Spacer(1, 5 * mm))

        source_details = detail_lookup[detail_lookup["Source File"] == source] if "Source File" in detail_lookup else pd.DataFrame()
        problem_details = source_details[source_details["Status"].astype(str).isin(["MISMATCH", "MISSING", "PART_MATCH"])] if not source_details.empty else pd.DataFrame()
        if not problem_details.empty:
            story.append(Paragraph("Identifier Deviations", styles["GXH2"]))
            story.append(_df_table(
                problem_details,
                styles,
                columns=["ECU", "Field", "Actual", "Expected", "Status", "Reason"],
                status_col="Status",
                widths=[22*mm, 35*mm, 48*mm, 48*mm, 28*mm, 95*mm],
            ))
        story.append(PageBreak())

    notes = metadata.get("engineering_notes", "")
    if notes:
        story.append(Paragraph("Engineering Notes", styles["GXH1"]))
        story.append(Paragraph(notes, styles["GXBody"]))

    story.append(Paragraph("Assessment disclaimer", styles["GXH1"]))
    story.append(Paragraph(
        "This report is a decision-support output based on Grade-X ECU identification data and the selected "
        "FRS/IASRC reference workbook. UPDATE_AVAILABLE and WRONG_RELEASE classifications are inferred from "
        "identifier matching and must not be treated as automatic approval for ECU programming or replacement.",
        styles["GXBody"],
    ))

    doc.build(story)
    return buffer.getvalue()
