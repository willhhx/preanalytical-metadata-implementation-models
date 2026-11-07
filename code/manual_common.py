"""
manual_common.py -- shared helpers for the manual (web-only catalogue) coding workflow.

Catalogues coded by hand: NCI CHTN, UK tissue directory (UKTD), CPTAC (PDC portal pages).
Coding scale (per scorecard element):
    0 not present | 1 free text only | 2 structured field | 3 structured + standards-coded | NA not applicable
"""
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd

from audit_common import ROOT

MANUAL = ROOT / "manual"
MANUAL.mkdir(exist_ok=True)

CATALOGUES = {
    "BBMRI": "BBMRI-ERIC Directory tissue collections: free-text description + structured fields (snapshot from 03_bbmri_pull.py)",
    "CHTN": "NCI Cooperative Human Tissue Network (collection / specimen-type descriptions)",
    "UKTD": "UK tissue directory (collection-level sample sets)",
    "CPTAC": "CPTAC specimen metadata as shown on the PDC portal (record-level)",
}
ACTIVE = ["BBMRI"]  # catalogues in the current study design (CHTN/UKTD/CPTAC dropped: no public record-level access)
LEVELS = ["0", "1", "2", "3", "NA"]
NUMERIC_LEVELS = [0, 1, 2, 3]
MAX_DIST = 3.0  # fixed ordinal scale 0..3, so weights do not depend on the categories observed


def core_elements(include_controls=False):
    card = pd.read_csv(ROOT / "scorecard_solid_tissue.csv")
    if not include_controls:
        card = card[card["weight_core"] == 1]
    return card["element_id"].tolist(), card


def norm_level(x):
    """Normalise a spreadsheet cell to one of '0','1','2','3','NA' or '' (blank). Raises on junk."""
    if x is None:
        return ""
    s = str(x).strip().upper()
    if s in ("", "NAN", "NONE"):
        return ""
    if s in ("NA", "N/A", "N.A."):
        return "NA"
    try:
        f = float(s)
    except ValueError:
        raise ValueError(f"invalid level {x!r}; allowed: 0,1,2,3,NA or blank")
    if f in (0.0, 1.0, 2.0, 3.0):
        return str(int(f))
    raise ValueError(f"invalid level {x!r}; allowed: 0,1,2,3,NA or blank")


def read_sheet(path):
    """Read a coding sheet (.csv or .xlsx) as strings, preserving 'NA' and normalising levels."""
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        df = pd.read_excel(path, sheet_name="coding", dtype=str, keep_default_na=False)
    else:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df = df.fillna("")
    df.columns = [c.strip() for c in df.columns]
    return df


def find_sheet(catalogue, coder):
    """Return the coding sheet for a coder ('coder1'/'coder2'). If both .xlsx and .csv exist, the most
    recently modified one wins (so whichever format you actually typed into is the one that is read)."""
    found = [MANUAL / f"coding_{catalogue}_{coder}{ext}" for ext in (".xlsx", ".csv")]
    found = [p for p in found if p.exists()]
    if not found:
        raise FileNotFoundError(f"No coding sheet found: manual/coding_{catalogue}_{coder}.(xlsx|csv)")
    best = max(found, key=lambda p: p.stat().st_mtime)
    if len(found) > 1:
        print(f"  note: both formats exist for {coder}; reading the newest: {best.name}")
    return best


def element_cols(df):
    """Element columns present in a sheet (ids look like A1, B3, D4 ...)."""
    import re
    return [c for c in df.columns if re.fullmatch(r"[A-G][0-9]", c)]


def clean_levels(df, cols):
    """Return a copy with level columns normalised; error message lists every bad cell."""
    df = df.copy()
    bad = []
    for c in cols:
        out = []
        for i, v in zip(df.index, df[c]):
            try:
                out.append(norm_level(v))
            except ValueError as e:
                bad.append(f"slot {df.loc[i, 'record_slot']} col {c}: {e}")
                out.append("")
        df[c] = out
    if bad:
        raise SystemExit("Invalid cells:\n  " + "\n  ".join(bad))
    return df


# ----------------------------------------------------------------------------- statistics
def cohen_kappa(a, b, weighted=False):
    """
    Cohen's kappa for two raters over categorical labels (strings).
    weighted=True: linear-weighted kappa on numeric ordinal labels 0..3 (non-numeric pairs dropped).
    Returns nan when kappa is undefined (no pairs, or chance agreement == 1).
    """
    a, b = list(a), list(b)
    if weighted:
        pairs = [(int(x), int(y)) for x, y in zip(a, b) if x in "0123" and y in "0123" and x != "" and y != ""]
        if not pairs:
            return float("nan")
        cats = NUMERIC_LEVELS
        idx = {c: i for i, c in enumerate(cats)}
        k = len(cats)
        o = np.zeros((k, k))
        for x, y in pairs:
            o[idx[x], idx[y]] += 1
        n = o.sum()
        e = np.outer(o.sum(1), o.sum(0)) / n
        d = np.abs(np.subtract.outer(np.arange(k), np.arange(k))) / MAX_DIST
        denom = (d * e).sum()
        if denom == 0:
            return float("nan")
        return 1.0 - (d * o).sum() / denom
    pairs = [(x, y) for x, y in zip(a, b) if x != "" and y != ""]
    if not pairs:
        return float("nan")
    cats = sorted({c for p in pairs for c in p})
    idx = {c: i for i, c in enumerate(cats)}
    k = len(cats)
    o = np.zeros((k, k))
    for x, y in pairs:
        o[idx[x], idx[y]] += 1
    n = o.sum()
    po = np.trace(o) / n
    pe = (o.sum(1) * o.sum(0)).sum() / n ** 2
    if math.isclose(pe, 1.0):
        return float("nan")
    return (po - pe) / (1 - pe)


def percentile_ci(values, alpha=0.05):
    v = np.array([x for x in values if x == x])
    if len(v) < 20:
        return (float("nan"), float("nan"))
    return (float(np.percentile(v, 100 * alpha / 2)), float(np.percentile(v, 100 * (1 - alpha / 2))))


def seeded_rng(seed):
    return random.Random(seed)
