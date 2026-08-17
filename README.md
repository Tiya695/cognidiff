<div align="center">

# CogniDiff

**Privacy-preserving early cognitive change detection**

Chrome extension · Keystroke dynamics · ML pipeline · Security hardened · CogniScore dashboard

</div>

---

CogniDiff watches the *rhythm* of your typing — how long keys are held, the gaps
between them, how often you delete and retype — and measures how far today drifts
from your own established baseline.

It never reads what you type. `event.key` is touched on exactly one line, to
bucket the key into one of five categories, and the character is discarded on the
next. The server then refuses any batch containing anything other than those five
category codes, so the guarantee holds even if the extension is changed.

> **CogniDiff detects deviation from an individual's own typing baseline. It does
> not detect, diagnose or confirm cognitive decline, and no clinical sensitivity
> or specificity is claimed because no clinically labelled data was used.**

---

## Quick start

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

```bash
copy .env.example .env
```

Generate the two secrets and paste them into `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Seed a demonstrable instance — 75 days of synthetic sessions, a fitted baseline,
scored history, and a clinician account with consent already granted:

```bash
python -m backend.seed_demo --days 75 --reset
```

Start the API:

```bash
uvicorn backend.main:app --reload --port 8000
```

Start the web app in a second terminal:

```bash
python -m http.server 3000 --directory frontend
```

Open **http://localhost:3000**.

| Role | Username | Password |
|---|---|---|
| User | `tiya` | `cognidiff2026` |
| Doctor | `dr.mehta` | `cognidiff2026` |

*(Demo credentials only. They exist in `backend/seed_demo.py` and nowhere else.)*

### The Chrome extension

1. `chrome://extensions` → enable **Developer mode**
2. **Load unpacked** → select the `extension/` folder
3. Click the icon, read the privacy notice, turn monitoring **on** — it is off by
   default, because consent precedes capture
4. Type on an allowlisted site; batches appear every 60 seconds

---

## What is here

```
extension/     Chrome MV3 — timing capture, consent popup, allowlist, data controls
backend/       FastAPI + SQLite — features, quality gate, scoring, auth, RBAC, audit
ml/            baseline · IsolationForest · LSTM · SHAP · XGBoost · drift · ablation · federated
frontend/      landing page, dashboard, mini-tasks, clinician report (no build step)
tests/         187 tests, including all twelve attacker simulations
docs/          feature definitions, audits, evaluation protocol, paper
```

### The web app

**Landing page** — a seven-state WebGL particle brain the reader scrolls through,
from `> ARRIVAL` to `> SUMMARY`. Roughly 90,000 points sampled onto a folded
cortical surface, rejection-biased toward the gyral crowns so the convolutions
read as filaments rather than grain. Camera, morph and highlight state are driven
by GSAP ScrollTrigger.

**Dashboard** — animated CogniScore ring with confidence band, alert banner,
7/30-day trend charts, the three changes that moved the score in plain English,
a Claude-written daily summary, data-quality statistics with exclusion reasons,
an optional context form, consent management and the full access log.

**Task assessment** — four cognitive mini-tasks (word recall, reaction time,
pattern memory, letter scramble) blended into the score at 70/30.

**Clinician report** — consent-gated, printable, with a 90-day trend, deviating
features, the consent record and a prominent disclaimer.

---

## Running things

```bash
python -m pytest tests/ -q                              # 187 tests
python -m pytest tests/ --cov=backend --cov=ml          # coverage
python -m pytest tests/test_security.py -v              # the twelve attacks
```

```bash
python -m ml.weight_sensitivity      # composite weighting sweep
python -m ml.false_positive_test     # false-positive validation
python -m ml.federated               # federated learning simulation
python -m backend.backup create      # encrypted backup
python -m backend.backup verify      # restore test
```

```bash
python -m pip_audit                  # dependency CVEs
python -m bandit -r backend/ ml/     # static analysis
```

---

## Results

