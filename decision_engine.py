from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


DEFAULT_RULES_PATH = Path(__file__).with_name("decision_rules.json")


def load_decision_rules(path: str | Path | None = None) -> dict[str, Any]:
    rules_path = Path(path) if path else DEFAULT_RULES_PATH
    with rules_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _text(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def _unique(items: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = _text(item)
        if value and value not in seen:
            output.append(value)
            seen.add(value)
    return output


def _mismatch_fields(
    details: pd.DataFrame | None,
    source_file: str,
    ecu: str,
) -> list[str]:
    if details is None or details.empty:
        return []
    required = {"Source File", "ECU", "Field", "Status"}
    if not required.issubset(details.columns):
        return []

    scoped = details[
        (details["Source File"].astype(str) == source_file)
        & (details["ECU"].astype(str) == ecu)
        & (details["Status"].astype(str).isin(["MISMATCH", "PART_MATCH", "MISSING"]))
    ]
    return _unique(scoped["Field"].astype(str).tolist())


def _regression_evidence(
    change_log: pd.DataFrame | None,
    source_file: str,
    ecu: str,
) -> list[str]:
    if change_log is None or change_log.empty:
        return []
    required = {"Current Session", "ECU", "Regression", "Change Type", "Field"}
    if not required.issubset(change_log.columns):
        return []

    scoped = change_log[
        (change_log["Current Session"].astype(str) == source_file)
        & (change_log["ECU"].astype(str) == ecu)
        & (change_log["Regression"].fillna(False).astype(bool))
    ]
    return [
        f"{row['Change Type']}: {row['Field']} changed from "
        f"{_text(row.get('Previous Value'))} to {_text(row.get('Current Value'))}"
        for _, row in scoped.iterrows()
    ]


def _highest_urgency(
    current: str,
    candidate: str,
    ranks: Mapping[str, int],
) -> str:
    if ranks.get(candidate, 0) > ranks.get(current, 0):
        return candidate
    return current


def advise_ecu(
    row: Mapping[str, Any],
    details: pd.DataFrame | None = None,
    change_log: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rules = dict(rules or load_decision_rules())
    source_file = _text(row.get("Source File"))
    ecu = _text(row.get("ECU"))
    status = _text(row.get("Status")) or "REVIEW"
    risk_score = float(row.get("Risk Score", 0) or 0)
    risk_level = _text(row.get("Risk Level"))
    persistent_dtc = int(float(row.get("Persistent DTC Count", 0) or 0))
    dtc_severity = _text(row.get("DTC Severity")).upper()
    dtc_codes = _text(row.get("DTC Codes"))
    dtc_category = _text(row.get("DTC Category"))
    mismatch_fields = _mismatch_fields(details, source_file, ecu)
    regression_evidence = _regression_evidence(change_log, source_file, ecu)

    default = rules["status_defaults"].get(
        status,
        rules["status_defaults"]["REVIEW"],
    )
    decision = default["decision"]
    urgency = default["urgency"]
    root_causes = [default["root_cause"]]
    actions = list(default["actions"])
    evidence = [
        f"Compliance status: {status}",
        f"Risk score: {risk_score:.0f}/100 ({risk_level or 'UNKNOWN'})",
    ]

    ranks = rules["urgency_rank"]
    for field in mismatch_fields:
        hypothesis = rules["field_hypotheses"].get(field)
        if not hypothesis:
            continue
        root_causes.append(hypothesis["root_cause"])
        actions.extend(hypothesis["actions"])
        evidence.append(f"{field}: mismatch or incomplete match")
        decision = hypothesis["decision"]
        urgency = _highest_urgency(urgency, hypothesis["urgency"], ranks)

    if persistent_dtc > 0:
        diagnostic = rules["diagnostic_rules"]["persistent_dtc"]
        root_causes.append(diagnostic["root_cause"])
        actions.extend(diagnostic["actions"])
        evidence.append(f"Persistent DTC count: {persistent_dtc}")
        if dtc_codes:
            evidence.append(f"DTC codes: {dtc_codes}")
        urgency = _highest_urgency(urgency, diagnostic["urgency"], ranks)

        category = dtc_category.upper()
        if "NETWORK" in category or dtc_codes.upper().startswith("U"):
            diagnostic = rules["diagnostic_rules"]["high_network_dtc"]
            root_causes.append(diagnostic["root_cause"])
            actions.extend(diagnostic["actions"])
            urgency = _highest_urgency(urgency, diagnostic["urgency"], ranks)
        elif "POWERTRAIN" in category or dtc_codes.upper().startswith("P"):
            diagnostic = rules["diagnostic_rules"]["high_powertrain_dtc"]
            root_causes.append(diagnostic["root_cause"])
            actions.extend(diagnostic["actions"])
            urgency = _highest_urgency(urgency, diagnostic["urgency"], ranks)

    if regression_evidence:
        root_causes.append(
            "A historical regression was detected between consecutive vehicle sessions."
        )
        actions.extend([
            "Review the last known-good session.",
            "Identify the software, hardware or diagnostic change introduced afterward.",
            "Repeat the comparison after corrective action.",
        ])
        evidence.extend(regression_evidence)
        urgency = _highest_urgency(urgency, "HIGH", ranks)

    # Software deviation plus matching hardware suggests programming/configuration first.
    if (
        "Hardware Number" not in mismatch_fields
        and any(field in mismatch_fields for field in ("Application SW", "Calibration SW", "Basic SW", "Software Number"))
    ):
        root_causes.append(
            "Hardware appears compatible while software identifiers differ, increasing the likelihood of a programming or package-selection issue."
        )
        actions.insert(0, "Verify the software package before considering hardware replacement.")

    # Hardware mismatch takes precedence over software-only reflash.
    if "Hardware Number" in mismatch_fields or "Part Number" in mismatch_fields:
        decision = "HARDWARE_AND_VARIANT_VERIFICATION"
        actions.insert(0, "Do not authorize software-only correction until hardware compatibility is confirmed.")

    # Persistent DTC with otherwise compliant software needs functional diagnosis.
    if status == "COMPLIANT" and persistent_dtc > 0:
        decision = "FUNCTIONAL_DIAGNOSTIC_REQUIRED"
        root_causes.insert(
            0,
            "Software configuration is compliant; the persistent fault therefore requires functional, electrical or network diagnosis.",
        )

    confidence_rules = rules["confidence"]
    confidence = float(confidence_rules["base"])
    if status in {"WRONG_RELEASE", "MISMATCH", "COMPLIANT", "UPDATE_AVAILABLE"}:
        confidence += confidence_rules["matching_status_bonus"]
    if mismatch_fields:
        confidence += confidence_rules["field_evidence_bonus"]
    if persistent_dtc > 0:
        confidence += confidence_rules["persistent_dtc_bonus"]
    if regression_evidence:
        confidence += confidence_rules["history_evidence_bonus"]
    if not mismatch_fields and persistent_dtc == 0 and status in {"REVIEW", "NO_REFERENCE", "PARTIAL_MATCH"}:
        confidence -= confidence_rules["low_data_penalty"]
    confidence = max(0.0, min(float(confidence_rules["cap"]), confidence))

    root_causes = _unique(root_causes)
    actions = _unique(actions)
    evidence = _unique(evidence)

    primary_root_cause = root_causes[0] if root_causes else "Insufficient evidence."
    return {
        "Decision": decision,
        "Decision Urgency": urgency,
        "Decision Confidence %": round(confidence, 1),
        "Primary Root Cause": primary_root_cause,
        "Root Cause Hypotheses": " | ".join(root_causes),
        "Recommended Actions": " | ".join(actions),
        "Verification Steps": " | ".join(actions[:4]),
        "Decision Evidence": " | ".join(evidence),
        "Action Count": len(actions),
        "Hypothesis Count": len(root_causes),
        "Mismatch Fields": ", ".join(mismatch_fields),
    }


def apply_decision_advisor(
    overview: pd.DataFrame,
    details: pd.DataFrame | None = None,
    change_log: pd.DataFrame | None = None,
    rules: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rules = dict(rules or load_decision_rules())
    if overview is None or overview.empty:
        return pd.DataFrame(), pd.DataFrame()

    advised_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []

    for _, row in overview.iterrows():
        advice = advise_ecu(
            row,
            details=details,
            change_log=change_log,
            rules=rules,
        )
        enriched = row.to_dict()
        enriched.update(advice)
        advised_rows.append(enriched)

        actions = [item.strip() for item in advice["Recommended Actions"].split(" | ") if item.strip()]
        for priority, action in enumerate(actions, start=1):
            action_rows.append({
                "Source File": row.get("Source File", ""),
                "VIN": row.get("VIN", ""),
                "ECU": row.get("ECU", ""),
                "Decision": advice["Decision"],
                "Decision Urgency": advice["Decision Urgency"],
                "Decision Confidence %": advice["Decision Confidence %"],
                "Risk Score": row.get("Risk Score", 0),
                "Risk Level": row.get("Risk Level", ""),
                "Action Priority": priority,
                "Recommended Action": action,
                "Primary Root Cause": advice["Primary Root Cause"],
                "Evidence": advice["Decision Evidence"],
            })

    return pd.DataFrame(advised_rows), pd.DataFrame(action_rows)


def vehicle_decision_summary(advised_overview: pd.DataFrame) -> pd.DataFrame:
    if advised_overview is None or advised_overview.empty:
        return pd.DataFrame()

    urgency_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    rows: list[dict[str, Any]] = []
    for (source_file, vin), group in advised_overview.groupby(["Source File", "VIN"], dropna=False):
        ordered = group.assign(
            _UrgencyRank=group["Decision Urgency"].map(urgency_rank).fillna(0)
        ).sort_values(
            ["_UrgencyRank", "Risk Score", "Decision Confidence %"],
            ascending=[False, False, False],
        )
        lead = ordered.iloc[0]
        rows.append({
            "Source File": source_file,
            "VIN": vin,
            "ECUs": len(group),
            "High/Critical Decisions": int(group["Decision Urgency"].isin(["HIGH", "CRITICAL"]).sum()),
            "Manual Reviews": int(group["Decision"].astype(str).str.contains("REVIEW").sum()),
            "Lead ECU": lead.get("ECU", ""),
            "Overall Decision": lead.get("Decision", ""),
            "Overall Urgency": lead.get("Decision Urgency", ""),
            "Decision Confidence %": lead.get("Decision Confidence %", 0),
            "Primary Root Cause": lead.get("Primary Root Cause", ""),
            "Recommended Next Step": str(lead.get("Recommended Actions", "")).split(" | ")[0],
        })

    return pd.DataFrame(rows).sort_values(
        ["High/Critical Decisions", "Decision Confidence %"],
        ascending=[False, False],
    ).reset_index(drop=True)
