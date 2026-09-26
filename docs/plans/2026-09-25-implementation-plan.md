# NPN SCM — Implementation Plan (PR1 SupplyGuard + P2 TrendWear Planner)

> **For agentic workers:** implement task by task, in order. Steps use checkbox (`- [ ]`) syntax.
> **Commits are made by the repository owner, not by the agent.** Where a task ends with "hand over for
> commit", print the suggested message and stop; do not run `git commit`.

**Goal:** Two independent, deployable applications — SupplyGuard (supplier allocation and delivery-risk
prediction) and TrendWear Planner (integrated S&OP) — built on real Kaggle data extended with clearly
labelled synthetic records, demo-ready by 2026-09-28.

**Architecture:** One repository, two self-contained apps under `apps/`, each with its own FastAPI backend,
static HTML/CSS/JS frontend, SQLite database and Dockerfile. `packages/` holds only shared front-end
modules and plumbing helpers.
No data, features, models or planning logic are shared between the apps.

**Tech Stack:** Python 3.12, FastAPI, pandas, scikit-learn, XGBoost, LightGBM, PuLP (CBC), SQLAlchemy,
SQLite, pytest · plain HTML, CSS and JavaScript (ES modules, no build step), Chart.js, `node --test` + jsdom ·
Hugging Face (Chronos-Bolt, hosted inference for narrative) · GitHub Actions → Hugging Face Docker Spaces.

## Status — 26 September 2026

**All 27 tasks are built.** 350 Python tests, 32 JavaScript tests, ruff clean, 13
screens, both containers defined, both Space staging trees verified.

Three things remain, and all three are the repository owner's to do:

1. **Commit and push.** Nothing in this build has been committed; that is
   deliberate and stated in the note above.
2. **Create the two Hugging Face Spaces** under `Nouman-20` and push the staged
   trees — `python scripts/stage_space.py pr1 --force` then the commands it prints.
   See `docs/runbook.md` §5.
3. **Add two repository secrets** for the deploy workflow: `HF_TOKEN` and
   `KAGGLE_ACCESS_TOKEN`. Both tokens used during the build should be rotated after
   30 September.

One limitation to note rather than discover: **the containers have never been
built**, because Docker is not installed on the build machine. What was verified is
the exact tree they create — both applications were started from the staged Space
directories, on port 7860, with the container's `PYTHONPATH`, and answered on
`/api/health`, `/api/kpis`, the pages and `/shared/`. `docs/runbook.md` §4 says the
same thing in the same words.

---

## Global Constraints

- **Separation rule:** PR1 and P2 share no data, no models and no runtime calls. `packages/` may contain only
  presentation and plumbing helpers. A test enforces this (Task 1).
- **No AI attribution** anywhere in the repository: commit messages, code comments, docs, UI.
- **Every row carries `origin`** of `real` or `synthetic`. All reported model metrics are computed on
  `origin = 'real'` rows only.
- **No leakage:** every trailing feature is computed strictly from records dated before the record being
  scored. Train/test splits are by time, never random.
- **Secrets** live in `.env` (gitignored): `HF_TOKEN`. Kaggle auth lives at `~/.kaggle/access_token`.
- **Python 3.12**, Node 22 (used only to run the JavaScript tests, never to build). The venv at `.venv` is
  already created.
- **No front-end framework and no build step.** Browser-native ES modules, one pinned local Chart.js, and
  our own ~150-line table module, so every member can read and defend the front end.
- Raw data is gitignored and re-downloadable via `scripts/fetch_data.py`.
- Every module gets a short guide in `docs/modules/<module>.md` written as part of that module's task.

---

## File structure

```
apps/pr1/backend/app/       config.py db.py models.py etl/ features/ risk/ optimizer/ scenarios/
                            narrative/ api/ main.py
apps/pr1/web/               index.html pages/*.html js/*.js css/*.css
apps/p2/backend/app/        config.py db.py models.py etl/ forecast/ production/ fabric/ markdown/ sop/
                            narrative/ api/ main.py
apps/p2/web/                index.html pages/*.html js/*.js css/*.css
packages/pyshared/          logging.py metrics.py timeutil.py
packages/web/               tokens.css base.css table.js chart.js api.js format.js
scripts/                    fetch_data.py
tests/                      test_separation.py  (+ per-app tests under each app's tests/)
```

---

### Task 1: Repository skeleton, shared packages, CI, separation test

**Files:**
- Create: `pyproject.toml`, `README.md`, `packages/pyshared/__init__.py`, `packages/pyshared/logging.py`,
  `packages/pyshared/metrics.py`, `packages/pyshared/timeutil.py`, `tests/test_separation.py`,
  `.github/workflows/ci.yml`, `apps/pr1/backend/app/__init__.py`, `apps/p2/backend/app/__init__.py`
- Test: `tests/test_separation.py`, `tests/test_metrics.py`

**Interfaces:**
- Produces: `pyshared.metrics.classification_report_dict(y_true, y_prob, threshold=0.5) -> dict` with keys
  `precision`, `recall`, `f1`, `roc_auc`, `pr_auc`, `support`, `positive_rate`.
  `pyshared.timeutil.time_split(df, date_col, test_fraction=0.25) -> tuple[DataFrame, DataFrame]`.
  `pyshared.logging.get_logger(name) -> logging.Logger`.

- [ ] **Step 1: Write the failing separation test**

```python
# tests/test_separation.py
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def _python_files(app: str):
    return (ROOT / "apps" / app).rglob("*.py")

def test_apps_never_import_each_other():
    for app, forbidden in (("pr1", "apps.p2"), ("p2", "apps.pr1")):
        for path in _python_files(app):
            text = path.read_text(encoding="utf-8")
            assert forbidden not in text, f"{path} imports the other application"

def test_shared_package_holds_no_domain_logic():
    banned = re.compile(r"\b(supplier|allocation|markdown|forecast|risk_score)\b", re.I)
    for path in (ROOT / "packages" / "pyshared").rglob("*.py"):
        assert not banned.search(path.read_text(encoding="utf-8")), f"{path} contains domain logic"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv/Scripts/python -m pytest tests/test_separation.py -v`
Expected: FAIL — the `apps/` and `packages/` directories do not exist yet.

- [ ] **Step 3: Create the skeleton and shared helpers**

```python
# packages/pyshared/metrics.py
from sklearn.metrics import (average_precision_score, f1_score, precision_score,
                             recall_score, roc_auc_score)

def classification_report_dict(y_true, y_prob, threshold: float = 0.5) -> dict:
    y_pred = (y_prob >= threshold).astype(int)
    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, y_prob)),
        "pr_auc": float(average_precision_score(y_true, y_prob)),
        "support": int(len(y_true)),
        "positive_rate": float(y_true.mean()),
        "threshold": float(threshold),
    }
```

```python
# packages/pyshared/timeutil.py
import pandas as pd

def time_split(df: pd.DataFrame, date_col: str, test_fraction: float = 0.25):
    ordered = df.sort_values(date_col)
    cut = int(len(ordered) * (1 - test_fraction))
    return ordered.iloc[:cut].copy(), ordered.iloc[cut:].copy()
```

`pyproject.toml` declares the dependencies listed in the tech stack and registers `packages` on the path.

- [ ] **Step 4: Write and run the metrics test**

```python
# tests/test_metrics.py
import numpy as np
from pyshared.metrics import classification_report_dict

def test_perfect_classifier_scores_one():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.2, 0.9, 0.8])
    out = classification_report_dict(y, p)
    assert out["f1"] == 1.0 and out["roc_auc"] == 1.0 and out["support"] == 4
```

Run: `.venv/Scripts/python -m pytest tests -v` → Expected: PASS.

- [ ] **Step 5: Add CI**

`.github/workflows/ci.yml` installs Python 3.12 and Node 22, runs `ruff check`, `pytest`, and `node --test` for the
shared and per-app JavaScript modules. It must run on push and pull request.

- [ ] **Step 6: Hand over for commit**

Suggested message: `chore: repository skeleton, shared helpers and CI`

---

### Task 2: Data fetch script

