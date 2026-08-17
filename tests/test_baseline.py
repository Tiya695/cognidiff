"""PersonalBaseline, the CogniScore, context adjustment and drift."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from backend.context_tracker import TOLERANCE, ContextTracker
from ml.baseline import PersonalBaseline
from ml.drift_detector import ModelDriftDetector


def session(**over) -> dict:
    base = {
        "wpm_estimate": 60.0, "avg_iki_ms": 180.0, "avg_hold_ms": 88.0,
        "error_rate": 0.04, "correction_rate": 0.02, "rhythm_variability": 90.0,
        "long_pause_count": 1.0, "burst_ratio": 0.25,
        "quality_score": 88.0, "excluded": 0, "time_slot": "morning",
        "date": date.today().isoformat(), "device_fingerprint": "Windows|md|en",
    }
    base.update(over)
    return base


def cohort(n=20, jitter=1.0, **over):
    """A settled two weeks of typing, with small natural variation."""
    out = []
    for i in range(n):
        wobble = math.sin(i * 1.7) * jitter
        out.append(session(
            wpm_estimate=60 + wobble * 2.0,
            avg_iki_ms=180 + wobble * 9.0,
            avg_hold_ms=88 + wobble * 3.0,
            error_rate=0.04 + wobble * 0.004,
            correction_rate=0.02 + wobble * 0.002,
            rhythm_variability=90 + wobble * 6.0,
            long_pause_count=1 + abs(wobble) * 0.4,
            burst_ratio=0.25 + wobble * 0.012,
            date=(date.today() - timedelta(days=n - i)).isoformat(),
            **over,
        ))
    return out


# ---------------------------------------------------------------------------
# fitting
# ---------------------------------------------------------------------------

def test_fit_computes_the_mean_we_compute_by_hand():
    sessions = [session(wpm_estimate=w) for w in (50, 60, 70)] * 4
    b = PersonalBaseline("u").fit(sessions)
    assert b.means["wpm_estimate"] == pytest.approx(60.0)


def test_fit_refuses_a_thin_baseline():
    with pytest.raises(ValueError, match="at least"):
        PersonalBaseline("u").fit(cohort(4))


def test_fit_ignores_excluded_and_low_quality_sessions():
    good = cohort(14)
    poison = [session(wpm_estimate=5, quality_score=20, excluded=1) for _ in range(20)]
    b = PersonalBaseline("u").fit(good + poison)
    assert b.n_sessions == 14
    assert b.means["wpm_estimate"] > 40      # the junk did not drag it down


def test_per_time_slot_baselines_are_built():
    sessions = cohort(12, time_slot="morning") + cohort(12, time_slot="night")
    b = PersonalBaseline("u").fit(sessions)
    assert "morning" in b.slot_means and "night" in b.slot_means


def test_deviation_on_an_unfitted_baseline_raises():
    with pytest.raises(RuntimeError):
        PersonalBaseline("u").deviation_score(session())


# ---------------------------------------------------------------------------
# deviation and the score
# ---------------------------------------------------------------------------

def test_a_baseline_matching_session_scores_high():
    b = PersonalBaseline("u").fit(cohort(20))
    assert b.cogni_score(session())["cogni_score"] >= 90


def test_typing_faster_is_not_penalised():
    """Adverse-only deviation: a good day must not look like a bad one."""
    b = PersonalBaseline("u").fit(cohort(20))
    faster = b.cogni_score(session(wpm_estimate=75))["cogni_score"]
    assert faster >= 88


def test_the_score_is_monotonic_in_deviation():
    """Worse deviation must never produce a higher score. This is the one
    property the whole metric is useless without."""
    b = PersonalBaseline("u").fit(cohort(20))
    scores = [
        b.cogni_score(session(avg_iki_ms=iki, error_rate=err))["cogni_score"]
        for iki, err in [(180, 0.04), (220, 0.06), (280, 0.09),
                         (350, 0.13), (450, 0.20)]
    ]
    assert scores == sorted(scores, reverse=True), scores


def test_worse_typing_lowers_the_score_meaningfully():
    b = PersonalBaseline("u").fit(cohort(20))
    normal = b.cogni_score(session())["cogni_score"]
    degraded = b.cogni_score(session(
        wpm_estimate=38, avg_iki_ms=330, error_rate=0.14,
        rhythm_variability=190, long_pause_count=6,
    ))["cogni_score"]
    assert degraded < normal - 20


def test_small_variation_stays_above_eighty():
    """Deviations from ordinary daily wobble must not read as 'something is
    wrong' — that is the entire reason the mapping is a sigmoid."""
    b = PersonalBaseline("u").fit(cohort(20))
    mild = b.cogni_score(session(wpm_estimate=57, avg_iki_ms=190,
                                 error_rate=0.045))["cogni_score"]
    assert mild >= 80


def test_score_is_bounded():
    b = PersonalBaseline("u").fit(cohort(20))
    absurd = b.cogni_score(session(
        wpm_estimate=1, avg_iki_ms=9_000, error_rate=0.95,
        rhythm_variability=5_000, long_pause_count=200, burst_ratio=0.0,
    ))["cogni_score"]
    assert 0.0 <= absurd <= 100.0


