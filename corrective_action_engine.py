from __future__ import annotations

from typing import Any

import pandas as pd


TEAM_RULES = {
    "INPUT_DATA": "Diagnostics / Data Engineering",
    "SOFTWARE_COMPLIANCE": "Software Release Engineering",
    "DIAGNOSTICS": "Diagnostics / Aftersales",
    "RELEASE_PACKAGE": "Software Release Engineering",
    "NETWORK": "E/E Architecture",
    "OEM_AUDIT": "Quality / Release Management",
    "VIN_CONSISTENCY": "Diagnostics / Vehicle Identity",
    "COMPLIANCE_IMPROVEMENT": "Software Release Engineering",
    "NO_REGRESSION": "Software Integration",
    "NO_NEW_DTC": "Diagnostics / Aftersales",
    "NO_REMOVED_ECU": "E/E Architecture",
    "TARGET_COMPLIANCE": "Software Release Engineering",
}

EVIDENCE_RULES = {
    "INPUT_DATA": "Corrected session export and Data Quality Gate result",
    "SOFTWARE_COMPLIANCE": "Compliant post-correction Grade-X session and ECU comparison",
    "DIAGNOSTICS": "DTC clear proof and post-repair diagnostic session",
    "RELEASE_PACKAGE": "Approved release package and release coverage evidence",
    "NETWORK": "Network-health report and dependency verification",
    "OEM_AUDIT": "Closed OEM Audit checklist with engineering approval",
    "VIN_CONSISTENCY": "Matching 17-character VIN evidence in both sessions",
    "COMPLIANCE_IMPROVEMENT": "Before/after compliance comparison",
    "NO_REGRESSION": "Post-programming session showing no regressed ECU",
    "NO_NEW_DTC": "Post-programming DTC scan with no new DTC",
    "NO_REMOVED_ECU": "Post-programming ECU presence verification",
    "TARGET_COMPLIANCE": "Post-programming compliance at approved target level",
}


