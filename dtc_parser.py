from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Iterable

import pandas as pd

LOG_PATTERN = re.compile(
    r"^(?P<level>DEBUG|INFO|WARN|WARNING|ERROR)\s+"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\s+"
    r"(?P<message>.*)$"
)
DTC_PATTERN = re.compile(r"\[(?P<ecu>[^\]]+)\].*?\bDTC\s*:\s*(?P<dtc>[A-Z0-9:.-]+)", re.I)
CLEAR_PATTERN = re.compile(r"DefaultOneEcuExecuteFaultClear\s*-\s*(?P<ecu>[A-Za-z0-9_]+)", re.I)
READ_START_PATTERN = re.compile(r"triageToolDtcClearAndReadParallel:\s*start", re.I)
VIN_PATTERN = re.compile(r"(?<![A-Z0-9])([A-HJ-NPR-Z0-9]{17})(?![A-Z0-9])", re.I)


def _decode_dtc(raw: str) -> tuple[str, str]:
    value = re.sub(r"[^A-Z0-9]", "", str(raw).upper())
    if len(value) >= 7 and value[0] in "PBCU":
        return value[:5], value[5:7]
    if len(value) >= 5:
        return value[:5], value[5:]
    return value, ""


def _category(base: str) -> str:
    return {
        "P": "Powertrain",
        "B": "Body",
        "C": "Chassis",
        "U": "Network / Communication",
    }.get((base or "")[:1], "Unknown")


def _severity(category: str, persistence: str) -> str:
    if persistence == "REAPPEARED_AFTER_CLEAR":
        return "HIGH"
    if persistence == "REPEATED":
        return "MEDIUM"
    if category in {"Powertrain", "Chassis"}:
        return "MEDIUM"
    return "LOW"


def infer_session_mapping(log_name: str, session_files: Iterable[str]) -> str:
    session_files = list(session_files)
    vin = next(iter(VIN_PATTERN.findall(log_name)), "")
    if vin:
        for session in session_files:
            if vin.upper() in str(session).upper():
                return str(session)
    return str(session_files[0]) if len(session_files) == 1 else ""