**Files:**
- Create: `scripts/fetch_data.py`, `docs/data-sources.md`
- Test: `tests/test_fetch_data.py`

**Interfaces:**
- Produces: `scripts.fetch_data.DATASETS: list[Dataset]` where
  `Dataset = namedtuple("Dataset", "slug files dest kind")`, and `fetch_all(force: bool = False) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetch_data.py
from scripts.fetch_data import DATASETS

def test_every_dataset_declares_a_destination_under_data_raw():
    assert DATASETS, "no datasets declared"
    for d in DATASETS:
        assert str(d.dest).startswith("data/raw/"), d
        assert d.kind in {"dataset", "file"}
```

- [ ] **Step 2: Run it, watch it fail** — `ModuleNotFoundError: scripts.fetch_data`.

- [ ] **Step 3: Implement the script**

It downloads, via the Kaggle CLI: `divyeshardeshana/supply-chain-shipment-pricing-data`,
`shahriarkabir/procurement-kpi-analysis-dataset`, `shfarshid/supplier-stability-dataset-for-procurement`,
`harshsingh2209/supply-chain-analysis`, `anirudhchauhan/retail-store-inventory-forecasting-dataset`, and the
individual SAP files `lfa1.csv`, `ekko.csv`, `ekpo.csv`, `eket.csv`, `ekbe.csv` from
`mustafakeser4/sap-dataset-bigquery-dataset`. Each lands in the folder layout already on disk. Existing files
are skipped unless `force=True`.

- [ ] **Step 4: Run the test** → PASS. Then run `python scripts/fetch_data.py --check`, which must report all
  files present without downloading anything.

- [ ] **Step 5: Write `docs/data-sources.md`** listing each dataset, its licence, row count and what it is
  used for. Copy the counts from the design document.

- [ ] **Step 6: Hand over for commit** — `feat: data fetch script and source documentation`

---

### Task 3: PR1 ETL — SCMS purchase orders into SQLite

**Files:**
- Create: `apps/pr1/backend/app/db.py`, `apps/pr1/backend/app/models.py`,
  `apps/pr1/backend/app/etl/scms.py`, `apps/pr1/backend/app/etl/__init__.py`
- Test: `apps/pr1/tests/test_etl_scms.py`

**Interfaces:**
- Produces: `etl.scms.load_scms(path: Path) -> pd.DataFrame` with columns
  `po_id, supplier_id, vendor, site, country, product_group, item, qty, unit_price, line_value,
  freight_cost, weight_kg, shipment_mode, po_date, promised_date, delivered_date, late_days, is_late, origin`.
  `supplier_id` is a slug of `vendor|site`. `origin` is `"real"`.
  Tables: `suppliers`, `materials`, `supplier_offers`, `po_history` (SQLAlchemy models in `models.py`).

- [ ] **Step 1: Write the failing tests**

```python
# apps/pr1/tests/test_etl_scms.py
import pandas as pd
from app.etl.scms import load_scms
from app.config import RAW_SCMS

def test_load_scms_shape_and_labels():
    df = load_scms(RAW_SCMS)
    assert len(df) == 10324
    assert df.supplier_id.nunique() == 217
    assert df.late_days.notna().all()
    assert 0.10 < df.is_late.mean() < 0.13          # real rate is 11.5%
    assert set(df.origin.unique()) == {"real"}

def test_no_negative_quantities_or_prices():
    df = load_scms(RAW_SCMS)
    assert (df.qty >= 0).all()
    assert (df.unit_price >= 0).all()

def test_dates_are_ordered_for_most_rows():
    df = load_scms(RAW_SCMS)
    ok = (df.promised_date >= df.po_date) | df.po_date.isna()
    assert ok.mean() > 0.9
```

- [ ] **Step 2: Run them, watch them fail.**

- [ ] **Step 3: Implement `load_scms`.** Parse the mixed-format dates with
  `pd.to_datetime(..., errors="coerce", format="mixed", dayfirst=True)`; treat the literal strings
  `"Date Not Captured"` and `"Pre-PO Process"` as missing; coerce `Freight Cost (USD)` to numeric and keep a
  boolean `freight_bundled` for the 40% of rows carrying text instead of a number; compute
  `late_days = delivered_date - promised_date` and `is_late = late_days > 0`.

- [ ] **Step 4: Run the tests** → PASS.

- [ ] **Step 5: Add the SQLAlchemy models and a `build_db()` that writes the frame into `po_history`,** with a
  test asserting the row count round-trips through SQLite.

- [ ] **Step 6: Write `docs/modules/pr1-etl.md`** — what the module does, the column contract, the two date
  quirks, and how to re-run it.

- [ ] **Step 7: Hand over for commit** — `feat(pr1): load SCMS delivery history into the database`

---

### Task 4: PR1 ETL — SAP vendor master and supplier catalogue

**Files:**
- Create: `apps/pr1/backend/app/etl/sap.py`, `apps/pr1/backend/app/etl/suppliers.py`
- Test: `apps/pr1/tests/test_etl_sap.py`, `apps/pr1/tests/test_supplier_catalogue.py`

**Interfaces:**
- Produces: `etl.sap.load_vendor_master(path) -> pd.DataFrame[supplier_id, name, country, city, origin]`
  (2,590 rows) and `etl.sap.load_po_outcomes(dir) -> pd.DataFrame[po_id, vendor, promised_date,
  received_date, qty, late_days, is_late, origin]` (~158,942 rows, 42% late).
  `etl.suppliers.build_catalogue(scms_df, sap_master) -> pd.DataFrame` — one row per supplier entity with
  `supplier_id, name, country, product_group, on_time_rate, avg_lead_days, p75_lead_days, defect_rate,
  avg_unit_price, historical_volume, origin, source`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/pr1/tests/test_etl_sap.py
def test_vendor_master_row_count():
    from app.etl.sap import load_vendor_master
    m = load_vendor_master(RAW_SAP / "lfa1.csv")
    assert m.supplier_id.nunique() == 2590
    assert m.country.nunique() > 30

def test_po_outcomes_have_both_dates_and_realistic_late_rate():
    from app.etl.sap import load_po_outcomes
    o = load_po_outcomes(RAW_SAP)
    assert len(o) > 150_000
    assert 0.38 < o.is_late.mean() < 0.46
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implement.** `load_po_outcomes` joins `eket` (schedule lines, promised date `eindt`) to the
  earliest goods receipt per line from `ekbe` (`vgabe == "1"`, posting date `budat`), then to `ekko` for the
  vendor. Keep only lines where both dates parse.

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Build the catalogue** from SCMS history, computing per-supplier statistics, and mark every row
  `origin="real"`, `source="scms"` or `"sap"`.

- [ ] **Step 6: Hand over for commit** — `feat(pr1): SAP vendor master and supplier catalogue`

---

### Task 5: PR1 synthetic supplier expansion to 500+

**Files:**
- Create: `apps/pr1/backend/app/etl/synthesize.py`, `docs/assumptions.md`
- Test: `apps/pr1/tests/test_synthesize.py`

**Interfaces:**
- Produces: `etl.synthesize.expand_suppliers(catalogue, target_total=520, seed=42) -> pd.DataFrame` with the
  same columns as the catalogue plus `moq, capacity_per_period, contract_min_share, contract_max_share`,
  and `etl.synthesize.attach_commercial_terms(catalogue, seed=42) -> pd.DataFrame` which adds those four
  columns to real suppliers too.

- [ ] **Step 1: Write the failing tests**

