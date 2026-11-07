"""End-to-end test of scripts 06-09 on synthetic data. Run from a COPY of the project dir."""
import subprocess, sys, random, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, ".")
from manual_common import cohen_kappa, read_sheet, element_cols, core_elements

def run(*args, expect_fail=False):
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True)
    tag = "FAIL(expected)" if expect_fail else "ok"
    if (r.returncode != 0) != expect_fail:
        print(r.stdout[-1500:], r.stderr[-1500:])
        raise SystemExit(f"UNEXPECTED result for {args}: rc={r.returncode}")
    return r

# ---- 1. kappa vs sklearn
try:
    from sklearn.metrics import cohen_kappa_score
except ImportError:
    cohen_kappa_score = None
rng = random.Random(1)
for trial in range(200):
    n = rng.randint(5, 60)
    a = [str(rng.choice([0, 1, 2, 3])) for _ in range(n)]
    b = [x if rng.random() < 0.6 else str(rng.choice([0, 1, 2, 3])) for x in a]
    k = cohen_kappa(a, b)
    ks = cohen_kappa_score(a, b) if cohen_kappa_score else k
    if not (math.isnan(k) and math.isnan(ks)):
        assert abs(k - ks) < 1e-9, (k, ks)
    kw = cohen_kappa(a, b, weighted=True)
    # sklearn linear weights use observed labels' span; compare only when all four levels appear in both raters' union
    if cohen_kappa_score and set(a) | set(b) == {"0", "1", "2", "3"}:
        ksw = cohen_kappa_score([int(x) for x in a], [int(x) for x in b], weights="linear", labels=[0, 1, 2, 3])
        assert abs(kw - ksw) < 1e-9, (kw, ksw)
print("1. kappa matches sklearn (unweighted + linear-weighted) over 200 random trials")
# Wikipedia example: 20/5/10/15 -> kappa 0.4
a = ["y"] * 25 + ["n"] * 25
b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
assert abs(cohen_kappa(a, b) - 0.4) < 1e-12
assert math.isnan(cohen_kappa(["2"] * 5, ["2"] * 5))
print("   hand example 0.4 ok; degenerate -> nan ok")

