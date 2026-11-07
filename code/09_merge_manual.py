#!/usr/bin/env python3
"""
09_merge_manual.py -- final manual dataset + record-level Preanalytical Completeness Index (PCI).

    python 09_merge_manual.py --all
    python 09_merge_manual.py --catalogue CHTN [--allow-unresolved] [--allow-blank]

Steps per catalogue
  1. read coder1 sheet (the full sample); drop unused reserve rows (reserve rows with no coding at all)
  2. apply manual/adjudication_<CAT>.csv `final_level` to double-coded cells that disagreed
     (fails if disagreements are unresolved, unless --allow-unresolved, which keeps coder 1's value)
  3. write manual/manual_coding_<CAT>.csv  (long format, read by 04_summarize.py)
  4. PCI per record = (# applicable core elements with level >= 2) / (# applicable core elements);
     NA elements are excluded from the denominator. Catalogue PCI = mean over records, bootstrap 95% CI
     (resampling records). Also per-element % of records with level >= 2 and mean level.

Writes out/manual_pci.csv, out/manual_element_summary.csv, out/manual_record_pci_<CAT>.csv
"""
import argparse

import numpy as np
import pandas as pd

from audit_common import OUT
from manual_common import (ACTIVE, CATALOGUES, MANUAL, clean_levels, core_elements, element_cols, find_sheet,
                           percentile_ci, read_sheet)


def apply_adjudication(cat, s1, cols, allow_unresolved):
    adj_path = MANUAL / f"adjudication_{cat}.csv"
    if not adj_path.exists():
        return s1, 0, 0
    adj = pd.read_csv(adj_path, dtype=str, keep_default_na=False)
    if adj.empty:
        return s1, 0, 0
    adj["record_slot"] = adj["record_slot"].astype(int)
    unresolved = adj[adj["final_level"].str.strip() == ""]
    if len(unresolved) and not allow_unresolved:
        raise SystemExit(f"[{cat}] {len(unresolved)} disagreements have no final_level in {adj_path.name}. "
                         f"Resolve them, or use --allow-unresolved to keep coder 1's value.")
    applied = 0
    s1 = s1.set_index("record_slot")
    for _, r in adj[adj["final_level"].str.strip() != ""].iterrows():
        lv = r["final_level"].strip().upper()
        lv = "NA" if lv in ("NA", "N/A") else str(int(float(lv)))
        if lv not in ("0", "1", "2", "3", "NA"):
            raise SystemExit(f"[{cat}] invalid final_level {r['final_level']!r} (slot {r['record_slot']})")
        s1.loc[r["record_slot"], r["element_id"]] = lv
        applied += 1
    return s1.reset_index(), applied, len(unresolved)