def test_top_deviating_feature_identifies_the_culprit():
    b = PersonalBaseline("u").fit(cohort(20))
    out = b.cogni_score(session(error_rate=0.28))
    assert out["top_deviating_feature"] == "error_rate"


def test_a_constant_feature_does_not_explode():
    """Someone perfectly consistent has near-zero std; without a floor, trivial
    jitter would register as a 40-sigma event."""
    flat = [session() for _ in range(20)]
    b = PersonalBaseline("u").fit(flat)
    devs = b.deviation_score(session(wpm_estimate=60.5))
    assert abs(devs["wpm_estimate"]["z"]) < 3


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    import ml.baseline as mod
    monkeypatch.setattr(mod, "MODEL_DIR", tmp_path)
    b = PersonalBaseline("round-trip", version=3).fit(cohort(20))
    b.save()
    loaded = PersonalBaseline.load("round-trip")
    assert loaded is not None
    assert loaded.version == 3
    assert loaded.means["wpm_estimate"] == pytest.approx(b.means["wpm_estimate"])


def test_load_missing_baseline_returns_none():
    assert PersonalBaseline.load("nobody-here") is None


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------

def test_no_context_leaves_the_score_alone():
    out = ContextTracker.adjust_score(70.0, None)
    assert out["adjusted_score"] == 70.0
    assert out["context_adjusted"] is False


def test_poor_sleep_adds_exactly_the_documented_tolerance():
    out = ContextTracker.adjust_score(70.0, {"sleep_quality": 2})
    assert out["adjusted_score"] == 70.0 + TOLERANCE["poor_sleep"]
    assert out["tolerance_applied"] == TOLERANCE["poor_sleep"]


def test_good_sleep_adds_nothing():
    assert ContextTracker.adjust_score(70.0, {"sleep_quality": 4})["tolerance_applied"] == 0


def test_tolerances_stack_but_are_capped():
    out = ContextTracker.adjust_score(50.0, {
        "sleep_quality": 1, "stress_level": 5, "feeling_unwell": True,
    })
    expected = TOLERANCE["poor_sleep"] + TOLERANCE["high_stress"] + TOLERANCE["feeling_unwell"]
    assert out["tolerance_applied"] == min(expected, 18)


def test_adjustment_cannot_exceed_one_hundred():
    assert ContextTracker.adjust_score(97.0, {"feeling_unwell": True})["adjusted_score"] == 100.0


def test_device_change_excludes_rather_than_forgives():
    """Adding tolerance points would still let a new keyboard bend the curve."""
    out = ContextTracker.adjust_score(70.0, {"device_changed": True})
    assert out["exclude_from_trend"] is True
    assert out["tolerance_applied"] == 0


def test_raw_score_is_always_preserved():
    out = ContextTracker.adjust_score(62.0, {"sleep_quality": 1})
    assert out["raw_score"] == 62.0
    assert out["adjusted_score"] > out["raw_score"]


# ---------------------------------------------------------------------------
# drift
# ---------------------------------------------------------------------------

def test_stable_data_shows_no_drift():
    b = PersonalBaseline("u").fit(cohort(20))
    out = ModelDriftDetector(b).check_drift(cohort(14))
    assert out["drift_severity"] in ("none", "low")


def test_a_sustained_shift_is_detected():
    b = PersonalBaseline("u").fit(cohort(20))
    shifted = [session(error_rate=0.16, avg_iki_ms=290, rhythm_variability=200)
               for _ in range(14)]
    out = ModelDriftDetector(b).check_drift(shifted)
    assert out["drift_severity"] in ("medium", "high")
    assert any(f["feature"] == "error_rate" for f in out["drifted_features"])


def test_a_device_change_classifies_as_environmental():
    b = PersonalBaseline("u").fit(cohort(20))
    history = cohort(10) + [
        session(device_fingerprint="Darwin|lg|en", avg_iki_ms=260,
                rhythm_variability=170, error_rate=0.09,
                date=(date.today() - timedelta(days=5 - i)).isoformat())
        for i in range(10)
    ]
    out = ModelDriftDetector(b).classify_drift(history)
    assert out["classification"] == "ABRUPT_ENVIRONMENTAL"
    assert out["recommended_action"] == "recalibrate"


def test_a_gradual_shift_with_no_cause_is_never_recalibrated_away():
    """The signal CogniDiff exists to find. If this test ever starts returning
    ABRUPT_ENVIRONMENTAL, the tool has become a false-alarm suppressor."""
    b = PersonalBaseline("u").fit(cohort(20))
    history = []
    for i in range(40):
        creep = i / 40.0
        history.append(session(
            wpm_estimate=60 - 12 * creep,
            avg_iki_ms=180 + 70 * creep,
            error_rate=0.04 + 0.05 * creep,
            rhythm_variability=90 + 70 * creep,
            date=(date.today() - timedelta(days=40 - i)).isoformat(),
        ))
    out = ModelDriftDetector(b).classify_drift(history)
    assert out["classification"] == "GRADUAL_UNEXPLAINED"
    assert out["recommended_action"] == "alert_and_keep_baseline"


def test_classification_needs_enough_data():
    b = PersonalBaseline("u").fit(cohort(20))
    assert ModelDriftDetector(b).classify_drift(cohort(3))["classification"] == "STABLE"
