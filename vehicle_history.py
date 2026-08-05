from __future__ import annotations
import re
from datetime import datetime
import pandas as pd

SOFTWARE_FIELDS = ["Hardware Number","Application SW","Calibration SW","Part Number","Basic SW","Software Number","Bootloader"]

def session_timestamp(source_file: str):
    value = str(source_file or "")
    m = re.search(r"(\d{4}-\d{2}-\d{2})[_ T](\d{2}-\d{2}-\d{2})", value)
    if m:
        try: return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H-%M-%S")
        except ValueError: pass
    return pd.NaT

def build_vehicle_history(summary: pd.DataFrame, overview: pd.DataFrame) -> pd.DataFrame:
    if summary.empty: return pd.DataFrame()
    base = summary.copy()
    base["Session Timestamp"] = base["Source File"].map(session_timestamp)
    cols = ["Source File","Session Timestamp","VIN","ECU ID","ECU Name",*SOFTWARE_FIELDS,
            "External DTC Count","Persistent DTC Count","DTC Codes","DTC Severity"]
    base = base[[c for c in cols if c in base.columns]]
    if not overview.empty:
        ocols = [c for c in ["Source File","ECU","Status","Target Release","Installed Release","Confidence %","Decision Reason"] if c in overview.columns]
        base = base.merge(overview[ocols].rename(columns={"ECU":"ECU ID"}), on=["Source File","ECU ID"], how="left")
    return base.sort_values(["VIN","Session Timestamp","Source File","ECU ID"]).reset_index(drop=True)

def build_change_log(history: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    if history.empty: return pd.DataFrame()
    for (vin,ecu), group in history.groupby(["VIN","ECU ID"], dropna=False):
        group=group.sort_values(["Session Timestamp","Source File"]).reset_index(drop=True)
        for i in range(1,len(group)):
            prev,cur=group.iloc[i-1],group.iloc[i]
            for field in SOFTWARE_FIELDS:
                if field in group.columns and str(prev.get(field,"") or "") != str(cur.get(field,"") or ""):
                    rows.append({"VIN":vin,"ECU":ecu,"Previous Session":prev["Source File"],"Current Session":cur["Source File"],
                                 "Change Type":"SOFTWARE_CHANGE","Field":field,"Previous Value":prev.get(field,""),
                                 "Current Value":cur.get(field,""),"Regression":False})
            old,new=str(prev.get("Status","") or ""),str(cur.get("Status","") or "")
            if old!=new:
                rows.append({"VIN":vin,"ECU":ecu,"Previous Session":prev["Source File"],"Current Session":cur["Source File"],
                             "Change Type":"COMPLIANCE_TRANSITION","Field":"Status","Previous Value":old,"Current Value":new,
                             "Regression":old=="COMPLIANT" and new in {"MISMATCH","WRONG_RELEASE","REVIEW"}})
            od,nd=int(prev.get("Persistent DTC Count",0) or 0),int(cur.get("Persistent DTC Count",0) or 0)
            if od!=nd:
                rows.append({"VIN":vin,"ECU":ecu,"Previous Session":prev["Source File"],"Current Session":cur["Source File"],
                             "Change Type":"DTC_CHANGE","Field":"Persistent DTC Count","Previous Value":od,"Current Value":nd,
                             "Regression":nd>od})
    return pd.DataFrame(rows)

def fleet_summary(history: pd.DataFrame, changes: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    if history.empty: return pd.DataFrame()
    for vin,group in history.groupby("VIN",dropna=False):
        latest=group.sort_values(["Session Timestamp","Source File"]).groupby("ECU ID").tail(1)
        status=latest.get("Status",pd.Series(dtype=str)).astype(str)
        vc=changes[changes["VIN"]==vin] if not changes.empty else pd.DataFrame()
        rows.append({"VIN":vin,"Sessions":group["Source File"].nunique(),"Latest ECUs":len(latest),
                     "Compliant":int((status=="COMPLIANT").sum()),"Critical":int(status.isin(["MISMATCH","WRONG_RELEASE"]).sum()),
                     "Persistent DTCs":int(pd.to_numeric(latest.get("Persistent DTC Count",0),errors="coerce").fillna(0).sum()),
                     "Software Changes":int((vc.get("Change Type",pd.Series(dtype=str))=="SOFTWARE_CHANGE").sum()),
                     "Regressions":int(vc.get("Regression",pd.Series(dtype=bool)).fillna(False).sum())})
    return pd.DataFrame(rows)
