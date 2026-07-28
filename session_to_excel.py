#!/usr/bin/env python3
"""
Bosch Grade-X .session XML parser -> Excel report

Usage:
    python session_to_excel.py input.session
    python session_to_excel.py input.session -o output.xlsx
    python session_to_excel.py folder_with_session_files -o combined.xlsx

Requires:
    artifact_tool
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

from artifact_tool import Workbook, SpreadsheetFile


def clean(value: Optional[str]) -> str:
    return (value or "").strip()


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def natural_join(prefix: str, number: str, revision: str) -> str:
    """Format software identifiers such as SW1002 Rev.1."""
    prefix, number, revision = clean(prefix), clean(number), clean(revision)
    if not any((prefix, number, revision)):
        return ""
    base = f"{prefix}{number}".strip()
    return f"{base} Rev.{revision}" if revision else base


@dataclass
class EcuRow:
    source_file: str
    session_id: str
    vehicle_model: str
    manufacturer: str
    ecu_id: str
    ecu_name: str
    vin: str
    hardware_number: str
    application_sw: str
    calibration_sw: str
    basic_sw: str
    bootloader: str
    identification_count: int
    dtc_count: int


def identification_records(ecu: ET.Element) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for item in ecu.findall("identifications"):
        records.append(
            {
                "id": clean(item.findtext("id")),
                "display": clean(item.findtext("displayText")),
                "value": clean(item.findtext("value")),
            }
        )
    return records


def find_value(
    records: list[dict[str, str]],
    *,
    include_all: Iterable[str],
    exclude_any: Iterable[str] = (),
    prefer_id: bool = True,
) -> str:
    """Find the first non-empty identifier matching all include tokens."""
    includes = [norm(x) for x in include_all]
    excludes = [norm(x) for x in exclude_any]

    def matches(text: str) -> bool:
        n = norm(text)
        return all(token in n for token in includes) and not any(token in n for token in excludes)

    fields = ("id", "display") if prefer_id else ("display", "id")
    for field in fields:
        for rec in records:
            if rec["value"] and matches(rec[field]):
                return rec["value"]
    return ""


def _category_match(text: str, category: str) -> bool:
    n = norm(text)
    if category == "bootloader":
        return "bootloader" in n or ("boot" in n and "loader" in n)
    return category in n and ("software" in n or "sw" in n)


def software_value(records: list[dict[str, str]], category: str) -> str:
    """
    Extract a composite software identifier. Handles both 'software' and 'SW'
    naming conventions and supplier-specific capitalization.
    """
    candidates = [
        rec for rec in records
        if _category_match(rec["id"] + " " + rec["display"], category)
    ]

    prefix = ""
    number = ""
    revision = ""

    for rec in candidates:
        text = norm(rec["id"] + " " + rec["display"])
        value = rec["value"]
        if not value or "frs" in text:
            continue
        if "prefix" in text and not prefix:
            prefix = value
        elif "revision" in text and not revision:
            revision = value
        elif "number" in text and "prefix" not in text and "revision" not in text:
            # Prefer an actual number/part string over a duplicated prefix value.
            if not number or re.search(r"\d", value):
                number = value
                if re.search(r"\d", value):
                    # Keep scanning only if this might still be a weak value.
                    pass

    # If duplicate "part number" records exist (e.g. one value is SW, another 925),
    # choose the first candidate containing a digit.
    numeric_numbers = []
    for rec in candidates:
        text = norm(rec["id"] + " " + rec["display"])
        if (
            rec["value"]
            and "number" in text
            and "prefix" not in text
            and "revision" not in text
            and "frs" not in text
            and re.search(r"\d", rec["value"])
        ):
            numeric_numbers.append(rec["value"])
    if numeric_numbers:
        number = numeric_numbers[0]

    return natural_join(prefix, number, revision)



def extract_vin(records: list[dict[str, str]], session_id: str) -> str:
    vin = find_value(records, include_all=["vehicle", "identification", "number"])
    if vin:
        return vin
    # Grade-X session IDs often start with the 17-character VIN.
    candidate = session_id.split("@", 1)[0].strip()
    return candidate if re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", candidate, re.I) else ""

def extract_hardware(records: list[dict[str, str]]) -> str:
    """Extract explicit ECU hardware number, otherwise fall back to ECU part number."""
    hardware_candidates = [
        rec for rec in records
        if "hardware" in norm(rec["id"] + " " + rec["display"])
        and "software" not in norm(rec["id"] + " " + rec["display"])
    ]

    prefix = ""
    number = ""
    revision = ""
    for rec in hardware_candidates:
        text = norm(rec["id"] + " " + rec["display"])
        value = rec["value"]
        if not value:
            continue
        if "prefix" in text and not prefix:
            prefix = value
        elif "revision" in text and not revision:
            revision = value
        elif "number" in text and "prefix" not in text and "revision" not in text:
            # Prefer OEM ECU hardware number over supplier-specific text.
            if "supplier" not in text or not number:
                number = value

    if number:
        return natural_join(prefix, number, revision)

    # Fallback: composite ECU part number.
    part_candidates = [
        rec for rec in records
        if "ecupartnumber" in norm(rec["id"] + " " + rec["display"])
        and not any(
            token in norm(rec["id"] + " " + rec["display"])
            for token in ("application", "calibration", "basic", "software")
        )
    ]
    for rec in part_candidates:
        text = norm(rec["id"] + " " + rec["display"])
        value = rec["value"]
        if not value:
            continue
        if "prefix" in text and not prefix:
            prefix = value
        elif "revision" in text and not revision:
            revision = value
        elif "prefix" not in text and "revision" not in text and re.search(r"\d", value):
            number = value

    return natural_join(prefix, number, revision)


def parse_session(path: Path) -> tuple[list[EcuRow], list[list[str]]]:
    root = ET.parse(path).getroot()
    session_id = clean(root.findtext("id"))
    vehicle_model = clean(root.findtext("./machine/model"))
    manufacturer = clean(root.findtext("./machine/manufacturer"))

    rows: list[EcuRow] = []
    raw_rows: list[list[str]] = []

    for ecu in root.findall("./machine/networks/ecus"):
        ecu_id = clean(ecu.findtext("id"))
        ecu_name = clean(ecu.findtext("displayName"))
        records = identification_records(ecu)

        for rec in records:
            raw_rows.append(
                [
                    path.name,
                    session_id,
                    ecu_id,
                    ecu_name,
                    rec["display"],
                    rec["value"],
                    rec["id"],
                ]
            )

        rows.append(
            EcuRow(
                source_file=path.name,
                session_id=session_id,
                vehicle_model=vehicle_model,
                manufacturer=manufacturer,
                ecu_id=ecu_id,
                ecu_name=ecu_name,
                vin=extract_vin(records, session_id),
                hardware_number=extract_hardware(records),
                application_sw=software_value(records, "application"),
                calibration_sw=software_value(records, "calibration"),
                basic_sw=software_value(records, "basic"),
                bootloader=software_value(records, "bootloader"),
                identification_count=len(records),
                dtc_count=len(ecu.findall("dtcs")),
            )
        )

    return rows, raw_rows


def collect_session_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.glob("*.session"))
    raise FileNotFoundError(f"Input not found: {input_path}")


def build_workbook(rows: list[EcuRow], raw_rows: list[list[str]], output_path: Path) -> None:
    wb = Workbook.create()

    summary = wb.worksheets.add("ECU Summary")
    headers = [
        "Source File",
        "Session ID",
        "Vehicle Model",
        "Manufacturer",
        "ECU ID",
        "ECU Name",
        "VIN",
        "Hardware Number",
        "Application SW",
        "Calibration SW",
        "Basic SW",
        "Bootloader",
        "Identifier Count",
        "DTC Count",
    ]
    values = [headers] + [
        [
            r.source_file,
            r.session_id,
            r.vehicle_model,
            r.manufacturer,
            r.ecu_id,
            r.ecu_name,
            r.vin,
            r.hardware_number,
            r.application_sw,
            r.calibration_sw,
            r.basic_sw,
            r.bootloader,
            r.identification_count,
            r.dtc_count,
        ]
        for r in rows
    ]
    summary.get_range_by_indexes(0, 0, len(values), len(headers)).values = values

    header = summary.get_range_by_indexes(0, 0, 1, len(headers))
    header.format = {
        "fill": "#1F4E78",
        "font": {"bold": True, "color": "#FFFFFF"},
        "horizontal_alignment": "center",
        "vertical_alignment": "center",
        "wrap_text": True,
    }
    summary.freeze_panes.freeze_rows(1)
    summary.get_range(f"A1:N{max(2, len(values))}").format.wrap_text = True
    summary.get_range("A:A").format.column_width = 34
    summary.get_range("B:B").format.column_width = 38
    summary.get_range("C:D").format.column_width = 16
    summary.get_range("E:F").format.column_width = 15
    summary.get_range("G:G").format.column_width = 21
    summary.get_range("H:L").format.column_width = 24
    summary.get_range("M:N").format.column_width = 14

    if len(values) > 1:
        summary.tables.add(f"A1:N{len(values)}", True, "EcuSummaryTable")
        summary.get_range(f"M2:N{len(values)}").format.number_format = "0"
        summary.get_range(f"A2:N{len(values)}").conditional_formats.add_custom(
            '=AND($I2="",$J2="",$K2="",$L2="")',
            {"fill": "#FFF2CC"},
        )

    raw = wb.worksheets.add("Raw Identifiers")
    raw_headers = [
        "Source File",
        "Session ID",
        "ECU ID",
        "ECU Name",
        "Display Text",
        "Value",
        "Identifier ID",
    ]
    raw_values = [raw_headers] + raw_rows
    raw.get_range_by_indexes(0, 0, len(raw_values), len(raw_headers)).values = raw_values
    raw_header = raw.get_range_by_indexes(0, 0, 1, len(raw_headers))
    raw_header.format = {
        "fill": "#44546A",
        "font": {"bold": True, "color": "#FFFFFF"},
        "horizontal_alignment": "center",
        "vertical_alignment": "center",
        "wrap_text": True,
    }
    raw.freeze_panes.freeze_rows(1)
    raw.get_range(f"A1:G{max(2, len(raw_values))}").format.wrap_text = True
    raw.get_range("A:A").format.column_width = 34
    raw.get_range("B:B").format.column_width = 38
    raw.get_range("C:D").format.column_width = 15
    raw.get_range("E:E").format.column_width = 42
    raw.get_range("F:F").format.column_width = 28
    raw.get_range("G:G").format.column_width = 70
    if len(raw_values) > 1:
        raw.tables.add(f"A1:G{len(raw_values)}", True, "RawIdentifiersTable")

    SpreadsheetFile.export_xlsx(wb).save(str(output_path))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract ECU software, calibration, bootloader, VIN and hardware data from Bosch Grade-X .session files."
    )
    parser.add_argument("input", type=Path, help=".session file or folder containing .session files")
    parser.add_argument("-o", "--output", type=Path, help="Output .xlsx path")
    args = parser.parse_args()

    files = collect_session_files(args.input)
    if not files:
        print("No .session files found.", file=sys.stderr)
        return 2

    all_rows: list[EcuRow] = []
    all_raw: list[list[str]] = []
    for file in files:
        rows, raw = parse_session(file)
        all_rows.extend(rows)
        all_raw.extend(raw)

    output = args.output or (
        args.input.with_suffix(".xlsx")
        if args.input.is_file()
        else args.input / "GradeX_ECU_Identifiers.xlsx"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    build_workbook(all_rows, all_raw, output)

    print(f"Parsed {len(files)} session file(s), {len(all_rows)} ECU(s).")
    print(f"Excel written to: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
