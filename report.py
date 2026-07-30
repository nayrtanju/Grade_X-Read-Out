from __future__ import annotations
import io
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

COLORS = {
    "MATCH": "C6EFCE", "COMPLIANT": "C6EFCE",
    "MISMATCH": "FFC7CE", "PART_MATCH": "FFEB9C", "REVIEW": "FFEB9C", "MISSING": "FFEB9C",
    "NO_REFERENCE": "D9E1F2", "NOT_APPLICABLE": "E7E6E6",
}
HEADER = "1F4E78"


def _safe(value):
    if pd.isna(value): return ""
    return value.item() if hasattr(value, "item") else value


def _add_sheet(wb: Workbook, name: str, df: pd.DataFrame, status_col: str | None = None):
    ws = wb.create_sheet(name[:31])
    ws.append(list(df.columns))
    for row in df.itertuples(index=False, name=None): ws.append([_safe(v) for v in row])
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor=HEADER); cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    if ws.max_row > 1: ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"
    thin = Side(style="thin", color="D9E1F2")
    status_idx = list(df.columns).index(status_col) + 1 if status_col and status_col in df.columns else None
    for r in range(2, ws.max_row + 1):
        status = str(ws.cell(r, status_idx).value or "") if status_idx else ""
        fill = PatternFill("solid", fgColor=COLORS.get(status, "FFFFFF"))
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(r, c); cell.alignment = Alignment(vertical="top", wrap_text=True); cell.border = Border(bottom=thin)
            if status_idx: cell.fill = fill
    for c in range(1, ws.max_column + 1):
        width = max([len(str(ws.cell(r, c).value or "")) for r in range(1, min(ws.max_row, 300) + 1)] + [10]) + 2
        ws.column_dimensions[get_column_letter(c)].width = min(max(width, 11), 42)
    return ws


def build_report(overview: pd.DataFrame, details: pd.DataFrame, summary: pd.DataFrame,
                 raw: pd.DataFrame, candidates: pd.DataFrame, release_sheet: str) -> bytes:
    wb = Workbook(); wb.remove(wb.active)
    cover = wb.create_sheet("Report Summary")
    cover["A1"] = "Grade-X Software Compliance Checker"; cover["A1"].font = Font(size=18, bold=True, color="1F4E78")
    cover["A3"] = "Reference release sheet"; cover["B3"] = release_sheet
    cover["A5"] = "ECUs checked"; cover["B5"] = len(overview)
    cover["A6"] = "Compliant"; cover["B6"] = int((overview.get("Status", pd.Series(dtype=str)) == "COMPLIANT").sum())
    cover["A7"] = "Mismatch"; cover["B7"] = int((overview.get("Status", pd.Series(dtype=str)) == "MISMATCH").sum())
    cover["A8"] = "Review"; cover["B8"] = int(overview.get("Status", pd.Series(dtype=str)).isin(["PART_MATCH", "REVIEW"]).sum())
    cover.column_dimensions["A"].width = 28; cover.column_dimensions["B"].width = 38
    _add_sheet(wb, "Compliance Overview", overview, "Status")
    _add_sheet(wb, "Field Details", details, "Status")
    _add_sheet(wb, "ECU Identifiers", summary)
    _add_sheet(wb, "Candidate Variants", candidates)
    _add_sheet(wb, "Raw Identifiers", raw)
    out = io.BytesIO(); wb.save(out); data = out.getvalue()
    # Structural validation before download; no Excel Table objects are created.
    check = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    check.close()
    return data
