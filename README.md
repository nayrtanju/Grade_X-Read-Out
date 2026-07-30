# Grade-X Software Compliance Checker — Sprint 2

Sprint 2 upgrades the compliance engine from simple equality checking to release-aware diagnostics.

## New in Sprint 2

- `COMPLIANT`: all applicable identifiers match the selected target release.
- `UPDATE_AVAILABLE`: the vehicle strongly matches an older release from the same model year.
- `PARTIAL_MATCH`: part numbers match but revision precision is insufficient for a full confirmation.
- `MISMATCH`: critical SW/HW identifiers differ from the selected target.
- `WRONG_RELEASE`: identifiers strongly match a different/non-target release.
- `REVIEW`: required identifiers are missing or the decision confidence is insufficient.
- `NO_REFERENCE`: no ECU variant exists in the selected release.
- Candidate confidence score and decision reason.
- Optional release-history analysis across all sheets for the detected model year.
- Updated dashboard and color-coded Excel report.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Upload the current FRS/IASRC workbook and one or more Grade-X `.session` files. The workbook is processed in memory and is not stored by the application.

## Streamlit Cloud

Use `app.py` as the Main file path.

## Important interpretation note

`UPDATE_AVAILABLE` and `WRONG_RELEASE` are inferred from the identifier match quality in the uploaded workbook. They should be treated as engineering decision support, not as an automatic flashing authorization.