```python
# apps/pr1/tests/test_synthesize.py
def test_expansion_reaches_target_and_labels_origin():
    out = expand_suppliers(catalogue, target_total=520, seed=42)
    assert len(out) >= 520
    assert (out.origin == "real").sum() == len(catalogue)
    assert (out.origin == "synthetic").sum() >= 520 - len(catalogue)

def test_synthetic_statistics_track_the_real_ones():
    out = expand_suppliers(catalogue, target_total=520, seed=42)
    real, syn = out[out.origin == "real"], out[out.origin == "synthetic"]
    for col in ("on_time_rate", "avg_lead_days", "avg_unit_price"):
        assert abs(syn[col].mean() - real[col].mean()) < 0.35 * real[col].std()

def test_expansion_is_deterministic():
    a = expand_suppliers(catalogue, 520, seed=42)
    b = expand_suppliers(catalogue, 520, seed=42)
    pd.testing.assert_frame_equal(a, b)

def test_every_supplier_has_usable_commercial_terms():
    out = expand_suppliers(catalogue, 520, seed=42)
    assert (out.moq >= 0).all()
    assert (out.capacity_per_period > out.moq).all()
    assert (out.contract_min_share <= out.contract_max_share).all()
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implement.** Sample each synthetic supplier's statistics from the real distribution per
  product group (log-normal for price and lead time, beta for on-time rate and defect rate), give it a
  generated name plus a real country drawn from the observed frequency, and derive commercial terms:
  `moq` = 10th percentile of that group's order quantity, `capacity_per_period` = 95th percentile scaled by a
  size factor, contract shares from the supplier's historical share band. Seeded and deterministic.

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Write `docs/assumptions.md`,** one row per derived field with its formula, exactly matching
  the implementation.

- [ ] **Step 6: Hand over for commit** — `feat(pr1): synthetic supplier expansion with labelled origin`

---

### Task 5b: PR1 plants, requirement plan and approved supplier list

**Files:**
- Create: `apps/pr1/backend/app/etl/plants.py`, `apps/pr1/backend/app/etl/requirements.py`,
  `apps/pr1/backend/app/etl/asl.py`
- Test: `apps/pr1/tests/test_requirements.py`, `apps/pr1/tests/test_asl.py`

**Interfaces:**
- Produces:
  `plants.derive_plants(po_history, top_n=8) -> pd.DataFrame[plant_id, name, country, historical_volume]`.
  `requirements.build_plan(po_history, plants, horizon_weeks=8, seasonal=True)
  -> pd.DataFrame[material_id, plant_id, week, required_qty, source]` where `source` is
  `"derived"` or `"manual"`.
  `asl.build(po_history, suppliers, plants) -> pd.DataFrame[supplier_id, material_id, plant_id,
  approved_since, qualification]` where `qualification` is `"traded"` or `"qualified"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_requirement_plan_covers_every_material_and_plant_for_the_horizon():
    plan = build_plan(po_history, plants, horizon_weeks=8)
    assert plan.week.nunique() == 8
    assert (plan.required_qty >= 0).all()
    assert plan.groupby(["material_id", "plant_id"]).size().eq(8).all()

def test_requirement_plan_totals_track_historical_consumption():
    plan = build_plan(po_history, plants, horizon_weeks=52, seasonal=False)
    hist_weekly = historical_weekly_total(po_history)
    assert abs(plan.required_qty.sum() / 52 - hist_weekly) / hist_weekly < 0.25

def test_pr1_contains_no_forecasting_model():
    # PR1 derives requirements from history; forecasting belongs to P2.
    src = (ROOT / "apps/pr1").rglob("*.py")
    for f in src:
        text = f.read_text(encoding="utf-8")
        assert "LGBMRegressor" not in text and "chronos" not in text.lower()

def test_asl_only_approves_suppliers_with_history_or_qualification():
    asl = build(po_history, suppliers, plants)
    assert set(asl.qualification.unique()) <= {"traded", "qualified"}
    traded = asl[asl.qualification == "traded"]
    for row in traded.itertuples():
        assert has_traded(po_history, row.supplier_id, row.material_id)

def test_every_material_has_at_least_two_approved_suppliers():
    asl = build(po_history, suppliers, plants)
    assert asl.groupby(["material_id", "plant_id"]).supplier_id.nunique().min() >= 2
```

- [ ] **Step 2: Run them, watch them fail.**

- [ ] **Step 3: Implement.** Plants are the eight highest-volume delivery locations. The requirement plan
  averages historical consumption per material and plant per week and applies a seasonal index computed from
  the month-of-year pattern in the history. The ASL marks a supplier `traded` where history exists, and
  `qualified` for synthetic suppliers assigned to materials in their product group.

- [ ] **Step 4: Run the tests** → PASS.

- [ ] **Step 5: Write `docs/modules/pr1-requirements.md`,** stating plainly that PR1 does not forecast, that
  requirements are a deterministic roll-up of history, and why (the separation rule).

- [ ] **Step 6: Hand over for commit** — `feat(pr1): plants, requirement plan and approved supplier list`

---

### Task 6: PR1 point-in-time features

**Files:**
- Create: `apps/pr1/backend/app/features/build.py`
- Test: `apps/pr1/tests/test_features.py`

**Interfaces:**
- Produces: `features.build.build_order_features(po_history: pd.DataFrame) -> pd.DataFrame` adding
  `supplier_prior_orders, supplier_prior_late_rate, supplier_prior_avg_delay, order_size_vs_supplier_median,
  promised_lead_days, is_peak_quarter, mode_air, mode_ocean, mode_truck, log_line_value, weight_per_unit`.

- [ ] **Step 1: Write the failing leakage test**

```python
# apps/pr1/tests/test_features.py
def test_trailing_features_use_only_earlier_orders():
    df = pd.DataFrame({
        "po_id": [1, 2, 3],
        "supplier_id": ["a", "a", "a"],
        "po_date": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01"]),
        "is_late": [1, 0, 1], "qty": [10, 10, 10], "line_value": [100.0, 100.0, 100.0],
        "promised_date": pd.to_datetime(["2020-02-01", "2020-03-01", "2020-04-01"]),
        "shipment_mode": ["Air", "Air", "Air"], "weight_kg": [5.0, 5.0, 5.0],
    })
    out = build_order_features(df).sort_values("po_date")
    assert pd.isna(out.supplier_prior_late_rate.iloc[0])   # nothing known yet
    assert out.supplier_prior_late_rate.iloc[1] == 1.0     # only order 1 counts
    assert out.supplier_prior_late_rate.iloc[2] == 0.5     # orders 1 and 2

def test_first_order_for_a_new_supplier_is_not_dropped():
    ...
    assert len(out) == len(df)
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implement** with `groupby(...).shift(1)` and expanding means, sorted by date.

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Hand over for commit** — `feat(pr1): point-in-time order features`

---

### Task 7: PR1 delay-risk model

**Files:**
- Create: `apps/pr1/backend/app/risk/delay.py`, `apps/pr1/backend/app/risk/registry.py`
- Test: `apps/pr1/tests/test_risk_delay.py`

**Interfaces:**
- Produces: `risk.delay.train(df) -> TrainedModel` where `TrainedModel` has `.predict_proba(df) -> np.ndarray`,
  `.metrics: dict`, `.feature_importance: dict[str, float]`, `.save(path)`, `.load(path)` (classmethod).
  `risk.registry.load_model(name: str) -> TrainedModel`, names `"delay" | "quality" | "disruption"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_delay_model_beats_the_supplier_history_baseline():
    model = train(features_df)
    assert model.metrics["roc_auc"] > 0.65
    assert model.metrics["pr_auc"] > model.metrics["baseline_pr_auc"]

def test_metrics_are_computed_on_real_rows_only():
    model = train(features_df)
    assert model.metrics["support"] == int((features_df.origin == "real").sum() * 0.25)

def test_split_is_chronological():
    model = train(features_df)
    assert model.metrics["train_end_date"] <= model.metrics["test_start_date"]
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implement** with `XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.05,
  scale_pos_weight=<neg/pos>)`, a chronological split from `pyshared.timeutil.time_split`, isotonic
  calibration on the training tail, and the metrics dictionary from `pyshared.metrics`. The baseline is the
  supplier's trailing late rate.

- [ ] **Step 4: Run tests** → PASS. If ROC-AUC misses 0.65, do not tune the threshold to pass the test —
  record the true number, adjust the assertion, and note the finding in the module guide.

- [ ] **Step 4b: Benchmark three models and keep the winner**

```python
def test_benchmark_reports_all_three_candidates():
    bench = benchmark(features_df)          # logistic regression, random forest, XGBoost
    assert set(bench) == {"logistic_regression", "random_forest", "xgboost"}
    for name, m in bench.items():
        assert {"precision", "recall", "f1", "roc_auc", "pr_auc"} <= set(m)

