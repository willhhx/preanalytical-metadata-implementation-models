#!/usr/bin/env python3
"""
07_make_coding_sheets.py -- build coding sheets for manual catalogues (wide format: one row per record).

    python 07_make_coding_sheets.py --catalogue CHTN --n 30 --xlsx

Creates (never overwrites existing sheets unless --force):
  manual/coding_<CAT>_coder1.csv   (+ .xlsx with dropdown validation when --xlsx and openpyxl is installed)
  manual/coding_<CAT>_coder2.csv   BLINDED random subset (default 20%, at least 6 records) for the second coder:
                                   same records, empty level cells, no coder-1 values.
Row order follows manual/sample_<CAT>.csv from 06_draw_sample.py (reserve rows marked is_reserve=TRUE).

Level key: 0 not present | 1 free text only | 2 structured field | 3 structured + standards-coded | NA not applicable
Full decision rules: CODING_GUIDE.md
"""
import argparse
import math

import pandas as pd

from manual_common import ROOT, CATALOGUES, LEVELS, MANUAL, core_elements, seeded_rng

FIXED = ["record_slot", "record_ref", "record_id", "record_url", "is_reserve"]
TAIL = ["evidence_url", "accessed_date", "coder", "notes"]


def write_xlsx(df, path, element_ids, card):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.datavalidation import DataValidation
    except ImportError:
        print("  (openpyxl not installed: skipping .xlsx; the CSV works fine in Excel/Numbers)")
        return False
    wb = Workbook()
    ws = wb.active
    ws.title = "coding"
    ws.append(list(df.columns))
    for row in df.itertuples(index=False):
        ws.append(["" if (isinstance(v, float) and math.isnan(v)) else v for v in row])
    head_fill = PatternFill("solid", fgColor="DDEBF7")
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = head_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "B2"
    dv = DataValidation(type="list", formula1='"0,1,2,3,NA"', allow_blank=True,
                        showErrorMessage=True, errorTitle="Invalid level",
                        error="Allowed values: 0, 1, 2, 3, NA (or leave blank until coded)")
    ws.add_data_validation(dv)
    for j, col in enumerate(df.columns, start=1):
        letter = get_column_letter(j)
        if col in element_ids:
            ws.column_dimensions[letter].width = 7
            dv.add(f"{letter}2:{letter}{len(df) + 1}")
        elif col in ("snap_description",):
            ws.column_dimensions[letter].width = 70
        elif col in ("record_ref", "record_url", "evidence_url", "notes") or col.startswith("snap_"):
            ws.column_dimensions[letter].width = 34
        else:
            ws.column_dimensions[letter].width = 14
    key = wb.create_sheet("key")
    key.append(["level", "meaning"])
    for lv, m in [("0", "Not present (no field / label on the page, or value 'unknown' / blank)"),
                  ("1", "Free text only (mentioned in a description, not a discrete field)"),
                  ("2", "Structured field that is populated for this record"),
                  ("3", "Structured AND standards-coded (SPREC, NCIt, SNOMED, UBERON, MIABIS code list)"),
                  ("NA", "Structurally not applicable (e.g. PMI for surgical tissue). Explain in notes")]:
        key.append([lv, m])
    key.append([])
    key.append(["element_id", "element"])
    for _, r in card.iterrows():
        key.append([r["element_id"], r["element"]])
    key.column_dimensions["B"].width = 80
    wb.save(path)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", required=True, choices=sorted(CATALOGUES))
    ap.add_argument("--n", type=int, default=30, help="records to code (used only if no sample file exists)")
    ap.add_argument("--second-fraction", type=float, default=0.20)
    ap.add_argument("--min-second", type=int, default=6)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--include-controls", action="store_true", help="also code control-domain elements")
    ap.add_argument("--xlsx", action="store_true", help="also write .xlsx with dropdown validation")
    ap.add_argument("--rebuild-coder2", action="store_true",
                    help="after coder 1 has marked INELIGIBLE rows: redraw the blinded coder-2 subset from the "
                         "eligible coded records only (touches ONLY the coder-2 sheet)")
    ap.add_argument("--force", action="store_true", help="overwrite existing sheets (DESTROYS coded work)")
    args = ap.parse_args()

    cat = args.catalogue
    element_ids, card = core_elements(args.include_controls)
    if args.rebuild_coder2:
        from manual_common import find_sheet, read_sheet
        s1 = read_sheet(find_sheet(cat, "coder1"))
        notes_up = s1["notes"].astype(str).str.upper()
        used = s1[[e for e in element_ids if e in s1.columns]].apply(lambda r: (r.astype(str).str.strip() != "").any(), axis=1)
        eligible = s1[used & ~notes_up.str.startswith(("INELIGIBLE", "UNUSED RESERVE"))]
        slots = sorted(eligible["record_slot"].astype(int).tolist())
        k = min(len(slots), max(args.min_second, math.ceil(args.second_fraction * len(slots))))
        chosen = sorted(seeded_rng(args.seed + 1).sample(slots, k))
        p2 = MANUAL / f"coding_{cat}_coder2.csv"
        if p2.exists():
            old = pd.read_csv(p2, dtype=str, keep_default_na=False)
            if old[[e for e in element_ids if e in old.columns]].apply(lambda r: (r.str.strip() != "").any(), axis=1).any():
                raise SystemExit("coder-2 sheet already has levels; not rebuilding (would destroy coded work).")
        keep = [c for c in s1.columns if c in FIXED or c.startswith("snap_")]
        sheet2 = s1.loc[s1["record_slot"].astype(int).isin(chosen), keep].copy()
        for e in element_ids:
            sheet2[e] = ""
        for t_ in TAIL:
            sheet2[t_] = ""
        sheet2["coder"] = "coder2"
        sheet2.to_csv(p2, index=False)
        write_xlsx(sheet2, p2.with_suffix(".xlsx"), set(element_ids), card)
        print(f"Rebuilt coder-2 sheet: {k} of {len(slots)} eligible records, slots {chosen}")
        return

    p1 = MANUAL / f"coding_{cat}_coder1.csv"
    p2 = MANUAL / f"coding_{cat}_coder2.csv"
    existing = [p for p in (p1, p2, p1.with_suffix(".xlsx")) if p.exists()]
    if existing and not args.force:
        raise SystemExit("Refusing to overwrite existing sheet(s): " + ", ".join(str(p.name) for p in existing)
                         + "\nUse --force only if no coding has been done.")

    sample_path = MANUAL / f"sample_{cat}.csv"
    if cat == "BBMRI" and not sample_path.exists():
        raise SystemExit("Run 06_draw_sample.py --catalogue BBMRI --frame ... first (no blank sheets for BBMRI).")
    if sample_path.exists():
        sample = pd.read_csv(sample_path, dtype=str, keep_default_na=False)
    else:
        print(f"WARNING: {sample_path.name} not found. Run 06_draw_sample.py first so records are chosen "
              f"by a documented random rule. Creating {args.n} blank slots.")
        sample = pd.DataFrame({"record_slot": [str(i) for i in range(1, args.n + 1)],
                               "record_ref": "", "record_id": "", "is_reserve": ""})
    base = pd.DataFrame({
        "record_slot": sample["record_slot"].astype(int),
        "record_ref": sample.get("record_ref", ""),
        "record_id": sample.get("record_id", ""),
        "record_url": "",
        "is_reserve": sample.get("is_reserve", ""),
    })
    snap_cols = []
    if cat == "BBMRI":
        snap_path = ROOT / "out" / "bbmri_collections_snapshot.csv"
        if not snap_path.exists():
            raise SystemExit("out/bbmri_collections_snapshot.csv missing: run 03_bbmri_pull.py (full pull) first.")
        snap = pd.read_csv(snap_path, dtype=str, keep_default_na=False)
        keep = ["id", "name", "description", "materials", "storage_temperatures", "sop", "quality",
                "data_categories", "type", "access_description", "keywords", "retrieved_utc"]
        keep = [c for c in keep if c in snap.columns]
        snap = snap[keep].rename(columns={c: f"snap_{c}" for c in keep if c != "id"})
        base = base.merge(snap, how="left", left_on="record_id", right_on="id").drop(columns=["id"])
        snap_cols = [c for c in base.columns if c.startswith("snap_")]
        if base["snap_name"].isna().any():
            raise SystemExit("Some sampled IDs are not in the snapshot: re-run 03 and 06 together.")
    sheet1 = base.copy()
    for e in element_ids:
        sheet1[e] = ""
    for t in TAIL:
        sheet1[t] = ""
    sheet1["coder"] = "coder1"
    sheet1.to_csv(p1, index=False)
    print(f"Wrote {p1.name}  ({len(sheet1)} rows incl. reserves, {len(element_ids)} element columns)")
    if args.xlsx:
        if write_xlsx(sheet1, p1.with_suffix(".xlsx"), set(element_ids), card):
            print(f"Wrote {p1.with_suffix('.xlsx').name}  (dropdowns: {', '.join(LEVELS)})")

    # Blinded second-coder subset (non-reserve records only)
    main_slots = sorted(base.loc[base["is_reserve"] != "TRUE", "record_slot"].tolist())
    k = min(len(main_slots), max(args.min_second, math.ceil(args.second_fraction * len(main_slots))))
    chosen = sorted(seeded_rng(args.seed + 1).sample(main_slots, k))
    sheet2 = base[base["record_slot"].isin(chosen)].copy()
    for e in element_ids:
        sheet2[e] = ""
    for t in TAIL:
        sheet2[t] = ""
    sheet2["coder"] = "coder2"
    sheet2.to_csv(p2, index=False)
    print(f"Wrote {p2.name}  ({k} blinded records: slots {chosen})")
    if args.xlsx:
        write_xlsx(sheet2, p2.with_suffix(".xlsx"), set(element_ids), card)
    print("\nNext: coder 1 fills coding_<CAT>_coder1; the second coder codes coder2 WITHOUT seeing coder 1's "
          "values. If you work alone, wait 48 h, then code coder2 from the evidence pages only "
          "(intra-rater reliability; say so in Methods).")


if __name__ == "__main__":
    main()
