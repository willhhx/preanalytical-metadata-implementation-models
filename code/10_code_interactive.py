#!/usr/bin/env python3
"""
10_code_interactive.py -- code a coding sheet record by record in the terminal (blank cells only).

    python 10_code_interactive.py --catalogue BBMRI --coder coder2

For each record that still has blank levels it prints the snapshot evidence (name, description, structured
fields) and asks for the 14 core levels one at a time. Allowed answers: 0 1 2 3 NA
Other keys at any prompt:  b = back one element   s = skip this record   q = save and quit   ? = show the rules
Progress is saved after every record (CSV and, if present, the XLSX), so you can quit and resume.
Open CODING_GUIDE.md (BBMRI section) first. For coder2 do NOT open coder 1's sheet.
"""
import argparse
import datetime as dt
import textwrap

import pandas as pd

from manual_common import MANUAL, core_elements, find_sheet, read_sheet, norm_level

RULES = """Levels: 0 not stated | 1 free text only | 2 structured field, populated | 3 structured + coded standard | NA not applicable
 NA: D1/D2 for frozen-only collections, D3 for FFPE-only, D4 unless post-mortem.   Do not infer. Code the snapshot only.
 E1: structured storage_temperatures=3 (2 if it includes temperatureOther); temperature only in text=1.
 G3: structured sop flags=2 (no named standard); named SOP/standard in text=1."""
SNAP = ["snap_name", "snap_description", "snap_materials", "snap_storage_temperatures", "snap_sop",
        "snap_quality", "snap_data_categories", "snap_type", "snap_keywords", "snap_access_description"]


def save(df, path_csv, core):
    df.to_csv(path_csv, index=False)
    xp = path_csv.with_suffix(".xlsx")
    if xp.exists():
        try:
            from openpyxl import load_workbook
            wb = load_workbook(xp)
            ws = wb["coding"]
            hdr = [c.value for c in ws[1]]
            for i in range(2, ws.max_row + 1):
                slot = str(ws.cell(i, hdr.index("record_slot") + 1).value)
                row = df[df["record_slot"] == slot].iloc[0]
                for col in list(core) + ["notes", "accessed_date", "evidence_url", "coder"]:
                    if col in hdr:
                        v = row[col]
                        if col in core and v in ("0", "1", "2", "3"):
                            v = int(v)
                        ws.cell(i, hdr.index(col) + 1).value = v if v != "" else None
            wb.save(xp)
        except Exception as e:  # noqa: BLE001
            print("  (xlsx not updated:", e, ")")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", default="BBMRI")
    ap.add_argument("--coder", default="coder2", choices=["coder1", "coder2"])
    args = ap.parse_args()
    src = find_sheet(args.catalogue, args.coder)
    df = read_sheet(src)
    core, card = core_elements()
    core = [e for e in core if e in df.columns]
    label = dict(zip(card["element_id"], card["element"]))
    path_csv = MANUAL / f"coding_{args.catalogue}_{args.coder}.csv"
    for c in core + ["notes", "accessed_date", "evidence_url", "coder"]:
        if c not in df.columns:
            df[c] = ""
    todo = [ix for ix in df.index
            if any(str(df.at[ix, e]).strip() == "" for e in core)
            and not str(df.at[ix, "notes"]).upper().startswith(("INELIGIBLE", "UNUSED"))]
    print(f"{len(todo)} record(s) with blank levels in {src.name}.\n{RULES}\n")
    for n, ix in enumerate(todo, 1):
        r = df.loc[ix]
        print("=" * 100)
        print(f"Record {n}/{len(todo)}   slot {r['record_slot']}   {r['record_id']}")
        for k in SNAP:
            v = str(r.get(k, "")).strip()
            if v and v.lower() != "nan":
                print(textwrap.fill(f"{k[5:]}: {v}", width=100, subsequent_indent="    "))
        print("-" * 100)
        i, vals = 0, {e: str(df.at[ix, e]).strip() for e in core}
        quit_now = False
        while i < len(core):
            e = core[i]
            if vals[e] != "":
                i += 1
                continue
            ans = input(f"  {e} {label.get(e, '')} [0/1/2/3/NA, b, s, q, ?]: ").strip().upper()
            if ans == "?":
                print(RULES)
            elif ans == "Q":
                quit_now = True
                break
            elif ans == "S":
                vals = None
                break
            elif ans == "B":
                j = i - 1
                while j >= 0 and vals[core[j]] == "":
                    j -= 1
                if j >= 0:
                    vals[core[j]] = ""
                    i = j
            else:
                try:
                    lv = norm_level(ans)
                except ValueError:
                    lv = None
                if lv is None or lv == "":
                    print("   -> enter 0, 1, 2, 3 or NA")
                else:
                    vals[e] = str(lv)
                    i += 1
        if quit_now:
            print("Saved. Quitting.")
            break
        if vals is None:
            print("  skipped")
            continue
        note = input("  notes (quote the deciding phrase for any level 1; Enter to skip): ").strip()
        for e in core:
            df.at[ix, e] = vals[e]
        df.at[ix, "notes"] = note
        df.at[ix, "accessed_date"] = dt.date.today().isoformat()
        df.at[ix, "evidence_url"] = "snapshot: out/bbmri_collections_snapshot.csv"
        df.at[ix, "coder"] = args.coder
        save(df, path_csv, core)
        print("  saved.\n")
    save(df, path_csv, core)
    left = sum(any(str(df.at[ix, e]).strip() == "" for e in core) for ix in todo)
    print(f"Done. Records still incomplete: {left}")


if __name__ == "__main__":
    main()
