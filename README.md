# Grade-X Software Compliance Checker — Sprint 5

Sprint 5 adds a professional reporting layer to the existing compliance, release-history and dashboard functions.

## Main capabilities

- Upload one or more Bosch Grade-X `.session` files
- Upload the current FRS / IASRC `.xlsx` or `.xlsm` reference workbook
- Automatic VIN model-year detection
- Target release recommendation and manual selection
- ECU-level software/hardware compliance assessment
- Release-history inference
- Management dashboard and priority-action list
- ECU Release Viewer
- Vehicle-to-vehicle comparison
- Professional Excel and PDF reports

## Sprint 5 Report Center

The new **Report Center** lets the user:

- Select which vehicles/sessions are included
- Enter report title and subtitle
- Enter prepared-by and department/project metadata
- Add an executive comment
- Add engineering notes
- Upload an optional PNG/JPG logo
- Download a professional Excel report
- Download a professional PDF report

### Excel report contents

- Executive Summary with KPI cards and status chart
- Dashboard Status
- Vehicle Summary
- Priority Actions
- Confidence Distribution
- Compliance Overview
- Release Details
- Field Details
- ECU Identifiers
- Candidate Variants
- Raw Identifiers
- One detail worksheet per vehicle/session
- Engineering Notes

### PDF report contents

- Cover and report metadata
- KPI summary
- Executive comment
- Status and vehicle summaries
- Priority actions
- ECU compliance details for each vehicle/session
- Identifier deviations
- Engineering notes
- Assessment disclaimer

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

The FRS/IASRC reference workbook is processed in memory. It is not automatically stored by the application.

## Important

`UPDATE_AVAILABLE` and `WRONG_RELEASE` are engineering decision-support classifications inferred from identifier matching. They must not be treated as automatic ECU flashing, replacement or warranty approval.
