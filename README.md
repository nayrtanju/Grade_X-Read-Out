# Grade-X Software Compliance Checker — Sprint 1 (Direct Workbook Mode)

This version intentionally does **not** use SQLite. The FRS/IASRC reference workbook must be uploaded for every new Streamlit session. The application reads the available release sheets directly from the uploaded `.xlsx` or `.xlsm` file and caches the parsed result in memory.

## Main features

- English and German user interface
- Upload one or more Grade-X `.session`/XML files
- Upload an FRS/IASRC `.xlsx` or `.xlsm` reference workbook
- Automatic model-year detection from VIN
- Recommended release sheet based on detected model year
- Direct ECU software/hardware compliance validation
- Candidate ECU variant matching
- Vehicle-to-vehicle comparison
- Safe, colour-coded Excel report without Excel Table objects

## Project files

- `app.py` — Streamlit interface
- `parser.py` — Grade-X session parser
- `frs_database.py` — direct FRS/IASRC workbook reader (despite the historic module name, no database is used)
- `compliance.py` — comparison and compliance logic
- `report.py` — Excel report generation
- `translations.py` — English/German interface text
- `utils.py` — shared helper functions

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud

Set **Main file path** to:

```text
app.py
```

At runtime:

1. Upload one or more Grade-X session files.
2. Upload the current FRS/IASRC reference workbook.
3. Confirm or change the automatically recommended release sheet.
4. Review the compliance results and download the Excel report.

## Data handling

The reference workbook is processed in memory for the current Streamlit session. It is not converted to SQLite and is not written into the repository by this application.

Do not commit internal FRS/IASRC workbooks, production VIN data, session files, or generated reports to a public repository.
