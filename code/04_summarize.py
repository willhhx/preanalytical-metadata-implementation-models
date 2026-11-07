#!/usr/bin/env python3
"""
04_summarize.py -- merge API completeness tables into a scorecard-aligned matrix.

Reads  : out/*_completeness.csv, element_map.csv, scorecard_solid_tissue.csv,
         optional manual/manual_coding_*.csv (filled-in sheets from 05_make_manual_sheet.py)
Writes : out/element_by_catalogue.csv   (one row per element x catalogue x stratum)
         out/heatmap_matrix.csv         (elements x catalogue, best % populated; for Fig 1)
         out/pci_preliminary.csv        (preliminary Preanalytical Completeness Index)

Suggested level (API-derived):  0 = element not in schema
                                1 = in schema, 0% populated
                                2 = in schema and populated (structured)
Level 3 (standards-coded) cannot be inferred automatically; set it by hand after reading
the value vocabularies in out/*_value_counts.csv.
"""
import glob
import re

import pandas as pd

from audit_common import OUT, ROOT


def suggest_level(schema_defined, pct):
    if not schema_defined:
        return 0
    if pct is None or pct == 0:
        return 1
    return 2


def main():
    smap = pd.read_csv(ROOT / "element_map.csv")
    card = pd.read_csv(ROOT / "scorecard_solid_tissue.csv")
    frames = [pd.read_csv(p) for p in sorted(glob.glob(str(OUT / "*_completeness.csv")))]
    if not frames:
        raise SystemExit("No out/*_completeness.csv found. Run the pull scripts first.")
    comp = pd.concat(frames, ignore_index=True)
    # exclude per-tissue GTEx rows and per-project GDC rows from the headline matrix
    head = comp[~comp["stratum"].str.startswith("tissue:") & ~comp["stratum"].str.contains(r"^(?:TCGA|CPTAC)-", regex=True)]

    rows = []
    for _, m in smap.iterrows():
        sub = head[head["source"] == m["source"]]
        rx = re.compile(m["field_regex"], re.I)
        for stratum, g in sub.groupby("stratum"):
            hit = g[g["field"].map(lambda f: bool(rx.search(str(f))))]
            if hit.empty:
                rows.append({"element_id": m["element_id"], "source": m["source"], "stratum": stratum,
                             "matched_fields": "", "schema_defined": False, "best_pct_populated": None,
                             "suggested_level": 0})
                continue
            best = hit.sort_values("pct_populated", ascending=False, na_position="last").iloc[0]
            sd = bool(hit["schema_defined"].any())
            pct = best["pct_populated"]
            rows.append({"element_id": m["element_id"], "source": m["source"], "stratum": stratum,
                         "matched_fields": ";".join(hit["field"]), "schema_defined": sd,
                         "best_pct_populated": pct, "suggested_level": suggest_level(sd, pct)})
    ebc = pd.DataFrame(rows).merge(card[["element_id", "domain", "element", "weight_core"]], on="element_id", how="left")
    ebc.to_csv(OUT / "element_by_catalogue.csv", index=False)

    # Manual coding (record-level levels 0-3 from web-only catalogues)
    manual_files = sorted(glob.glob(str(ROOT / "manual" / "manual_coding_*.csv")))
    if manual_files:
        man = pd.concat([pd.read_csv(p) for p in manual_files], ignore_index=True)
        man["level"] = pd.to_numeric(man["level"], errors="coerce")  # blank / NA stay NaN
        agg = (man.dropna(subset=["level"]).groupby(["catalogue", "element_id"])
               .agg(mean_level=("level", "mean"), pct_ge2=("level", lambda x: 100 * (x >= 2).mean()),
                    n_records=("level", "size")).reset_index())
        agg.to_csv(OUT / "manual_summary.csv", index=False)
        print("Manual coding summary -> out/manual_summary.csv")

    # Heatmap matrix: elements x (source:stratum), best % populated
    ebc["col"] = ebc["source"] + ":" + ebc["stratum"]
    mat = ebc.pivot_table(index=["element_id", "element"], columns="col",
                          values="best_pct_populated", aggfunc="max")
    mat.to_csv(OUT / "heatmap_matrix.csv")

    # Preliminary PCI. Two versions so the denominator problem is visible:
    #   PCI_mapped_only      = share of *mapped* core elements with suggested level >= 2
    #   PCI_full_provisional = share of ALL core scorecard elements with level >= 2
    #                          (unmapped elements count as 0 until you verify them by hand)
    core_ids = card.loc[card["weight_core"] == 1, "element_id"].tolist()
    out_rows = []
    for (src, stratum), g in ebc.groupby(["source", "stratum"]):
        best = g.groupby("element_id")["suggested_level"].max()
        mapped = [e for e in core_ids if e in best.index]
        ge2 = sum(1 for e in core_ids if best.get(e, 0) >= 2)
        out_rows.append({"source": src, "stratum": stratum,
                         "n_core_total": len(core_ids), "n_core_mapped": len(mapped),
                         "n_core_ge2": ge2,
                         "PCI_mapped_only": round(ge2 / len(mapped), 3) if mapped else None,
                         "PCI_full_provisional": round(ge2 / len(core_ids), 3)})
    pci = pd.DataFrame(out_rows)
    pci.to_csv(OUT / "pci_preliminary.csv", index=False)
    print(pci.to_string(index=False))
    print("\nNote: PCI_full_provisional treats unmapped core elements as 0. Verify them by hand "
          "(schema + manual coding) before reporting any PCI.")

    mp = OUT / "manual_pci.csv"
    if mp.exists():
        print("\nManual-tier catalogues (record-level PCI, mean over records with bootstrap 95% CI):")
        print(pd.read_csv(mp).to_string(index=False))


if __name__ == "__main__":
    main()