def test_selected_model_is_the_best_by_pr_auc_unless_within_noise():
    bench = benchmark(features_df)
    chosen = select(bench, tolerance=0.01)  # prefer the simpler model when within 0.01 PR-AUC
    assert chosen in bench
```

All three use identical features and the identical chronological split. `select()` prefers the simpler model
when it is within 0.01 PR-AUC of the best, and the comparison table goes into the module guide and the model
panel. This is what we point at when the panel asks why XGBoost.

- [ ] **Step 5: Write `docs/modules/pr1-risk.md`** — features, split, metrics, and the honest statement that
  SCMS is the primary training set and SAP the larger validation set.

- [ ] **Step 6: Hand over for commit** — `feat(pr1): delivery delay risk model`

---

### Task 8: PR1 quality and disruption models

**Files:**
- Create: `apps/pr1/backend/app/risk/quality.py`, `apps/pr1/backend/app/risk/disruption.py`,
  `apps/pr1/backend/app/etl/procurement_files.py`
- Test: `apps/pr1/tests/test_risk_quality.py`, `apps/pr1/tests/test_risk_disruption.py`

**Interfaces:**
- Produces: the same `TrainedModel` interface as Task 7, trained on
  `supplier_order_lines.csv` (label `has_md_event`, 13.7% positive) and `procurement_kpi.csv`
  (label `Order_Status in {"Cancelled", "Partially Delivered"}`, 17.5% positive).

- [ ] **Step 1: Write the failing tests** — assert the positive rates above, that both models beat a
  majority-class baseline on PR-AUC, and that `predict_proba` returns values inside `[0, 1]`.
- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Implement** — XGBoost for quality; logistic regression with standardised features for
  disruption, because 777 rows will not support anything larger and it stays explainable in the interview.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Extend `docs/modules/pr1-risk.md`** with both models and their honest sample sizes.
- [ ] **Step 6: Hand over for commit** — `feat(pr1): quality and disruption risk models`

---

### Task 9: PR1 allocation MILP

**Files:**
- Create: `apps/pr1/backend/app/optimizer/model.py`, `apps/pr1/backend/app/optimizer/types.py`
- Test: `apps/pr1/tests/test_optimizer.py`

**Interfaces:**
- Consumes: supplier catalogue with commercial terms (Task 5), risk probabilities (Tasks 7–8).
- Produces:
```python
@dataclass
class AllocationRequest:
    requirements: list[Requirement]           # material_id, week, quantity, need_by
    weights: Weights                          # cost, risk, quality  (each 0..1)
    max_supplier_share: float = 0.4
    min_suppliers_per_material: int = 2

@dataclass
class AllocationResult:
    lines: list[AllocationLine]               # supplier_id, material_id, week, qty, unit_cost,
                                              # risk_cost, quality_cost, reason
    total_cost: float; expected_late_value: float; solve_seconds: float; status: str
def solve(request, suppliers, risk) -> AllocationResult
```

- [ ] **Step 1: Write the failing constraint tests**

```python
def test_only_approved_suppliers_receive_volume():
    r = solve(req(material="M1", plant="P1", qty=1000), suppliers, risk, asl)
    approved = set(asl.query("material_id=='M1' and plant_id=='P1'").supplier_id)
    assert {l.supplier_id for l in r.lines} <= approved

def test_demand_is_met_exactly():
    r = solve(req(material="M1", week=1, qty=1000), suppliers, risk)
    assert sum(l.qty for l in r.lines if l.material_id == "M1") == 1000

def test_moq_is_respected():
    r = solve(req(qty=1000), suppliers_with_moq_300, risk)
    assert all(l.qty >= 300 for l in r.lines)

def test_no_supplier_exceeds_the_concentration_cap():
    r = solve(req(qty=1000, max_supplier_share=0.4), suppliers, risk)
    assert max(l.qty for l in r.lines) <= 400

def test_capacity_is_never_exceeded():
    ...

def test_contract_minimum_is_honoured():
    ...

def test_a_risky_supplier_loses_volume_when_the_risk_weight_rises():
    low = solve(req(weights=Weights(cost=1, risk=0.0, quality=0)), suppliers, risk)
    high = solve(req(weights=Weights(cost=1, risk=1.0, quality=0)), suppliers, risk)
    assert share_of(high, "risky_supplier") < share_of(low, "risky_supplier")

def test_infeasible_request_returns_a_status_not_an_exception():
    r = solve(req(qty=10**9), suppliers, risk)
    assert r.status == "infeasible"

def test_solves_within_two_seconds_at_full_scale():
    r = solve(req_12_materials_8_weeks, all_520_suppliers, risk)
    assert r.solve_seconds < 2.0
```

- [ ] **Step 2: Run, fail.**
- [ ] **Step 3: Implement** in PuLP with CBC, exactly the objective and the seven constraint families from
  design §3.3. Eligibility by risk-adjusted lead time is a pre-filter, not a constraint, to keep the model
  small. Every line gets a generated `reason` string comparing it to the cheapest eligible option.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Write `docs/modules/pr1-optimizer.md`** with the full formulation in plain English and the
  mathematics side by side. This is the document the team studies for Sep 30.
- [ ] **Step 6: Hand over for commit** — `feat(pr1): supplier allocation MILP`

---

### Task 10: PR1 baselines and savings comparison

**Files:**
- Create: `apps/pr1/backend/app/optimizer/baselines.py`
- Test: `apps/pr1/tests/test_baselines.py`

**Interfaces:**
- Produces: `baselines.cheapest_first(request, suppliers) -> AllocationResult`,
  `baselines.equal_split(request, suppliers) -> AllocationResult`,
  `baselines.historical_mix(request, suppliers, history) -> AllocationResult`,
  `baselines.compare(optimised, baselines: dict[str, AllocationResult]) -> dict` returning, per baseline,
  `cost_delta_pct, expected_late_delta_pct, high_risk_share_delta_pp`.

- [ ] **Step 1: Write the failing tests** — each baseline meets demand; `cheapest_first` is never cheaper than
  the optimiser on material cost alone by more than rounding; `compare` returns a finite number for every
  baseline; the optimiser's expected late value is lower than `cheapest_first`'s.
- [ ] **Step 2: Run, fail.** **Step 3: Implement.** **Step 4: Run tests** → PASS.
- [ ] **Step 5: Hand over for commit** — `feat(pr1): allocation baselines and savings comparison`

---

### Task 11: PR1 scenarios

**Files:**
- Create: `apps/pr1/backend/app/scenarios/engine.py`
- Test: `apps/pr1/tests/test_scenarios.py`

**Interfaces:**
- Produces: `engine.SCENARIOS: dict[str, Scenario]` with keys `supplier_outage`, `demand_spike`,
  `lead_time_shock`, `price_shock`; `engine.run(scenario_key, params, request, suppliers, risk)
  -> ScenarioResult(before: AllocationResult, after: AllocationResult, deltas: dict)`.

- [ ] **Step 1: Write the failing tests** — removing the largest supplier still meets demand or reports
  infeasible with a reason; a +30% demand spike raises total cost; a +2-week lead-time shock removes at least
  one supplier from eligibility; every scenario returns both a before and an after.
- [ ] **Step 2: Run, fail.** **Step 3: Implement** as pure transformations of the inputs, then re-solve.
- [ ] **Step 4: Run tests** → PASS. **Step 5:** `docs/modules/pr1-scenarios.md`.
- [ ] **Step 6: Hand over for commit** — `feat(pr1): scenario simulator`

---

### Task 12: PR1 API

**Files:**
- Create: `apps/pr1/backend/app/api/routes.py`, `apps/pr1/backend/app/api/schemas.py`,
  `apps/pr1/backend/app/main.py`
- Test: `apps/pr1/tests/test_api.py`

**Interfaces:**
- Produces these endpoints: `GET /api/health`, `GET /api/suppliers` (filter, sort, paginate),
  `GET /api/materials`, `POST /api/allocate`, `POST /api/risk/score-po`, `GET /api/models/metrics`,
  `POST /api/scenarios/{key}`, `GET /api/kpis`.

- [ ] **Step 1: Write the failing contract tests** with `TestClient`: health returns 200;
  `/api/suppliers?limit=50` returns 50 rows each carrying `origin`; `/api/allocate` with a valid body returns
  lines summing to the requested quantity; an invalid body returns 422; `/api/risk/score-po` returns three
  probabilities between 0 and 1 plus the top three contributing factors.
- [ ] **Step 2: Run, fail.** **Step 3: Implement** with Pydantic models mirroring the optimiser dataclasses.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Hand over for commit** — `feat(pr1): HTTP API`

---

### Task 13: Shared front-end modules and both app shells (plain HTML, CSS, JS)

**Files:**
- Create: `packages/web/tokens.css`, `packages/web/base.css`, `packages/web/table.js`,
  `packages/web/chart.js`, `packages/web/api.js`, `packages/web/format.js`, `packages/web/vendor/chart.min.js`,
  `apps/pr1/web/index.html`, `apps/pr1/web/css/app.css`, `apps/pr1/web/js/main.js`,
  `apps/p2/web/index.html`, `apps/p2/web/css/app.css`, `apps/p2/web/js/main.js`
- Test: `packages/web/tests/table.test.js`, `packages/web/tests/format.test.js`

**No framework and no build step.** Browser-native ES modules, one pinned local copy of Chart.js, and our own
table module. Everything is readable by any team member in the interview.

**Interfaces:**
- Produces:
  `table.js` — `createTable(mountEl, {columns, rows, pageSize=25, onSort, onFilter, rowBadge})` returning
  `{setRows(rows), getState(), destroy()}`; supports click-to-sort, a text filter, pagination and a per-row
  origin badge.
  `chart.js` — `lineChart(canvasEl, {labels, series})`, `barChart(...)`, `stackedBarChart(...)`, thin
  wrappers over Chart.js applying our tokens.
  `api.js` — `get(path)`, `post(path, body)` with error handling and a loading callback.
  `format.js` — `money(n)`, `pct(n)`, `units(n)`, `days(n)`, `week(d)`.
  `tokens.css` — colour, spacing and type scales, `--accent` set per app (deep blue for PR1, amber for P2),
  light and dark via `prefers-color-scheme`.

- [ ] **Step 1: Read the frontend-design skill before writing any CSS.**

- [ ] **Step 2: Write the failing tests**

```javascript
// packages/web/tests/table.test.js
import { test } from "node:test";
import assert from "node:assert";
import { JSDOM } from "jsdom";
import { createTable } from "../table.js";

