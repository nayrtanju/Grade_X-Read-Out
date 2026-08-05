from __future__ import annotations

from typing import Any

import pandas as pd

from multi_session_engine import build_multi_session_analysis, session_datetime


MERGE_FIELDS = [
    "VIN",
    "ECU Name",
    "Hardware Number",
    "Part Number",
    "Application SW",
    "Calibration SW",
    "Basic SW",
    "Software Number",
    "Bootloader",
    "DTC Count",
]


def _text(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def _prepare_sessions(
    session_frames: list[tuple[str, pd.DataFrame]],
) -> list[tuple[str, pd.Timestamp, pd.DataFrame]]:
    prepared = []
    for index, (file_name, frame) in enumerate(session_frames):
        prepared.append((
            file_name,
            session_datetime(file_name, index),
            frame.copy(),
        ))
    return sorted(prepared, key=lambda item: (item[1], item[0]))


def build_unified_snapshot(
    session_frames: list[tuple[str, pd.DataFrame]],
) -> dict[str, pd.DataFrame]:
    if not session_frames:
        empty = pd.DataFrame()
        return {
            "summary": empty,
            "snapshot": empty,
            "field_provenance": empty,
            "conflicts": empty,
            "ecu_presence": empty,
            "session_catalog": empty,
            "change_history": empty,
        }

    prepared = _prepare_sessions(session_frames)
    multi = build_multi_session_analysis(session_frames)

    field_events: list[dict[str, Any]] = []
    presence_rows: list[dict[str, Any]] = []

    all_ecus: set[str] = set()
    for file_name, session_date, frame in prepared:
        ecus = set(
            frame.get("ECU ID", pd.Series(dtype=str))
            .dropna().astype(str).str.strip()
        )
        all_ecus |= {ecu for ecu in ecus if ecu}
        for ecu in ecus:
            if not ecu:
                continue
            presence_rows.append({
                "Session File": file_name,
                "Session Date": session_date,
                "ECU": ecu,
                "Present": True,
            })

        for _, row in frame.iterrows():
            ecu = _text(row.get("ECU ID", ""))
            if not ecu:
                continue
            for field in MERGE_FIELDS:
                value = row.get(field, "")
                normalized = _text(value)
                if normalized == "":
                    continue
                field_events.append({
                    "Session File": file_name,
                    "Session Date": session_date,
                    "ECU": ecu,
                    "Field": field,
                    "Value": value,
                    "Normalized Value": normalized,
                })

    events = pd.DataFrame(field_events)
    if events.empty:
        empty = pd.DataFrame()
        return {
            "summary": empty,
            "snapshot": empty,
            "field_provenance": empty,
            "conflicts": empty,
            "ecu_presence": pd.DataFrame(presence_rows),
            "session_catalog": multi["catalog"],
            "change_history": multi["change_history"],
        }

    events = events.sort_values(
        ["ECU", "Field", "Session Date", "Session File"]
    ).reset_index(drop=True)

    snapshot_rows: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []
    conflict_rows: list[dict[str, Any]] = []

    latest_session_name = prepared[-1][0]
    latest_session_date = prepared[-1][1]
    latest_frame = prepared[-1][2]
    latest_ecus = set(
        latest_frame.get("ECU ID", pd.Series(dtype=str))
        .dropna().astype(str).str.strip()
    )

    for ecu in sorted(all_ecus):
        row_out: dict[str, Any] = {
            "ECU": ecu,
            "Present in Latest Session": ecu in latest_ecus,
            "Latest Session File": latest_session_name,
            "Latest Session Date": latest_session_date,
        }
        ecu_events = events[events["ECU"] == ecu]

        changed_field_count = 0
        conflict_count = 0
        contributing_sessions: set[str] = set()

        for field in MERGE_FIELDS:
            scoped = ecu_events[ecu_events["Field"] == field]
            if scoped.empty:
                row_out[field] = ""
                row_out[f"{field} Source"] = ""
                continue

            latest = scoped.iloc[-1]
            distinct_values = [
                value for value in scoped["Normalized Value"].drop_duplicates().tolist()
                if value != ""
            ]
            row_out[field] = latest["Value"]
            row_out[f"{field} Source"] = latest["Session File"]
            contributing_sessions.update(scoped["Session File"].astype(str))

            changed = len(distinct_values) > 1
            if changed:
                changed_field_count += 1
                conflict_count += 1
                conflict_rows.append({
                    "ECU": ecu,
                    "Field": field,
                    "Distinct Value Count": len(distinct_values),
                    "Values": " → ".join(distinct_values),
                    "First Session": scoped.iloc[0]["Session File"],
                    "Latest Session": latest["Session File"],
                    "Selected Value": latest["Normalized Value"],
                    "Resolution": "LATEST_NON_EMPTY_VALUE",
                })

            provenance_rows.append({
                "ECU": ecu,
                "Field": field,
                "Selected Value": latest["Normalized Value"],
                "Source Session": latest["Session File"],
                "Source Date": latest["Session Date"],
                "Observed Sessions": scoped["Session File"].nunique(),
                "Distinct Values": len(distinct_values),
                "Changed Across Sessions": changed,
            })

        row_out["Changed Field Count"] = changed_field_count
        row_out["Conflict Count"] = conflict_count
        row_out["Contributing Sessions"] = len(contributing_sessions)
        row_out["Merge Status"] = (
            "STALE_ECU" if ecu not in latest_ecus
            else "CONFLICT_RESOLVED" if conflict_count > 0
            else "MERGED"
        )
        snapshot_rows.append(row_out)

    snapshot = pd.DataFrame(snapshot_rows)
    provenance = pd.DataFrame(provenance_rows)
    conflicts = pd.DataFrame(conflict_rows)
    presence = pd.DataFrame(presence_rows)

    latest_present = int(snapshot["Present in Latest Session"].sum())
    stale_ecus = int((~snapshot["Present in Latest Session"]).sum())
    conflict_ecus = int(snapshot["Conflict Count"].gt(0).sum())
    total_fields = len(snapshot) * len(MERGE_FIELDS)
    populated_fields = 0
    for field in MERGE_FIELDS:
        populated_fields += int(snapshot[field].astype(str).str.strip().ne("").sum())
    completeness = populated_fields / total_fields * 100 if total_fields else 0.0

    conflict_rate = (
        len(conflicts) / max(1, populated_fields) * 100
        if populated_fields else 0.0
    )
    merge_quality = max(
        0.0,
        min(
            100.0,
            completeness
            - min(25.0, conflict_rate * 1.5)
            - min(20.0, stale_ecus * 2.0),
        ),
    )
    merge_level = (
        "GOOD" if merge_quality >= 85
        else "FAIR" if merge_quality >= 70
        else "POOR" if merge_quality >= 50
        else "CRITICAL"
    )

    summary = pd.DataFrame([{
        "Sessions Merged": len(prepared),
        "Unified ECUs": len(snapshot),
        "ECUs in Latest Session": latest_present,
        "Stale ECUs": stale_ecus,
        "ECUs with Conflicts": conflict_ecus,
        "Field Conflicts": len(conflicts),
        "Populated Fields": populated_fields,
        "Total Merge Fields": total_fields,
        "Data Completeness %": round(completeness, 1),
        "Conflict Rate %": round(conflict_rate, 1),
        "Merge Quality Score": round(merge_quality, 1),
        "Merge Quality Level": merge_level,
        "Latest Session": latest_session_name,
        "Resolution Strategy": "Latest non-empty value per ECU field",
    }])

    return {
        "summary": summary,
        "snapshot": snapshot,
        "field_provenance": provenance,
        "conflicts": conflicts,
        "ecu_presence": presence,
        "session_catalog": multi["catalog"],
        "change_history": multi["change_history"],
    }
