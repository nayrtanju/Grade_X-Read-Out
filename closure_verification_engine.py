from __future__ import annotations

from typing import Any

import pandas as pd


ALLOWED_CLOSURE_STATUS = [
    "OPEN",
    "IN_PROGRESS",
    "EVIDENCE_SUBMITTED",
    "VERIFIED_CLOSED",
    "REJECTED",
]

ALLOWED_VERIFICATION = [
    "NOT_REVIEWED",
    "ACCEPTED",
    "REJECTED",
]


def _text(value: Any) -> str:
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value or "").strip()


def prepare_closure_register(actions: pd.DataFrame | None) -> pd.DataFrame:
    if actions is None or actions.empty:
        return pd.DataFrame(columns=[
            "Action ID",
            "Priority",
            "Owner Team",
            "Gate / Finding",
            "Required Action",
            "Required Evidence",
            "Closure Criterion",
            "Sign-off Blocking",
            "Closure Status",
            "Evidence Reference",
            "Verification Result",
            "Reviewer Comment",
        ])

    result = actions.copy()
    defaults = {
        "Closure Status": "OPEN",
        "Evidence Reference": "",
        "Verification Result": "NOT_REVIEWED",
        "Reviewer Comment": "",
    }
    for column, default in defaults.items():
        if column not in result.columns:
            result[column] = default

    preferred = [
        "Action ID",
        "Priority",
        "Owner Team",
        "Gate / Finding",
        "Required Action",
        "Required Evidence",
        "Closure Criterion",
        "Sign-off Blocking",
        "Closure Status",
        "Evidence Reference",
        "Verification Result",
        "Reviewer Comment",
    ]
    for column in preferred:
        if column not in result.columns:
            result[column] = ""
    return result[preferred].copy()


def evaluate_action_closure(register: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    register = prepare_closure_register(register)

    if register.empty:
        summary = pd.DataFrame([{
            "Actions": 0,
            "Verified Closed": 0,
            "Evidence Submitted": 0,
            "In Progress": 0,
            "Open / Rejected": 0,
            "Blocking Actions Remaining": 0,
            "Closure Rate %": 100.0,
            "Evidence Acceptance %": 100.0,
            "Final Sign-off Readiness": "READY",
            "Recommendation": "FINAL_SIGN_OFF_READY",
        }])
        return {
            "summary": summary,
            "register": register,
            "open_actions": register,
            "evidence_matrix": register,
            "team_summary": pd.DataFrame(),
        }

    closure_status = register["Closure Status"].map(_text)
    verification = register["Verification Result"].map(_text)
    blocking = register["Sign-off Blocking"].fillna(False).astype(bool)

    verified_closed = int(
        (closure_status.eq("VERIFIED_CLOSED") & verification.eq("ACCEPTED")).sum()
    )
    evidence_submitted = int(closure_status.eq("EVIDENCE_SUBMITTED").sum())
    in_progress = int(closure_status.eq("IN_PROGRESS").sum())
    open_rejected = int(
        closure_status.isin(["OPEN", "REJECTED"]).sum()
        + verification.eq("REJECTED").sum()
    )

    blocking_remaining_mask = blocking & ~(
        closure_status.eq("VERIFIED_CLOSED") & verification.eq("ACCEPTED")
    )
    blocking_remaining = int(blocking_remaining_mask.sum())

    total = len(register)
    closure_rate = verified_closed / total * 100 if total else 100.0

    reviewed = verification.isin(["ACCEPTED", "REJECTED"])
    accepted = verification.eq("ACCEPTED")
    evidence_acceptance = (
        accepted.sum() / reviewed.sum() * 100 if reviewed.sum() else 0.0
    )

    if blocking_remaining > 0:
        readiness = "BLOCKED"
    elif verified_closed == total:
        readiness = "READY"
    elif verified_closed > 0 or evidence_submitted > 0 or in_progress > 0:
        readiness = "CONDITIONAL"
    else:
        readiness = "NOT_READY"

    summary = pd.DataFrame([{
        "Actions": total,
        "Verified Closed": verified_closed,
        "Evidence Submitted": evidence_submitted,
        "In Progress": in_progress,
        "Open / Rejected": open_rejected,
        "Blocking Actions Remaining": blocking_remaining,
        "Closure Rate %": round(closure_rate, 1),
        "Evidence Acceptance %": round(evidence_acceptance, 1),
        "Final Sign-off Readiness": readiness,
        "Recommendation": (
            "FINAL_SIGN_OFF_READY"
            if readiness == "READY"
            else "VERIFY_REMAINING_NON_BLOCKING_ACTIONS"
            if readiness == "CONDITIONAL"
            else "CLOSE_BLOCKING_ACTIONS"
            if readiness == "BLOCKED"
            else "START_ACTION_CLOSURE"
        ),
    }])

    open_actions = register[
        ~(
            closure_status.eq("VERIFIED_CLOSED")
            & verification.eq("ACCEPTED")
        )
    ].copy()

    evidence_matrix = register[[
        "Action ID",
        "Owner Team",
        "Priority",
        "Required Evidence",
        "Evidence Reference",
        "Verification Result",
        "Closure Criterion",
        "Closure Status",
        "Sign-off Blocking",
    ]].copy()

    team_summary = (
        register.assign(
            _closed=closure_status.eq("VERIFIED_CLOSED")
            & verification.eq("ACCEPTED"),
            _blocking_remaining=blocking_remaining_mask,
        )
        .groupby("Owner Team", dropna=False)
        .agg(
            Actions=("Action ID", "count"),
            Verified_Closed=("_closed", "sum"),
            Blocking_Remaining=("_blocking_remaining", "sum"),
            Evidence_Submitted=(
                "Closure Status",
                lambda values: int(
                    pd.Series(values).astype(str).eq("EVIDENCE_SUBMITTED").sum()
                ),
            ),
        )
        .reset_index()
        .rename(columns={
            "Verified_Closed": "Verified Closed",
            "Blocking_Remaining": "Blocking Remaining",
            "Evidence_Submitted": "Evidence Submitted",
        })
    )

    return {
        "summary": summary,
        "register": register,
        "open_actions": open_actions,
        "evidence_matrix": evidence_matrix,
        "team_summary": team_summary,
    }
