# Grade-X Software Compliance Checker

A modular Streamlit application for reading Bosch Grade-X `.session` files and comparing ECU identifiers with an FRS/IASRC release workbook.

## Modules

- `app.py` — Streamlit UI
- `parser.py` — Grade-X XML/session parser
- `frs_database.py` — FRS/IASRC workbook and release-sheet reader
- `compliance.py` — variant selection and field-level compliance engine
- `report.py` — validated Excel report generation without Excel Table objects
- `translations.py` — English/German interface text
- `utils.py` — identifier normalization and VIN model-year decoding

## Run locally

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
# source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Workflow

1. Upload one or more `.session` files.
2. Upload the FRS/IASRC `.xlsx` or `.xlsm` workbook.
3. The app detects the vehicle model year from the VIN and recommends the latest matching release sheet.
4. Each ECU is matched to the best reference variant using its available identifiers.
5. Review overall and field-level statuses and download the formatted Excel report.

## Status logic

- `COMPLIANT` / `MATCH`: exact or fully-supported match — green
- `PART_MATCH`: part number matches but revision detail is insufficient — yellow
- `REVIEW` / `MISSING`: manual review required — yellow
- `MISMATCH`: installed and target identifiers differ — red
- `NO_REFERENCE`: no ECU reference candidate — blue/grey

Do not publish proprietary FRS/IASRC workbooks, VINs, release data, or customer data in a public repository without authorization.
