#!/usr/bin/env python3
"""
06_draw_sample.py -- pre-registered random selection of records for manual coding.

Two modes (pick the one your catalogue allows):

  A) You can export or copy a list of record / collection IDs into a CSV (one ID per row):
       python 06_draw_sample.py --catalogue CHTN --frame my_ids.csv --id-col id --n 30

  B) Web-only search results; you only know how many results there are and how many per page:
       python 06_draw_sample.py --catalogue UKTD --total-results 412 --page-size 20 --n 30
     -> each sampled slot gets a result position, page number and row-on-page to open.

The seed (default 2026) and the rule text are saved, so the selection is reproducible and can be
quoted in Methods. Record in `sample_<CAT>_RULE.txt` the date, the search/filter used and the sort
order of the results at the time of sampling (do this BEFORE you look at any record).

Outputs: manual/sample_<CAT>.csv, manual/sample_<CAT>_RULE.txt
"""
import argparse
import datetime as dt

import pandas as pd

from manual_common import CATALOGUES, MANUAL, seeded_rng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", required=True, choices=sorted(CATALOGUES))
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--reserve", type=int, default=5,
                    help="extra pre-drawn records, used in order if a sampled record is ineligible")
    ap.add_argument("--frame", help="CSV listing every eligible record/collection ID")
    ap.add_argument("--id-col", default="id", help="ID column name in --frame")
    ap.add_argument("--total-results", type=int, help="total number of eligible search results")
    ap.add_argument("--page-size", type=int, help="results per page in the web interface")
    ap.add_argument("--filter-note", default="", help="text: search/filter used (e.g. 'tissue; cancer')")
    ap.add_argument("--sort-note", default="", help="text: result sort order shown by the website")
    ap.add_argument("--force", action="store_true", help="overwrite an existing sample file")
    args = ap.parse_args()

    out = MANUAL / f"sample_{args.catalogue}.csv"
    if out.exists() and not args.force:
        raise SystemExit(f"{out} already exists. Re-drawing would change your sample; use --force only if "
                         f"you have not started coding.")
    rng = seeded_rng(args.seed)

    if args.frame:
        frame = pd.read_csv(args.frame, dtype=str, keep_default_na=False)
        if args.id_col not in frame.columns:
            raise SystemExit(f"--id-col {args.id_col!r} not in {list(frame.columns)}")
        ids = [x for x in frame[args.id_col].str.strip().tolist() if x]
        ids = sorted(set(ids))  # deterministic order before sampling
        total_draw = args.n + args.reserve
        if total_draw > len(ids):
            raise SystemExit(f"--n + --reserve = {total_draw} is larger than the frame ({len(ids)} unique IDs)")
        pick = rng.sample(ids, total_draw)
        rows = [{"record_slot": i + 1, "record_ref": rid, "record_id": rid, "position": "", "page": "", "row": "",
                 "is_reserve": "TRUE" if i >= args.n else ""} for i, rid in enumerate(pick)]
        rule = (f"{args.n} (+{args.reserve} reserves) of {len(ids)} unique IDs from frame '{args.frame}' drawn without replacement "
                f"with Python random.Random(seed={args.seed}).sample on the sorted ID list.")
    elif args.total_results and args.page_size:
        total_draw = args.n + args.reserve
        if total_draw > args.total_results:
            raise SystemExit("--n + --reserve is larger than --total-results")
        positions = rng.sample(range(1, args.total_results + 1), total_draw)  # already in random order
        rows = []
        for i, pos in enumerate(positions):
            page = (pos - 1) // args.page_size + 1
            row = (pos - 1) % args.page_size + 1
            rows.append({"record_slot": i + 1, "record_ref": f"result #{pos} (page {page}, row {row})",
                         "record_id": "", "position": pos, "page": page, "row": row,
                         "is_reserve": "TRUE" if i >= args.n else ""})
        rule = (f"{args.n} (+{args.reserve} reserves) result positions drawn without replacement from 1..{args.total_results} with "
                f"Python random.Random(seed={args.seed}).sample; page = ceil(position/{args.page_size}); "
                f"row = position within page.")
    else:
        raise SystemExit("Provide --frame, or both --total-results and --page-size.")

    pd.DataFrame(rows).to_csv(out, index=False)
    note = (f"Catalogue: {args.catalogue} ({CATALOGUES[args.catalogue]})\n"
            f"Drawn on: {dt.date.today().isoformat()}\n"
            f"Rule: {rule}\n"
            f"Filter/search used: {args.filter_note or '[FILL IN]'}\n"
            f"Result sort order: {args.sort_note or '[FILL IN]'}\n"
            f"Inclusion rule: [FILL IN, e.g. human tissue collections only]\n"
            f"If a sampled record is ineligible (e.g. no tissue), write 'INELIGIBLE: reason' in its notes and use the "
            f"next unused reserve slot (is_reserve = TRUE) in slot order; never hand-pick replacements.\n")
    (MANUAL / f"sample_{args.catalogue}_RULE.txt").write_text(note)
    print(f"Wrote {out} ({len(rows)} slots)")
    print(note)


if __name__ == "__main__":
    main()
