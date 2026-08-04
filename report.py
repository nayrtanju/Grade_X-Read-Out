
from __future__ import annotations

import io
from datetime import datetime
from typing import Mapping

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from release_viewer import release_detail_rows
from dashboard import action_items, confidence_distribution, status_counts, vehicle_summary

COLORS = {
    "MATCH": "C6EFCE", "COMPLIANT": "C6EFCE",
    "UPDATE_AVAILABLE": "FFF2CC", "PART_MATCH": "FFEB9C", "PARTIAL_MATCH": "FFEB9C",
    "REVIEW": "FCE4D6", "MISSING": "FCE4D6",
    "MISMATCH": "FFC7CE", "WRONG_RELEASE": "F4B084",
    "NO_REFERENCE": "D9E1F2", "NOT_APPLICABLE": "E7E6E6",
    "HIGH": "FFC7CE", "MEDIUM": "FFF2CC", "LOW": "D9EAF7",
}
HEADER = "1F4E78"
SUBHEADER = "D9EAF7"
TEXT_DARK = "1F2937"
BORDER_COLOR = "D9E1F2"


def _safe(value):
    if isinstance(value, tuple):
        return ".".join(map(str, value))
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return value.item() if hasattr(value, "item") else value


def _style_header(ws, row=1):
    for cell in ws[row]:
        cell.fill = PatternFill("solid", fgColor=HEADER)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _add_sheet(wb: Workbook, name: str, df: pd.DataFrame, status_col: str | None = None):
    ws = wb.create_sheet(name[:31])
    ws.append(list(df.columns))
    for row in df.itertuples(index=False, name=None):
        ws.append([_safe(v) for v in row])
    _style_header(ws)
    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"
    thin = Side(style="thin", color=BORDER_COLOR)
    status_idx = list(df.columns).index(status_col) + 1 if status_col and status_col in df.columns else None
    for r in range(2, ws.max_row + 1):
        status = str(ws.cell(r, status_idx).value or "") if status_idx else ""
        fill = PatternFill("solid", fgColor=COLORS.get(status, "FFFFFF"))
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(r, c)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(bottom=thin)
            if status_idx:
                cell.fill = fill
    for c in range(1, ws.max_column + 1):
        width = max([len(str(ws.cell(r, c).value or "")) for r in range(1, min(ws.max_row, 300) + 1)] + [10]) + 2
        ws.column_dimensions[get_column_letter(c)].width = min(max(width, 11), 48)
    ws.sheet_view.showGridLines = False
    return ws


