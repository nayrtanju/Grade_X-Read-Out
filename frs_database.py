from __future__ import annotations
import io, re, zipfile
import xml.etree.ElementTree as ET
from typing import NamedTuple
import pandas as pd
from utils import text, ecu_base

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
M = "{" + MAIN_NS + "}"

FIELDS = {
    "Bootloader": "Bootloader Version (0xF101)",
    "Calibration SW": "Calibration SW Part Number (0xF102)",
    "Part Number": "Part Number and Version (0xF103)",
    "Application SW": "Application SW Part Number (0xF104)",
    "Basic SW": "Basic Software Data Part Number (0xF105)",
    "Software Number": "SW Number (0xF188)",
    "Hardware Number": "ECU HW Number (0xF191)",
}

class ReleaseInfo(NamedTuple):
    sheet: str
    model_year: str
    release_rank: tuple[int, ...]
    variant_count: int = 0


def _rank(name: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", name)) or (0,)


def _model_year(name: str) -> str:
    match = re.search(r"MY\s*(2[3-9]|30)", name.upper())
    return "MY" + match.group(1) if match else ""


def _sheet_targets(z: zipfile.ZipFile) -> dict[str, str]:
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rel_map = {r.attrib["Id"]: r.attrib["Target"] for r in rels.findall("{" + PKG_REL_NS + "}Relationship")}
    result = {}
    sheets = wb.find(M + "sheets")
    for s in sheets or []:
        rid = s.attrib["{" + REL_NS + "}id"]
        target = rel_map[rid].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        result[s.attrib["name"]] = target
    return result


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(M + "t")) for si in root.findall(M + "si")]


def release_sheets(data: bytes) -> list[ReleaseInfo]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = list(_sheet_targets(z))
    out = []
    for name in names:
        upper = name.upper()
        if ("IASRC" not in upper and "FRS" not in upper) or upper == "VEHICLE FRS CHECK":
            continue
        out.append(ReleaseInfo(name, _model_year(name), _rank(name)))
    return sorted(out, key=lambda x: (x.model_year, x.release_rank), reverse=True)


def recommended_sheet(infos: list[ReleaseInfo], model_year: str) -> str:
    candidates = [x for x in infos if x.model_year == model_year]
    return candidates[0].sheet if candidates else (infos[0].sheet if infos else "")


def _col_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref).group(0)
    n = 0
    for char in letters:
        n = n * 26 + ord(char) - 64
    return n


def _read_sheet(z: zipfile.ZipFile, targets: dict[str, str], shared: list[str], sheet_name: str) -> pd.DataFrame:
    if sheet_name not in targets:
        raise ValueError(f"Reference sheet not found: {sheet_name}")
    root = ET.fromstring(z.read(targets[sheet_name]))
    records = []
    canonical = ["ECU Variant", "SW Version"] + list(FIELDS.values())
    sheet_data = root.find(M + "sheetData")
    for row in sheet_data or []:
        if int(row.attrib.get("r", "0")) == 1:
            continue
        values = [""] * 9
        for cell in row.findall(M + "c"):
            idx = _col_index(cell.attrib["r"])
            if idx > 9:
                continue
            kind = cell.attrib.get("t", "")
            value = ""
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in cell.iter(M + "t"))
            else:
                node = cell.find(M + "v")
                if node is not None and node.text is not None:
                    value = node.text
                    if kind == "s":
                        value = shared[int(value)]
            values[idx - 1] = text(value)
        if not any(values):
            continue
        rec = dict(zip(canonical, values))
        rec["Reference Sheet"] = sheet_name
        rec["Model Year"] = _model_year(sheet_name)
        rec["Release Rank"] = _rank(sheet_name)
        rec["ECU Base"] = ecu_base(rec["ECU Variant"])
        records.append(rec)
    return pd.DataFrame(records)


def load_reference_sheet(data: bytes, sheet_name: str) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        targets = _sheet_targets(z)
        shared = _shared_strings(z)
        return _read_sheet(z, targets, shared, sheet_name)


def load_reference_catalog(data: bytes, sheet_names: list[str] | None = None) -> pd.DataFrame:
    """Load multiple release sheets into one in-memory catalog.

    Duplicate rows are retained because the same identifiers may legitimately appear in
    several releases; this is required for installed-release inference.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        targets = _sheet_targets(z)
        shared = _shared_strings(z)
        available = [x.sheet for x in release_sheets(data)]
        selected = sheet_names or available
        frames = [_read_sheet(z, targets, shared, name) for name in selected if name in targets]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
