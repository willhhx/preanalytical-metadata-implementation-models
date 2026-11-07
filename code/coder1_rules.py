#!/usr/bin/env python3
"""
coder1_rules.py -- rule-based, fully reproducible first-pass coding of the BBMRI sample (coder 1).

Applies the eligibility rule and the level rules from CODING_GUIDE.md (BBMRI section) to the snapshot text
in manual/coding_BBMRI_coder1.*, using only the snap_* columns. Every level-1 decision records the matched
phrase in `notes`. This pass was produced with AI assistance (Claude) and MUST be spot-checked by the
researcher before reporting; declare this in Methods.

Eligibility (fixed before coding):
  tissue   : 'TISSUE_*' in materials, OR the description states tissue/biopsy/FFPE/frozen/paraffin/resection
  oncology : name/description mention cancer, tumour, neoplasm, malignancy, carcinoma, sarcoma, lymphoma, leukaemia,
             OR >= 50% of the keywords are neoplasm terms
  Ineligible records are skipped; reserves (is_reserve=TRUE) are used in slot order until 30 records are coded.

Usage:  python coder1_rules.py            (writes coding_BBMRI_coder1.csv and .xlsx; refuses if levels already filled)
"""
import datetime as dt
import re
import sys

import pandas as pd

from manual_common import MANUAL, core_elements

TODAY = dt.date.today().isoformat()
PATH = MANUAL / "coding_BBMRI_coder1.csv"


def clean(v):
    v = "" if v is None else str(v)
    return "" if v.strip().lower() == "nan" else v


ONC = re.compile(r"cancer|tumou?r|neoplas|malignan|carcinoma|sarcoma|lymphoma|leuk[a]?emi|melanoma|glioma|myeloma|oncolog", re.I)
TIS = re.compile(r"tissue|biops|FFPE|paraffin|frozen|resect|tumou?r bank|tumou?r material", re.I)
RULES = {  # element -> (regex, level when matched)
    "B1": (re.compile(r"underwent surgery|surgery|surgical cohort|resection|biops\w*|explant\w*|post-?mortem|autops\w*|surplus diagnostic", re.I), 1),
    "B3": (re.compile(r"warm isch[a]?emi\w*", re.I), 1),
    "B4": (re.compile(r"cold isch[a]?emi\w*|time to (?:freezing|fixation)|within \d+ ?(?:min|minutes|h|hours)", re.I), 1),
    "D1": (re.compile(r"formalin|neutral[- ]buffered|paraformaldehyde|PAXgene", re.I), 1),
    "D2": (re.compile(r"fixation (?:time|duration)|fixed for|hours in formalin", re.I), 1),
    "D3": (re.compile(r"snap[- ]frozen|snap[- ]freez\w*|instant freezing|isopentane|liquid nitrogen|\bOCT\b|RNAlater|controlled[- ]rate|flash[- ]frozen", re.I), 1),
    "E1": (re.compile(r"[-−–]\s?\d{2,3}\s?°?\s?C", re.I), 1),
    "E2": (re.compile(r"stored for|storage (?:time|duration)|years in storage", re.I), 1),
    "E3": (re.compile(r"thaw", re.I), 1),
    "E4": (re.compile(r"(?:temperature|freezer|storage)[^.]{0,40}monitor\w*|monitor\w*[^.]{0,40}(?:temperature|freezer|storage)|excursion", re.I), 1),
    "G1": (re.compile(r"verified by the pathologist|pathologist|\bRIN\b|DV200|quality control|\bQC\b|percent tumou?r|tumou?r content", re.I), 1),
    "G2": (re.compile(r"SPREC", re.I), 1),
    "G3": (re.compile(r"\bSOP\b|ISO ?20387|ISBER|standard operating procedure", re.I), 1),
}
POSTMORTEM = re.compile(r"post-?mortem|autops\w*", re.I)
FFPE_EVID = re.compile(r"FFPE|paraffin|formalin|fixed", re.I)
FROZEN_EVID = re.compile(r"frozen|OCT\b|snap|freez", re.I)


