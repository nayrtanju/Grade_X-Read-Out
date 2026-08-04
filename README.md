# Grade-X Software Compliance Checker - Sprint 6

Sprint 6 adds DTC log parsing and diagnostic correlation to the existing software compliance, release-history, dashboard and professional-reporting functions.

## Main capabilities

- Upload one or more Bosch Grade-X `.session` files
- Upload the current FRS / IASRC `.xlsx` or `.xlsm` reference workbook
- Optionally upload one or more Grade-X DTC `.log` or `.txt` files
- Map each DTC log to its corresponding vehicle/session
- Parse ECU, DTC code, failure type, timestamp and read cycle
- Detect DTCs that reappear after a clear operation
- Correlate DTC findings with ECU application, calibration, hardware and bootloader levels
- Automatic VIN model-year detection
- Target release recommendation and manual selection
- ECU-level software/hardware compliance assessment
- Release-history inference
- Management dashboard and priority-action list
- ECU Release Viewer
- Vehicle-to-vehicle comparison
- Professional Excel and PDF reports

## Sprint 6 DTC Center

The new **DTC Center** displays:

- Unique DTC records
- Affected ECUs
- DTC event count
- DTCs that reappeared after clear
- DTC base code and failure type
- Network, powertrain, body or chassis category
- Occurrence count
- First and last detection time
- Read-cycle count
- Persistence classification
- Diagnostic severity

### Persistence classification

- `REAPPEARED_AFTER_CLEAR`: The DTC was detected after a clear request.
- `REPEATED`: The DTC appeared more than once in the log.
- `OBSERVED_ONCE`: The DTC appeared once and no post-clear recurrence was detected.

### Severity classification

- `HIGH`: DTC reappeared after clear.
- `MEDIUM`: Repeated DTC or a one-time powertrain/chassis DTC.
- `LOW`: One-time body/network observation without recurrence.

These are triage classifications and do not replace the OEM diagnostic specification.

## Session correlation

When one session is uploaded, DTC logs are automatically mapped to it.

With multiple sessions:

- A VIN in the DTC log filename is used for automatic mapping where possible.
- Otherwise the user selects the corresponding session in the mapping panel.

The correlated ECU table includes:

- External DTC Count
- Persistent DTC Count
- DTC Codes
- DTC Severity

Persistent DTCs are also added to the Priority Actions list.

## Reporting

### Excel report

Sprint 6 adds:

- DTC Summary
- DTC Events
- DTC columns in ECU and vehicle sheets
- Persistent-DTC KPI in the Executive Summary

### PDF report

Sprint 6 adds:

- Persistent-DTC KPI
- Diagnostic Trouble Codes section
- DTC count and code information in vehicle ECU details

## Installation

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run:

```bash
streamlit run app.py
```

## Streamlit Cloud

Use:

```text
Main file path: app.py
```

The repository includes `runtime.txt` to request Python 3.13.

## Data handling

The session, DTC and FRS/IASRC files are processed in memory. They are not automatically stored by the application.

## Important

- `UPDATE_AVAILABLE` and `WRONG_RELEASE` are engineering decision-support classifications inferred from identifier matching.
- DTC persistence and severity are log-based triage classifications.
- Neither result should be treated as automatic approval for ECU flashing, replacement or warranty authorization.
