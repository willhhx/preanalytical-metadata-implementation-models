#!/usr/bin/env python3
"""
02_gtex_pull.py -- GTEx preanalytical field completeness (positive-control catalogue).

API       : GTEx Portal API v2  https://gtexportal.org/api/v2
Endpoints : GET /biobank/sample   (paginated sample-level annotations; dataset gtex_v8)
            [fallback] public sample-annotation flat file (SampleAttributesDS.txt),
            supply with --annotation-file after downloading it in a browser.
Purpose   : Count how many GTEx samples populate ischemic time, fixative time,
            autolysis score, RIN etc.; flag impossible values (negative ischemic time).
            Metadata only; no genotype/expression data and no individual-level
            controlled-access data are touched.

Usage:
    python 02_gtex_pull.py --ack-terms --max-pages 3        # pilot
    python 02_gtex_pull.py --ack-terms                      # full
    python 02_gtex_pull.py --annotation-file GTEx_Analysis_v8_Annotations_SampleAttributesDS.txt
Outputs: out/gtex_completeness.csv, out/gtex_numeric_checks.csv, out/gtex_run_manifest.json
"""
import argparse

import pandas as pd

from audit_common import (AuditClient, COMPLETENESS_COLUMNS, OUT, completeness_row,
                          is_missing, require_terms_ack, utcnow, write_manifest)

import os
BASE = os.environ.get("GTEX_BASE", "https://gtexportal.org/api/v2")
TERMS = "https://gtexportal.org/home/aboutGTEx  (GTEx Portal data usage / citation policy)"

# Preanalytical-relevant columns. v2 API camelCase names and legacy flat-file codes are both listed;
# whichever exist in the retrieved data are scored.
PREANALYTIC_FIELDS = {
    "ischemic_time":      ["ischemicTime", "SMTSISCH"],
    "material_type":      ["materialType"],
    "original_material":  ["originalMaterialType"],
    "pathology_notes":    ["pathologyNotes"],
    "hardy_scale":        ["hardyScale"],
    "sample_mass":        ["mass", "amount"],
    "concentration":      ["concentration"],
    "fixative_time":      ["paxgeneTime", "SMTSPAX"],
    "autolysis_score":    ["autolysisScore", "SMATSSCR"],
    "rin":                ["rin", "SMRIN"],
    "tissue_site":        ["tissueSite", "SMTS"],
    "tissue_site_detail": ["tissueSiteDetail", "SMTSD"],
    "uberon_id":          ["uberonId", "SMUBRID"],
    "procurement_period": ["SMTSTPTREF"],
    "fixative_type":      ["fixative", "SMFIXTYPE"],
    "preservation_type":  ["preservationType", "SMPRSVTYPE"],
    "nucleic_acid_batch": ["SMNABTCH", "SMNABTCHT"],
}


def records_of(r):
    """Response shapes seen: {'sample': [...], 'numPages':..} (biobank/sample) or {'data': [...], 'paging_info':{..}}."""
    for key in ("sample", "data", "items"):
        if isinstance(r.get(key), list):
            return r[key]
    return []