def judge(r, core):
    name, desc = clean(r["snap_name"]), clean(r["snap_description"])
    kws = [k for k in clean(r["snap_keywords"]).split(";") if k]
    mats = clean(r["snap_materials"])
    temps = [t for t in clean(r["snap_storage_temperatures"]).split(";") if t]
    sops = clean(r["snap_sop"])
    text = f"{name}. {desc}"
    kwshare = (sum(bool(ONC.search(k)) for k in kws) / len(kws)) if kws else 0.0
    tissue_ok = "TISSUE_" in mats or bool(TIS.search(desc))
    onc_ok = bool(ONC.search(text)) or kwshare >= 0.5
    if not tissue_ok or not onc_ok:
        why = []
        if not tissue_ok:
            why.append("no solid-tissue evidence in materials or description")
        if not onc_ok:
            why.append(f"not oncology-focused (neoplasm terms in {kwshare:.0%} of keywords, none in name/description)")
        return None, "INELIGIBLE: " + "; ".join(why)

    lv, notes = {}, []
    paraffin = "TISSUE_PARAFFIN_EMBEDDED" in mats or "TISSUE_STAINED" in mats or bool(FFPE_EVID.search(desc))
    frozen = "TISSUE_FROZEN" in mats or bool(FROZEN_EVID.search(desc))
    for e in core:
        if e == "D4":
            if POSTMORTEM.search(text):
                lv[e] = "0"; notes.append("D4: post-mortem collection, PMI not stated")
            else:
                lv[e] = "NA"
            continue
        if e == "E1":
            if temps:
                lv[e] = "2" if any(t == "temperatureOther" for t in temps) else "3"
                notes.append(f"E1: structured storage_temperatures={'/'.join(temps)}" +
                             (" (mixed incl. temperatureOther -> 2)" if lv[e] == "2" and len(temps) > 1 else ""))
                continue
        if e == "G3" and sops:
            lv[e] = "2"; notes.append("G3: structured sop field populated (existence flags, no named standard)")
            continue
        if e in ("D1", "D2") and frozen and not paraffin:
            lv[e] = "NA"; notes.append(f"{e}: NA frozen-only collection"); continue
        if e == "D3" and paraffin and not frozen:
            lv[e] = "NA"; notes.append("D3: NA FFPE-only collection"); continue
        rx, val = RULES[e]
        m = rx.search(text) or (rx.search(clean(r["snap_access_description"])) if e == "G3" else None)
        if m:
            lv[e] = str(val); notes.append(f'{e}: "{m.group(0)}"')
        else:
            lv[e] = "0"
    return lv, "; ".join(notes)


def main():
    core, _ = core_elements()
    df = pd.read_csv(PATH, dtype=str, keep_default_na=False)
    if any(df[e].str.strip().ne("").any() for e in core):
        sys.exit("Levels already present in coder 1 sheet; refusing to overwrite. Delete the sheet and re-run 07 if you want a fresh pass.")
    for c in [c for c in df.columns if c.startswith("snap_")]:
        df[c] = df[c].map(clean)

    need = 30
    coded = 0
    for ix in df.sort_values("record_slot", key=lambda s: s.astype(int)).index:
        r = df.loc[ix]
        if coded >= need:
            df.loc[ix, "notes"] = "UNUSED RESERVE (30 eligible records already coded)" if r["is_reserve"] == "TRUE" else ""
            continue
        lv, note = judge(r, core)
        df.loc[ix, "evidence_url"] = "snapshot: out/bbmri_collections_snapshot.csv (retrieved " + r["snap_retrieved_utc"][:10] + ")"
        df.loc[ix, "accessed_date"] = TODAY
        df.loc[ix, "coder"] = "coder1 (AI-assisted rules pass: Claude; researcher verification pending)"
        if lv is None:
            df.loc[ix, "notes"] = note
            continue
        for e in core:
            df.loc[ix, e] = lv[e]
        df.loc[ix, "notes"] = note
        coded += 1
    df.to_csv(PATH, index=False)

    # xlsx: fill in the existing workbook so dropdown validation is kept
    xp = PATH.with_suffix(".xlsx")
    try:
        from openpyxl import load_workbook
        wb = load_workbook(xp)
        ws = wb["coding"]
        hdr = [c.value for c in ws[1]]
        for i in range(2, ws.max_row + 1):
            slot = str(ws.cell(i, hdr.index("record_slot") + 1).value)
            row = df[df["record_slot"] == slot].iloc[0]
            for col in hdr:
                if col in core or col in ("evidence_url", "accessed_date", "coder", "notes") or col.startswith("snap_"):
                    v = row[col]
                    if col in core and v in ("0", "1", "2", "3"):
                        v = int(v)
                    ws.cell(i, hdr.index(col) + 1).value = v if v != "" else None
        wb.save(xp)
        print("updated", xp.name)
    except Exception as ex:  # noqa: BLE001
        print("xlsx not updated:", ex)
    print(f"coded {coded} eligible records")
    show = df[["record_slot", "is_reserve"] + core + ["notes"]].copy()
    show["notes"] = show["notes"].str.slice(0, 60)
    print(show.to_string(index=False))


if __name__ == "__main__":
    main()
