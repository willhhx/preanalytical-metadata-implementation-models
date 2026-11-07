# Methods: API description and code availability (fill-in template)

Fill the bracketed items from `out/*_run_manifest.json` and `out/api_call_log.jsonl` after your full run.

## Suggested Methods paragraph (about 150 words)

> Catalogue metadata were retrieved programmatically in Python [version] using the `requests` [version] and `pandas` [version] libraries. For the Genomic Data Commons (GDC), we queried the public REST API (`https://api.gdc.cancer.gov`, data release [from /status], accessed [date]) at the `/cases/_mapping` endpoint to establish which sample fields (`samples.*`) the API exposes and at the `/cases` endpoint to retrieve the nested sample records for TCGA and CPTAC projects. For GTEx we queried the GTEx Portal API v2 (`/dataset/sample`, datasetId gtex_v8, accessed [date]). For the BBMRI-ERIC Directory we queried the public MOLGENIS EMX2 GraphQL endpoint of the aggregated ERIC schema (`https://directory.bbmri-eric.eu/ERIC/graphql`, table `Collections`, schema read by introspection, accessed [date]). Only catalogue-level and sample-annotation metadata were retrieved; no controlled-access, genomic or personal data were accessed. Requests were rate-limited to one per [0.5] s, every request and response checksum was logged, and raw responses were archived. Fields were scored against a solid-tissue SPREC-based scorecard (Supplementary Table S1). In addition, [30] BBMRI-ERIC tissue and cancer-related collections were drawn at random (seeded, with reserves) from a dated snapshot and coded by two raters for preanalytical information present in free text or structured fields (Cohen's kappa reported). Code and logs are available at [GitHub URL; Zenodo DOI].

## API table (supplementary or Methods table)

| Source | API / version | Base URL | Endpoint(s) | Purpose | Key parameters | Output | Date accessed |
|---|---|---|---|---|---|---|---|
| GDC (TCGA, CPTAC) | GDC REST API, release [x] | https://api.gdc.cancer.gov | /status, /cases/_mapping, /v0/submission/_dictionary/sample, /cases | Schema exposure and field population per project | filters (program, project_id), fields, size, from | out/gdc_completeness.csv | [ ] |
| GTEx | GTEx Portal API v2 | https://gtexportal.org/api/v2 | /dataset/sample | Sample-level ischemia, fixative, autolysis, RIN population | datasetId=gtex_v8, page, itemsPerPage | out/gtex_completeness.csv | [ ] |
| BBMRI-ERIC Directory | MOLGENIS EMX2 GraphQL | https://directory.bbmri-eric.eu/ERIC/graphql | introspection of `Collections`; `Collections(limit, offset)` | Collection attribute schema and population; snapshot for manual coding | limit, offset, orderby id | out/bbmri_completeness.csv | [ ] |

## Code availability statement (for Declarations: Availability of data and materials)

> The scripts used to query the APIs, the scorecard, the raw API responses (SHA-256 checksummed), the call log and the manual coding sheets are available at [GitHub repository URL] and archived at Zenodo ([DOI]), version [v1.0.0].

## How to get a DOI (10 minutes)

1. Create a GitHub repository and push this folder. Add a `LICENSE` file (MIT for code, CC-BY for data).
2. Log in to Zenodo with GitHub, switch the repository on in Zenodo's GitHub settings, then create a GitHub Release (v1.0.0). Zenodo mints the DOI automatically.
3. Put the DOI in the Availability of data and materials statement and the reference list.
4. Do not commit `raw/` if it is large: put it in the Zenodo upload directly or keep only `api_call_log.jsonl` with checksums.