def _executive_summary_sheet(
    wb: Workbook,
    overview: pd.DataFrame,
    release_sheet: str,
    metadata: Mapping[str, str],
):
    ws = wb.create_sheet("Executive Summary")
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:H2")
    ws["A1"] = metadata.get("report_title") or "Grade-X Software Compliance Report"
    ws["A1"].font = Font(size=20, bold=True, color=HEADER)
    ws["A1"].alignment = Alignment(vertical="center")

    ws["A4"] = "Target release"
    ws["B4"] = release_sheet
    ws["D4"] = "Prepared by"
    ws["E4"] = metadata.get("prepared_by", "")
    ws["A5"] = "Department / Project"
    ws["B5"] = metadata.get("project", "")
    ws["D5"] = "Report date"
    ws["E5"] = metadata.get("report_date", datetime.now().strftime("%Y-%m-%d %H:%M"))
    ws["A6"] = "Reference file"
    ws["B6"] = metadata.get("reference_file", "")
    ws["D6"] = "Vehicles / sessions"
    ws["E6"] = int(overview["Source File"].nunique()) if "Source File" in overview else 0

    for cell in ("A4", "D4", "A5", "D5", "A6", "D6"):
        ws[cell].font = Font(bold=True, color=TEXT_DARK)
        ws[cell].fill = PatternFill("solid", fgColor=SUBHEADER)

    statuses = overview.get("Status", pd.Series(dtype=str)).astype(str)
    total = len(overview)
    compliant = int((statuses == "COMPLIANT").sum())
    critical = int(statuses.isin(["MISMATCH", "WRONG_RELEASE"]).sum())
    updates = int((statuses == "UPDATE_AVAILABLE").sum())
    persistent_dtcs = int(pd.to_numeric(
        overview.get("Persistent DTC Count", pd.Series(dtype=float)), errors="coerce"
    ).fillna(0).sum())
    avg_conf = pd.to_numeric(overview.get("Confidence %", pd.Series(dtype=float)), errors="coerce").mean()
    compliance_rate = compliant / total * 100 if total else 0

    metrics = [
        ("ECUs checked", total, "D9EAF7"),
        ("Compliance rate", f"{compliance_rate:.1f}%", "C6EFCE"),
        ("Critical findings", critical, "FFC7CE" if critical else "C6EFCE"),
        ("Updates available", updates, "FFF2CC"),
        ("Persistent DTCs", persistent_dtcs, "FCE4D6" if persistent_dtcs else "C6EFCE"),
    ]
    start_cols = [1, 3, 5, 7, 9]
    for (label, value, color), col in zip(metrics, start_cols):
        ws.merge_cells(start_row=8, start_column=col, end_row=8, end_column=col+1)
        ws.merge_cells(start_row=9, start_column=col, end_row=10, end_column=col+1)
        label_cell = ws.cell(8, col)
        value_cell = ws.cell(9, col)
        label_cell.value = label
        value_cell.value = value
        label_cell.font = Font(bold=True, color=TEXT_DARK)
        label_cell.alignment = Alignment(horizontal="center")
        value_cell.font = Font(size=18, bold=True, color=HEADER)
        value_cell.alignment = Alignment(horizontal="center", vertical="center")
        for row in range(8, 11):
            for c in range(col, col+2):
                ws.cell(row, c).fill = PatternFill("solid", fgColor=color)
                ws.cell(row, c).border = Border(
                    left=Side(style="thin", color=BORDER_COLOR),
                    right=Side(style="thin", color=BORDER_COLOR),
                    top=Side(style="thin", color=BORDER_COLOR),
                    bottom=Side(style="thin", color=BORDER_COLOR),
                )

    ws["A13"] = "Status"
    ws["B13"] = "Count"
    ws["C13"] = "Share"
    status_order = [
        "COMPLIANT", "UPDATE_AVAILABLE", "PARTIAL_MATCH", "REVIEW",
        "MISMATCH", "WRONG_RELEASE", "NO_REFERENCE"
    ]
    for idx, status in enumerate(status_order, start=14):
        count = int((statuses == status).sum())
        ws.cell(idx, 1, status)
        ws.cell(idx, 2, count)
        ws.cell(idx, 3, count / total if total else 0)
        ws.cell(idx, 3).number_format = "0.0%"
        for c in range(1, 4):
            ws.cell(idx, c).fill = PatternFill("solid", fgColor=COLORS.get(status, "FFFFFF"))
    for c in range(1, 4):
        ws.cell(13, c).fill = PatternFill("solid", fgColor=HEADER)
        ws.cell(13, c).font = Font(color="FFFFFF", bold=True)

    pie = PieChart()
    labels = Reference(ws, min_col=1, min_row=14, max_row=13 + len(status_order))
    values = Reference(ws, min_col=2, min_row=13, max_row=13 + len(status_order))
    pie.add_data(values, titles_from_data=True)
    pie.set_categories(labels)
    pie.title = "Compliance status distribution"
    pie.height = 8.5
    pie.width = 12
    ws.add_chart(pie, "E13")

    if metadata.get("executive_comment"):
        ws.merge_cells("A24:J24")
        ws["A24"] = "Executive comment"
        ws["A24"].fill = PatternFill("solid", fgColor=HEADER)
        ws["A24"].font = Font(color="FFFFFF", bold=True)
        ws.merge_cells("A25:J30")
        ws["A25"] = metadata["executive_comment"]
        ws["A25"].alignment = Alignment(wrap_text=True, vertical="top")
        ws["A25"].fill = PatternFill("solid", fgColor="F8FAFC")

    for col in range(1, 11):
        ws.column_dimensions[get_column_letter(col)].width = 15
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["E"].width = 25
    ws.freeze_panes = "A4"
    return ws