| | |
|---|---|
| Tests | **187 passing** |
| Attacker simulations | **12 / 12 blocked** |
| `bandit` | **0 HIGH, 0 MEDIUM** across 4,895 LOC |
| `pip-audit` | 1 finding, accepted and documented (unreachable code path) |
| Session false-positive rate | **13.71%** (95% CI 12.00–15.50) |
| Week-level escalation on normal data | **0.0%** |
| Data-quality exclusion rate | **3.6%** |
| Feature-importance agreement | Spearman ρ = **0.867** across three methods |
| Accessibility | **0 contrast failures**, worst 5.21:1 |

---

## Design decisions worth knowing

**The baseline is fitted on the first fortnight and never continuously refitted.**
A baseline that follows the data absorbs whatever change is happening and
redefines it as normal — which makes gradual decline undetectable by
construction. During development, fitting over all data scored a visibly
degraded period at 93.9/100 "stable"; with a fixed window the same data scored
16.2 "declining".

**A session is flagged only when two models agree.** The statistical baseline and
the IsolationForest fail in different ways, so requiring both means neither
model's characteristic false positive can raise a flag alone.

**Alerts escalate on persistence, not on a bad day.** Cognitive performance
varies with sleep, stress and illness. Only a declining 30-day trend combined
with repeated anomalies recommends professional evaluation.

**Environmental drift is separated from unexplained drift.** A device change puts
the user into a recalibration window with alerts suppressed. A gradual shift with
no environmental cause is left alone — that is the signal the tool exists to
find.

**No endpoint takes a caller-supplied user ID.** Identity comes from a signed
token, so IDOR is eliminated structurally rather than by a check.

**ADMIN has no access to health data.** Internal misuse is a real threat model.

**Nothing is loaded from a CDN.** Every library is vendored with a recorded
SHA-384. There is no third-party host in the request path and the app works
offline.

---

## Documentation

| Document | What it covers |
|---|---|
| [`feature_definitions.md`](docs/feature_definitions.md) | every feature: formula, units, range, rationale |
| [`data_flow_audit.md`](docs/data_flow_audit.md) | every step from keydown to dashboard |
| [`privacy_architecture.md`](docs/privacy_architecture.md) | what is protected, and the threat model's gaps |
| [`attacker_simulation_results.md`](docs/attacker_simulation_results.md) | twelve attacks, requests and responses |
| [`dependency_audit.md`](docs/dependency_audit.md) | pip-audit, bandit, production hardening |
| [`incident_response.md`](docs/incident_response.md) | seven steps, dry-run recorded |
| [`backup_recovery.md`](docs/backup_recovery.md) | retention, restore test, deletion-vs-backup policy |
| [`evaluation_protocol.md`](docs/evaluation_protocol.md) | metrics fixed before experiments |
| [`ground_truth_strategy.md`](docs/ground_truth_strategy.md) | the three label layers and the claim boundary |
| [`ablation_results.md`](docs/ablation_results.md) | feature contribution, three-method convergence |
| [`false_positive_test.md`](docs/false_positive_test.md) | false-alarm validation |
| [`drift_validation.md`](docs/drift_validation.md) | environmental vs unexplained change |
| [`weight_sensitivity.md`](docs/weight_sensitivity.md) | why 70/30, with the table |
| [`accessibility_test.md`](docs/accessibility_test.md) | contrast, keyboard, screen reader, print |
| [`reproducibility.md`](docs/reproducibility.md) | seeds, versions, clean-checkout re-run |
| [`experiment_log.md`](docs/experiment_log.md) | one row per run; every paper number traces here |
| [`research_paper.md`](docs/research_paper.md) | the write-up |
| [`extension_notes.md`](docs/extension_notes.md) | Chrome extension architecture |

---

## Optional extras

The core install runs everything. These enable the full research pipeline; each
module reports which backend actually ran, so a fallback never impersonates the
real thing.

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

```bash
pip install shap xgboost flwr anthropic
```

Without `anthropic` (or `ANTHROPIC_API_KEY`), daily summaries come from a local
template and say so.

---

## Production

```bash
set ENV=production
```

Turns off Swagger, ReDoc and the OpenAPI schema, enables HSTS, and refuses to
start without a real `SECRET_KEY`. Run `uvicorn` **without** `--reload`, and
serve only the `frontend/` directory — never the repository root.