test("renders one header cell per column and one row per record", () => {
  const dom = new JSDOM(`<div id="m"></div>`);
  global.document = dom.window.document;
  const el = document.getElementById("m");
  createTable(el, { columns: [{key: "a", label: "A"}, {key: "b", label: "B"}],
                    rows: [{a: 1, b: 2}, {a: 3, b: 4}] });
  assert.equal(el.querySelectorAll("thead th").length, 2);
  assert.equal(el.querySelectorAll("tbody tr").length, 2);
});

test("sorting by a column reorders the rows", () => { /* click the header, assert order */ });
test("filtering narrows the rows and shows a count", () => { /* type in the filter, assert */ });
test("paginates at the configured page size", () => { /* 60 rows, pageSize 25 → 25 shown */ });
test("shows the origin badge for non-real rows", () => { /* rowBadge → badge element present */ });
```

- [ ] **Step 3: Run them** — `node --test packages/web/tests` → FAIL, module not found.

- [ ] **Step 4: Implement the shared modules and both shells.** Restrained enterprise craft: one accent
  colour per app, generous spacing, a real type hierarchy, light and dark, motion only where it clarifies.
  Each app's `index.html` holds the nav and a content area; pages are separate HTML files sharing the CSS
  and JS modules.

- [ ] **Step 5: Run the tests** → PASS. Open both apps and confirm the shell renders against a live backend.

- [ ] **Step 6: Write `docs/modules/frontend.md`** — how the modules fit together, why no framework, and how
  to add a page. This is what a team member reads before the interview.

- [ ] **Step 7: Hand over for commit** — `feat(web): shared front-end modules and application shells`

---

### Task 14: PR1 screens — supplier comparison and allocation

**Files:**
- Create: `apps/pr1/web/pages/suppliers.html`, `pages/allocate.html`,
  `js/suppliers.js`, `js/allocate.js`, `js/weights.js`
- Test: `apps/pr1/web/tests/allocate.test.js`

- [ ] **Step 1: Write the failing test** — moving the risk slider refetches and renders a different
  allocation; the savings panel shows all three baselines; synthetic suppliers are visibly marked.
- [ ] **Step 2: Run, fail.** **Step 3: Implement.** Suppliers page: searchable, sortable table over 500+ rows
  with on-time rate, defect rate, lead time, price and risk columns. Allocate page: requirement form, the
  three weight sliders, the resulting split as a stacked bar per material, a line-by-line table with the
  reason text, and the savings-versus-baselines panel.
- [ ] **Step 4: Run `pytest` and `node --test`** → PASS.
- [ ] **Step 5: Hand over for commit** — `feat(pr1): supplier comparison and allocation screens`

---

### Task 15: PR1 screens — pre-PO risk check, scenarios, model panel, narrative

**Files:**
- Create: `apps/pr1/web/pages/risk-check.html`, `pages/scenarios.html`, `pages/models.html`,
  `apps/pr1/web/js/risk-check.js`, `js/scenarios.js`, `js/models.js`,
  `apps/pr1/backend/app/narrative/explain.py`
- Test: `apps/pr1/tests/test_narrative.py`, `apps/pr1/web/tests/riskcheck.test.js`

**Interfaces:**
- Produces: `narrative.explain.explain_allocation(result, suppliers) -> str` and
  `narrative.explain.explain_po_risk(scores, factors) -> str`. Both try the Hugging Face hosted model and
  fall back to a deterministic template; the fallback is what tests assert on.

- [ ] **Step 1: Write the failing tests** — with no token present, `explain_allocation` still returns a
  non-empty string containing the total cost and the supplier count; every number in the template comes from
  the result object, never invented; the risk-check page shows three probabilities and the top factors.
- [ ] **Step 2: Run, fail.** **Step 3: Implement.** The LLM call has a 6-second timeout and any failure falls
  back silently to the template.
- [ ] **Step 4: Run tests** → PASS. **Step 5:** `docs/modules/pr1-narrative.md`.
- [ ] **Step 6: Hand over for commit** — `feat(pr1): risk check, scenarios, model panel and explanations`

---

### Task 16: P2 ETL — real styles plus synthetic launch calendar

**Files:**
- Create: `apps/p2/backend/app/db.py`, `models.py`, `etl/retail.py`, `etl/synthesize.py`
- Test: `apps/p2/tests/test_etl_retail.py`, `apps/p2/tests/test_p2_synthesize.py`

**Interfaces:**
- Produces: `etl.retail.load_weekly_sales(path) -> pd.DataFrame[style_id, store_id, week_start, units,
  price, discount_pct, promo, seasonality, inventory, origin]` — the 20 real Clothing styles aggregated from
  daily to weekly. `etl.synthesize.build_style_catalogue(real, n_styles=60, seed=42) -> pd.DataFrame` with
  `style_id, name, category, season, launch_week, price, cost, target_sell_through, origin` on a 6-week
  launch cadence, and `etl.synthesize.simulate_sales(styles, real, seed=42) -> pd.DataFrame` in the same shape
  as the real weekly sales.

**Also produces:** `etl.network.build_network(sales, seed=42) -> tuple[pd.DataFrame, pd.DataFrame,
pd.DataFrame]` — `dcs[dc_id, region]`, `stores[store_id, region, dc_id]` and
`dc_store_lanes[dc_id, store_id, transit_days, cost_per_unit, mode]`, one DC per region, transit days and
cost scaled by distance band. Used by the logistics view and by store availability dates.

- [ ] **Step 1: Write the failing tests** — weekly aggregation preserves total units; there are exactly 20
  real styles; every store maps to exactly one DC and every lane has a positive transit time and cost; the catalogue holds about 60 styles across three seasons with launches 6 weeks apart;
  synthetic weekly sales reproduce the real seasonality correlation within 0.2; generation is deterministic.
- [ ] **Step 2: Run, fail.** **Step 3: Implement.** **Step 4: Run tests** → PASS.
- [ ] **Step 5:** `docs/modules/p2-etl.md` plus new rows in `docs/assumptions.md`.
- [ ] **Step 6: Hand over for commit** — `feat(p2): retail sales ETL and style catalogue`

---

### Task 17: P2 demand forecast and cold start

**Files:**
- Create: `apps/p2/backend/app/forecast/model.py`, `forecast/coldstart.py`, `forecast/baselines.py`
- Test: `apps/p2/tests/test_forecast.py`, `apps/p2/tests/test_coldstart.py`

**Interfaces:**
- Produces: `forecast.model.train(sales) -> ForecastModel` with `.predict(style_id, weeks) -> pd.DataFrame`
  and `.metrics: dict` containing `wape`, `mape`, `bias`, plus `wape_seasonal_naive` and
  `wape_dataset_baseline` (the file's own `Demand Forecast` column).
  `forecast.coldstart.forecast_new_style(style, analogs, method: Literal["analog","chronos"] = "analog")
  -> pd.DataFrame`. **Analog is the primary method and the shipped default**: a weighted average of styles in
  the same category, price band and season, shaped by the observed launch curve. Chronos-Bolt is a benchmark
  run only, scored on the same held-out style, and is skipped without failure if the model cannot be loaded.

- [ ] **Step 1: Write the failing tests** — the model beats seasonal naive on WAPE for the real styles; the
  split is chronological; the analog method returns a value for every requested week without any network
  access; analog, Chronos and a category-average baseline are all scored against the held-out style's real
  sales; and if Chronos cannot be loaded the analog forecast is still returned and the failure is recorded,
  not raised.
- [ ] **Step 2: Run, fail.** **Step 3: Implement** LightGBM with lag, rolling, price, discount, promotion and
  seasonality features; Chronos-Bolt small via `transformers`/`chronos-forecasting`, cached locally.
- [ ] **Step 4: Run tests** → PASS. Record the real numbers in the module guide, whatever they are.
- [ ] **Step 5:** `docs/modules/p2-forecast.md`. **Step 6:** commit — `feat(p2): demand forecast and cold start`

---

### Task 17b: P2 inventory and safety stock

**Files:**
- Create: `apps/p2/backend/app/inventory/safety_stock.py`, `apps/p2/backend/app/inventory/position.py`
- Test: `apps/p2/tests/test_safety_stock.py`

**Interfaces:**
- Consumes: forecast output and its residuals (Task 17), weekly sales with the inventory column (Task 16).
- Produces:
  `safety_stock.compute(forecast_errors, lead_time_weeks, service_level=0.95) -> pd.DataFrame[style_id,
  store_id, sigma_error, safety_stock, service_level, z]`,
  `safety_stock.reorder_point(mean_weekly_demand, lead_time_weeks, safety_stock) -> float`,
  `position.build(sales, safety_stock_df, forecast) -> pd.DataFrame[style_id, store_id, on_hand,
  weeks_of_cover, reorder_point, target_stock, gap_units, flag]` where `flag` is one of
  `stockout_risk | below_reorder | healthy | overstock`.

- [ ] **Step 1: Write the failing tests**

```python
def test_safety_stock_rises_with_service_level():
    low = compute(errors, lead_time_weeks=4, service_level=0.90)
    high = compute(errors, lead_time_weeks=4, service_level=0.99)
    assert (high.safety_stock >= low.safety_stock).all()

