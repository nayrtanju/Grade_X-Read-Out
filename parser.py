from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from typing import Iterable, NamedTuple
import pandas as pd
from utils import compact, text


class EcuRecord(NamedTuple):
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
    part_number: str
    basic_sw: str
    software_number: str
    bootloader: str
    identifier_count: int
    dtc_count: int


def _records(ecu: ET.Element) -> list[dict[str, str]]:
    return [{
        "id": text(x.findtext("id")),
        "display": text(x.findtext("displayText")),
        "value": text(x.findtext("value")),
    } for x in ecu.findall("identifications")]


def _find(records: list[dict[str, str]], include: Iterable[str], exclude: Iterable[str] = ()) -> str:
    inc = [compact(x) for x in include]
    exc = [compact(x) for x in exclude]
    for key in ("id", "display"):
        for r in records:
            hay = compact(r[key])
            if r["value"] and all(x in hay for x in inc) and not any(x in hay for x in exc):
                return r["value"]
    return ""


def _composite(records: list[dict[str, str]], category: str) -> str:
    candidates = []
    for r in records:
        key = compact(r["id"] + " " + r["display"])
        match = (category == "bootloader" and ("BOOTLOADER" in key or ("BOOT" in key and "LOADER" in key))) \
            or (category != "bootloader" and category.upper() in key and ("SOFTWARE" in key or "SW" in key))
        if match and "FRS" not in key:
            candidates.append((key, r["value"]))
    prefix = number = revision = ""
    for key, value in candidates:
        if not value:
            continue
        if "PREFIX" in key and not prefix:
            prefix = value
        elif "REVISION" in key and not revision:
            revision = value
        elif "NUMBER" in key and "PREFIX" not in key and "REVISION" not in key and re.search(r"\d", value):
            number = number or value
    if not number:
        return ""
    base = f"{prefix}{number}".strip()
    return f"{base} Rev.{revision}" if revision else base


def _part_number(records: list[dict[str, str]]) -> str:
    candidates = []
    for r in records:
        key = compact(r["id"] + " " + r["display"])
        if "PARTNUMBER" in key and not any(x in key for x in ("APPLICATION", "CALIBRATION", "BASIC", "BOOTLOADER")):
            candidates.append((key, r["value"]))
    prefix = number = revision = ""
    for key, value in candidates:
        if not value or "FRS" in key:
            continue
        if "PREFIX" in key and not prefix:
            prefix = value
        elif "REVISION" in key and not revision:
            revision = value
        elif "NUMBER" in key and "PREFIX" not in key and "REVISION" not in key and re.search(r"\d", value):
            number = number or value
    if not number:
        return ""
    base = f"{prefix}{number}".strip()
    return f"{base} Rev.{revision}" if revision else base


def _software_number(records: list[dict[str, str]]) -> str:
    return _find(records, ["software", "number"], ["application", "calibration", "basic", "bootloader", "prefix", "revision"])


def parse_session(file_name: str, data: bytes) -> tuple[list[EcuRecord], list[dict[str, str]]]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid Grade-X XML/session file: {exc}") from exc

    session_id = text(root.findtext("id"))
    model = text(root.findtext("./machine/model"))
    manufacturer = text(root.findtext("./machine/manufacturer"))
    ecus = root.findall("./machine/networks/ecus")
    if not ecus:
        raise ValueError("No ECU nodes found under ./machine/networks/ecus")

    result, raw = [], []
    for ecu in ecus:
        ecu_id = text(ecu.findtext("id"))
        ecu_name = text(ecu.findtext("displayName"))
        records = _records(ecu)
        vin = _find(records, ["vehicle", "identification", "number"])
        if not vin:
            candidate = session_id.split("@", 1)[0]
            vin = candidate if re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", candidate, re.I) else ""
        for r in records:
            raw.append({"Source File": file_name, "Session ID": session_id, "ECU ID": ecu_id,
                        "ECU Name": ecu_name, "Identifier ID": r["id"], "Display Text": r["display"], "Value": r["value"]})
        result.append(EcuRecord(
            file_name, session_id, model, manufacturer, ecu_id, ecu_name, vin,
            _find(records, ["hardware", "number"], ["software", "supplier"]) or _find(records, ["hardware"], ["software"]),
            _composite(records, "application"), _composite(records, "calibration"), _part_number(records),
            _composite(records, "basic"), _software_number(records), _composite(records, "bootloader"),
            len(records), len(ecu.findall("dtcs"))))
    return result, raw


def records_frame(rows: list[EcuRecord]) -> pd.DataFrame:
    mapping = {
        "source_file": "Source File", "session_id": "Session ID", "vehicle_model": "Vehicle Model",
        "manufacturer": "Manufacturer", "ecu_id": "ECU ID", "ecu_name": "ECU Name", "vin": "VIN",
        "hardware_number": "Hardware Number", "application_sw": "Application SW",
        "calibration_sw": "Calibration SW", "part_number": "Part Number", "basic_sw": "Basic SW",
        "software_number": "Software Number", "bootloader": "Bootloader",
        "identifier_count": "Identifier Count", "dtc_count": "DTC Count",
    }
    return pd.DataFrame([x._asdict() for x in rows]).rename(columns=mapping)
