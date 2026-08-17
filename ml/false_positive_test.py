"""False-positive validation.

The question: if a cognitively normal person has a variable week — slept badly,
stressed, rushing, a couple of genuinely scrappy sessions — how often does
CogniDiff wrongly call it anomalous?

In a health tool this number matters more than sensitivity. A false alarm costs
a real person real anxiety about their own mind, and a tool that cries wolf gets
switched off long before it ever catches anything.

Target: **below 15%** on normal variation.

    python -m ml.false_positive_test
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from backend.alert_engine import (
    STATUS_PERSISTENT,
    STATUS_SIGNIFICANT,
    STATUS_STABLE,
    AlertEngine,
)
from backend.config import DOCS_DIR, SEED, set_all_seeds
from ml.anomaly_detector import AnomalyDetector, dual_confirmation
from ml.baseline import PersonalBaseline

TARGET_FP_RATE = 15.0


def _session(rng, drift=0.0, wobble=1.0, day=None) -> dict:
    """One session. `wobble` scales *non-cognitive* day-to-day variation."""
    return {
        "wpm_estimate": float(rng.normal(60 - 6 * drift, 4.5 * wobble)),
        "avg_iki_ms": float(rng.normal(180 + 34 * drift, 14 * wobble)),
        "avg_hold_ms": float(rng.normal(88 + 5 * drift, 5 * wobble)),
        "error_rate": float(np.clip(rng.normal(0.040 + 0.022 * drift,
                                               0.010 * wobble), 0.002, 0.5)),
        "correction_rate": float(np.clip(rng.normal(0.020 + 0.010 * drift,
                                                    0.006 * wobble), 0.001, 0.4)),
        "rhythm_variability": float(rng.normal(90 + 32 * drift, 12 * wobble)),
        "long_pause_count": float(max(0, rng.normal(1 + 2 * drift, 0.8 * wobble))),
        "burst_ratio": float(np.clip(rng.normal(0.25 - 0.05 * drift,
                                                0.03 * wobble), 0, 1)),
        "quality_score": 88.0,
        "excluded": 0,
        "time_slot": "morning",
        "device_fingerprint": "Windows|md|en",
        "date": (day or date.today()).isoformat(),
    }


def run(n_normal_days: int = 7, sessions_per_day: int = 5,
        n_repeats: int = 40) -> dict:
    """Simulate many variable-but-normal weeks and count the false flags."""
    set_all_seeds(SEED)
    rng = np.random.default_rng(SEED)

    # A settled baseline fortnight.
    baseline_sessions = [
        _session(rng, drift=0.0, wobble=1.0,
                 day=date.today() - timedelta(days=30 - i))
        for i in range(40)
    ]
    baseline = PersonalBaseline("fp-test").fit(baseline_sessions)
    detector = AnomalyDetector("fp-test").fit(baseline_sessions)

    session_flags = 0
    session_total = 0
    week_alerts = 0
    scores: list[float] = []

    for _ in range(n_repeats):
        day_anomalies: list[bool] = []
        day_scores: list[float] = []

        for d in range(n_normal_days):
            # Normal life: some days are simply more variable than others.
            # Stress and tiredness raise error rate by up to 50% on some days —
            # without changing anything cognitive.
            wobble = float(rng.uniform(0.7, 1.9))
            stressed = rng.random() < 0.35

            flagged_sessions = 0
            for _ in range(sessions_per_day):
                s = _session(rng, drift=0.0, wobble=wobble)
                if stressed:
                    s["error_rate"] *= float(rng.uniform(1.0, 1.5))

                deviation = baseline.overall_deviation(s)
                anomaly = detector.predict(s)
                verdict = dual_confirmation(deviation, anomaly)

                session_total += 1
                if verdict["concerning"]:
                    session_flags += 1
                    flagged_sessions += 1

                score = baseline.cogni_score(s)["cogni_score"]
                scores.append(score)
                day_scores.append(score)

            # A day counts as anomalous when most of its sessions were flagged,
            # not when any single one was. One distracted minute out of five is
            # a distracted minute, and treating it as an anomalous *day* would
            # let ordinary noise walk the alert ladder on its own.
            day_anomalies.append(flagged_sessions > sessions_per_day / 2)

        alert = AlertEngine().evaluate(
            "fp-test", day_scores, day_anomalies, trend_30d="stable",
        )
        # MONITOR is by design a soft state — "within the range of normal
        # variation, we are keeping an eye on it" — and raises nothing with the
        # user. Only SIGNIFICANT and above count as a false alarm.
        if alert.status_code in (STATUS_SIGNIFICANT, STATUS_PERSISTENT):
            week_alerts += 1

    session_fp = 100.0 * session_flags / session_total
    week_fp = 100.0 * week_alerts / n_repeats

    return {
        "seed": SEED,
        "weeks_simulated": n_repeats,
        "days_per_week": n_normal_days,
        "sessions_per_day": sessions_per_day,
        "sessions_total": session_total,
        "session_false_positive_rate_pct": round(session_fp, 2),
        "week_escalation_rate_pct": round(week_fp, 2),
        "week_escalation_counts": "SIGNIFICANT_DEVIATION or PERSISTENT_DEVIATION only",
        "target_pct": TARGET_FP_RATE,
        "passes": session_fp < TARGET_FP_RATE,
        "mean_cogni_score": round(float(np.mean(scores)), 2),
        "min_cogni_score": round(float(np.min(scores)), 2),
        "thresholds": {
            "deviation_threshold_pct": 25.0,
            "isolationforest_contamination": detector.contamination,
            "dual_confirmation": "both models must agree before a flag is raised",
        },
        "bootstrap_95ci": _bootstrap_ci(session_flags, session_total),
    }


def _bootstrap_ci(successes: int, total: int, n: int = 1000) -> list[float]:
    """95% CI for the false-positive rate.

    A single point estimate from one small self-collected dataset is not
    evidence; the interval is the honest version of the number.
    """
    rng = np.random.default_rng(SEED)
    observed = np.zeros(total, dtype=int)
    observed[:successes] = 1
    means = [rng.choice(observed, size=total, replace=True).mean() * 100
             for _ in range(n)]
    return [round(float(np.percentile(means, 2.5)), 2),
            round(float(np.percentile(means, 97.5)), 2)]


def main() -> None:
    result = run()

    print(f"sessions simulated       {result['sessions_total']}")
    print(f"session FP rate          {result['session_false_positive_rate_pct']}%"
          f"  (95% CI {result['bootstrap_95ci'][0]}–{result['bootstrap_95ci'][1]}%)")
    print(f"week escalation rate     {result['week_escalation_rate_pct']}%")
    print(f"mean CogniScore          {result['mean_cogni_score']}")
    print(f"target                   below {result['target_pct']}%")
    print(f"result                   {'PASS' if result['passes'] else 'FAIL'}")

    out = Path(DOCS_DIR) / "false_positive_test.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
