"""Central configuration, version tracking and determinism controls.

Every CogniScore CogniDiff stores carries the four version fields defined here,
so any score in the database can be traced back to the exact model, baseline and
feature definitions that produced it — and reproduced.
"""

from __future__ import annotations

import os
import random
import subprocess
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("COGNIDIFF_DB", ROOT / "cognidiff.db"))
MODEL_DIR = ROOT / "ml" / "models"
BACKUP_DIR = ROOT / "backups"
DOCS_DIR = ROOT / "docs"

MODEL_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------

ENV = os.getenv("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "false").lower() == "true"

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError("SECRET_KEY must be set in production. See .env.example.")
    # Development only. A fixed dev key keeps tokens valid across reloads;
    # production refuses to start without a real one (checked above).
    SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

BACKUP_KEY = os.getenv("BACKUP_KEY", "")

CORS_ORIGINS = [
    o.strip() for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",") if o.strip()
]

# --------------------------------------------------------------------------
# version tracking — written onto every cogniscores row
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_git_commit() -> str:
    """Short SHA of the current commit, or 'unversioned' outside a repo."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=5, check=False,
        )
        sha = out.stdout.strip()
        return sha if sha else "unversioned"
    except (OSError, subprocess.SubprocessError):
        return "unversioned"


VERSIONS = {
    # Bump when the anomaly model architecture or hyperparameters change.
    "model_version": "isolationforest_v1",
    # Bump whenever a feature definition in features.py changes meaning.
    # Scores computed under different schema versions are NOT comparable.
    "feature_schema_version": "v1",
    # LSTM trend model.
    "lstm_version": "lstm_h32_v1",
}


def version_fields(baseline_version: int = 1) -> dict:
    """The four traceability fields stamped onto every stored score."""
    return {
        "model_version": VERSIONS["model_version"],
        "baseline_version": baseline_version,
        "feature_schema_version": VERSIONS["feature_schema_version"],
        "code_commit": get_git_commit(),
    }


# --------------------------------------------------------------------------
# determinism — an unseeded experiment cannot be defended at viva
# --------------------------------------------------------------------------

SEED = int(os.getenv("COGNIDIFF_SEED", "42"))


def set_all_seeds(seed: int = SEED) -> int:
    """Seed every RNG in play. Call at the top of every training/eval script."""
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)

    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass

    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
    except ImportError:
        pass

    return seed


# --------------------------------------------------------------------------
# domain constants
# --------------------------------------------------------------------------

#: Features the baseline, anomaly detector and explainer all agree on.
FEATURE_NAMES = [
    "wpm_estimate",
    "avg_iki_ms",
    "avg_hold_ms",
    "error_rate",
    "correction_rate",
    "rhythm_variability",
    "long_pause_count",
    "burst_ratio",
]

#: Weights applied in the CogniScore. IKI and error rate are the strongest
#: cognitive signals in the keystroke-dynamics literature; burst ratio is the
#: noisiest, so it is damped.
FEATURE_WEIGHTS = {
    "wpm_estimate": 1.0,
    "avg_iki_ms": 1.5,
    "avg_hold_ms": 1.0,
    "error_rate": 1.5,
    "correction_rate": 1.0,
    "rhythm_variability": 1.2,
    "long_pause_count": 1.0,
    "burst_ratio": 0.8,
}

#: Human-readable names used in SHAP explanations and the dashboard.
FEATURE_LABELS = {
    "wpm_estimate": "Typing speed",
    "avg_iki_ms": "Pausing between keys",
    "avg_hold_ms": "Key hold time",
    "error_rate": "Typing errors",
    "correction_rate": "Corrections made",
    "rhythm_variability": "Typing rhythm steadiness",
    "long_pause_count": "Long pauses",
    "burst_ratio": "Fluent typing bursts",
}

QUALITY_EXCLUDE_THRESHOLD = 60.0
MIN_BASELINE_SESSIONS = 10
RECALIBRATION_SESSIONS = 30

#: The baseline is fitted on the FIRST two weeks of quality sessions, not on
#: everything collected to date. This matters more than it looks: a baseline
#: refitted continuously over all data absorbs whatever change is happening and
#: redefines it as normal, which makes gradual decline undetectable by
#: construction. The baseline is a fixed reference point; deviation is measured
#: against it until the user or the drift detector deliberately recalibrates.
BASELINE_WINDOW_DAYS = 14

#: Composite weighting between passive keystroke monitoring and the active
#: mini-tasks. Chosen by the sweep in ml/weight_sensitivity.py — see
#: docs/weight_sensitivity.md for the full table. Not a preference; a measured
#: trade-off.
#:
#: The sweep ran 100/0, 90/10, 80/20, 70/30, 60/40 and 50/50 against
#: false-positive rate, score stability and responsiveness. 70/30 sits at the
#: knee: within 5% of the best responsiveness-per-unit-instability, at a third
#: of the false-positive rate of the peak, and leaning less on an optional input
#: the user skips most days.
KEYSTROKE_WEIGHT = 0.70
TASK_WEIGHT = 0.30
