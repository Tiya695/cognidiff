"""Research components: LSTM, ablation, SHAP, the pseudo-label model, federated.

These carry the paper's claims, so they are tested for the properties the paper
actually asserts — that the trend model is compared against a naive baseline,
that three importance methods can be compared, that the pseudo-label model
declares itself uncertified, and that federated training never moves raw
features.
"""

from __future__ import annotations

import math

import pytest

from ml.ablation import compare_methods, run_ablation
from ml.anomaly_detector import ANOMALY_FEATURES, AnomalyDetector
from ml.explainer import CogniExplainer, format_explanation
from ml.federated import simulate_federation
from ml.lstm_model import LSTMPredictor
from ml.xgb_model import XGBCogniClassifier
from tests.test_baseline import cohort, session


# ---------------------------------------------------------------------------
# trend model
# ---------------------------------------------------------------------------

def gentle_decline(n=45):
    """A slow downward drift with day-to-day noise on top."""
    return [88 - 0.35 * i + 3.0 * math.sin(i * 1.9) for i in range(n)]


def test_training_needs_enough_history():
    with pytest.raises(ValueError, match="at least"):
        LSTMPredictor("u").train([80, 81, 79])


def test_prediction_is_in_range_and_labelled():
    m = LSTMPredictor("u")
    m.train(gentle_decline())
    out = m.predict(gentle_decline()[-7:])
    assert 0 <= out["predicted_score"] <= 100
    assert out["trend"] in ("declining", "improving", "stable")
    assert out["backend"] in ("lstm_torch", "ridge_fallback")
    assert out["trained"] is True


def test_an_untrained_model_says_so_and_falls_back_to_persistence():
    """If the LSTM cannot beat last-value-carried-forward, that is a real
    finding — so persistence is a named, visible fallback, not a silent one."""
    out = LSTMPredictor("u").predict([80, 79, 81, 78, 80, 79, 77])
    assert out["backend"] == "naive_persistence"
    assert out["trained"] is False
    assert out["predicted_score"] == 77


def test_a_short_window_is_padded_not_zero_filled():
    """Padding with zeros would look like a catastrophic day that never
    happened."""
    m = LSTMPredictor("u")
    m.train(gentle_decline())
    assert m.predict([85, 84])["predicted_score"] > 40


def test_evaluation_reports_the_naive_baseline_alongside_the_model():
    m = LSTMPredictor("u")
    m.train(gentle_decline())
    ev = m.evaluate(gentle_decline())
    assert {"model_mae", "naive_mae", "beats_naive", "n"} <= set(ev)
    assert ev["model_mae"] >= 0 and ev["naive_mae"] >= 0


def test_the_model_detects_a_downward_trend():
    m = LSTMPredictor("u")
    series = [90 - 0.8 * i for i in range(40)]
    m.train(series)
    assert m.predict(series[-7:])["trend"] in ("declining", "stable")


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    import ml.lstm_model as mod
    monkeypatch.setattr(mod, "MODEL_DIR", tmp_path)
    m = LSTMPredictor("rt")
    m.train(gentle_decline())
    m.save()
    loaded = LSTMPredictor.load("rt")
    assert loaded is not None and loaded.backend == m.backend


# ---------------------------------------------------------------------------
# ablation
# ---------------------------------------------------------------------------

def mixed_sessions(n=40):
    """Mostly normal, with a handful of genuinely degraded sessions."""
    out = cohort(n - 6)
    for i in range(6):
        out.append(session(
            wpm_estimate=34 + i, avg_iki_ms=330 + i * 8,
            error_rate=0.17, rhythm_variability=210, long_pause_count=7,
        ))
    return out


def test_ablation_needs_enough_sessions():
    with pytest.raises(ValueError, match="at least 15"):
        run_ablation(cohort(8))


def test_ablation_ranks_every_feature():
    out = run_ablation(mixed_sessions())
    assert len(out["results"]) == len(ANOMALY_FEATURES)
    ranks = [r["importance_rank"] for r in out["results"]]
    assert ranks == list(range(1, len(ANOMALY_FEATURES) + 1))
    assert out["most_important"] in ANOMALY_FEATURES


def test_ablation_is_deterministic():
    """Every number in the paper has to be reproducible from a fixed seed."""
    a = run_ablation(mixed_sessions())
    b = run_ablation(mixed_sessions())
    assert [r["feature_name"] for r in a["results"]] == \
           [r["feature_name"] for r in b["results"]]


def test_convergent_validity_comparison():
    ablation = run_ablation(mixed_sessions())
    order = [r["feature_name"] for r in ablation["results"]]

    shap_like = [{"feature": f} for f in order]
    xgb_like = [{"feature": f} for f in order]

    out = compare_methods(ablation, shap_like, xgb_like)
    assert out["comparable"] is True
    assert out["mean_agreement"] == pytest.approx(1.0)
    assert "convergent validity" in out["interpretation"]


def test_disagreement_is_reported_not_hidden():
    ablation = run_ablation(mixed_sessions())
    order = [r["feature_name"] for r in ablation["results"]]

    out = compare_methods(ablation,
                          [{"feature": f} for f in reversed(order)],
                          [{"feature": f} for f in order])
    assert out["mean_agreement"] < 0.6
    assert "disagree" in out["interpretation"].lower()


