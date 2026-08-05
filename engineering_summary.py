from __future__ import annotations

from typing import Any

import pandas as pd


def _n(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _join_sentences(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def engineering_summary(
    overview: pd.DataFrame,
    vehicle_health: pd.DataFrame,
    warranty_summary: pd.DataFrame,
    language: str = "English",
) -> pd.DataFrame:
    if overview is None or overview.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    german = language == "Deutsch"

    for (source_file, vin), group in overview.groupby(["Source File", "VIN"], dropna=False):
        health_match = vehicle_health[
            (vehicle_health["Source File"].astype(str) == str(source_file))
            & (vehicle_health["VIN"].astype(str) == str(vin))
        ]
        warranty_match = warranty_summary[
            (warranty_summary["Source File"].astype(str) == str(source_file))
            & (warranty_summary["VIN"].astype(str) == str(vin))
        ]

        health = health_match.iloc[0] if not health_match.empty else pd.Series(dtype=object)
        warranty = warranty_match.iloc[0] if not warranty_match.empty else pd.Series(dtype=object)

        status = group.get("Status", pd.Series(dtype=str)).astype(str)
        compliant = int((status == "COMPLIANT").sum())
        update = int((status == "UPDATE_AVAILABLE").sum())
        critical_config = int(status.isin(["MISMATCH", "WRONG_RELEASE"]).sum())
        review = int(status.isin(["REVIEW", "PARTIAL_MATCH", "NO_REFERENCE"]).sum())
        persistent = int(
            pd.to_numeric(group.get("Persistent DTC Count", 0), errors="coerce")
            .fillna(0).sum()
        )
        high_decisions = int(
            group.get("Decision Urgency", pd.Series(dtype=str))
            .astype(str).isin(["HIGH", "CRITICAL"]).sum()
        )
        highest = group.sort_values(
            ["Risk Score", "Decision Confidence %"],
            ascending=[False, False],
        ).iloc[0]

        health_score = _n(health.get("Vehicle Health Score", 0))
        health_level = str(health.get("Vehicle Health Level", "UNKNOWN"))
        warranty_code = str(warranty.get("Warranty Recommendation", "FURTHER_DIAGNOSTIC_REQUIRED"))
        warranty_label = str(warranty.get("Warranty Recommendation Label", warranty_code))
        next_step = str(warranty.get("Required Next Step", ""))
        root_cause = str(highest.get("Primary Root Cause", ""))
        top_actions = str(highest.get("Recommended Actions", "")).split(" | ")[:3]
        top_actions_text = "; ".join(action for action in top_actions if action)

        if german:
            executive = _join_sentences([
                f"Die Fahrzeugkonfiguration umfasst {len(group)} ausgewertete Steuergeräte.",
                f"{compliant} Steuergeräte sind vollständig konform.",
                f"{critical_config} kritische Software-/Release-Abweichungen, {update} verfügbare Updates und {review} manuell zu prüfende Ergebnisse wurden erkannt.",
                f"Der Fahrzeugzustand beträgt {health_score:.1f}/100 und wird als {health_level} bewertet.",
                f"{persistent} persistente DTC-Einträge und {high_decisions} Entscheidungen mit hoher oder kritischer Dringlichkeit liegen vor.",
            ])
            technical = _join_sentences([
                f"Das Steuergerät mit dem höchsten Risiko ist {highest.get('ECU', '')} mit einem Risikowert von {_n(highest.get('Risk Score', 0)):.0f}/100.",
                f"Primäre technische Hypothese: {root_cause}",
                f"Empfohlene technische Schritte: {top_actions_text}",
            ])
            warranty_text = _join_sentences([
                f"Warranty-Triage-Empfehlung: {warranty_label}.",
                f"Erforderlicher nächster Schritt: {next_step}",
                "Die Empfehlung ist eine regelbasierte Entscheidungshilfe und keine automatische Warranty-Freigabe.",
            ])
        else:
            executive = _join_sentences([
                f"The vehicle configuration contains {len(group)} assessed ECUs.",
                f"{compliant} ECUs are fully compliant.",
                f"{critical_config} critical software/release deviations, {update} available updates and {review} manual-review results were identified.",
                f"Vehicle Health is {health_score:.1f}/100 and is classified as {health_level}.",
                f"The assessment contains {persistent} persistent DTC records and {high_decisions} high/critical-urgency decisions.",
            ])
            technical = _join_sentences([
                f"The highest-risk ECU is {highest.get('ECU', '')} with a risk score of {_n(highest.get('Risk Score', 0)):.0f}/100.",
                f"Primary technical hypothesis: {root_cause}",
                f"Recommended technical steps: {top_actions_text}",
            ])
            warranty_text = _join_sentences([
                f"Warranty triage recommendation: {warranty_label}.",
                f"Required next step: {next_step}",
                "This is a rule-based decision-support recommendation and not an automatic warranty authorization.",
            ])

        rows.append({
            "Source File": source_file,
            "VIN": vin,
            "Executive Summary": executive,
            "Technical Summary": technical,
            "Warranty Summary": warranty_text,
            "Combined Engineering Summary": _join_sentences([executive, technical, warranty_text]),
            "Vehicle Health Score": health_score,
            "Vehicle Health Level": health_level,
            "Warranty Recommendation": warranty_code,
            "Lead ECU": highest.get("ECU", ""),
            "Lead Risk Score": highest.get("Risk Score", 0),
            "Lead Decision": highest.get("Decision", ""),
        })

    return pd.DataFrame(rows)


def fleet_engineering_summary(
    vehicle_summaries: pd.DataFrame,
    language: str = "English",
) -> str:
    if vehicle_summaries is None or vehicle_summaries.empty:
        return ""

    german = language == "Deutsch"
    vehicles = len(vehicle_summaries)
    critical = int(
        (vehicle_summaries["Vehicle Health Level"].astype(str) == "CRITICAL").sum()
    )
    poor = int(
        (vehicle_summaries["Vehicle Health Level"].astype(str) == "POOR").sum()
    )
    escalation = int(
        (vehicle_summaries["Warranty Recommendation"].astype(str) == "ENGINEERING_ESCALATION").sum()
    )
    average_health = pd.to_numeric(
        vehicle_summaries["Vehicle Health Score"], errors="coerce"
    ).mean()

    if german:
        return (
            f"Die Flottenauswertung umfasst {vehicles} Fahrzeuge/Sessions mit einem "
            f"durchschnittlichen Fahrzeugzustand von {average_health:.1f}/100. "
            f"{critical} Fahrzeuge sind als CRITICAL und {poor} als POOR bewertet. "
            f"Für {escalation} Fahrzeuge wird eine Engineering-Eskalation empfohlen."
        )

    return (
        f"The fleet assessment covers {vehicles} vehicles/sessions with an average "
        f"Vehicle Health score of {average_health:.1f}/100. "
        f"{critical} vehicles are classified as CRITICAL and {poor} as POOR. "
        f"Engineering escalation is recommended for {escalation} vehicles."
    )