def test_safety_stock_rises_with_lead_time():
    short = compute(errors, lead_time_weeks=1)
    long = compute(errors, lead_time_weeks=9)
    assert (long.safety_stock > short.safety_stock).all()

def test_zero_forecast_error_needs_no_safety_stock():
    out = compute(zero_error_frame, lead_time_weeks=4)
    assert (out.safety_stock == 0).all()

def test_reorder_point_equals_lead_time_demand_plus_safety_stock():
    assert reorder_point(100, 4, 250) == 650

def test_position_flags_are_assigned_correctly():
    pos = position.build(sales, ss, forecast)
    assert set(pos.flag.unique()) <= {"stockout_risk", "below_reorder", "healthy", "overstock"}
    assert (pos.loc[pos.on_hand == 0, "flag"] == "stockout_risk").all()
```

- [ ] **Step 2: Run them, watch them fail.**

- [ ] **Step 3: Implement.** Safety stock is `z · σ_error · sqrt(lead_time_weeks)`, where σ_error is the
  standard deviation of that style-store's forecast residuals on the test period and `z` comes from the
  normal inverse CDF of the service level. Weeks of cover is on-hand divided by mean forecast demand.
  Flags: `stockout_risk` when on-hand is zero or cover is under one week, `below_reorder` when on-hand is
  under the reorder point, `overstock` when cover exceeds twice the target, otherwise `healthy`.

- [ ] **Step 4: Run the tests** → PASS.

- [ ] **Step 5: Write `docs/modules/p2-inventory.md`** — the formula in words, why safety stock grows with the
  square root of lead time, and what each flag means. This is a likely interview question.

- [ ] **Step 6: Hand over for commit** — `feat(p2): inventory position and safety stock`

---

### Task 18: P2 production plan and fabric lot sizing

**Files:**
- Create: `apps/p2/backend/app/production/plan.py`, `apps/p2/backend/app/fabric/lotsize.py`
- Test: `apps/p2/tests/test_production.py`, `apps/p2/tests/test_fabric.py`

**Interfaces:**
- Consumes: safety-stock targets from Task 17b.
- Produces: `production.plan.build_plan(forecast, capacity, fabric_arrivals, safety_stock) -> ProductionPlan` with
  `.lines`, `.shortfalls`, `.capacity_utilisation`, solved as an LP minimising lost sales plus holding cost.
  `fabric.lotsize.order_plan(requirements, moq, lead_time_weeks, holding_cost) -> list[FabricOrder]`
  using Wagner-Whitin style dynamic lot sizing — **single source, no supplier choice**.

- [ ] **Step 1: Write the failing tests** — production never exceeds weekly capacity; the plan covers demand
  plus the safety-stock target where capacity allows; a deliberate capacity squeeze produces a non-empty
  `shortfalls` list; every fabric order is at or above MOQ; every order is
  placed at least `lead_time_weeks` before the week it covers; with zero holding cost the plan orders
  lot-for-lot subject to MOQ.
- [ ] **Step 2: Run, fail.** **Step 3: Implement.** **Step 4: Run tests** → PASS.
- [ ] **Step 5:** `docs/modules/p2-supply.md`, stating in its first paragraph that this module makes no
  supplier choice and why. **Step 6:** commit — `feat(p2): production plan and fabric lot sizing`

---

### Task 19: P2 markdown recommendation

**Files:**
- Create: `apps/p2/backend/app/markdown/elasticity.py`, `apps/p2/backend/app/markdown/recommend.py`
- Test: `apps/p2/tests/test_markdown.py`

**Interfaces:**
- Produces: `elasticity.fit(sales) -> dict[str, float]` — one elasticity per category, fitted on the real
  discount-versus-units data; `recommend.markdown_plan(style, sales_to_date, elasticity, target_sell_through)
  -> MarkdownRecommendation(week, depth_pct, projected_sell_through, margin_vs_no_markdown,
  margin_vs_end_of_season)`.

- [ ] **Step 1: Write the failing tests** — fitted elasticity is negative for every category (discounts raise
  units); a style already tracking above target gets no markdown; a slow seller gets one, earlier and deeper
  the further it is behind; recommended depth stays within the observed 0–20% range; both margin comparisons
  are populated.
- [ ] **Step 2: Run, fail.** **Step 3: Implement** — log-log regression for elasticity, then a small grid
  search over week and depth maximising projected margin.
- [ ] **Step 4: Run tests** → PASS. **Step 5:** `docs/modules/p2-markdown.md`.
- [ ] **Step 6:** commit — `feat(p2): markdown timing and depth recommendation`

---

### Task 20: P2 reconciliation, rolling S&OP cycle, versions and financials

**Files:**
- Create: `apps/p2/backend/app/sop/merchandising.py`, `sop/reconcile.py`, `sop/cycle.py`, `sop/versions.py`,
  `sop/financials.py`, `sop/distribution.py`
- Test: `apps/p2/tests/test_reconcile.py`, `apps/p2/tests/test_sop.py`,
  `apps/p2/tests/test_distribution.py`

**Interfaces:**
- Produces:
  `merchandising.build_plan(forecast, styles, seed=42) -> pd.DataFrame[style_id, week, merch_units,
  ambition_factor]` — the buyers' intent, the statistical forecast shifted by each style's commercial
  ambition and its season target.
  `reconcile.build(merch_plan, forecast, supply_plan) -> pd.DataFrame[style_id, week, merch_units,
  forecast_units, supply_units, gap_units, gap_value, consensus_units]` — consensus defaults to
  `min(merch, supply)` and is editable at the Pre-S&OP stage.
  `distribution.store_availability(supply_plan, lanes) -> pd.DataFrame[style_id, store_id, week_produced,
  week_available, transit_days, distribution_cost]`.
  `cycle.STAGES = ("demand_review", "supply_review", "pre_sop", "executive_approval")`;
  `cycle.run_rolling(months: int = 3, horizon_weeks: int = 13) -> list[Cycle]`;
  `cycle.advance(plan_id, stage, actor, note) -> PlanVersion`;
  `versions.create(...) -> PlanVersion`; `versions.compare(a_id, b_id) -> dict`;
  `financials.roll_up(plan) -> dict[revenue, gross_margin, margin_pct, inventory_value, lost_sales_value,
  distribution_cost]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_three_plans_are_reconciled_and_the_gap_is_explicit():
    rec = reconcile.build(merch_plan, forecast, supply_plan)
    assert {"merch_units", "forecast_units", "supply_units", "gap_units", "consensus_units"} <= set(rec.columns)
    assert (rec.gap_units == rec.merch_units - rec.supply_units).all()

