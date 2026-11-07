#!/usr/bin/env python3
"""
01_gdc_pull.py -- GDC (TCGA + CPTAC) preanalytical field completeness.

API       : NCI Genomic Data Commons REST API  https://api.gdc.cancer.gov
Endpoints : GET /status                          (API + data release version)
            GET /cases/_mapping                  (fields exposed; sample fields appear as "samples.*")
            GET /v0/submission/_dictionary/sample (data dictionary entry; best effort)
            GET /cases?facets=project.project_id (project list)
            GET /cases?filters=...&fields=samples.*  (record-level retrieval, paginated;
                                                      the GDC has no /samples endpoint, so each
                                                      case's nested samples are the records)
Purpose   : For each project, count how many sample records populate each
            preanalytical field (ischemia/freezing times, preservation, FFPE/OCT, etc.).
            Only metadata is retrieved -- no files, no patient-level downloads.

Usage (pilot first!):
    python 01_gdc_pull.py --ack-terms --programs TCGA CPTAC --max-per-project 200
    python 01_gdc_pull.py --ack-terms --programs TCGA CPTAC            # full run
Outputs:
    out/gdc_completeness.csv, out/gdc_value_counts.csv, out/gdc_run_manifest.json,
    out/api_call_log.jsonl, raw/gdc/<sha256>.json
"""
import argparse
import json
from collections import Counter, defaultdict

import pandas as pd

from audit_common import (AuditClient, COMPLETENESS_COLUMNS, OUT, completeness_row,
                          is_missing, require_terms_ack, utcnow, write_manifest)

import os
BASE = os.environ.get("GDC_BASE", "https://api.gdc.cancer.gov")
TERMS = "https://gdc.cancer.gov/about-data/data-analysis-policies  (GDC Data Access / API terms)"

# Candidate preanalytical-relevant sample fields (requested as `samples.<name>` on /cases).
# Only those that appear in /cases/_mapping are requested; the rest are
# reported as schema_defined = False (itself a finding).
CANDIDATE_FIELDS = [
    # identity
    "sample_type", "tissue_type", "composition", "tumor_descriptor", "biospecimen_anatomic_site",
    # collection / ischemia
    "time_between_clamping_and_freezing", "time_between_excision_and_freezing",
    "days_to_collection", "days_to_sample_procurement", "initial_weight", "current_weight",
    # preservation / fixation / storage
    "preservation_method", "freezing_method", "is_ffpe", "oct_embedded",
    "shortest_dimension", "intermediate_dimension", "longest_dimension",
    # quality / provenance
    "portions.is_ffpe", "portions.weight", "portions.analytes.analyte_type",
    "portions.analytes.analyte_quantity", "portions.analytes.concentration",
    "portions.analytes.a260_a280_ratio", "portions.analytes.well_number",
    "portions.slides.percent_tumor_cells", "portions.slides.percent_necrosis",
    "portions.slides.percent_normal_cells", "portions.slides.section_location",
]
CATEGORICAL = ["sample_type", "tissue_type", "composition", "preservation_method",
               "freezing_method", "is_ffpe", "oct_embedded", "tumor_descriptor"]
PROJECT_FIELD = "project.project_id"
PROGRAM_FIELD = "project.program.name"
SP = "samples."


