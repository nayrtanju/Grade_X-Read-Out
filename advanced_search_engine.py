from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd


SEARCHABLE_COLUMNS = [
    "Session File",
    "Session Date",
    "VIN",
    "ECU",
    "ECU Name",
    "Hardware Number",
    "Part Number",
    "Application SW",
    "Calibration SW",
    "Basic SW",
    "Software Number",
    "Bootloader",
    "Installed Release",
    "Target Release",
    "Reference Sheet",
    "Status",
    "Risk Level",
    "Risk Score",
    "DTC Code",
    "DTC Description",
    "DTC Status",
    "Severity",
    "Category",
    "Diff Status",
    "Changed Fields",
]


def _text(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def _contains(value: Any, query: str, regex: bool = False) -> bool:
    text = _text(value)
    if regex:
        try:
            return re.search(query, text, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    return query.casefold() in text.casefold()


def normalize_search_frame(
    frame: pd.DataFrame,
    *,
    source_type: str,
    source_name: str = "",
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    result = frame.copy()
    rename_map = {
        "ECU ID": "ECU",
        "Source File": "Session File",
        "Analysis Date": "Session Date",
        "Reference Sheet": "Reference Sheet",
    }
    result = result.rename(columns={k: v for k, v in rename_map.items() if k in result.columns})

    if "ECU" not in result.columns and "ECU Variant" in result.columns:
        result["ECU"] = result["ECU Variant"]
    if "ECU Name" not in result.columns and "ECU" in result.columns:
        result["ECU Name"] = result["ECU"]
    if "Session File" not in result.columns:
        result["Session File"] = source_name
    if "Session Date" not in result.columns:
        result["Session Date"] = pd.NaT

    result.insert(0, "Source Type", source_type)
    result.insert(1, "Source Name", source_name or source_type)

    for column in SEARCHABLE_COLUMNS:
        if column not in result.columns:
            result[column] = ""

    return result


def combine_search_sources(
    sources: Iterable[tuple[str, str, pd.DataFrame]],
) -> pd.DataFrame:
    frames = []
    for source_type, source_name, frame in sources:
        normalized = normalize_search_frame(
            frame,
            source_type=source_type,
            source_name=source_name,
        )
        if not normalized.empty:
            frames.append(normalized)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


def advanced_search(
    frame: pd.DataFrame,
    *,
    query: str = "",
    regex: bool = False,
    source_types: list[str] | None = None,
    ecus: list[str] | None = None,
    statuses: list[str] | None = None,
    severities: list[str] | None = None,
    categories: list[str] | None = None,
    date_from: Any = None,
    date_to: Any = None,
    min_risk: float | None = None,
    max_risk: float | None = None,
    changed_only: bool = False,
    dtc_only: bool = False,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()

    result = frame.copy()

    if source_types:
        result = result[result["Source Type"].astype(str).isin(source_types)]
    if ecus:
        result = result[result["ECU"].astype(str).isin(ecus)]
    if statuses:
        status_columns = [col for col in ("Status", "Diff Status", "DTC Status") if col in result.columns]
        if status_columns:
            mask = pd.Series(False, index=result.index)
            for column in status_columns:
                mask |= result[column].astype(str).isin(statuses)
            result = result[mask]
    if severities and "Severity" in result.columns:
        result = result[result["Severity"].astype(str).isin(severities)]
    if categories and "Category" in result.columns:
        result = result[result["Category"].astype(str).isin(categories)]

    if date_from is not None or date_to is not None:
        dates = pd.to_datetime(result["Session Date"], errors="coerce")
        if date_from is not None:
            result = result[dates >= pd.Timestamp(date_from)]
            dates = pd.to_datetime(result["Session Date"], errors="coerce")
        if date_to is not None:
            result = result[dates <= pd.Timestamp(date_to) + pd.Timedelta(days=1)]

    if min_risk is not None or max_risk is not None:
        risks = pd.to_numeric(result["Risk Score"], errors="coerce")
        if min_risk is not None:
            result = result[risks >= float(min_risk)]
            risks = pd.to_numeric(result["Risk Score"], errors="coerce")
        if max_risk is not None:
            result = result[risks <= float(max_risk)]

    if changed_only:
        changed_mask = pd.Series(False, index=result.index)
        for column in ("Diff Status", "Changed Fields", "Change Type"):
            if column in result.columns:
                values = result[column].astype(str)
                changed_mask |= values.ne("") & ~values.eq("UNCHANGED")
        result = result[changed_mask]

    if dtc_only:
        dtc_mask = pd.Series(False, index=result.index)
        for column in ("DTC Code", "DTC Description", "DTC Status"):
            if column in result.columns:
                dtc_mask |= result[column].astype(str).str.strip().ne("")
        result = result[dtc_mask]

    query = query.strip()
    if query:
        searchable = [col for col in SEARCHABLE_COLUMNS if col in result.columns]
        mask = pd.Series(False, index=result.index)
        for column in searchable:
            mask |= result[column].map(lambda value: _contains(value, query, regex=regex))
        result = result[mask]

    return result.reset_index(drop=True)


def search_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame([{
            "Results": 0,
            "Source Types": 0,
            "Sessions": 0,
            "VINs": 0,
            "ECUs": 0,
            "DTC Records": 0,
            "Changed Records": 0,
            "Critical Records": 0,
        }])

    dtc_records = 0
    if "DTC Code" in frame.columns:
        dtc_records = int(frame["DTC Code"].astype(str).str.strip().ne("").sum())

    changed_records = 0
    if "Diff Status" in frame.columns:
        changed_records = int(
            frame["Diff Status"].astype(str).isin(["ADDED", "REMOVED", "MODIFIED"]).sum()
        )

    critical_records = 0
    if "Severity" in frame.columns:
        critical_records = int(frame["Severity"].astype(str).eq("CRITICAL").sum())

    return pd.DataFrame([{
        "Results": len(frame),
        "Source Types": frame["Source Type"].astype(str).nunique(),
        "Sessions": frame["Session File"].astype(str).replace("", pd.NA).dropna().nunique(),
        "VINs": frame["VIN"].astype(str).replace("", pd.NA).dropna().nunique(),
        "ECUs": frame["ECU"].astype(str).replace("", pd.NA).dropna().nunique(),
        "DTC Records": dtc_records,
        "Changed Records": changed_records,
        "Critical Records": critical_records,
    }])


def search_facets(frame: pd.DataFrame) -> dict[str, list[str]]:
    if frame is None or frame.empty:
        return {
            "source_types": [],
            "ecus": [],
            "statuses": [],
            "severities": [],
            "categories": [],
        }

    statuses = set()
    for column in ("Status", "Diff Status", "DTC Status"):
        if column in frame.columns:
            statuses.update(
                value for value in frame[column].dropna().astype(str).unique()
                if value.strip()
            )

    return {
        "source_types": sorted(
            value for value in frame["Source Type"].dropna().astype(str).unique()
            if value.strip()
        ),
        "ecus": sorted(
            value for value in frame["ECU"].dropna().astype(str).unique()
            if value.strip()
        ),
        "statuses": sorted(statuses),
        "severities": sorted(
            value for value in frame["Severity"].dropna().astype(str).unique()
            if value.strip()
        ) if "Severity" in frame.columns else [],
        "categories": sorted(
            value for value in frame["Category"].dropna().astype(str).unique()
            if value.strip()
        ) if "Category" in frame.columns else [],
    }
