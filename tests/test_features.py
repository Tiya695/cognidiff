"""Feature extraction — checked against values computed by hand.

If any assertion here changes, FEATURE_SCHEMA_VERSION in config.py must change
with it. Scores produced under different feature definitions are not comparable,
and a silent redefinition would invalidate every stored score without anybody
noticing.
"""

from __future__ import annotations

import pytest

from backend.features import (
    burst_ratio,
    detect_correction_events,
    enrich_batch,
    rhythm_variability,
    time_slot,
)


# ---------------------------------------------------------------------------
# correction events — the definition that consecutive-backspace-pairs gets wrong
# ---------------------------------------------------------------------------

def test_the_worked_example_from_the_spec():
    """"hello wrld", three separate backspaces, then retype "o".

    Counting consecutive backspace pairs would find none here, because each
    backspace is separated by a gap. The episode definition finds exactly one
    correction, which is what a human observer would say happened.
    """
    cats = list("hellowrld") + ["b", "b", "b"] + ["l"]
    times = [0, 120, 240, 360, 480, 600, 720, 840, 960,
             1200, 1600, 2000,          # backspaces, spread over 800 ms
             2400]                       # the retype

    out = detect_correction_events(cats, times)
    assert out["correction_events"] == 1
    assert out["mean_keystrokes_deleted_per_event"] == 3.0


def test_two_episodes_separated_by_normal_typing():
    cats = ["l", "b", "l", "l", "l", "l", "l", "b", "l"]
    times = [0, 100, 200,
             5000, 5100, 5200, 5300,     # >2 s of normal typing ends episode 1
             9000, 9100]

    out = detect_correction_events(cats, times)
    assert out["correction_events"] == 2


def test_one_long_deletion_run_is_a_single_event():
    cats = ["l"] + ["b"] * 12 + ["l"]
    times = [0] + [100 + i * 90 for i in range(12)] + [1400]

    out = detect_correction_events(cats, times)
    assert out["correction_events"] == 1
    assert out["mean_keystrokes_deleted_per_event"] == 12.0


def test_batch_opening_on_a_backspace_is_not_a_new_event():
    """The deletion continues typing we never captured, so it is not evidence
    of a correction *in this batch*."""
    out = detect_correction_events(["b", "b", "l"], [0, 100, 300])
    assert out["correction_events"] == 0


def test_no_backspaces_means_no_corrections():
    out = detect_correction_events(list("hello"), [0, 100, 200, 300, 400])
    assert out["correction_events"] == 0
    assert out["mean_correction_duration_ms"] == 0.0


def test_empty_input_is_handled():
    out = detect_correction_events([], [])
    assert out["correction_events"] == 0


# ---------------------------------------------------------------------------
# individual features
# ---------------------------------------------------------------------------

def test_rhythm_variability_is_population_std():
    # mean 200, deviations -100/0/+100 → population std = sqrt(20000/3) ≈ 81.65
    assert rhythm_variability([100, 200, 300]) == pytest.approx(81.65, abs=0.02)


def test_rhythm_variability_of_a_perfect_metronome_is_zero():
    assert rhythm_variability([200] * 10) == 0.0


def test_rhythm_variability_ignores_impossible_intervals():
    """A 60-second gap is the user going for coffee, not a typing rhythm."""
    assert rhythm_variability([200, 200, 200, 999_999]) == 0.0


def test_burst_ratio_counts_intervals_under_150ms():
    assert burst_ratio([100, 120, 200, 400]) == 0.5
    assert burst_ratio([500, 600]) == 0.0
    assert burst_ratio([]) == 0.0


@pytest.mark.parametrize("hour,slot", [
    (5, "morning"), (11, "morning"), (12, "afternoon"), (16, "afternoon"),
    (17, "evening"), (21, "evening"), (22, "night"), (3, "night"), (0, "night"),
])
def test_time_slot_buckets(hour, slot):
    assert time_slot(hour) == slot


# ---------------------------------------------------------------------------
# enrich_batch
# ---------------------------------------------------------------------------

def test_error_rate_is_backspaces_over_keystrokes():
    out = enrich_batch({
        "total_keystrokes": 200, "backspace_count": 10,
        "key_categories": "", "offsets_ms": [], "hour": 10,
    })
    assert out["error_rate"] == 0.05


def test_zero_keystrokes_does_not_divide_by_zero():
    out = enrich_batch({"total_keystrokes": 0, "backspace_count": 0, "hour": 9})
    assert out["error_rate"] == 0.0
    assert out["correction_rate"] == 0.0
    assert out["rhythm_variability"] == 0.0


def test_intervals_are_derived_from_offsets_when_absent():
    out = enrich_batch({
        "total_keystrokes": 4, "backspace_count": 0,
        "key_categories": "llll", "offsets_ms": [0, 100, 300, 600],
        "hour": 14,
    })
    # intervals 100, 200, 300 → one under the 150 ms burst threshold
    assert out["burst_ratio"] == pytest.approx(1 / 3, abs=0.001)
    assert out["time_slot"] == "afternoon"


def test_enrichment_never_carries_text():
    """The one guarantee the whole privacy claim rests on."""
    out = enrich_batch({
        "total_keystrokes": 5, "backspace_count": 1,
        "key_categories": "llbls", "offsets_ms": [0, 90, 180, 300, 500],
        "hour": 10,
    })
    serialisable = {k: v for k, v in out.items() if not k.startswith("_")}
    for value in serialisable.values():
        assert not isinstance(value, str) or value in (
            "morning", "afternoon", "evening", "night", None,
        ) or value == out.get("device_fingerprint")