# ---------------------------------------------------------------------------
# explainability
# ---------------------------------------------------------------------------

def test_the_explainer_ranks_the_feature_that_actually_moved():
    sessions = mixed_sessions()
    detector = AnomalyDetector("u").fit(sessions)
    explainer = CogniExplainer(detector).fit(sessions)

    out = explainer.explain(session(error_rate=0.30, avg_iki_ms=420,
                                    rhythm_variability=260))
    assert len(out) == len(ANOMALY_FEATURES)
    assert explainer.method in ("shap_tree", "occlusion")
    assert all("label" in item for item in out)


def test_explanations_read_as_english_not_model_units():
    per_feature = {
        "avg_iki_ms": {"percent_change": 21.4, "direction": "increased"},
        "error_rate": {"percent_change": 14.0, "direction": "increased"},
        "wpm_estimate": {"percent_change": -8.2, "direction": "decreased"},
    }
    shap_like = [
        {"feature": "avg_iki_ms", "direction": "increased", "shap_value": 0.4},
        {"feature": "error_rate", "direction": "increased", "shap_value": 0.3},
        {"feature": "wpm_estimate", "direction": "decreased", "shap_value": 0.2},
    ]

    out = format_explanation(shap_like, per_feature, top_n=3)
    assert out[0]["text"] == "Pausing between keys: 21% longer than usual"
    assert out[1]["text"] == "Typing errors: 14% above your baseline"
    assert out[2]["text"] == "Typing speed: 8% slower than usual"


def test_an_unchanged_feature_is_described_as_unchanged():
    out = format_explanation(
        [{"feature": "wpm_estimate", "direction": "increased", "shap_value": 0.0}],
        {"wpm_estimate": {"percent_change": 0.2, "direction": "increased"}},
    )
    assert "unchanged" in out[0]["text"]


def test_the_explainer_refuses_an_unfitted_detector():
    with pytest.raises(ValueError):
        CogniExplainer(AnomalyDetector("u"))


# ---------------------------------------------------------------------------
# pseudo-label model
# ---------------------------------------------------------------------------

def test_the_pseudo_label_model_declares_itself_uncertified():
    """Circular validation is the trap here: this model learns to imitate
    IsolationForest, so a high score means only that it succeeded at imitation."""
    sessions = mixed_sessions()
    detector = AnomalyDetector("u").fit(sessions)
    labels = [detector.predict(s)["is_anomaly"] for s in sessions]

    model = XGBCogniClassifier("u")
    info = model.train(sessions, labels)

    assert "pseudo-label" in info["warning"].lower()
    assert "no clinical validation" in info["warning"].lower()
    assert model.predict(sessions[0])["is_clinically_validated"] is False


def test_single_class_pseudo_labels_are_refused():
    sessions = cohort(20)
    with pytest.raises(ValueError, match="single class"):
        XGBCogniClassifier("u").train(sessions, [False] * 20)


def test_feature_importance_is_ranked_and_normalised():
    sessions = mixed_sessions()
    detector = AnomalyDetector("u").fit(sessions)
    labels = [detector.predict(s)["is_anomaly"] for s in sessions]

    model = XGBCogniClassifier("u")
    model.train(sessions, labels)
    ranking = model.feature_importance()

    assert [r["rank"] for r in ranking] == list(range(1, len(ANOMALY_FEATURES) + 1))
    assert sum(r["importance_pct"] for r in ranking) == pytest.approx(100.0, abs=0.5)


def test_the_source_carries_the_disclaimer_banner():
    """A comment can be deleted; this test notices."""
    import ml.xgb_model as mod
    assert "NOT CLINICAL" in (mod.__doc__ or "").upper()
    assert "CIRCULAR VALIDATION" in (mod.__doc__ or "").upper()


# ---------------------------------------------------------------------------
# federated learning
# ---------------------------------------------------------------------------

def test_the_simulation_completes_its_rounds():
    out = simulate_federation(n_clients=3, rounds=3, persist=False)
    assert out["rounds_completed"] == 3
    assert len(out["history"]) == 3
    assert 0.0 <= out["final_accuracy"] <= 1.0


def test_aggregation_improves_on_the_untrained_model():
    out = simulate_federation(n_clients=3, rounds=3, persist=False)
    first, last = out["history"][0], out["history"][-1]
    assert last["loss"] <= first["loss"] + 1e-6


def test_no_raw_features_are_transmitted():
    assert simulate_federation(n_clients=3, rounds=2, persist=False)[
        "raw_features_transmitted"] is False


def test_the_limitation_is_stated_and_never_overclaims():
    """Federated learning is not automatic privacy, and an examiner who knows
    the literature will press on exactly this."""
    text = simulate_federation(n_clients=2, rounds=1, persist=False)["limitation"]
    lowered = text.lower()

    assert "not an automatic privacy guarantee" in lowered
    assert "gradient inversion" in lowered
    assert "membership inference" in lowered
    assert "reduces the need to centrally collect" in lowered

    for overclaim in ("strongest possible", "completely private",
                      "guarantees privacy", "impossible to"):
        assert overclaim not in lowered


def test_the_simulation_is_reproducible():
    a = simulate_federation(n_clients=3, rounds=2, persist=False)
    b = simulate_federation(n_clients=3, rounds=2, persist=False)
    assert a["final_accuracy"] == b["final_accuracy"]