def fetch_api(cl, endpoint, dataset, items, max_pages):
    rows, page, pages, total = [], 0, None, None
    params_extra = {"datasetId": dataset} if dataset else {}
    while True:
        r = cl.get_json(f"{BASE}/{endpoint}", params={**params_extra, "page": page, "itemsPerPage": items})
        recs = records_of(r)
        rows.extend(recs)
        pi = r.get("paging_info") or r.get("pagingInfo") or {}
        pages = r.get("numPages", pi.get("numberOfPages", pages))
        total = r.get("recordsTotal", pi.get("totalNumberOfItems", total))
        page += 1  # the API pages are 0-based
        print(f"  page {page}/{pages}  ({len(rows)}/{total} records)")
        if not recs or (pages is not None and page >= pages) or (max_pages and page >= max_pages):
            break
    return pd.DataFrame(rows), {"total_reported": total, "pages_reported": pages}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ack-terms", action="store_true")
    ap.add_argument("--endpoint", default="biobank/sample", choices=["biobank/sample", "dataset/sample"],
                    help="biobank/sample = physical-sample catalogue; dataset/sample = analysis-sample annotations")
    ap.add_argument("--dataset", default="",
                    help="optional datasetId (e.g. gtex_v8). biobank/sample ignored it in testing and returned gtex_v10")
    ap.add_argument("--items-per-page", type=int, default=250)
    ap.add_argument("--max-pages", type=int, default=0, help="0 = all pages")
    ap.add_argument("--annotation-file", help="Use a locally downloaded flat file instead of the API")
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    stratum = (args.dataset or "gtex_api") if not args.annotation_file else "gtex_flatfile"
    manifest = {"started_utc": utcnow(), "base_url": BASE, "endpoint": args.endpoint, "dataset": args.dataset,
                "terms_acknowledged": bool(args.ack_terms)}

    if args.annotation_file:
        df = pd.read_csv(args.annotation_file, sep="\t", low_memory=False)
        manifest.update(mode="flat_file", annotation_file=args.annotation_file)
    else:
        require_terms_ack(args, "gtex", TERMS)
        cl = AuditClient("gtex", delay=args.delay)
        df, info = fetch_api(cl, args.endpoint, args.dataset, args.items_per_page, args.max_pages)
        manifest.update(mode="api_v2", **info)
        if df.empty:
            raise SystemExit("No records returned; check out/api_call_log.jsonl or use --annotation-file.")

    manifest["columns_returned"] = list(df.columns)
    if "analysisRelease" in df.columns:
        manifest["analysisRelease_counts"] = {str(k): int(v) for k, v in df["analysisRelease"].value_counts().items()}
        print("analysisRelease returned:", manifest["analysisRelease_counts"])
    if "materialType" in df.columns:
        manifest["materialType_counts"] = {str(k): int(v) for k, v in df["materialType"].value_counts().items()}
    n = len(df)
    print(f"{n} sample records, {df.shape[1]} columns")

    rows, numeric = [], []
    for element, candidates in PREANALYTIC_FIELDS.items():
        present = [c for c in candidates if c in df.columns]
        if not present:
            rows.append(completeness_row("gtex", stratum, element, False, n, 0,
                                         f"none of {candidates} present in returned columns"))
            continue
        col = present[0]
        populated = int((~df[col].map(is_missing)).sum())
        rows.append(completeness_row("gtex", stratum, element, True, n, populated, f"column={col}"))
        if element in ("ischemic_time", "fixative_time", "rin"):
            x = pd.to_numeric(df[col], errors="coerce").dropna()
            numeric.append({"element": element, "column": col, "n_numeric": len(x),
                            "n_negative": int((x < 0).sum()), "n_zero": int((x == 0).sum()),
                            "min": x.min() if len(x) else None, "median": x.median() if len(x) else None,
                            "max": x.max() if len(x) else None})
    # per-tissue ischemic-time completeness (useful for a supplementary figure)
    tcol = next((c for c in ("tissueSiteDetail", "SMTSD") if c in df.columns), None)
    icol = next((c for c in PREANALYTIC_FIELDS["ischemic_time"] if c in df.columns), None)
    if tcol and icol:
        for tissue, g in df.groupby(tcol):
            rows.append(completeness_row("gtex", f"tissue:{tissue}", "ischemic_time", True, len(g),
                                         int((~g[icol].map(is_missing)).sum()), f"column={icol}"))

    pd.DataFrame(rows, columns=COMPLETENESS_COLUMNS).to_csv(OUT / "gtex_completeness.csv", index=False)
    pd.DataFrame(numeric).to_csv(OUT / "gtex_numeric_checks.csv", index=False)
    write_manifest("gtex", manifest)
    print("Done. See out/gtex_completeness.csv and out/gtex_numeric_checks.csv")


if __name__ == "__main__":
    main()
