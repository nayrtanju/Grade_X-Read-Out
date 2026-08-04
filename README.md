# Grade-X Software Compliance Checker — Sprint 7

Sprint 7 adds fleet analysis, vehicle history and regression detection.

## New capabilities

- Group multiple Grade-X sessions by VIN
- Extract session timestamps from Grade-X file names
- Build chronological ECU software/hardware history
- Detect Application SW, Calibration SW, Basic SW, Bootloader, part-number and hardware changes
- Detect compliance-status transitions
- Flag regression when a previously compliant ECU becomes MISMATCH, WRONG_RELEASE or REVIEW
- Detect increases in persistent DTC count
- Provide fleet-level vehicle/session/KPI summary
- Export Fleet Summary, Change Log and Vehicle History to Excel

## Recommended workflow

Upload multiple `.session` files for the same VIN, the FRS/IASRC reference workbook, and optional DTC logs. The Fleet & Vehicle History tab then compares chronologically ordered sessions.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Streamlit Cloud main file: `app.py`
