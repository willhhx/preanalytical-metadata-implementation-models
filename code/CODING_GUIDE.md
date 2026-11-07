# Coding guide: manually coded records (BBMRI-ERIC Directory collections)

Code each sampled record against the 14 core scorecard elements. One record = one collection / sample set / specimen entry, as the catalogue presents it. Write down once, before coding, what "a record" means for each catalogue (put it in `manual/sample_<CAT>_RULE.txt`).

## Levels

| Level | Rule |
|---|---|
| 0 | Not present: no field or label for the element on the page, or the value is blank / "unknown" / "not reported". |
| 1 | Free text only: the information appears inside a description or notes, not in a discrete field. |
| 2 | Structured: a discrete, populated field or dropdown value for this record (e.g. "Storage temperature: -80 C"). |
| 3 | Structured and standards-coded: the value uses a published code or ontology (SPREC code, MIABIS code list, NCIt, SNOMED CT, UBERON). Name the standard in `notes`. |
| NA | Structurally not applicable (e.g. post-mortem interval for a surgical resection, fixation duration for snap-frozen-only material). Explain in `notes`. |

## Decision rules

1. **Code what the page shows for that record**, not what the catalogue "probably" records. If you need to open another page (e.g. a help or data-dictionary page) to know the field exists, a field that is visible only there counts as level 0 for the record.
2. **Ranges count as structured** (level 2) when they sit in a discrete field ("cold ischemia: < 1 h"). The same phrase inside a paragraph is level 1.
3. **A field that exists but is empty for this record is level 0.** Write `schema_only` in `notes`, so we can report "defined but unpopulated" separately.
4. **Collection-level catalogues** (UKTD, CHTN): a statement about the whole collection applies to the record. If the collection says "samples stored at -80 C", E1 = 2 (or 3 if coded).
5. **Do not infer.** "Snap frozen" does not imply a cold ischemia time. "FFPE" does not imply a fixative type or duration. Code the element that is actually stated.
6. **Mixed values** inside one record (e.g. several storage temperatures): code the level of the least informative statement and note "mixed".
7. **Ineligible record** (e.g. no human tissue): write `INELIGIBLE: reason` in `notes`, leave levels blank, and use the next reserve row (`is_reserve = TRUE`) in slot order.

## Elements (core)

B1 type of collection | B3 warm ischemia time | B4 cold ischemia time | D1 fixative type | D2 fixation duration | D3 stabilisation / freezing method | D4 post-mortem interval (autopsy only) | E1 long-term storage temperature | E2 storage duration | E3 freeze-thaw cycles | E4 temperature excursion / monitoring record | G1 any sample QC metric | G2 SPREC code or coded equivalent | G3 named standard / SOP link

## Evidence and reliability

- Paste the page URL in `evidence_url` and the date in `accessed_date` (one URL per record is enough if all elements are on that page; otherwise list several separated by `;`).
- Take a dated screenshot or save the page as PDF for each coded record; keep them in a folder outside the code repository.
- The second coder works from the same pages **without seeing coder 1's levels** (`coding_<CAT>_coder2.*` is blank by design). If you work alone, wait at least 48 hours and re-code the subset from the evidence pages only, then say "intra-rater" in Methods.
- Code in one file format per coder (CSV or xlsx), not both. If both exist, the newest is read.

## BBMRI-ERIC Directory collections (the manual tier in the current design)

Records are tissue collections drawn at random from `out/bbmri_frame_tissue_cancer.csv` (tissue-related AND cancer-related collections) with `06_draw_sample.py`. The coding sheet carries a **dated snapshot** of each collection (`snap_*` columns: name, free-text description, materials, storage temperatures, SOP, quality, data categories, keywords, retrieval time). **Code from the snapshot columns only**, not from the live site, so both coders see identical evidence.

- **2**: the information sits in a discrete, populated structured field (e.g. `snap_storage_temperatures` for E1, `snap_sop` for G3).
- **3**: the structured value comes from a published code list (the Directory's MIABIS ontologies, e.g. storage temperature codes). Name the list in `notes`.
- **1**: the information is only in free text (`snap_description`, `snap_keywords`), for example "snap frozen within 30 min of excision" (B4/D3), "stored at -80 C" (E1 without a structured field), "fixed in 10% NBF for 24 h" (D1/D2).
- **0**: not stated anywhere in the snapshot.
- **NA**: structurally not applicable (e.g. D4 post-mortem interval for surgical collections; D1/D2 for frozen-only collections). Explain in `notes`.
- **Ineligible** (e.g. the collection is not human tissue after all): write `INELIGIBLE: reason` in `notes` and use the next reserve slot in order.
- Quote the deciding phrase in `notes` for every level 1 (short, a few words) so the second coder and adjudication can see what was relied on.
