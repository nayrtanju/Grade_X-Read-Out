# Grade-X Software Compliance Checker — Sprint 4

Streamlit application for validating Grade-X `.session` ECU identifiers against an uploaded FRS/IASRC reference workbook.

## Sprint 4 scope

Sprint 4 adds a management dashboard on top of the Sprint 3 release viewer and Sprint 2 compliance engine.

### Dashboard

- Dynamic vehicle/session, ECU, status and minimum-confidence filters
- Filtered ECU count and compliance rate
- Critical mismatch / wrong-release KPI
- Average confidence KPI
- Status distribution
- Confidence distribution
- Vehicle-level summary
- Prioritised action list with affected identifier fields

### Compliance decisions

- `COMPLIANT`
- `UPDATE_AVAILABLE`
- `PARTIAL_MATCH`
- `MISMATCH`
- `WRONG_RELEASE`
- `REVIEW`
- `NO_REFERENCE`

### Release Viewer

- Installed ECU identifiers
- Target values and field-level results
- Best historical release match
- Release timeline candidates
- Target release variants

### Excel report

The downloaded report contains:

- Report Summary
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

The report uses normal worksheet ranges and filters; no Excel Table XML objects are created.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud

Set **Main file path** to:

```text
app.py
```

The FRS/IASRC workbook is uploaded for every application session and processed in memory. It is not stored by the application.


## Sprint 4 Hotfix

- Added missing EN/DE translation keys.
- Replaced deprecated `use_container_width=True` with `width="stretch"`.
- Replaced runtime-sensitive dataclasses with `NamedTuple` records for Python 3.14 compatibility.
- Added `runtime.txt` requesting Python 3.13 on Streamlit Cloud.
