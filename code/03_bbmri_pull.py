#!/usr/bin/env python3
"""
03_bbmri_pull.py -- BBMRI-ERIC Directory (collection-level) preanalytical completeness.

API       : BBMRI-ERIC Directory (MOLGENIS EMX2), public GraphQL endpoint of the aggregated "ERIC" schema
            https://directory.bbmri-eric.eu/ERIC/graphql
            (the older MOLGENIS REST v2 path /api/v2/eu_bbmri_eric_collections returned HTTP 404 in testing;
             it is kept behind --api rest in case a mirror still serves it)
Calls     : 1. GraphQL introspection of the table type "Collections" -> schema attributes ("schema defined")
            2. query { Collections(limit, offset) { <scalar fields>, <ref fields>{name} } Collections_agg{count} }
Purpose   : Establish which collection attributes exist in the Directory schema and how often
            they are populated, overall and for the tissue/cancer-relevant subset.
            Only public collection descriptions are read (no login, no sample- or person-level data).

Usage:
    python 03_bbmri_pull.py --ack-terms --probe                       # list table types / fields, no data pull
    python 03_bbmri_pull.py --ack-terms --max-records 300    # pilot
    python 03_bbmri_pull.py --ack-terms                      # full
Outputs: out/bbmri_completeness.csv, out/bbmri_attributes.csv, out/bbmri_run_manifest.json
"""
import argparse
import json
import re

import pandas as pd

from audit_common import (AuditClient, COMPLETENESS_COLUMNS, OUT, completeness_row,
                          is_missing, require_terms_ack, utcnow, write_manifest)

import os
BASE = os.environ.get("BBMRI_BASE", "https://directory.bbmri-eric.eu/ERIC/graphql")
REST_BASE = os.environ.get("BBMRI_REST_BASE", "https://directory.bbmri-eric.eu/api/v2")
ENTITY = "eu_bbmri_eric_collections"  # REST mode only
TERMS = "https://www.bbmri-eric.eu/  (BBMRI-ERIC Acceptable Use Policy of IT services; check Directory terms)"

PREANALYTIC_RE = re.compile(
    r"(storage|temperature|material|preserv|fixat|ischem|sop|quality|standard|sample_access|"
    r"type|data_categor|diagnos|size|order_of_magnitude|sex|age)", re.I)
CANCER_RE = re.compile(r"cancer|tumou?r|carcinoma|neoplas|oncolog|leuk[a]?emi|lymphom|melanom|sarcoma|malignan|\\bC[0-9]{2}\\b", re.I)
TISSUE_RE = re.compile(r"TISSUE|FFPE|PATHOLOGY|CANCER|TUMOR|TUMOUR", re.I)


def flatten_value(v):
    """MOLGENIS returns refs as dicts (with href/id/label) and mrefs as {'items': [...]}."""
    if isinstance(v, dict):
        if "name" in v and len(v) <= 2:
            return v["name"]
        if "items" in v:
            return [flatten_value(i) for i in v["items"]]
        return v.get("id") or v.get("label") or v.get("name") or json.dumps(v)[:80]
    if isinstance(v, list):
        return [flatten_value(i) for i in v]
    return v


PERSON_TYPES = {"Persons", "Publishers"}
TYPE_Q = "query($n:String!){__type(name:$n){name fields{name type{kind name ofType{kind name ofType{kind name ofType{kind name}}}}}}}"


def unwrap(t):
    """Return (kind, name, is_list) of a GraphQL type reference, skipping NON_NULL/LIST wrappers."""
    is_list = False
    while t and t.get("kind") in ("NON_NULL", "LIST"):
        if t["kind"] == "LIST":
            is_list = True
        t = t.get("ofType")
    return (t or {}).get("kind"), (t or {}).get("name"), is_list


def introspect(cl, name):
    r = cl.post_json(BASE, {"query": TYPE_Q, "variables": {"n": name}})
    t = (r.get("data") or {}).get("__type")
    return t["fields"] if t else None


