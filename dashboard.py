from __future__ import annotations

import pandas as pd

STATUS_ORDER = [
    "MISMATCH",
    "WRONG_RELEASE",
    "UPDATE_AVAILABLE",
    "REVIEW",
    "PARTIAL_MATCH",
    "NO_REFERENCE",
    "COMPLIANT",
]

STATUS_PRIORITY = {
    "MISMATCH": 1,
    "WRONG_RELEASE": 2,
    "UPDATE_AVAILABLE": 3,
    "REVIEW": 4,
    "PARTIAL_MATCH": 5,
    "NO_REFERENCE": 6,
    "COMPLIANT": 7,
}

ACTION_TEXT = {
    "MISMATCH": "Investigate critical SW/HW mismatch",
    "WRONG_RELEASE": "Verify vehicle variant and installed release",
    "UPDATE_AVAILABLE": "Plan update to the selected target release",
    "REVIEW": "Complete missing identifiers and review manually",
    "PARTIAL_MATCH": "Confirm full revision information",
    "NO_REFERENCE": "Add or select the correct ECU reference",
    "COMPLIANT": "No action required",
}


def status_counts(overview: pd.DataFrame) -> pd.DataFrame:
    if overview.empty or "Status" not in overview.columns:
        return pd.DataFrame(columns=["Status", "Count", "Share %"])
    counts = overview["Status"].fillna("UNKNOWN").astype(str).value_counts()
    total = int(counts.sum())
    rows = []
    for status in STATUS_ORDER + sorted(set(counts.index).difference(STATUS_ORDER)):
        if status not in counts:
            continue
        count = int(counts[status])
        rows.append({"Status": status, "Count": count, "Share %": round(count / total * 100, 1) if total else 0})
    return pd.DataFrame(rows)


def vehicle_summary(overview: pd.DataFrame) -> pd.DataFrame:
    if overview.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    for source_file, group in overview.groupby("Source File", dropna=False):
        statuses = group.get("Status", pd.Series(dtype=str)).fillna("UNKNOWN").astype(str)
        confidence = pd.to_numeric(group.get("Confidence %", pd.Series(dtype=float)), errors="coerce")
        rows.append({
            "Source File": source_file,
            "VIN": next((str(x) for x in group.get("VIN", pd.Series(dtype=str)).dropna() if str(x).strip()), ""),
            "ECUs": len(group),
            "Compliant": int((statuses == "COMPLIANT").sum()),
            "Update Available": int((statuses == "UPDATE_AVAILABLE").sum()),
            "Mismatch / Wrong Release": int(statuses.isin(["MISMATCH", "WRONG_RELEASE"]).sum()),
            "Review / Partial": int(statuses.isin(["REVIEW", "PARTIAL_MATCH"]).sum()),
            "No Reference": int((statuses == "NO_REFERENCE").sum()),
            "Compliance %": round((statuses == "COMPLIANT").mean() * 100, 1) if len(statuses) else 0,
            "Average Confidence %": round(float(confidence.mean()), 1) if confidence.notna().any() else 0,
        })
    return pd.DataFrame(rows).sort_values(
        ["Mismatch / Wrong Release", "Update Available", "Compliance %"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def action_items(overview: pd.DataFrame, details: pd.DataFrame | None = None) -> pd.DataFrame:
    if overview.empty:
        return pd.DataFrame()
    out = overview.copy()
    out["Priority"] = out.get("Status", pd.Series(dtype=str)).map(STATUS_PRIORITY).fillna(99).astype(int)
    out["Recommended Action"] = out.get("Status", pd.Series(dtype=str)).map(ACTION_TEXT).fillna("Review manually")

    if details is not None and not details.empty:
        problem = details[details.get("Status", pd.Series(dtype=str)).isin(["MISMATCH", "MISSING", "PART_MATCH"])]
        affected = (
            problem.groupby(["Source File", "ECU"], dropna=False)["Field"]
            .apply(lambda x: ", ".join(dict.fromkeys(str(v) for v in x if str(v).strip())))
            .rename("Affected Fields")
            .reset_index()
        )
        out = out.merge(affected, on=["Source File", "ECU"], how="left")
    else:
        out["Affected Fields"] = ""

    out["Affected Fields"] = out.get("Affected Fields", "").fillna("")
    columns = [
        "Priority", "Source File", "VIN", "ECU", "Status", "Confidence %",
        "Installed Release", "Target Release", "Affected Fields", "Decision Reason", "Recommended Action",
    ]
    available = [c for c in columns if c in out.columns]
    return out[out.get("Status", pd.Series(dtype=str)) != "COMPLIANT"][available].sort_values(
        ["Priority", "Confidence %"], ascending=[True, False]
    ).reset_index(drop=True)


def confidence_distribution(overview: pd.DataFrame) -> pd.DataFrame:
    if overview.empty:
        return pd.DataFrame(columns=["Confidence Band", "Count"])
    confidence = pd.to_numeric(overview.get("Confidence %", pd.Series(dtype=float)), errors="coerce").fillna(0)
    bands = pd.cut(
        confidence,
        bins=[-0.1, 39.999, 69.999, 89.999, 100.001],
        labels=["Low (0–39%)", "Medium (40–69%)", "High (70–89%)", "Very high (90–100%)"],
    )
    counts = bands.value_counts(sort=False)
    return pd.DataFrame({"Confidence Band": counts.index.astype(str), "Count": counts.values})


def apply_dashboard_filters(
    overview: pd.DataFrame,
    details: pd.DataFrame,
    source_files: list[str] | None = None,
    ecus: list[str] | None = None,
    statuses: list[str] | None = None,
    minimum_confidence: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    filtered = overview.copy()
    if source_files:
        filtered = filtered[filtered["Source File"].isin(source_files)]
    if ecus:
        filtered = filtered[filtered["ECU"].isin(ecus)]
    if statuses:
        filtered = filtered[filtered["Status"].isin(statuses)]
    confidence = pd.to_numeric(filtered.get("Confidence %", pd.Series(index=filtered.index, dtype=float)), errors="coerce").fillna(0)
    filtered = filtered[confidence >= minimum_confidence]

    if details.empty or filtered.empty:
        return filtered.reset_index(drop=True), details.iloc[0:0].copy()
    keys = filtered[["Source File", "ECU"]].drop_duplicates()
    filtered_details = details.merge(keys, on=["Source File", "ECU"], how="inner")
    return filtered.reset_index(drop=True), filtered_details.reset_index(drop=True)
