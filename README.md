# Grade-X Software Compliance Checker — Sprint 3

Sprint 3 adds a professional ECU Release Viewer to the direct-workbook architecture.

## Main features

- Upload Grade-X `.session` / XML files
- Upload the current FRS/IASRC `.xlsx` or `.xlsm` workbook for each Streamlit session
- Automatic model-year and target-release suggestion
- Sprint 2 compliance statuses and installed-release inference
- New ECU Release Viewer with:
  - vehicle/session and ECU selection
  - installed ECU identifiers
  - target release comparison
  - field-level MATCH / PART_MATCH / MISMATCH / MISSING reasons
  - best historical release match
  - release-history candidate ranking
  - all target-release variants for the selected ECU
- Excel report with a new `Release Details` worksheet
- English and German interface

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud

Use `app.py` as the Main file path.

## Data handling

The FRS/IASRC workbook is processed in memory. It is not written to a SQLite database or automatically stored by the application.

## Engineering note

Installed-release and update-availability classifications are decision-support inferences based on identifier matching. They do not authorize ECU flashing by themselves.