def build_fields(cl, table):
    """Scalar fields are selected directly; object fields via their `name` (or `id`) sub-field."""
    fields = introspect(cl, table)
    if not fields:
        return None, None
    attrs, selections, cache = [], [], {}
    for f in fields:
        nm = f["name"]
        if nm.startswith("_") or nm.startswith("mg_") or nm.endswith(("_groupBy", "_agg")):
            continue  # EMX2 helper fields (aggregates / group-bys), not data attributes
        kind, tname, is_list = unwrap(f["type"])
        sel = None
        if tname in PERSON_TYPES:
            sel = None  # contact / head / publisher persons: personal data, never retrieved
        elif kind in ("SCALAR", "ENUM"):
            sel = nm
        elif kind == "OBJECT":
            if tname not in cache:
                cache[tname] = introspect(cl, tname) or []
            subs = {x["name"] for x in cache[tname]}
            sub = "name" if "name" in subs else ("id" if "id" in subs else None)
            sel = f"{nm}{{{sub}}}" if sub else None
        attrs.append({"name": nm, "kind": kind, "type": tname, "is_list": is_list, "selected": bool(sel)})
        if sel:
            selections.append(sel)
    return attrs, selections


def gql_records(cl, table, selections, has_id, page_size, max_records):
    items, offset, total = [], 0, None
    order = ", orderby:{id:ASC}" if has_id else ""
    while True:
        q = (f"{{ {table}(limit:{page_size}, offset:{offset}{order}) {{ {' '.join(selections)} }} "
             f"{table}_agg {{ count }} }}")
        r = cl.post_json(BASE, {"query": q})
        if r.get("errors"):
            raise RuntimeError(f"GraphQL errors: {json.dumps(r['errors'])[:600]}")
        d = r["data"]
        batch = d.get(table) or []
        total = (d.get(f"{table}_agg") or {}).get("count", total)
        items.extend(batch)
        offset += len(batch)
        print(f"  {len(items)}/{total}")
        if not batch or (total is not None and offset >= total) or (max_records and len(items) >= max_records):
            break
    return items, total