def _vehicle_report_sheets(wb: Workbook, overview: pd.DataFrame, details: pd.DataFrame):
    if "Source File" not in overview.columns:
        return
    for index, (source, group) in enumerate(overview.groupby("Source File", dropna=False), start=1):
        name = f"Vehicle {index}"[:31]
        ws = wb.create_sheet(name)
        ws.sheet_view.showGridLines = False
        ws.merge_cells("A1:J2")
        ws["A1"] = f"Vehicle / Session: {source}"
        ws["A1"].font = Font(size=16, bold=True, color=HEADER)
        vin_series = group.get("VIN", pd.Series(dtype=str)).dropna()
        ws["A4"] = "VIN"
        ws["B4"] = vin_series.iloc[0] if not vin_series.empty else ""
        ws["D4"] = "ECUs"
        ws["E4"] = len(group)
        ws["G4"] = "Compliance rate"
        ws["H4"] = f"{(group['Status'].astype(str) == 'COMPLIANT').mean() * 100:.1f}%"

        display_cols = [
            "ECU", "Status", "Matched Variant", "Installed Release", "Target Release",
            "Confidence %", "Matches", "Partial Matches", "Mismatches", "Missing", "Decision Reason"
        ]
        display_cols = [c for c in display_cols if c in group.columns]
        start_row = 6
        for c, header in enumerate(display_cols, start=1):
            ws.cell(start_row, c, header)
        _style_header(ws, start_row)
        for r_idx, (_, row) in enumerate(group[display_cols].iterrows(), start=start_row+1):
            status = str(row.get("Status", ""))
            fill = PatternFill("solid", fgColor=COLORS.get(status, "FFFFFF"))
            for c_idx, col in enumerate(display_cols, start=1):
                cell = ws.cell(r_idx, c_idx, _safe(row[col]))
                cell.fill = fill
                cell.alignment = Alignment(vertical="top", wrap_text=True)

        source_details = details[details["Source File"] == source] if "Source File" in details.columns else pd.DataFrame()
        deviations = source_details[source_details["Status"].astype(str).isin(["MISMATCH", "MISSING", "PART_MATCH"])] if not source_details.empty else pd.DataFrame()
        next_row = ws.max_row + 3
        if not deviations.empty:
            ws.cell(next_row, 1, "Identifier Deviations")
            ws.cell(next_row, 1).font = Font(size=13, bold=True, color=HEADER)
            next_row += 1
            dev_cols = [c for c in ["ECU", "Field", "Actual", "Expected", "Status", "Reason"] if c in deviations.columns]
            for c_idx, col in enumerate(dev_cols, start=1):
                ws.cell(next_row, c_idx, col)
            _style_header(ws, next_row)
            for r_idx, (_, row) in enumerate(deviations[dev_cols].iterrows(), start=next_row+1):
                fill = PatternFill("solid", fgColor=COLORS.get(str(row.get("Status", "")), "FFFFFF"))
                for c_idx, col in enumerate(dev_cols, start=1):
                    ws.cell(r_idx, c_idx, _safe(row[col])).fill = fill

        for c in range(1, ws.max_column + 1):
            width = max([len(str(ws.cell(r, c).value or "")) for r in range(1, min(ws.max_row, 250)+1)] + [10]) + 2
            ws.column_dimensions[get_column_letter(c)].width = min(max(width, 11), 46)
        ws.freeze_panes = "A7"


def build_report(
    overview: pd.DataFrame,
    details: pd.DataFrame,
    summary: pd.DataFrame,
    raw: pd.DataFrame,
    candidates: pd.DataFrame,
    release_sheet: str,
    metadata: Mapping[str, str] | None = None,
    dtc_summary: pd.DataFrame | None = None,
    dtc_events: pd.DataFrame | None = None,
    vehicle_history: pd.DataFrame | None = None,
    change_log: pd.DataFrame | None = None,
    fleet_overview: pd.DataFrame | None = None,
) -> bytes:
    metadata = dict(metadata or {})
    wb = Workbook()
    wb.remove(wb.active)

    _executive_summary_sheet(wb, overview, release_sheet, metadata)
    _add_sheet(wb, "Dashboard Status", status_counts(overview), "Status")
    _add_sheet(wb, "Vehicle Summary", vehicle_summary(overview))
    _add_sheet(wb, "Priority Actions", action_items(overview, details), "Status")
    _add_sheet(wb, "Confidence Distribution", confidence_distribution(overview))
    _add_sheet(wb, "Compliance Overview", overview, "Status")
    _add_sheet(wb, "Release Details", release_detail_rows(summary, overview, details), "Status")
    _add_sheet(wb, "Field Details", details, "Status")
    _add_sheet(wb, "ECU Identifiers", summary)
    _add_sheet(wb, "Candidate Variants", candidates)
    _add_sheet(wb, "Raw Identifiers", raw)
    if dtc_summary is not None and not dtc_summary.empty:
        _add_sheet(wb, "DTC Summary", dtc_summary, "Severity")
    if dtc_events is not None and not dtc_events.empty:
        _add_sheet(wb, "DTC Events", dtc_events)
    if fleet_overview is not None and not fleet_overview.empty:
        _add_sheet(wb, "Fleet Summary", fleet_overview)
    if change_log is not None and not change_log.empty:
        _add_sheet(wb, "Change Log", change_log)
    if vehicle_history is not None and not vehicle_history.empty:
        _add_sheet(wb, "Vehicle History", vehicle_history)
    _vehicle_report_sheets(wb, overview, details)

    if metadata.get("engineering_notes"):
        ws = wb.create_sheet("Engineering Notes")
        ws["A1"] = "Engineering Notes"
        ws["A1"].font = Font(size=16, bold=True, color=HEADER)
        ws["A3"] = metadata["engineering_notes"]
        ws["A3"].alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions["A"].width = 110
        ws.row_dimensions[3].height = 240
        ws.sheet_view.showGridLines = False

    out = io.BytesIO()
    wb.save(out)
    data = out.getvalue()

    check = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    required = {
        "Executive Summary", "Dashboard Status", "Vehicle Summary", "Priority Actions",
        "Compliance Overview", "Release Details", "Field Details"
    }
    missing = required.difference(check.sheetnames)
    check.close()
    if missing:
        raise ValueError(f"Generated report is incomplete: {sorted(missing)}")
    return data
