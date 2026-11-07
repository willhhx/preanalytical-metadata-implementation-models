# Implementation models for structured preanalytical metadata across public biobank ecosystems

Code, API call logs, coding sheets and derived results for the manuscript
*Implementation Models for Structured Preanalytical Metadata Across Public Biobank Ecosystems: A Comparative Cross-Repository Analysis* (Haoxi Hu, Northeastern University).

Ecosystems examined: GDC (TCGA and CPTAC; Data Release 46.0), GTEx Portal API v2 (dataset gtex_v8), BBMRI-ERIC Directory (GraphQL). Only public metadata were retrieved; no controlled-access or individual-level data.

## Layout
| Folder | Contents |
|---|---|
| `code/` | Pull scripts (`01`-`03`), summary (`04`), manual-tier sampling, coding sheets, agreement and merge scripts (`06`-`10`), rule-based first coder, coding guide, API methods description, tests |
| `results/` | Derived tables, run manifests and the per-call API log with SHA-256 response hashes (`api_call_log.jsonl`) |
| `coding/` | BBMRI-ERIC sample draw (seed 2026), both coders' sheets, adjudication and merged coding |

Raw archived API responses (about 83 MB, named by SHA-256) are not stored here. Re-running the pull scripts regenerates them and the hashes in the log can be used to compare.

## Reproducing
```bash
cd code
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python 01_gdc_pull.py --ack-terms --programs TCGA CPTAC
python 02_gtex_pull.py --ack-terms --endpoint dataset/sample --dataset gtex_v8
python 03_bbmri_pull.py --ack-terms
python tests/test_manual.py   # run from a COPY of code/ (it writes to out/ and manual/)
```
Scripts write to `code/out/` and `code/manual/`; the archived versions of those folders from the study run are `results/` and `coding/`. Read each service's terms of use before passing `--ack-terms`. Live API outputs change over time (GDC release, BBMRI snapshot).

## Notes
- The first coding pass (`coder1_rules.py`) is rule-based; the independent second coder was human. See `code/CODING_GUIDE.md`.
- The BBMRI snapshot (`results/bbmri_collections_snapshot.csv`) is public Directory metadata as retrieved on 6 Nov 2026.
- Code is released under the MIT licence (see `LICENSE`). Data originate from the cited services and remain subject to their terms.
