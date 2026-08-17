"""Weight sensitivity sweep for the keystroke/task composite.

80/20 is not a preference. When the examiner asks "why exactly 80 and 20", the
answer needs to be a table, so this sweeps the weighting across six settings and
measures three things that trade off against each other:

  false-positive rate  how often known-normal days get flagged
  stability            std dev of the daily composite across a stable week
                       (low is good — a metric that jitters is unreadable)
  responsiveness       how far the score drops on deliberately degraded days
                       (high is good — a metric that never moves is useless)

The best weighting is the one with the best stability-to-responsiveness ratio at
an acceptable false-positive rate. Run:

    python -m ml.weight_sensitivity
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from backend.config import DOCS_DIR, SEED, set_all_seeds

WEIGHTINGS = [(1.00, 0.00), (0.90, 0.10), (0.80, 0.20),
              (0.70, 0.30), (0.60, 0.40), (0.50, 0.50)]

FP_THRESHOLD = 70.0      # a composite below this would raise a flag
ACCEPTABLE_FP = 15.0     # percent — the ceiling from docs/false_positive_test.md

#: How much responsiveness we are willing to give up to sit at the knee of the
#: curve rather than its peak.
KNEE_TOLERANCE = 0.05


#: Fraction of degraded days where the change is ACUTE — it shows in the active
#: tasks but the day's passive typing still looks ordinary. This is the entire
#: reason the task channel exists, and a sweep that omits it can only ever
#: conclude "use whichever channel is quieter", which is not a finding about
#: CogniDiff, only about the simulation.
ACUTE_ONLY_FRACTION = 0.35

#: How often the user actually completes the optional mini-tasks. Measured
#: loosely from the demo instance and deliberately pessimistic — optional
#: self-assessment in a long-running health tool is skipped far more often
#: than it is done.
TASK_COMPLETION_RATE = 0.30


def _simulate(rng, n_days: int, degraded: bool):
    """Return (keystroke_scores, task_scores) for `n_days`.

    The two channels are modelled as partially independent readings of the same
    underlying state. Passive monitoring is steadier and catches gradual change;
    the active tasks are noisier but catch acute change the same day it happens.
    """
    # Active tasks are intrinsically noisier than passive monitoring: one
    # mistimed click moves a reaction-time score far more than one distracted
    # minute moves a week of typing rhythm. That noise is why the task channel
    # does not get equal weight.
    K_NOISE, T_NOISE = 6.0, 13.0

    if not degraded:
        return (np.clip(rng.normal(88, K_NOISE, n_days), 0, 100),
                np.clip(rng.normal(85, T_NOISE, n_days), 0, 100))

    acute_only = rng.random(n_days) < ACUTE_ONLY_FRACTION

    # Gradual degradation shows in both channels.
    keystroke = rng.normal(58, K_NOISE + 3, n_days)
    task = rng.normal(62, T_NOISE, n_days)

    # Acute degradation shows in the tasks while the day's typing looks normal.
    keystroke = np.where(acute_only, rng.normal(86, K_NOISE, n_days), keystroke)
    task = np.where(acute_only, rng.normal(48, T_NOISE, n_days), task)

    return np.clip(keystroke, 0, 100), np.clip(task, 0, 100)


def sweep(n_days: int = 400) -> dict:
    set_all_seeds(SEED)
    rng = np.random.default_rng(SEED)

    normal_k, normal_t = _simulate(rng, n_days, degraded=False)
    stable_k, stable_t = _simulate(rng, 7, degraded=False)
    bad_k, bad_t = _simulate(rng, n_days // 4, degraded=True)

    # Whether the user actually did the tasks that day. This is the cost the
    # sweep would otherwise miss: the mini-tasks are user-initiated and mostly
    # skipped, and scoring.py falls back to keystroke-only when they are absent.
    # The heavier the task weight, the further a task day sits from a non-task
    # day — so the score jumps for reasons that have nothing to do with the
    # person. Without this term the trade-off is monotonic and the sweep just
    # picks whichever endpoint the noise model favours.
    stable_has_task = rng.random(len(stable_k)) < TASK_COMPLETION_RATE
    normal_has_task = rng.random(n_days) < TASK_COMPLETION_RATE
    bad_has_task = rng.random(len(bad_k)) < TASK_COMPLETION_RATE

    def blend(keystroke, task, has_task, kw, tw):
        return np.where(has_task, kw * keystroke + tw * task, keystroke)

    rows = []
    for kw, tw in WEIGHTINGS:
        normal = blend(normal_k, normal_t, normal_has_task, kw, tw)
        stable = blend(stable_k, stable_t, stable_has_task, kw, tw)
        # Degraded days get the same availability treatment. Assuming the tasks
        # are always there on exactly the days that matter would hand the task
        # channel a benefit it does not have in practice.
        bad = blend(bad_k, bad_t, bad_has_task, kw, tw)

        fp_rate = float((normal < FP_THRESHOLD).mean() * 100)
        stability = float(stable.std())
        responsiveness = float(normal.mean() - bad.mean())
        ratio = responsiveness / stability if stability else 0.0

        rows.append({
            "keystroke_weight": kw,
            "task_weight": tw,
            "label": f"{int(kw * 100)}/{int(tw * 100)}",
            "false_positive_rate_pct": round(fp_rate, 2),
            "stability_std": round(stability, 3),
            "responsiveness_points": round(responsiveness, 2),
            "responsiveness_per_std": round(ratio, 3),
            "acceptable_fp": fp_rate <= ACCEPTABLE_FP,
        })

    eligible = [r for r in rows if r["acceptable_fp"]]
    pool = eligible or rows
    peak = max(pool, key=lambda r: r["responsiveness_per_std"])

    # Knee rule, not raw maximum. The trade-off curve flattens: past a point,
    # more task weight buys a fraction of a percent of responsiveness while the
    # false-positive rate keeps climbing. So take the *smallest* task weight
    # that gets within KNEE_TOLERANCE of the best ratio.
    #
    # The tie-break direction is deliberate. Keystroke monitoring is passive and
    # always running; the mini-tasks depend on the user choosing to sit down and
    # do them. When two weightings perform equivalently, the one that leans on
    # the channel which is actually there is the more robust choice.
    threshold = peak["responsiveness_per_std"] * (1 - KNEE_TOLERANCE)
    knee = min(
        (r for r in pool if r["responsiveness_per_std"] >= threshold),
        key=lambda r: r["task_weight"],
    )

    return {
        "n_days_normal": n_days,
        "n_days_degraded": n_days // 4,
        "flag_threshold": FP_THRESHOLD,
        "acceptable_fp_ceiling": ACCEPTABLE_FP,
        "knee_tolerance": KNEE_TOLERANCE,
        "seed": SEED,
        "simulation_assumptions": {
            "acute_only_fraction": ACUTE_ONLY_FRACTION,
            "task_completion_rate": TASK_COMPLETION_RATE,
            "note": (
                "The conclusion is conditional on these two parameters. They are "
                "estimates, not measurements — a real deployment should re-run "
                "this sweep against observed task-completion rates."
            ),
        },
        "rows": rows,
        "peak": peak["label"],
        "chosen": knee["label"],
        "chosen_because": (
            f"{peak['label']} has the highest responsiveness-per-unit-instability "
            f"({peak['responsiveness_per_std']}), but the curve is flat near the "
            f"top: {knee['label']} reaches {knee['responsiveness_per_std']} — "
            f"within {int(KNEE_TOLERANCE * 100)}% of the peak — at a lower "
            f"false-positive rate ({knee['false_positive_rate_pct']}% versus "
            f"{peak['false_positive_rate_pct']}%) and with less reliance on an "
            f"optional, frequently-skipped input."
        ),
    }


def main() -> None:
    result = sweep()

    header = f"{'weighting':>10} {'FP %':>7} {'stability':>10} {'response':>9} {'resp/std':>9}"
    print(header)
    print("-" * len(header))
    for r in result["rows"]:
        mark = " *" if r["label"] == result["chosen"] else ""
        print(f"{r['label']:>10} {r['false_positive_rate_pct']:>7.2f} "
              f"{r['stability_std']:>10.3f} {r['responsiveness_points']:>9.2f} "
              f"{r['responsiveness_per_std']:>9.3f}{mark}")

    print(f"\nchosen: {result['chosen']}")
    print(result["chosen_because"])

    out = Path(DOCS_DIR) / "weight_sensitivity.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
