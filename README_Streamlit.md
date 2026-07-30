Grade-X Software Compliance Checker

A Streamlit application that reads Bosch Grade-X .session files and validates ECU software identifiers against an FRS/IASRC reference workbook.

Features

English and German user interface

Multiple .session uploads

VIN and model-year detection

Automatic FRS/IASRC sheet recommendation

ECU variant candidate matching

Field-level checks for:

Bootloader

Calibration Software

Part Number / Version

Application Software

Basic Software

Vehicle Manufacturer ECU Software Number

Hardware Number

Compliance dashboard and mismatch details

Two-vehicle software comparison

Excel compliance report

Repository files

streamlit_app.py
requirements.txt
README_Compliance_Checker.md

The large FRS/IASRC workbook does not have to be committed to GitHub. Users can upload it from the application. Alternatively, place one of these files next to streamlit_app.py:

FRS Partnumber Overview MY23_MY24_MY25_MY26_MY27_250726.xlsm
FRS_Partnumber_Overview.xlsm
FRS_Partnumber_Overview.xlsx

Local installation

python -m venv .venv

Windows:

.venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py

Linux/macOS:

source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py

Streamlit Community Cloud

Push streamlit_app.py, requirements.txt, and this README to GitHub.

Open Streamlit Community Cloud.

Select the repository and streamlit_app.py as the entry point.

Deploy.

Upload the FRS/IASRC workbook through the application.

Matching logic

The application normalizes identifiers such as:

SW-0000001002-001501
SW1002 Rev.1

A full identifier match is reported when the available part number and revision agree. Grade-X may expose only a short revision while the reference workbook stores a longer release revision. In this case, the result is shown as PART MATCH / review required, rather than incorrectly reporting an exact match.

Important

Before publishing the repository or reference data, confirm that no proprietary vehicle, customer, VIN, software-release, or company-confidential information is included.
