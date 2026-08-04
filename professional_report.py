
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
    canvas.drawString(15 * mm, 8 * mm, "Grade-X Software Compliance Checker")
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
        author="Grade-X Software Compliance Checker",
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
) -> bytes:
    metadata = dict(metadata or {})
    if selected_files:
        overview = overview[overview["Source File"].isin(selected_files)].copy()
        details = details[details["Source File"].isin(selected_files)].copy()
        summary = summary[summary["Source File"].isin(selected_files)].copy()

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
    avg_conf = pd.to_numeric(overview.get("Confidence %", pd.Series(dtype=float)), errors="coerce").mean()
    rate = compliant / total * 100 if total else 0

    metrics = [
        ("ECUs checked", total),
        ("Compliance rate", f"{rate:.1f}%"),
        ("Critical findings", critical),
        ("Updates available", updates),
        ("Average confidence", f"{avg_conf:.1f}%" if pd.notna(avg_conf) else "0.0%"),
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
                     "Confidence %", "Matches", "Partial Matches", "Mismatches", "Missing", "Decision Reason"],
            status_col="Status",
            widths=[20*mm, 28*mm, 42*mm, 35*mm, 35*mm, 20*mm, 15*mm, 20*mm, 18*mm, 15*mm, 72*mm],
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
