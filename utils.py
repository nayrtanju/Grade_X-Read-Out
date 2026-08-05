from __future__ import annotations
import re
from typing import Any

EMPTY_VALUES = {"", "-", "#N/A", "N/A", "NA", "NONE", "NULL"}


def text(value: Any) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    return "" if value.upper() in EMPTY_VALUES else value


def compact(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", text(value).upper())


def ecu_base(value: str) -> str:
    raw = text(value).upper().strip()
    raw = re.sub(r"^GREN[_\-\s]+", "", raw)
    raw = raw.replace("E_CALL", "ECALL").replace("E-CALL", "ECALL")
    token = re.split(r"[_\-\s]", raw, maxsplit=1)[0]
    aliases = {"E": "ECALL", "ECALL": "ECALL", "GWS": "GS", "EGS": "TCU"}
    return aliases.get(token, token)


def identifier_parts(value: str) -> tuple[str, str, str]:
    """Return prefix, 10-digit part number, revision-like suffix when available."""
    s = text(value).upper()
    prefix_match = re.search(r"\b(BL|SW|EE|EI)\b", s.replace("-", " "))
    prefix = prefix_match.group(1) if prefix_match else ""
    nums = re.findall(r"\d+", s)
    if not nums:
        return prefix, "", ""

    # Grade-X short format: SW870 Rev.1
    if "REV" in s and len(nums) >= 1:
        part = nums[0].zfill(10)
        revision = nums[-1]
        return prefix, part, revision

    # Reference format: SW-0000000870-001500
    part = nums[0].zfill(10)
    revision = nums[1] if len(nums) > 1 else ""
    return prefix, part, revision


def model_year_from_vin(vin: str) -> str:
    vin = text(vin).upper()
    if len(vin) != 17:
        return ""
    mapping = {
        "P": "MY23", "R": "MY24", "S": "MY25", "T": "MY26",
        "V": "MY27", "W": "MY28", "X": "MY29", "Y": "MY30",
    }
    return mapping.get(vin[9], "")
