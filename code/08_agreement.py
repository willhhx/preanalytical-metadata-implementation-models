#!/usr/bin/env python3
"""
08_agreement.py -- inter-/intra-rater agreement between coder1 and coder2, plus an adjudication sheet.

    python 08_agreement.py --catalogue CHTN
    python 08_agreement.py --all

Reads  manual/coding_<CAT>_coder1.(csv|xlsx) and manual/coding_<CAT>_coder2.(csv|xlsx)
Writes out/agreement_<CAT>.csv       per-element and pooled agreement (% agreement, Cohen's kappa,
                                     linear-weighted kappa on numeric levels, bootstrap 95% CI for pooled)
       manual/adjudication_<CAT>.csv one row per disagreeing cell. Fill `final_level` (0-3 or NA) after
                                     discussion; 09_merge_manual.py uses it.

Reporting guidance: report the POOLED kappa (all element x record cells) in the paper. Per-element
kappas rest on only ~6 records and are unstable; they are provided for diagnosing unclear elements.
Kappa is undefined (nan) when all ratings fall in one category; use % agreement then.
"""
import argparse

import numpy as np
import pandas as pd

from audit_common import OUT
from manual_common import (ACTIVE, CATALOGUES, MANUAL, clean_levels, cohen_kappa, element_cols, find_sheet,
                           percentile_ci, read_sheet, seeded_rng)


def pooled_stats(long, weighted_boot=True, n_boot=2000, seed=2026):
    a, b = long["c1"].tolist(), long["c2"].tolist()
    stats = {"n_pairs": len(long),
             "pct_agreement": 100 * float(np.mean([x == y for x, y in zip(a, b)])) if len(long) else float("nan"),
             "kappa": cohen_kappa(a, b), "kappa_linear_weighted": cohen_kappa(a, b, weighted=True)}
    slots = long["record_slot"].unique()
    groups = {s: g for s, g in long.groupby("record_slot")}
    rng = np.random.default_rng(seed)
    kb, kw = [], []
    for _ in range(n_boot):
        pick = rng.choice(slots, size=len(slots), replace=True)
        g = pd.concat([groups[s] for s in pick])
        kb.append(cohen_kappa(g["c1"], g["c2"]))
        kw.append(cohen_kappa(g["c1"], g["c2"], weighted=True))
    stats["kappa_ci_low"], stats["kappa_ci_high"] = percentile_ci(kb)
    stats["kappa_w_ci_low"], stats["kappa_w_ci_high"] = percentile_ci(kw)
    return stats


def run(cat, n_boot):
    p1, p2 = find_sheet(cat, "coder1"), find_sheet(cat, "coder2")
    s1, s2 = read_sheet(p1), read_sheet(p2)
    cols = [c for c in element_cols(s1) if c in element_cols(s2)]
    s1, s2 = clean_levels(s1, cols), clean_levels(s2, cols)
    s1["record_slot"] = s1["record_slot"].astype(int)
    s2["record_slot"] = s2["record_slot"].astype(int)
    m = s2[["record_slot"] + cols].merge(s1[["record_slot", "record_id", "record_ref"] + cols],
                                         on="record_slot", suffixes=("_2", "_1"))
    if m.empty:
        raise SystemExit(f"[{cat}] no overlapping record_slot values between coder sheets")
    long = pd.concat([pd.DataFrame({"record_slot": m["record_slot"], "record_id": m["record_id"],
                                    "record_ref": m["record_ref"], "element_id": e,
                                    "c1": m[f"{e}_1"], "c2": m[f"{e}_2"]}) for e in cols], ignore_index=True)
    blank = long[(long["c1"] == "") | (long["c2"] == "")]
    if len(blank):
        print(f"[{cat}] WARNING: {len(blank)} cells blank in one/both sheets are excluded "
              f"(code every cell before final reporting).")
    long = long[(long["c1"] != "") & (long["c2"] != "")]
    if long.empty:
        raise SystemExit(f"[{cat}] nothing to compare yet: no record has been coded in BOTH sheets. "
                         f"Finish coder 1 (all rows) and coder 2 (its 6 rows), save, then re-run.")

    rows = []
    for e, g in long.groupby("element_id"):
        rows.append({"catalogue": cat, "level": "element", "element_id": e, "n_pairs": len(g),
                     "pct_agreement": round(100 * float((g["c1"] == g["c2"]).mean()), 1),
                     "kappa": cohen_kappa(g["c1"], g["c2"]),
                     "kappa_linear_weighted": cohen_kappa(g["c1"], g["c2"], weighted=True)})
    pooled = pooled_stats(long, n_boot=n_boot)
    rows.append({"catalogue": cat, "level": "POOLED", "element_id": "ALL", **pooled})
    res = pd.DataFrame(rows).round(3)
    res.to_csv(OUT / f"agreement_{cat}.csv", index=False)

    dis = long[long["c1"] != long["c2"]].copy()
    adj = MANUAL / f"adjudication_{cat}.csv"
    if adj.exists():
        old = pd.read_csv(adj, dtype=str, keep_default_na=False)
        if (old["final_level"] != "").any():
            print(f"[{cat}] {adj.name} already has adjudicated values; NOT overwriting. "
                  f"Delete it manually to regenerate.")
            return res
    out = dis.rename(columns={"c1": "coder1", "c2": "coder2"})
    out["final_level"] = ""
    out["adjudication_note"] = ""
    out.sort_values(["record_slot", "element_id"]).to_csv(adj, index=False)
    print(f"[{cat}] pairs={pooled['n_pairs']}  agreement={pooled['pct_agreement']:.1f}%  "
          f"kappa={pooled['kappa']:.3f} [{pooled['kappa_ci_low']:.3f}, {pooled['kappa_ci_high']:.3f}]  "
          f"weighted kappa={pooled['kappa_linear_weighted']:.3f}")
    print(f"        {len(out)} disagreements -> {adj.name}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", choices=sorted(CATALOGUES))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n-boot", type=int, default=2000)
    args = ap.parse_args()
    cats = list(ACTIVE) if args.all else [args.catalogue]
    if not args.all and not args.catalogue:
        raise SystemExit("Use --catalogue BBMRI or --all")
    for c in cats:
        try:
            run(c, args.n_boot)
        except FileNotFoundError as e:
            print(f"[{c}] skipped: {e}")


if __name__ == "__main__":
    main()