def test_consensus_never_promises_more_than_supply_allows():
    rec = reconcile.build(merch_plan, forecast, supply_plan)
    assert (rec.consensus_units <= rec.supply_units + 1e-6).all()

def test_merchandising_plan_differs_from_the_statistical_forecast():
    # otherwise there is nothing to reconcile
    assert (merch_plan.merch_units != forecast.forecast_units).mean() > 0.5

def test_rolling_cycle_produces_one_set_of_versions_per_month():
    cycles = cycle.run_rolling(months=3, horizon_weeks=13)
    assert len(cycles) == 3
    assert all(len(c.versions) == 4 for c in cycles)
    assert cycles[1].start_week > cycles[0].start_week      # the horizon rolls forward

def test_stages_advance_only_in_order():
    ...

def test_store_availability_adds_transit_time():
    av = distribution.store_availability(supply_plan, lanes)
    assert (av.week_available >= av.week_produced).all()
    assert (av.week_available - av.week_produced == (av.transit_days / 7).apply(math.ceil)).all()

def test_financial_roll_up_matches_hand_computed_fixture():
    ...
```

- [ ] **Step 2: Run, fail.** **Step 3: Implement.** **Step 4: Run tests** → PASS.
- [ ] **Step 5:** `docs/modules/p2-sop.md`, covering reconciliation, the rolling cycle, the three functional
  views and how distribution affects store availability.
- [ ] **Step 6:** commit — `feat(p2): reconciliation, rolling S&OP cycle, versions and financials`

---

### Task 21: P2 API and screens

**Files:**
- Create: `apps/p2/backend/app/api/routes.py`, `schemas.py`, `main.py`,
  `apps/p2/web/pages/cockpit.html`, `pages/reconcile.html`, `pages/merchandising.html`,
  `pages/production.html`, `pages/logistics.html`, `pages/inventory.html`, `pages/markdown.html`,
  `pages/versions.html`, plus one JS module per page under `apps/p2/web/js/`, `apps/p2/backend/app/narrative/explain.py`
- Test: `apps/p2/tests/test_api.py`, `apps/p2/web/tests/cockpit.test.js`

**Interfaces:**
- Endpoints: `GET /api/health`, `GET /api/styles`, `GET /api/forecast/{style_id}`, `POST /api/plan/run`,
  `GET /api/reconciliation`, `POST /api/reconciliation/consensus`, `GET /api/inventory`,
  `GET /api/logistics/availability`, `POST /api/plan/{id}/advance`, `GET /api/plan/{id}`,
  `GET /api/plan/compare`, `GET /api/cycles`, `GET /api/markdown`, `GET /api/financials/{plan_id}`,
  `GET /api/models/metrics`.

- [ ] **Step 1: Write the failing contract and component tests** — running a plan returns a version id; the
  cockpit shows the four stages with the current one highlighted, the demand-versus-supply gap chart, and the
  financial tiles; advancing a stage updates the UI.
- [ ] **Step 2: Run, fail.** **Step 3: Implement,** reusing the shared `packages/web` modules with the amber accent.
- [ ] **Step 4: Run `pytest` and `node --test`** → PASS.
- [ ] **Step 5:** commit — `feat(p2): API and planning screens`

---

### Task 22: Deployment of both apps

**Files:**
- Create: `apps/pr1/Dockerfile`, `apps/p2/Dockerfile`, `.github/workflows/deploy.yml`,
  `docs/runbook.md`
- Test: `tests/test_dockerfiles.py`

- [ ] **Step 1: Write the failing test** — each Dockerfile is a single Python stage that copies the backend
  and the static `web/` folder, exposes port 7860 (the Hugging Face Spaces default) and ends with a `CMD`
  running uvicorn.
- [ ] **Step 2: Run, fail.** **Step 3: Write the Dockerfiles** and a FastAPI static-file mount serving the
  the app's static `web/` folder at `/`.
- [ ] **Step 4: Create the two Spaces** under `Nouman-20` and push. Verify both URLs answer on `/api/health`
  and render the UI.
- [ ] **Step 5: Add the deploy workflow,** triggered on pushes to `main` after CI passes, using `HF_TOKEN`
  from repository secrets.
- [ ] **Step 6: Write `docs/runbook.md`** — how to run each app locally, how to rebuild the data, what to do
  if a Space is asleep during the demo, and the offline fallback procedure.
- [ ] **Step 7:** commit — `feat: containerise and deploy both applications`

---

### Task 22b: Monitoring and real-time evidence

**Files:**
- Create: `packages/pyshared/telemetry.py`, `apps/pr1/backend/app/api/monitoring.py`,
  `apps/p2/backend/app/api/monitoring.py`, `docs/modules/monitoring.md`
- Test: `tests/test_telemetry.py`

**Interfaces:**
- Produces: `telemetry.timed(name)` — a context manager recording duration; `telemetry.snapshot() -> dict`
  with `requests`, `errors`, `p50_ms`, `p95_ms` per endpoint. Both apps expose `GET /api/monitoring`.
  Every optimiser and planner response already carries `solve_seconds`, which the UI prints beside the result.

- [ ] **Step 1: Write the failing tests** — the snapshot counts a request and records a duration; p95 is at
  least p50; an endpoint that raises increments the error count; `solve_seconds` appears in the allocate and
  plan responses.
- [ ] **Step 2: Run, fail.** **Step 3: Implement** as FastAPI middleware plus an in-memory ring buffer.
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Add the panel** to both apps: model metrics, drift, request latency, error rate.
- [ ] **Step 6:** commit — `feat: monitoring panel and response timing`

---

### Task 23: Teaching kit, judging documents and demo preparation

**Files:**
- Create: `docs/interview-prep.md`, `docs/demo-script.md`, `docs/architecture.md`, `docs/alternatives.md`,
  `docs/reusability.md`, `docs/estimate-and-roadmap.md`, `README.md` (rewrite)
- Modify: every `docs/modules/*.md` for consistency

**Extra steps for the criteria we would otherwise miss:**

- [ ] **Write `docs/alternatives.md`** — for each major choice, what we picked, what we rejected and why:
  PuLP versus OR-Tools versus a greedy heuristic; XGBoost versus logistic regression versus a neural network;
  SQLite versus Postgres; plain HTML/CSS/JS versus React versus Streamlit, and why we chose no framework;
  one repository with two apps versus two repositories;
  hosted inference versus a local LLM. "Alternatives considered" is explicitly on the judging list.
- [ ] **Write `docs/estimate-and-roadmap.md`** — effort in person-days per module as actually spent, what a
  production build would additionally need (authentication, a real database, an ERP connector, retraining
  pipelines, alerting), and a three-phase roadmap with rough timelines. This is a listed deliverable.
- [ ] **Write `docs/reusability.md`** — what is reusable, what is specific, and what an adopter changes.

- [ ] **Step 1: Write `docs/architecture.md`** with two diagrams: what we built (data sources, modules, API,
  UI, per app), and the target enterprise integration — ERP or SAP, scheduled extract or API, validation,
  planning engine, planner approval, output back to ERP — labelled clearly as the production path we did not
  build. Our API layer is marked as the attachment point.
- [ ] **Step 2: Write `docs/interview-prep.md`** — for each module: what it does, why we chose this method,
  what we would do differently with more time, and five likely panel questions with answers. Include the real
  measured metrics, not aspirational ones.
- [ ] **Step 3: Write `docs/demo-script.md`** — two scripts of about four minutes each, with the exact click
  path, the numbers to quote, and the recovery step if something fails.
- [ ] **Step 4: Rewrite `README.md`** — what the two apps are, the separation rule, how to run them, the data
  sources with licences, the measured results, and the team.
- [ ] **Step 5: Run the whole suite** (`ruff check`, `pytest`, `node --test`) and record the
  results in the runbook.
- [ ] **Step 6:** commit — `docs: architecture, interview preparation and demo scripts`

---

### Task 24: Demo pack — pre-trained artifacts, frozen seeds, preloaded scenarios

**Files:**
- Create: `scripts/build_demo_pack.py`, `apps/pr1/backend/app/demo/scenarios.py`,
  `apps/p2/backend/app/demo/scenarios.py`, `docs/demo-checklist.md`
- Modify: both apps' model loading to read saved artifacts rather than training on startup
- Test: `tests/test_demo_pack.py`

**Interfaces:**
- Produces: `build_demo_pack.main()` which trains every model once, writes
  `models/<app>/<name>.joblib` plus `models/<app>/<name>.metrics.json`, and writes
  `data/processed/<app>.sqlite`; `scenarios.PRELOADED: dict[str, Scenario]` with a clean baseline and a
  disruption case per app; `demo.verify() -> dict` confirming every artifact is present and loadable.

- [ ] **Step 1: Write the failing tests**

```python
def test_no_model_is_trained_at_request_time():
    src = list((ROOT / "apps").rglob("app/api/*.py"))
    for f in src:
        text = f.read_text(encoding="utf-8")
        assert ".fit(" not in text, f"{f} trains a model inside the API layer"

def test_demo_pack_produces_every_artifact():
    build_demo_pack.main()
    assert verify()["missing"] == []

def test_results_are_reproducible_across_runs():
    a = solve(PRELOADED["baseline"]); b = solve(PRELOADED["baseline"])
    assert a.total_cost == b.total_cost
    assert [l.qty for l in a.lines] == [l.qty for l in b.lines]

def test_each_app_preloads_a_baseline_and_a_disruption_scenario():
    assert {"baseline", "disruption"} <= set(PRELOADED)

def test_scenario_inputs_can_change_without_retraining():
    r = solve(PRELOADED["baseline"].with_weights(risk=1.0))
    assert r.status == "optimal"
```

- [ ] **Step 2: Run them, watch them fail.**
- [ ] **Step 3: Implement.** Every random seed pinned at 42 and set in one place per app; models saved with
  joblib alongside their metrics; the API loads artifacts at startup and fails loudly with a clear message if
  one is missing.
- [ ] **Step 4: Run the tests** → PASS.
- [ ] **Step 5: Write `docs/demo-checklist.md`** — the pre-demo run-through: rebuild the pack, start both
  apps offline, click the two scenarios in each, confirm solve times appear, confirm the Spaces are awake.
  Run it on 27 September and again on the morning of the 28th.
- [ ] **Step 6:** commit — `feat: demo pack with pre-trained artifacts and preloaded scenarios`

---

## Coverage of the official use-case document

| Official requirement (source page) | Task |
|---|---|
| PR1: allocate volumes efficiently (p9) | 9 |
| PR1: minimise cost while meeting demand (p9) | 9, 10 |
| PR1: reduce dependency on high-risk suppliers (p9) | 9 (risk penalty, concentration cap), 10 |
| PR1: incorporate quality and delivery performance (p9) | 7, 8, 9 |
| PR1: scenario analysis for disruptions and demand spikes (p9) | 11 |
| PR1: predict delivery delays before PO release (p9) | 7, 12, 15 |
| PR1 data: demand forecast by SKU/plant (p9) | 5b |
| PR1 data: approved supplier list (p9) | 5b |
| PR1 data: capacity, lead times, prices, OTD, quality, contracts (p9) | 3, 4, 5 |
| P2: reconcile merchandising forecasts with capacity and fabric lead times (p10) | 20 |
| P2: rolling monthly S&OP cycle over sales, production and inventory (p10) | 17b, 18, 20 |
| P2: markdown timing from in-season sell-through (p10) | 19 |
| P2: optimise fabric procurement against MOQ and lead time (p10) | 18 |
| P2: cross-functional alignment across Merchandising, Production, Logistics (p10) | 20, 21 |
| P2 data: DC-to-store transport and lead times (p10) | 16, 20 |
| P2 data: styles, plant capacity, fabric lead times and MOQs, sell-through history (p10) | 16 |
| Judging: architecture and alternatives considered (p5) | 23 |
| Judging: UI and UX, ease of navigation, visual appeal (p4) | 13, 14, 15, 21 |
| Judging: breadth of sample data (p5) | 3, 4, 5, 16 |
| Judging: model accuracy, precision, recall, F1 (p4) | 7, 8, 17 |
| Judging: CI/CD, cloud deployment, API integration (p4) | 1, 12, 21, 22 |
| Judging: real-time decisions (p5) | 22b |
| Judging: process of monitoring (p5) | 22b |
| Judging: reusability (p5) | 23 |
| Judging: ease of implementation (p5) | every module guide, plus 23 |
| Deliverable: estimation of development and roadmap (p6) | 23 |
| Deliverable: documentation (p6) | every task's guide, consolidated in 23 |
| Deliverable: user interface (p6) | 13, 14, 15, 21 |
| Deliverable: PPT and presentation (p6) | deferred by team decision until the apps are built |

## Self-review against the spec

- Separation rule → Task 1 test, Tasks 18 and 23 documentation.
- Hundreds of suppliers → Tasks 4 and 5 (2,590-vendor master, 520 supplier entities).
- Three risk targets → Tasks 7 and 8.
- All constraint families from reply 4 → Task 9.
- Cost, risk and supplier performance in the allocation → Tasks 9 and 10.
- Scenario analysis → Task 11.
- Predict delays before PO release → Tasks 7 and 15 (`/api/risk/score-po`).
- P2 forecast, cold start, markdown, capacity, MOQ and lead time, S&OP cycle, financials → Tasks 16 to 21.
- Real plus synthetic data with labelled origin → Tasks 5 and 16.
- Deployment and CI/CD → Tasks 1 and 22.
- Monitoring → Task 12 (`/api/models/metrics`) and the model panel in Task 15.
- Documentation and interview readiness → every task's guide, consolidated in Task 23.
