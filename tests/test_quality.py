"""The data quality gate — one test per documented reject criterion.

Each reason code exists because a specific kind of junk was able to move a
score. These tests are what stop it becoming able to again.
"""

from __future__ import annotations

from backend.data_quality import DataQualityEngine, quality_tier
from backend.features import enrich_batch
from tests.conftest import make_batch


def score(batch: dict, baseline_device=None):
    enriched = enrich_batch(batch)
    enriched["key_categories"] = batch.get("key_categories", "")
    enriched["complete"] = batch.get("complete", True)
    return DataQualityEngine(baseline_device=baseline_device).score_session(enriched)


def test_a_good_session_passes():
    result = score(make_batch())
    assert result.should_exclude is False
    assert result.quality_score >= 60
    assert quality_tier(result.quality_score) in ("excellent", "acceptable")


def test_low_volume_is_rejected():
    """Three keystrokes is not a typing sample. This is the canonical case."""
    result = score(make_batch(keystrokes=3, duration_ms=4_000))
    assert result.should_exclude is True
    assert "LOW_VOLUME" in result.reason_codes
    assert result.quality_score < 60


def test_nineteen_keystrokes_is_still_below_the_floor():
    result = score(make_batch(keystrokes=19, duration_ms=50_000))
    assert result.should_exclude is True
    assert "LOW_VOLUME" in result.reason_codes


def test_short_duration_is_flagged():
    result = score(make_batch(keystrokes=60, duration_ms=8_000))
    assert "SHORT_DURATION" in result.reason_codes


def test_missing_features_is_rejected():
    batch = make_batch()
    enriched = enrich_batch(batch)
    enriched["rhythm_variability"] = None
    result = DataQualityEngine().score_session(enriched)
    assert result.should_exclude is True
    assert "MISSING_FEATURES" in result.reason_codes


def test_nan_counts_as_missing():
    batch = make_batch()
    enriched = enrich_batch(batch)
    enriched["error_rate"] = float("nan")
    result = DataQualityEngine().score_session(enriched)
    assert result.should_exclude is True
    assert "MISSING_FEATURES" in result.reason_codes


def test_impossible_timing_is_rejected():
    """Browser lag must never look like cognitive slowing."""
    batch = make_batch()
    enriched = enrich_batch(batch)
    enriched["avg_iki_ms"] = 45_000        # 45 seconds between keys
    result = DataQualityEngine().score_session(enriched)
    assert result.should_exclude is True
    assert "ABNORMAL_TIMING" in result.reason_codes


def test_zero_millisecond_intervals_are_a_clock_artefact():
    batch = make_batch()
    enriched = enrich_batch(batch)
    enriched["_intervals"] = [0.0] * 40 + [180.0] * 10
    result = DataQualityEngine().score_session(enriched)
    assert "ABNORMAL_TIMING" in result.reason_codes


def test_impossible_wpm_is_rejected():
    batch = make_batch(wpm=900)
    result = score(batch)
    assert result.should_exclude is True
    assert "ABNORMAL_TIMING" in result.reason_codes


def test_incomplete_capture_is_flagged():
    batch = make_batch()
    batch["complete"] = False
    result = score(batch)
    assert "INCOMPLETE_CAPTURE" in result.reason_codes


def test_device_change_caps_quality_and_sets_the_flag():
    """A new keyboard changes typing rhythm far more than a mild cognitive
    change does, so a session from an unfamiliar device can never carry full
    weight."""
    result = score(make_batch(device="Darwin|lg|en"), baseline_device="Windows|md|en")
    assert result.device_changed is True
    assert result.quality_score <= 50
    assert "DEVICE_CHANGED" in result.reason_codes


def test_same_device_is_not_flagged():
    result = score(make_batch(device="Windows|md|en"), baseline_device="Windows|md|en")
    assert result.device_changed is False
    assert "DEVICE_CHANGED" not in result.reason_codes


def test_digits_only_session_is_penalised_for_diversity():
    """A minute of pure numeric entry is a spreadsheet, not prose. Its rhythm
    is genuinely different and would pollute a baseline built on writing."""
    batch = make_batch()
    batch["key_categories"] = "d" * len(batch["key_categories"])
    prose = score(make_batch())
    numeric = score(batch)
    assert numeric.breakdown["diversity"] < prose.breakdown["diversity"]


def test_every_reason_code_has_a_description():
    from backend.data_quality import REASON_CODES
    for code, text in REASON_CODES.items():
        assert code.isupper()
        assert len(text) > 10


def test_result_serialises_for_the_api():
    payload = score(make_batch(keystrokes=3)).as_dict()
    assert set(payload) >= {
        "quality_score", "should_exclude", "reason_codes", "reasons",
        "breakdown", "device_changed",
    }
    assert isinstance(payload["reasons"][0], str)


def test_tier_boundaries():
    assert quality_tier(95) == "excellent"
    assert quality_tier(80) == "acceptable"
    assert quality_tier(60) == "acceptable"
    assert quality_tier(59.9) == "excluded"
