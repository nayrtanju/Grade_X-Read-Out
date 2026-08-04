from __future__ import annotations
import io
import pandas as pd
from openpyxl import Workbook, load_workbook
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
}
HEADER = "1F4E78"


def _safe(value):
    if isinstance(value, tuple):
        return ".".join(map(str, value))
    if pd.isna(value):
        return ""
    return value.item() if hasattr(value, "item") else value


def _add_sheet(wb: Workbook, name: str, df: pd.DataFrame, status_col: str | None = None):
    ws = wb.create_sheet(name[:31])
    ws.append(list(df.columns))
    for row in df.itertuples(index=False, name=None):
        ws.append([_safe(v) for v in row])
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor=HEADER)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"
    thin = Side(style="thin", color="D9E1F2")
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
    return ws


def build_report(overview: pd.DataFrame, details: pd.DataFrame, summary: pd.DataFrame,
                 raw: pd.DataFrame, candidates: pd.DataFrame, release_sheet: str) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    cover = wb.create_sheet("Report Summary")
    cover["A1"] = "Grade-X Software Compliance Checker — Sprint 4"
    cover["A1"].font = Font(size=18, bold=True, color="1F4E78")
    cover["A3"] = "Selected target release sheet"
    cover["B3"] = release_sheet
    status_series = overview.get("Status", pd.Series(dtype=str))
    rows = [
        ("ECUs checked", len(overview)),
        ("Compliant", int((status_series == "COMPLIANT").sum())),
        ("Update available", int((status_series == "UPDATE_AVAILABLE").sum())),
        ("Partial match", int((status_series == "PARTIAL_MATCH").sum())),
        ("Mismatch", int((status_series == "MISMATCH").sum())),
        ("Wrong release", int((status_series == "WRONG_RELEASE").sum())),
        ("Review", int((status_series == "REVIEW").sum())),
        ("No reference", int((status_series == "NO_REFERENCE").sum())),
    ]
    for i, (label, value) in enumerate(rows, start=5):
        cover.cell(i, 1, label)
        cover.cell(i, 2, value)
        status_key = {
            "Compliant": "COMPLIANT", "Update available": "UPDATE_AVAILABLE", "Partial match": "PARTIAL_MATCH",
            "Mismatch": "MISMATCH", "Wrong release": "WRONG_RELEASE", "Review": "REVIEW", "No reference": "NO_REFERENCE",
        }.get(label)
        if status_key:
            cover.cell(i, 2).fill = PatternFill("solid", fgColor=COLORS[status_key])
    cover.column_dimensions["A"].width = 30
    cover.column_dimensions["B"].width = 42

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

    out = io.BytesIO()
    wb.save(out)
    data = out.getvalue()
    check = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    required = {"Report Summary", "Dashboard Status", "Vehicle Summary", "Priority Actions", "Compliance Overview", "Release Details", "Field Details"}
    missing = required.difference(check.sheetnames)
    check.close()
    if missing:
        raise ValueError(f"Generated report is incomplete: {sorted(missing)}")
    return data
