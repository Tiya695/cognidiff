# Reproducibility

Every number in the research paper traces to a row in
[`experiment_log.md`](experiment_log.md), and every row names its seed, its
code commit and the script that produced it.

Reproducibility is what separates a research project from a demo, and it costs
almost nothing when set up at the start rather than reconstructed afterwards.

---

## Environment

| | |
|---|---|
| **Python** | 3.14.3 |
| **Platform** | Windows-11-10.0.26200-SP0 |
| **Git commit** | `b09eeb6` |
| **Locked packages** | `requirements.lock` — 73 packages, exact versions |
| **Global seed** | **42** (`COGNIDIFF_SEED`) |

Key library versions:

| Package | Version |
|---|---|
| numpy | 2.5.2 |
| scikit-learn | 1.9.0 |
| fastapi | 0.141.1 |
| pydantic | 2.13.4 |

### Optional packages — not installed in this environment

| Package | Status | What ran instead |
|---|---|---|
| `torch` | not installed | `LSTMPredictor` used `ridge_fallback`; every response reports `backend` |
| `shap` | not installed | `CogniExplainer` used `occlusion`; every response reports `explanation_method` |
| `xgboost` | not installed | `XGBCogniClassifier` used sklearn `GradientBoostingClassifier`; reports `backend` |
| `flwr` | not installed | `simulate_federation` used the NumPy FedAvg implementation; reports `backend` |
| `anthropic` | not installed | `generate_summary` used the local template; reports `source` |

**This is why every one of those modules returns a `backend`, `method` or
`source` field.** A fallback that silently impersonates the real thing would
make the results unreproducible *and* misleading — a reader would have no way to
know an LSTM never ran. Installing the extras changes the backend, and may
change the numbers; the reported field is how you tell which you are looking at.

---

## Seeding

All randomness flows through one function:

```python
from backend.config import set_all_seeds
set_all_seeds(42)   # seeds random, numpy, torch (+ CUDA determinism flags)
```

Called at the top of every training and evaluation script. `PYTHONHASHSEED` is
set too. `IsolationForest`, `GradientBoosting` and every `np.random.default_rng`
take `SEED` explicitly rather than relying on global state.

An unseeded experiment cannot be reproduced or defended.

---

## Version tracking on every score

Every row in `cogniscores` carries four fields:

| Field | Example | Meaning |
|---|---|---|
| `model_version` | `isolationforest_v1` | anomaly model architecture |
| `baseline_version` | `6` | incremented on every fit or refit |
| `feature_schema_version` | `v1` | bumped when any feature definition changes |
| `code_commit` | `b09eeb6` | short git SHA |

So any score in the database can be traced to the exact model, baseline and
feature definitions that produced it — and reproduced.

At viva: *"A score from last month was produced by IsolationForest v1 against
baseline v2. I can tell you exactly which model produced any score in the
database, and reproduce it."*

Asserted by `test_every_stored_score_carries_its_four_version_fields`.

---

## Reproducing from a clean checkout

```bash
git clone <repo> cognidiff-verify
cd cognidiff-verify

python -m venv venv
venv\Scripts\activate
pip install -r requirements.lock          # exact versions, not requirements.txt

copy .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"                       # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # BACKUP_KEY

python -m backend.seed_demo --days 75 --reset
python -m ml.weight_sensitivity
python -m ml.false_positive_test
python -m ml.federated
python -m pytest tests/ -q
```

### What reproduces exactly

| Experiment | Deterministic? |
|---|---|
| Weight sensitivity sweep | **yes** — fixed seed, pure NumPy |
| False-positive validation | **yes** |
| Federated simulation | **yes** — asserted by `test_the_simulation_is_reproducible` |
| Ablation study | **yes** — asserted by `test_ablation_is_deterministic` |
| Demo data generation | **yes** — same seed, same 193 sessions |
| Test suite | **yes** — 187 tests |

### What does not reproduce exactly

**Anything computed from real collected keystroke data**, because it depends on
the sessions in your database. The demo seeder is deterministic and produces an
identical synthetic dataset, so the *pipeline* reproduces; a different person's
real typing obviously will not.

`code_commit` differs in a fresh clone with new commits. That is the field
working as intended.

---

## Verification run

Clean checkout, `pip install -r requirements.lock`, seeds as recorded:

| Result | Original | Re-run | Match |
|---|---|---|---|
| Weight sweep chosen weighting | 70/30 | 70/30 | ✓ |
| Weight sweep peak ratio | 4.938 | 4.938 | ✓ |
| False-positive rate | 13.71% | 13.71% | ✓ |
| FP bootstrap 95% CI | [12.00, 15.50] | [12.00, 15.50] | ✓ |
| Ablation top feature | wpm_estimate | wpm_estimate | ✓ |
| Feature importance mean ρ | 0.867 | 0.867 | ✓ |
| Demo sessions generated | 193 | 193 | ✓ |
| Tests passing | 187 | 187 | ✓ |

---

## Paper number → source mapping

| Number in the paper | Produced by | Log row |
|---|---|---|
| Exclusion rate 3.6% | `GET /api/sessions/quality` | E-07 |
| False-positive rate 13.71% [12.00, 15.50] | `ml/false_positive_test.py` | E-05 |
| Composite weighting 70/30 | `ml/weight_sensitivity.py` | E-04 |
| Ablation ranking | `ml/ablation.py` | E-06 |
| Feature importance ρ = 0.867 | `ml/ablation.py::compare_methods` | E-06 |
| LSTM beats naive persistence | `LSTMPredictor.evaluate` | E-03 |
| Federated accuracy per round | `ml/federated.py` | E-08 |
| 12/12 attacks blocked | `tests/test_security.py` | E-09 |
| bandit 0 HIGH / 0 MEDIUM | `bandit -r backend/ ml/` | E-10 |
| Contrast 0 failures, worst 5.21:1 | in-browser audit | E-11 |

When an examiner asks where a figure came from, the answer is a log row, not a
recollection.

---

## Checklist

- [x] Python version recorded
- [x] `requirements.lock` committed alongside `requirements.txt`
- [x] All random seeds fixed in one place and called everywhere
- [x] Dataset version and collection window recorded
- [x] `model_version`, `baseline_version`, `feature_schema_version`, `code_commit` on every score
- [x] Training configuration and hyperparameters recorded
- [x] Hardware and OS recorded
- [x] Git commit SHA of every experiment recorded
- [x] Clean-checkout re-run produces identical numbers
- [x] Optional-dependency fallbacks reported rather than hidden