def parse_dtc_log(
    file_name: str,
    data: bytes,
    mapped_session: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    text = data.decode("utf-8", errors="replace")
    events: list[dict] = []
    last_clear: dict[str, datetime] = {}
    clear_count: defaultdict[str, int] = defaultdict(int)
    read_cycle = 0

    for line_number, line in enumerate(text.splitlines(), start=1):
        match = LOG_PATTERN.match(line.strip())
        if not match:
            continue
        timestamp_text = match.group("timestamp").replace(",", ".")
        try:
            timestamp = datetime.fromisoformat(timestamp_text)
        except ValueError:
            timestamp = pd.NaT
        message = match.group("message")

        if READ_START_PATTERN.search(message):
            read_cycle += 1

        clear_match = CLEAR_PATTERN.search(message)
        if clear_match:
            ecu = clear_match.group("ecu")
            if isinstance(timestamp, datetime):
                last_clear[ecu] = timestamp
            clear_count[ecu] += 1
            continue

        dtc_match = DTC_PATTERN.search(message)
        if not dtc_match:
            continue

        ecu = dtc_match.group("ecu").strip()
        raw_dtc = dtc_match.group("dtc").strip().upper()
        base, failure_type = _decode_dtc(raw_dtc)
        clear_time = last_clear.get(ecu)
        after_clear = bool(clear_time and isinstance(timestamp, datetime) and timestamp >= clear_time)

        events.append({
            "Mapped Session": mapped_session,
            "Source Log": file_name,
            "Line": line_number,
            "Timestamp": timestamp,
            "Read Cycle": read_cycle,
            "ECU": ecu,
            "DTC Raw": raw_dtc,
            "DTC": base,
            "Failure Type": failure_type,
            "Category": _category(base),
            "Seen After Clear": after_clear,
            "Clear Count Before Event": clear_count.get(ecu, 0),
            "Log Level": match.group("level"),
        })

    event_df = pd.DataFrame(events)
    if event_df.empty:
        return pd.DataFrame(columns=[
            "Mapped Session", "Source Log", "ECU", "DTC", "Failure Type", "Category",
            "Occurrences", "First Seen", "Last Seen", "Read Cycles", "Seen After Clear",
            "Persistence", "Severity",
        ]), event_df

    summary_rows = []
    group_cols = ["Mapped Session", "Source Log", "ECU", "DTC", "Failure Type", "Category"]
    for keys, group in event_df.groupby(group_cols, dropna=False):
        mapped, source, ecu, dtc, failure_type, category = keys
        occurrences = len(group)
        seen_after_clear = bool(group["Seen After Clear"].any())
        if seen_after_clear:
            persistence = "REAPPEARED_AFTER_CLEAR"
        elif occurrences > 1:
            persistence = "REPEATED"
        else:
            persistence = "OBSERVED_ONCE"
        summary_rows.append({
            "Mapped Session": mapped,
            "Source Log": source,
            "ECU": ecu,
            "DTC": dtc,
            "Failure Type": failure_type,
            "Category": category,
            "Occurrences": occurrences,
            "First Seen": group["Timestamp"].min(),
            "Last Seen": group["Timestamp"].max(),
            "Read Cycles": int(group["Read Cycle"].nunique()),
            "Seen After Clear": seen_after_clear,
            "Persistence": persistence,
            "Severity": _severity(category, persistence),
        })

    summary = pd.DataFrame(summary_rows).sort_values(
        ["Severity", "Occurrences", "ECU", "DTC"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)
    return summary, event_df.sort_values(["Timestamp", "Line"]).reset_index(drop=True)


def combine_dtc_results(
    parsed_results: Iterable[tuple[pd.DataFrame, pd.DataFrame]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries, events = [], []
    for summary, event in parsed_results:
        if summary is not None and not summary.empty:
            summaries.append(summary)
        if event is not None and not event.empty:
            events.append(event)
    return (
        pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame(),
        pd.concat(events, ignore_index=True) if events else pd.DataFrame(),
    )


def correlate_dtc_with_ecus(summary: pd.DataFrame, dtc_summary: pd.DataFrame) -> pd.DataFrame:
    out = summary.copy()
    if dtc_summary is None or dtc_summary.empty:
        out["External DTC Count"] = 0
        out["Persistent DTC Count"] = 0
        out["DTC Codes"] = ""
        out["DTC Severity"] = ""
        return out

    grouped_rows = []
    for (mapped_session, ecu), group in dtc_summary.groupby(["Mapped Session", "ECU"], dropna=False):
        codes = [
            f"{row['DTC']}:{row['Failure Type']}" if str(row.get("Failure Type", "")).strip()
            else str(row["DTC"])
            for _, row in group.iterrows()
        ]
        severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "": 0}
        severity = max(
            (str(x) for x in group["Severity"].fillna("")),
            key=lambda x: severity_order.get(x, 0),
            default="",
        )
        grouped_rows.append({
            "Source File": mapped_session,
            "ECU ID": ecu,
            "External DTC Count": int(len(group)),
            "Persistent DTC Count": int(group["Persistence"].isin(["REAPPEARED_AFTER_CLEAR", "REPEATED"]).sum()),
            "DTC Codes": ", ".join(dict.fromkeys(codes)),
            "DTC Severity": severity,
        })

    correlation = pd.DataFrame(grouped_rows)
    out = out.merge(correlation, on=["Source File", "ECU ID"], how="left")
    out["External DTC Count"] = out["External DTC Count"].fillna(0).astype(int)
    out["Persistent DTC Count"] = out["Persistent DTC Count"].fillna(0).astype(int)
    out["DTC Codes"] = out["DTC Codes"].fillna("")
    out["DTC Severity"] = out["DTC Severity"].fillna("")
    return out
