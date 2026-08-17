"""CogniDiff machine-learning package.

Four complementary models, each catching a different kind of change:

  baseline.py         statistical deviation from the user's own baseline
  anomaly_detector.py unsupervised IsolationForest outlier detection
  lstm_model.py       longitudinal next-day trend prediction
  xgb_model.py        exploratory pseudo-label classifier (NOT clinically validated)

plus explainer.py (SHAP), drift_detector.py, ablation.py and federated.py.
"""