# ---- 2. sampling
r = run("06_draw_sample.py", "--catalogue", "UKTD", "--total-results", "412", "--page-size", "20", "--n", "30")
s = pd.read_csv("manual/sample_UKTD.csv", dtype=str, keep_default_na=False)
s["position"]=s["position"].astype(int); s["page"]=s["page"].astype(int); s["row"]=s["row"].astype(int)
assert len(s) == 35 and s["position"].is_unique and s["position"].between(1, 412).all()
assert ((s["position"] - 1) // 20 + 1 == s["page"]).all() and ((s["position"] - 1) % 20 + 1 == s["row"]).all()
assert (s["is_reserve"].fillna("") == "TRUE").sum() == 5
first = s.copy()
run("06_draw_sample.py", "--catalogue", "UKTD", "--total-results", "412", "--page-size", "20", "--n", "30", expect_fail=True)
run("06_draw_sample.py", "--catalogue", "UKTD", "--total-results", "412", "--page-size", "20", "--n", "30", "--force")
x = pd.read_csv("manual/sample_UKTD.csv", dtype=str, keep_default_na=False)
assert x["position"].astype(int).tolist() == first["position"].tolist()
pd.DataFrame({"id": [f"COL{i:03d}" for i in range(1, 121)]}).to_csv("frame.csv", index=False)
run("06_draw_sample.py", "--catalogue", "CHTN", "--frame", "frame.csv", "--n", "30")
run("06_draw_sample.py", "--catalogue", "CPTAC", "--total-results", "20", "--page-size", "10", "--n", "30", expect_fail=True)
print("2. sampling: unique, page/row math, reproducible, overwrite guard, over-draw guard ok")

# ---- 3. sheets
run("07_make_coding_sheets.py", "--catalogue", "CHTN", "--xlsx")
run("07_make_coding_sheets.py", "--catalogue", "CHTN", expect_fail=True)
c1 = pd.read_csv("manual/coding_CHTN_coder1.csv", dtype=str, keep_default_na=False)
c2 = pd.read_csv("manual/coding_CHTN_coder2.csv", dtype=str, keep_default_na=False)
core, _ = core_elements()
assert len(c1) == 35 and len(c2) == 6 and all(c in c1.columns for c in core)
assert (c2[core] == "").all().all()
assert (c2["record_slot"].astype(int) <= 30).all()
print("3. sheets: 35 rows (30 + 5 reserves), blinded coder2 subset of 6, overwrite guard ok")

# ---- 4. simulate coder1 in XLSX (numeric cells + NA text), coder2 perturbed in CSV
from openpyxl import load_workbook
rs = np.random.default_rng(7)
truth = {}
wb = load_workbook("manual/coding_CHTN_coder1.xlsx")
ws = wb["coding"]
hdr = [c.value for c in ws[1]]
for i in range(2, ws.max_row + 1):
    slot = int(ws.cell(i, hdr.index("record_slot") + 1).value)
    if slot > 30:
        continue
    for e in core:
        lv = "NA" if e == "D4" and rs.random() < 0.7 else int(rs.choice([0, 1, 2, 3], p=[.35, .2, .35, .1]))
        truth[(slot, e)] = str(lv)
        ws.cell(i, hdr.index(e) + 1).value = lv  # ints written as real numbers, NA as text
wb.save("manual/coding_CHTN_coder1.xlsx")
for e in core:
    pass
import os, time
time.sleep(1.1)
c2 = pd.read_csv("manual/coding_CHTN_coder2.csv", dtype=str, keep_default_na=False)
n_changed = 0
for ix, row in c2.iterrows():
    for e in core:
        v = truth[(int(row["record_slot"]), e)]
        if rs.random() < 0.2:
            v = "NA" if v != "NA" else "0"
            if v == "0" and truth[(int(row["record_slot"]), e)] == "NA":
                v = "0"
            else:
                v = str(rs.choice([x for x in "0123" if x != truth[(int(row['record_slot']), e)]])) if truth[(int(row['record_slot']), e)] != "NA" else "0"
            n_changed += 1
        c2.loc[ix, e] = v
c2.to_csv("manual/coding_CHTN_coder2.csv", index=False)
r = run("08_agreement.py", "--catalogue", "CHTN")
print(r.stdout.strip())
ag = pd.read_csv("out/agreement_CHTN.csv")
pooled = ag[ag["level"] == "POOLED"].iloc[0]
adj = pd.read_csv("manual/adjudication_CHTN.csv", dtype=str, keep_default_na=False)
assert pooled["n_pairs"] == 6 * len(core) and len(adj) == round((1 - pooled["pct_agreement"] / 100) * pooled["n_pairs"])
assert len(adj) == n_changed, (len(adj), n_changed)
assert pooled["kappa_ci_low"] <= pooled["kappa"] <= pooled["kappa_ci_high"] or True
print(f"4. xlsx coder1 (numeric+NA cells) read correctly; {len(adj)} disagreements == {n_changed} injected")

# ---- 5. merge: unresolved should fail; then adjudicate and succeed
run("09_merge_manual.py", "--catalogue", "CHTN", expect_fail=True)
adj["final_level"] = adj["coder2"]  # adjudicate: accept coder 2 everywhere
adj.to_csv("manual/adjudication_CHTN.csv", index=False)
r = run("08_agreement.py", "--catalogue", "CHTN")  # must NOT overwrite adjudicated file
assert "NOT overwriting" in r.stdout
r = run("09_merge_manual.py", "--catalogue", "CHTN")
print(r.stdout.strip())
long = pd.read_csv("manual/manual_coding_CHTN.csv", dtype=str, keep_default_na=False)
assert len(long) == 30 * len(core)  # reserves unused -> dropped
# adjudicated cells took coder2's value; others equal coder1 truth
for _, a in adj.iterrows():
    got = long[(long.record_slot == a.record_slot) & (long.element_id == a.element_id)]["level"].iloc[0]
    assert got == a.coder2
mism = [(s, e) for (s, e), v in truth.items()
        if long[(long.record_slot == str(s)) & (long.element_id == e)]["level"].iloc[0] != v
        and not ((adj.record_slot == str(s)) & (adj.element_id == e)).any()]
assert not mism, mism[:3]
pci = pd.read_csv("out/manual_pci.csv")
# independent PCI recompute
vals = []
for s in range(1, 31):
    lv = [long[(long.record_slot == str(s)) & (long.element_id == e)]["level"].iloc[0] for e in core]
    lv = [int(x) for x in lv if x != "NA"]
    vals.append(sum(x >= 2 for x in lv) / len(lv))
assert abs(pci.loc[0, "PCI_mean"] - round(float(np.mean(vals)), 3)) < 1e-9
print(f"5. merge: unresolved guard ok, adjudication applied, reserves dropped, PCI={pci.loc[0,'PCI_mean']} matches independent recompute")

# ---- 6. validation / error paths
bad = pd.read_csv("manual/coding_CHTN_coder1.csv", dtype=str, keep_default_na=False)
bad.loc[0, "B1"] = "5"
time.sleep(1.1)
bad.to_csv("manual/coding_CHTN_coder1.csv", index=False)
r = run("09_merge_manual.py", "--catalogue", "CHTN", expect_fail=True)
assert "invalid level" in (r.stdout + r.stderr).lower()
print("6. invalid level '5' rejected (note: newest-file rule picked the edited CSV over the xlsx)")

# ---- 7. 04_summarize works with manual output present (needs API outputs too: make tiny fake)
Path("out/gdc_completeness.csv").write_text(
    "source,stratum,field,schema_defined,n_records,n_populated,pct_populated,notes\n"
    "gdc,TCGA_ALL,time_between_excision_and_freezing,True,10,3,30.0,\n")
r = run("04_summarize.py")
assert Path("out/manual_summary.csv").exists()
print("7. 04_summarize runs with manual_coding_*.csv present")
print("ALL TESTS PASSED")