def _text(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def _priority(status: str) -> str:
    return {
        "FAIL": "P1_CRITICAL",
        "WARNING": "P2_HIGH",
        "NOT_AVAILABLE": "P3_MEDIUM",
    }.get(status, "P4_LOW")


def _closure_criterion(gate: str) -> str:
    mapping = {
        "INPUT_DATA": "Readiness Decision becomes READY.",
        "SOFTWARE_COMPLIANCE": "All required ECUs become COMPLIANT with no wrong release.",
        "DIAGNOSTICS": "Persistent and newly introduced DTC count becomes zero.",
        "RELEASE_PACKAGE": "Coverage and consistency meet target with no mixed package.",
        "NETWORK": "Network Health reaches acceptable level with no critical violation.",
        "OEM_AUDIT": "OEM Audit Decision becomes PASS.",
        "VIN_CONSISTENCY": "Before and after VIN values match and are valid.",
        "COMPLIANCE_IMPROVEMENT": "After-programming compliance is not lower than before.",
        "NO_REGRESSION": "Regressed ECU count becomes zero.",
        "NO_NEW_DTC": "ECUs with new DTCs becomes zero.",
        "NO_REMOVED_ECU": "Removed ECU count becomes zero.",
        "TARGET_COMPLIANCE": "After-programming compliance reaches the approved threshold.",
    }
    return mapping.get(gate, "Finding is corrected and objective evidence is attached.")


def build_corrective_action_plan(
    assessment_gates: pd.DataFrame | None = None,
    programming_gates: pd.DataFrame | None = None,
    programming_findings: pd.DataFrame | None = None,
    audit_findings: pd.DataFrame | None = None,
    data_quality_findings: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    rows: list[dict[str, Any]] = []

    def add_gate_rows(frame: pd.DataFrame | None, source: str) -> None:
        if frame is None or frame.empty:
            return
        for _, item in frame.iterrows():
            status = _text(item.get("Status"))
            if status == "PASS":
                continue
            gate = _text(item.get("Gate") or item.get("Check ID"))
            evidence = _text(item.get("Evidence"))
            required = _text(item.get("Required Action"))
            rows.append({
                "Source": source,
                "Action ID": f"{source[:3].upper()}-{len(rows)+1:03d}",
                "Gate / Finding": gate,
                "Status": status or "OPEN",
                "Priority": _priority(status),
                "Owner Team": TEAM_RULES.get(gate, "Engineering"),
                "Required Action": required or "Review and correct the open finding.",
                "Required Evidence": EVIDENCE_RULES.get(
                    gate, "Objective verification evidence and updated analysis result"
                ),
                "Closure Criterion": _closure_criterion(gate),
                "Sign-off Blocking": status == "FAIL",
            })

    add_gate_rows(assessment_gates, "FULL_ASSESSMENT")
    add_gate_rows(programming_gates, "PROGRAMMING_VALIDATION")

    for frame, source in (
        (programming_findings, "PROGRAMMING_FINDING"),
        (audit_findings, "OEM_AUDIT_FINDING"),
        (data_quality_findings, "DATA_QUALITY_FINDING"),
    ):
        if frame is None or frame.empty:
            continue
        for _, item in frame.iterrows():
            status = _text(item.get("Status") or item.get("Severity") or "WARNING")
            gate = _text(
                item.get("Gate")
                or item.get("Check ID")
                or item.get("Field")
                or item.get("ECU")
                or "OPEN_FINDING"
            )
            required = _text(item.get("Required Action"))
            evidence = _text(item.get("Evidence") or item.get("Finding"))
            rows.append({
                "Source": source,
                "Action ID": f"{source[:3].upper()}-{len(rows)+1:03d}",
                "Gate / Finding": gate,
                "Status": status,
                "Priority": _priority("FAIL" if status in {"CRITICAL", "FAIL"} else "WARNING"),
                "Owner Team": TEAM_RULES.get(gate, "Engineering"),
                "Required Action": required or "Correct and verify the reported finding.",
                "Required Evidence": evidence or "Objective verification evidence",
                "Closure Criterion": _closure_criterion(gate),
                "Sign-off Blocking": status in {"CRITICAL", "FAIL"},
            })

    actions = pd.DataFrame(rows)
    if actions.empty:
        actions = pd.DataFrame(columns=[
            "Source", "Action ID", "Gate / Finding", "Status", "Priority",
            "Owner Team", "Required Action", "Required Evidence",
            "Closure Criterion", "Sign-off Blocking",
        ])
    else:
        rank = {"P1_CRITICAL": 1, "P2_HIGH": 2, "P3_MEDIUM": 3, "P4_LOW": 4}
        actions["_rank"] = actions["Priority"].map(rank).fillna(9)
        actions = actions.sort_values(
            ["_rank", "Sign-off Blocking", "Owner Team", "Action ID"],
            ascending=[True, False, True, True],
        ).drop(columns="_rank").reset_index(drop=True)

    blocking = int(actions["Sign-off Blocking"].fillna(False).sum()) if not actions.empty else 0
    p1 = int(actions["Priority"].eq("P1_CRITICAL").sum()) if not actions.empty else 0
    p2 = int(actions["Priority"].eq("P2_HIGH").sum()) if not actions.empty else 0
    teams = int(actions["Owner Team"].nunique()) if not actions.empty else 0

    decision = (
        "BLOCKED" if blocking > 0
        else "CONDITIONAL" if len(actions) > 0
        else "READY"
    )
    summary = pd.DataFrame([{
        "Open Actions": len(actions),
        "Sign-off Blocking Actions": blocking,
        "P1 Critical Actions": p1,
        "P2 High Actions": p2,
        "Responsible Teams": teams,
        "Sign-off Evidence Status": decision,
        "Recommendation": (
            "CLOSE_BLOCKING_ACTIONS_BEFORE_SIGN_OFF"
            if decision == "BLOCKED"
            else "CLOSE_REMAINING_ACTIONS_BEFORE_FINAL_APPROVAL"
            if decision == "CONDITIONAL"
            else "EVIDENCE_PACK_READY"
        ),
    }])

    evidence = actions[[
        "Action ID", "Gate / Finding", "Owner Team", "Required Evidence",
        "Closure Criterion", "Sign-off Blocking"
    ]].copy() if not actions.empty else pd.DataFrame(columns=[
        "Action ID", "Gate / Finding", "Owner Team", "Required Evidence",
        "Closure Criterion", "Sign-off Blocking"
    ])

    team_summary = (
        actions.groupby("Owner Team", dropna=False)
        .agg(
            Open_Actions=("Action ID", "count"),
            Blocking_Actions=("Sign-off Blocking", "sum"),
            P1_Actions=("Priority", lambda values: int((values == "P1_CRITICAL").sum())),
            P2_Actions=("Priority", lambda values: int((values == "P2_HIGH").sum())),
        )
        .reset_index()
        .rename(columns={
            "Open_Actions": "Open Actions",
            "Blocking_Actions": "Blocking Actions",
            "P1_Actions": "P1 Actions",
            "P2_Actions": "P2 Actions",
        })
        if not actions.empty else pd.DataFrame()
    )

    return {
        "summary": summary,
        "actions": actions,
        "evidence_matrix": evidence,
        "team_summary": team_summary,
    }