def flatten_hit(hit, fields):
    """Return {field: value} for dotted fields; lists are collapsed to the non-missing items."""
    out = {}
    for f in fields:
        parts = f.split(".")
        vals = [hit]
        for p in parts:
            nxt = []
            for v in vals:
                if isinstance(v, dict) and p in v:
                    nxt.append(v[p])
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict) and p in item:
                            nxt.append(item[p])
            # flatten one list level
            vals = [x for item in nxt for x in (item if isinstance(item, list) else [item])]
        vals = [x for x in vals if not is_missing(x)]
        out[f] = vals[0] if vals else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ack-terms", action="store_true")
    ap.add_argument("--programs", nargs="+", default=["TCGA", "CPTAC"])
    ap.add_argument("--max-per-project", type=int, default=0, help="0 = all records")
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()
    require_terms_ack(args, "gdc", TERMS)

    cl = AuditClient("gdc", delay=args.delay)
    manifest = {"started_utc": utcnow(), "base_url": BASE, "programs": args.programs,
                "max_per_project": args.max_per_project, "page_size": args.page_size,
                "terms_acknowledged": True}

    # 1. API / data release version
    status = cl.get_json(f"{BASE}/status")
    manifest["gdc_status"] = status
    print("GDC status:", json.dumps(status)[:300])

    # 2. Which fields does the samples endpoint expose?
    mapping = cl.get_json(f"{BASE}/cases/_mapping")
    exposed = {f[len(SP):] for f in mapping.get("fields", []) if f.startswith(SP)}
    manifest["n_exposed_sample_fields"] = len(exposed)
    schema_defined = {f: (f in exposed) for f in CANDIDATE_FIELDS}
    # keep every exposed field that *looks* preanalytical, in case names differ from my list
    kw = ("freez", "ischem", "clamp", "excis", "preserv", "fixat", "ffpe", "oct", "storage",
          "temperature", "weight", "time_between", "warm", "cold")
    discovered = sorted(f for f in exposed if any(k in f.lower() for k in kw))
    manifest["discovered_preanalytical_like_fields"] = discovered
    print("Preanalytical-like fields exposed by API:", discovered)

    # 2b. Data dictionary (best effort; endpoint availability may change)
    try:
        dd = cl.get_json(f"{BASE}/v0/submission/_dictionary/sample")
        props = sorted((dd.get("properties") or {}).keys())
        manifest["dictionary_sample_properties"] = props
    except Exception as e:  # noqa: BLE001
        manifest["dictionary_sample_properties"] = f"unavailable: {e}"

    fields_to_request = [f for f in CANDIDATE_FIELDS if schema_defined[f]]
    for f in discovered:
        if f not in fields_to_request and f not in schema_defined:
            fields_to_request.append(f)
            schema_defined[f] = True
    sample_fields = sorted(set(fields_to_request + ["submitter_id"]))
    request_fields = sorted({SP + f for f in sample_fields} | {PROJECT_FIELD, "submitter_id"})

    # 3. Project list per program
    projects = []
    for prog in args.programs:
        flt = {"op": "=", "content": {"field": PROGRAM_FIELD, "value": prog}}
        r = cl.get_json(f"{BASE}/cases", params={
            "filters": json.dumps(flt), "facets": PROJECT_FIELD, "size": 0})
        buckets = r["data"]["aggregations"][PROJECT_FIELD]["buckets"]
        for b in buckets:
            projects.append((prog, b["key"], b["doc_count"]))
    manifest["projects"] = [{"program": p, "project_id": k, "n_cases": n} for p, k, n in projects]
    print(f"{len(projects)} projects, {sum(n for _,_,n in projects)} cases total")

    # 4. Record-level retrieval
    n_rec = Counter()
    n_pop = defaultdict(Counter)
    values = defaultdict(Counter)
    for prog, pid, total in projects:
        flt = {"op": "=", "content": {"field": PROJECT_FIELD, "value": pid}}
        got_cases, got_samples, start = 0, 0, 0
        cap = args.max_per_project  # 0 = all; otherwise cap on SAMPLE records per project
        while got_cases < total and (cap == 0 or got_samples < cap):
            size = min(args.page_size, total - got_cases)
            r = cl.get_json(f"{BASE}/cases", params={
                "filters": json.dumps(flt), "fields": ",".join(request_fields),
                "size": size, "from": start, "sort": "submitter_id"})
            hits = r["data"]["hits"]
            if not hits:
                break
            for h in hits:
                for smp in (h.get("samples") or []):
                    if cap and got_samples >= cap:
                        break
                    flat = flatten_hit(smp, [f for f in sample_fields if f != "submitter_id"])
                    for stratum in (pid, f"{prog}_ALL"):
                        n_rec[stratum] += 1
                        for f, v in flat.items():
                            if v is not None:
                                n_pop[stratum][f] += 1
                            if f in CATEGORICAL:
                                values[(stratum, f)][str(v) if v is not None else "<missing>"] += 1
                    got_samples += 1
            got_cases += len(hits)
            start += len(hits)
        print(f"  {pid}: {got_samples} sample records from {got_cases}/{total} cases")

    # 5. Output
    rows = []
    all_fields = sorted(set(CANDIDATE_FIELDS) | set(discovered))
    for stratum in sorted(n_rec):
        for f in all_fields:
            rows.append(completeness_row(
                "gdc", stratum, f, bool(schema_defined.get(f, False)),
                n_rec[stratum], n_pop[stratum][f] if schema_defined.get(f, False) else 0,
                "" if schema_defined.get(f, False) else "field not exposed under samples.* on /cases"))
    pd.DataFrame(rows, columns=COMPLETENESS_COLUMNS).to_csv(OUT / "gdc_completeness.csv", index=False)

    vrows = [{"stratum": s, "field": f, "value": v, "count": c}
             for (s, f), cnt in values.items() for v, c in cnt.most_common()]
    pd.DataFrame(vrows, columns=["stratum", "field", "value", "count"]).to_csv(
        OUT / "gdc_value_counts.csv", index=False)

    manifest["records_retrieved"] = dict(n_rec)
    write_manifest("gdc", manifest)
    print("Done. See out/gdc_completeness.csv")


if __name__ == "__main__":
    main()