def run(cat, args, core_ids):
    s1 = read_sheet(find_sheet(cat, "coder1"))
    cols = [c for c in core_ids if c in element_cols(s1)]
    s1 = clean_levels(s1, cols)
    s1["record_slot"] = s1["record_slot"].astype(int)

    used = s1[cols].apply(lambda r: (r != "").any(), axis=1)
    is_res = s1.get("is_reserve", pd.Series([""] * len(s1))).astype(str).str.upper() == "TRUE"
    notes_up = s1.get("notes", pd.Series([""] * len(s1))).astype(str).str.upper()
    skipped = notes_up.str.startswith(("INELIGIBLE", "UNUSED RESERVE"))
    if (skipped & used).any():
        raise SystemExit(f"[{cat}] rows marked INELIGIBLE/UNUSED RESERVE also contain levels: "
                         f"slots {s1.loc[skipped & used, 'record_slot'].tolist()}. Clear one or the other.")
    print(f"[{cat}] excluded {int((skipped & ~used).sum())} ineligible/unused-reserve rows "
          f"and {int((is_res & ~used & ~skipped).sum())} untouched reserves")
    s1 = s1[~((is_res | skipped) & ~used)].copy()
    s1, n_applied, n_unres = apply_adjudication(cat, s1, cols, args.allow_unresolved)

    blanks = [(r.record_slot, c) for r in s1.itertuples() for c in cols if getattr(r, c) == ""]
    if blanks and not args.allow_blank:
        shown = ", ".join(f"slot {s}:{c}" for s, c in blanks[:12])
        raise SystemExit(f"[{cat}] {len(blanks)} uncoded cells (e.g. {shown}). Code them, or use "
                         f"--allow-blank to exclude blank cells.")

    long = s1.melt(id_vars=[c for c in ["record_slot", "record_id", "record_ref", "evidence_url",
                                        "accessed_date", "coder", "notes"] if c in s1.columns],
                   value_vars=cols, var_name="element_id", value_name="level")
    long.insert(0, "catalogue", cat)
    long.to_csv(MANUAL / f"manual_coding_{cat}.csv", index=False)

    rec_rows = []
    for r in s1.itertuples():
        vals = [getattr(r, c) for c in cols if getattr(r, c) not in ("", "NA")]
        rec_rows.append({"catalogue": cat, "record_slot": r.record_slot,
                         "n_applicable": len(vals),
                         "n_ge2": sum(int(v) >= 2 for v in vals),
                         "PCI": (sum(int(v) >= 2 for v in vals) / len(vals)) if vals else np.nan})
    rec = pd.DataFrame(rec_rows)
    rec.to_csv(OUT / f"manual_record_pci_{cat}.csv", index=False)
    v = rec["PCI"].dropna().to_numpy()
    rng = np.random.default_rng(2026)
    boots = [rng.choice(v, size=len(v), replace=True).mean() for _ in range(5000)] if len(v) else []
    lo, hi = percentile_ci(boots)
    summary = {"catalogue": cat, "n_records": int(len(v)), "PCI_mean": round(float(v.mean()), 3) if len(v) else None,
               "PCI_ci_low": round(lo, 3), "PCI_ci_high": round(hi, 3),
               "n_cells_excluded_blank": len(blanks), "n_adjudicated": n_applied,
               "n_unresolved_kept_coder1": n_unres}

    el_rows = []
    for c in cols:
        x = long[(long["element_id"] == c) & (~long["level"].isin(["", "NA"]))]["level"].astype(int)
        n_na = int((long[long["element_id"] == c]["level"] == "NA").sum())
        el_rows.append({"catalogue": cat, "element_id": c, "n_coded": len(x), "n_NA": n_na,
                        "pct_ge2": round(100 * float((x >= 2).mean()), 1) if len(x) else None,
                        "mean_level": round(float(x.mean()), 2) if len(x) else None,
                        "pct_level0": round(100 * float((x == 0).mean()), 1) if len(x) else None})
    print(f"[{cat}] records={summary['n_records']}  PCI={summary['PCI_mean']} "
          f"[{summary['PCI_ci_low']}, {summary['PCI_ci_high']}]  adjudicated cells={n_applied}")
    return summary, el_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", choices=sorted(CATALOGUES))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--allow-unresolved", action="store_true")
    ap.add_argument("--allow-blank", action="store_true")
    args = ap.parse_args()
    if not args.all and not args.catalogue:
        raise SystemExit("Use --catalogue BBMRI or --all")
    core_ids, _ = core_elements(False)
    sums, els = [], []
    for c in (list(ACTIVE) if args.all else [args.catalogue]):
        try:
            s, e = run(c, args, core_ids)
            sums.append(s)
            els.extend(e)
        except FileNotFoundError as ex:
            print(f"[{c}] skipped: {ex}")
    if sums:
        pd.DataFrame(sums).to_csv(OUT / "manual_pci.csv", index=False)
        pd.DataFrame(els).to_csv(OUT / "manual_element_summary.csv", index=False)
        print("Wrote out/manual_pci.csv and out/manual_element_summary.csv. Now run: python 04_summarize.py")


if __name__ == "__main__":
    main()