def probe(cl, table):
    r = cl.post_json(BASE, {"query": "{__schema{types{name kind}}}"})
    names = sorted(t["name"] for t in r["data"]["__schema"]["types"]
                   if t["kind"] == "OBJECT" and not t["name"].startswith("_"))
    print("Object types:", ", ".join(names))
    fields = introspect(cl, table)
    print(f"\nFields of {table}:" if fields else f"\nType {table!r} not found; pick one from the list above (--table).")
    for f in fields or []:
        print("  ", f["name"], unwrap(f["type"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ack-terms", action="store_true")
    ap.add_argument("--api", choices=["graphql", "rest"], default="graphql")
    ap.add_argument("--table", default="Collections", help="EMX2 table type (see --probe)")
    ap.add_argument("--probe", action="store_true", help="only introspect the schema and print it")
    ap.add_argument("--page-size", type=int, default=200)
    ap.add_argument("--max-records", type=int, default=0, help="0 = all")
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()
    require_terms_ack(args, "bbmri", TERMS)

    cl = AuditClient("bbmri", delay=args.delay)
    if args.probe:
        probe(cl, args.table)
        return
    manifest = {"started_utc": utcnow(), "api": args.api, "base_url": BASE if args.api == "graphql" else REST_BASE,
                "table": args.table if args.api == "graphql" else ENTITY,
                "terms_acknowledged": True, "page_size": args.page_size}

    if args.api == "graphql":
        # 1. Schema: all attributes defined for the collections table
        attrs, selections = build_fields(cl, args.table)
        if not attrs:
            raise SystemExit(f"Type {args.table!r} not found. Run: python 03_bbmri_pull.py --probe")
        pd.DataFrame(attrs).to_csv(OUT / "bbmri_attributes.csv", index=False)
        schema_names = {a["name"] for a in attrs}
        manifest.update(n_schema_attributes=len(attrs),
                        attributes_not_selectable=[a["name"] for a in attrs if not a["selected"]])
        print(f"Schema: {len(attrs)} attributes ({len(selections)} readable)")
        # 2. Records
        items, total = gql_records(cl, args.table, selections, "id" in schema_names,
                                   args.page_size, args.max_records)
        manifest["total_collections"] = total
    else:
        meta = cl.get_json(f"{REST_BASE}/{ENTITY}", params={"num": 0})
        m = meta.get("meta", {})
        attrs = [{"name": a.get("name"), "fieldType": a.get("fieldType"),
                  "nillable": a.get("nillable"), "label": a.get("label")} for a in m.get("attributes", [])]
        pd.DataFrame(attrs).to_csv(OUT / "bbmri_attributes.csv", index=False)
        manifest.update(total_collections=meta.get("total"), n_schema_attributes=len(attrs))
        schema_names = {a["name"] for a in attrs}
        print(f"Schema: {len(attrs)} attributes; {meta.get('total')} collections reported")
        items, start = [], 0
        while True:
            r = cl.get_json(f"{REST_BASE}/{ENTITY}", params={"num": args.page_size, "start": start})
            batch = r.get("items", [])
            items.extend(batch)
            start += len(batch)
            total = r.get("total", meta.get("total"))
            print(f"  {len(items)}/{total}")
            if not batch or (total is not None and start >= total) or (args.max_records and len(items) >= args.max_records):
                break
    if args.max_records:
        items = items[:args.max_records]
    not_retrieved = {a["name"] for a in attrs if a.get("selected") is False} if args.api == "graphql" else set()

    recs = [{k: flatten_value(v) for k, v in it.items() if k != "_href"} for it in items]
    df = pd.DataFrame(recs)
    manifest["records_retrieved"] = len(df)

    # 3. Strata: all collections; tissue-relevant subset (by 'materials' attribute or name)
    def is_tissue(row):
        mats = row.get("materials")
        mats = mats if isinstance(mats, list) else [mats]
        text = " ".join(str(x) for x in mats if x) + " " + str(row.get("name", ""))
        return bool(TISSUE_RE.search(text))

    tissue_mask = df.apply(is_tissue, axis=1) if len(df) else pd.Series([], dtype=bool)
    strata = {"all_collections": df, "tissue_relevant": df[tissue_mask]}
    manifest["n_tissue_relevant"] = int(tissue_mask.sum())

    # Frames for the manual free-text coding tier (06_draw_sample.py --catalogue BBMRI --frame ...)
    def joined(v):
        if isinstance(v, list):
            return ";".join(str(x) for x in v if not is_missing(x))
        return "" if is_missing(v) else str(v)

    def is_cancer(row):
        text = " ".join(joined(row.get(c)) for c in ("name", "description", "diagnosis_available", "keywords"))
        return bool(CANCER_RE.search(text))

    if len(df):
        cancer_mask = df.apply(is_cancer, axis=1)
        snap = df.copy()
        for c in snap.columns:
            snap[c] = snap[c].map(joined)
        snap.insert(0, "retrieved_utc", manifest["started_utc"])
        snap["is_tissue_relevant"] = tissue_mask.values
        snap["is_cancer_related"] = cancer_mask.values
        snap.to_csv(OUT / "bbmri_collections_snapshot.csv", index=False)
        for nm, mask in (("tissue_cancer", tissue_mask & cancer_mask), ("tissue", tissue_mask)):
            df.loc[mask, ["id"]].drop_duplicates().to_csv(OUT / f"bbmri_frame_{nm}.csv", index=False)
            manifest[f"n_frame_{nm}"] = int(mask.sum())
        print(f"Frames: tissue+cancer={manifest['n_frame_tissue_cancer']}, tissue={manifest['n_frame_tissue']} "
              f"-> out/bbmri_frame_*.csv ; snapshot -> out/bbmri_collections_snapshot.csv")

    rows = []
    for sname, sub in strata.items():
        for col in df.columns:
            if col.startswith("_"):
                continue
            pop = int((~sub[col].map(is_missing)).sum())
            note = "" if PREANALYTIC_RE.search(col) else "not preanalytical-like"
            rows.append(completeness_row("bbmri", sname, col, col in schema_names, len(sub), pop, note))
        # schema attributes that never appeared in records at all
        for a in sorted(schema_names - set(df.columns)):
            why = ("not retrieved by design (person-linked field)" if a in not_retrieved
                   else "defined in schema; absent from all returned records")
            rows.append(completeness_row("bbmri", sname, a, True, len(sub), 0, why))

    pd.DataFrame(rows, columns=COMPLETENESS_COLUMNS).to_csv(OUT / "bbmri_completeness.csv", index=False)

    # Value counts of storage temperature and materials (for Results text)
    vc = []
    for col in [c for c in df.columns if re.search(r"storage|material", c, re.I)]:
        exploded = df[col].explode() if df[col].map(lambda x: isinstance(x, list)).any() else df[col]
        for v, c in exploded.fillna("<missing>").astype(str).value_counts().items():
            vc.append({"field": col, "value": v, "count": int(c)})
    pd.DataFrame(vc).to_csv(OUT / "bbmri_value_counts.csv", index=False)

    write_manifest("bbmri", manifest)
    print("Done. See out/bbmri_completeness.csv")


if __name__ == "__main__":
    main()
