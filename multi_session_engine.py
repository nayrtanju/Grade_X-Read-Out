from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import pandas as pd

from configuration_diff_engine import compare_configurations, normalize_session


DATE_PATTERNS = [
    r"(?P<year>\d{4})[-_](?P<month>\d{2})[-_](?P<day>\d{2})[T_ -](?P<hour>\d{2})[-_:](?P<minute>\d{2})[-_:](?P<second>\d{2})",
    r"(?P<year>\d{4})[-_](?P<month>\d{2})[-_](?P<day>\d{2})",
]


def session_datetime(file_name: str, fallback_order: int = 0) -> pd.Timestamp:
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, str(file_name))
        if not match:
            continue
        values = {key: int(value) for key, value in match.groupdict(default="0").items()}
        try:
            return pd.Timestamp(datetime(
                values["year"], values["month"], values["day"],
                values.get("hour", 0), values.get("minute", 0), values.get("second", 0),
            ))
        except ValueError:
            pass
    return pd.Timestamp("2000-01-01") + pd.Timedelta(seconds=fallback_order)


def build_session_catalog(session_frames: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    rows = []
    for order, (file_name, frame) in enumerate(session_frames):
        vin_values = frame.get("VIN", pd.Series(dtype=str)).dropna().astype(str)
        rows.append({
            "Session Order": order + 1,
            "Session File": file_name,
            "Session Date": session_datetime(file_name, order),
            "VIN": vin_values.iloc[0] if not vin_values.empty else "",
            "ECU Count": int(frame.get("ECU ID", pd.Series(dtype=str)).nunique()),
            "DTC Count": int(
                pd.to_numeric(
                    frame.get("DTC Count", pd.Series(dtype=float)),
                    errors="coerce",
                ).fillna(0).sum()
            ),
            "Vehicle Model": (
                frame.get("Vehicle Model", pd.Series(dtype=str)).dropna().astype(str).iloc[0]
                if not frame.get("Vehicle Model", pd.Series(dtype=str)).dropna().empty
                else ""
            ),
        })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result = result.sort_values(["Session Date", "Session Order"]).reset_index(drop=True)
    result["Chronological Index"] = range(1, len(result) + 1)
    return result


def build_ecu_timeline(
    session_frames: list[tuple[str, pd.DataFrame]],
    catalog: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    date_lookup = {
        str(row["Session File"]): row["Session Date"]
        for _, row in catalog.iterrows()
    }
    for file_name, frame in session_frames:
        for _, row in frame.iterrows():
            rows.append({
                "Session File": file_name,
                "Session Date": date_lookup.get(file_name),
                "VIN": row.get("VIN", ""),
                "ECU": row.get("ECU ID", ""),
                "ECU Name": row.get("ECU Name", ""),
                "Hardware Number": row.get("Hardware Number", ""),
                "Part Number": row.get("Part Number", ""),
                "Application SW": row.get("Application SW", ""),
                "Calibration SW": row.get("Calibration SW", ""),
                "Basic SW": row.get("Basic SW", ""),
                "Software Number": row.get("Software Number", ""),
                "Bootloader": row.get("Bootloader", ""),
                "DTC Count": row.get("DTC Count", 0),
            })
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(
        ["ECU", "Session Date", "Session File"]
    ).reset_index(drop=True)


def build_pairwise_transitions(
    session_frames: list[tuple[str, pd.DataFrame]],
    catalog: pd.DataFrame,
    ignore_fields: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame_lookup = {name: frame for name, frame in session_frames}
    ordered_files = catalog.sort_values(
        ["Session Date", "Chronological Index"]
    )["Session File"].astype(str).tolist()

    summary_frames = []
    ecu_frames = []
    field_frames = []
    for index in range(1, len(ordered_files)):
        previous_name = ordered_files[index - 1]
        current_name = ordered_files[index]
        previous = normalize_session(frame_lookup[previous_name], previous_name)
        current = normalize_session(frame_lookup[current_name], current_name)
        result = compare_configurations(
            previous,
            current,
            left_label=previous_name,
            right_label=current_name,
            ignore_fields=ignore_fields or ["VIN"],
        )
        summary = result["summary"].copy()
        summary.insert(0, "Transition Number", index)
        summary.insert(1, "Previous Session", previous_name)
        summary.insert(2, "Current Session", current_name)
        summary_frames.append(summary)

        ecu_diff = result["ecu_diff"].copy()
        if not ecu_diff.empty:
            ecu_diff.insert(0, "Transition Number", index)
            ecu_diff.insert(1, "Previous Session", previous_name)
            ecu_diff.insert(2, "Current Session", current_name)
            ecu_frames.append(ecu_diff)

        field_diff = result["field_diff"].copy()
        if not field_diff.empty:
            field_diff.insert(0, "Transition Number", index)
            field_diff.insert(1, "Previous Session", previous_name)
            field_diff.insert(2, "Current Session", current_name)
            field_frames.append(field_diff)

    return (
        pd.concat(summary_frames, ignore_index=True) if summary_frames else pd.DataFrame(),
        pd.concat(ecu_frames, ignore_index=True) if ecu_frames else pd.DataFrame(),
        pd.concat(field_frames, ignore_index=True) if field_frames else pd.DataFrame(),
    )


def build_ecu_change_history(
    timeline: pd.DataFrame,
) -> pd.DataFrame:
    if timeline is None or timeline.empty:
        return pd.DataFrame()

    tracked_fields = [
        "Hardware Number", "Part Number", "Application SW",
        "Calibration SW", "Basic SW", "Software Number",
        "Bootloader", "DTC Count",
    ]
    rows = []
    for ecu, group in timeline.groupby("ECU", dropna=False):
        group = group.sort_values(["Session Date", "Session File"]).reset_index(drop=True)
        for index in range(1, len(group)):
            previous = group.iloc[index - 1]
            current = group.iloc[index]
            for field in tracked_fields:
                before = str(previous.get(field, "") or "").strip()
                after = str(current.get(field, "") or "").strip()
                if before == after:
                    continue
                rows.append({
                    "ECU": ecu,
                    "ECU Name": current.get("ECU Name", ""),
                    "Previous Session": previous.get("Session File", ""),
                    "Current Session": current.get("Session File", ""),
                    "Change Date": current.get("Session Date"),
                    "Field": field,
                    "Previous Value": before,
                    "Current Value": after,
                    "Change Direction": (
                        "INCREASE" if field == "DTC Count" and float(after or 0) > float(before or 0)
                        else "DECREASE" if field == "DTC Count" and float(after or 0) < float(before or 0)
                        else "CHANGED"
                    ),
                })
    return pd.DataFrame(rows).sort_values(
        ["Change Date", "ECU", "Field"]
    ).reset_index(drop=True) if rows else pd.DataFrame()


def build_vehicle_session_trend(
    catalog: pd.DataFrame,
    transition_summary: pd.DataFrame,
) -> pd.DataFrame:
    if catalog is None or catalog.empty:
        return pd.DataFrame()
    result = catalog.copy()
    transition_lookup = {}
    if transition_summary is not None and not transition_summary.empty:
        transition_lookup = {
            str(row["Current Session"]): row
            for _, row in transition_summary.iterrows()
        }
    rows = []
    for _, session in result.iterrows():
        transition = transition_lookup.get(str(session["Session File"]))
        rows.append({
            "Session File": session["Session File"],
            "Session Date": session["Session Date"],
            "VIN": session["VIN"],
            "ECU Count": session["ECU Count"],
            "DTC Count": session["DTC Count"],
            "Added ECUs": int(transition.get("Added ECUs", 0)) if transition is not None else 0,
            "Removed ECUs": int(transition.get("Removed ECUs", 0)) if transition is not None else 0,
            "Modified ECUs": int(transition.get("Modified ECUs", 0)) if transition is not None else 0,
            "Critical Differences": int(transition.get("Critical Differences", 0)) if transition is not None else 0,
            "Major Differences": int(transition.get("Major Differences", 0)) if transition is not None else 0,
            "Overall Assessment": transition.get("Overall Assessment", "BASELINE") if transition is not None else "BASELINE",
        })
    return pd.DataFrame(rows)


def build_multi_session_analysis(
    session_frames: list[tuple[str, pd.DataFrame]],
    ignore_fields: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    catalog = build_session_catalog(session_frames)
    timeline = build_ecu_timeline(session_frames, catalog)
    transition_summary, transition_ecus, transition_fields = build_pairwise_transitions(
        session_frames, catalog, ignore_fields=ignore_fields
    )
    change_history = build_ecu_change_history(timeline)
    vehicle_trend = build_vehicle_session_trend(catalog, transition_summary)
    return {
        "catalog": catalog,
        "ecu_timeline": timeline,
        "transition_summary": transition_summary,
        "transition_ecus": transition_ecus,
        "transition_fields": transition_fields,
        "change_history": change_history,
        "vehicle_trend": vehicle_trend,
    }
