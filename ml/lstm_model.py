"""Longitudinal trend model — next-day CogniScore prediction.

Why a recurrent model at all: a single day's score says almost nothing. Stress,
sleep and a bad keyboard day all move it. The signal CogniDiff is looking for
lives in the *shape of the sequence* over weeks. An LSTM carries a cell state
across time steps and learns, through its forget/input/output gates, which past
days still matter — so a slow downward drift with noisy days on top is
learnable, where a plain feed-forward model sees only seven unordered numbers.

(This is also the answer to the vanishing-gradient question: in a plain RNN the
gradient is multiplied by the recurrent weight at every step, so it decays
geometrically and the model cannot learn long-range dependence. The LSTM's cell
state is updated additively through gates, so gradients flow back along it
without that repeated multiplication.)

torch is optional. Without it, the class falls back to a ridge-regression
predictor over the same window and reports `backend="ridge_fallback"` — never
silently pretending an LSTM ran.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import joblib
import numpy as np

from backend.config import MODEL_DIR, SEED, set_all_seeds

try:  # optional dependency
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:  # pragma: no cover - depends on environment
    torch = None
    nn = object
    HAS_TORCH = False

SEQ_LEN = 7
HIDDEN = 32
EPOCHS = 100
LR = 0.01


if HAS_TORCH:

    class _LSTMNet(nn.Module):
        """1-layer LSTM (hidden 32) → Linear(1)."""

        def __init__(self, hidden: int = HIDDEN):
            super().__init__()
            self.lstm = nn.LSTM(input_size=1, hidden_size=hidden, num_layers=1,
                                batch_first=True)
            self.head = nn.Linear(hidden, 1)

        def forward(self, x):                     # x: (batch, seq, 1)
            out, _ = self.lstm(x)
            return self.head(out[:, -1, :])       # last time step only

else:  # pragma: no cover
    _LSTMNet = None


class LSTMPredictor:
    """Predicts tomorrow's CogniScore from the last 7 daily averages."""

    def __init__(self, user_id: str, seq_len: int = SEQ_LEN):
        self.user_id = user_id
        self.seq_len = seq_len
        self.backend = "lstm_torch" if HAS_TORCH else "ridge_fallback"
        self.net = None
        self.coefs: Optional[np.ndarray] = None      # ridge fallback
        self.intercept = 0.0
        self.mean = 75.0
        self.scale = 15.0
        self.n_train = 0
        self.train_loss: Optional[float] = None

    # -- data ---------------------------------------------------------------

    def _windows(self, series: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
        arr = np.asarray([float(v) for v in series], dtype=float)
        X, y = [], []
        for i in range(len(arr) - self.seq_len):
            X.append(arr[i:i + self.seq_len])
            y.append(arr[i + self.seq_len])
        if not X:
            return np.empty((0, self.seq_len)), np.empty((0,))
        return np.array(X), np.array(y)

    def _norm(self, a: np.ndarray) -> np.ndarray:
        return (a - self.mean) / self.scale

    def _denorm(self, a):
        return a * self.scale + self.mean

    # -- training -----------------------------------------------------------

    def train(self, series: Sequence[float], epochs: int = EPOCHS) -> dict:
        set_all_seeds(SEED)
        X, y = self._windows(series)
        if len(X) < 3:
            raise ValueError(
                f"Need at least {self.seq_len + 3} daily scores to train; "
                f"got {len(series)}."
            )

        flat = np.asarray(series, dtype=float)
        self.mean = float(flat.mean())
        self.scale = float(flat.std()) or 1.0
        self.n_train = len(X)

        Xn, yn = self._norm(X), self._norm(y)

        if HAS_TORCH:
            self.net = _LSTMNet()
            opt = torch.optim.Adam(self.net.parameters(), lr=LR)
            loss_fn = torch.nn.MSELoss()

            xb = torch.tensor(Xn, dtype=torch.float32).unsqueeze(-1)
            yb = torch.tensor(yn, dtype=torch.float32).unsqueeze(-1)

            self.net.train()
            last = 0.0
            for _ in range(epochs):
                opt.zero_grad()
                loss = loss_fn(self.net(xb), yb)
                loss.backward()
                opt.step()
                last = float(loss.item())
            self.train_loss = round(last, 6)
        else:
            # Ridge closed form: w = (XᵀX + λI)⁻¹ Xᵀy, with a bias column.
            lam = 1.0
            A = np.hstack([Xn, np.ones((len(Xn), 1))])
            w = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ yn)
            self.coefs, self.intercept = w[:-1], float(w[-1])
            pred = A @ w
            self.train_loss = round(float(((pred - yn) ** 2).mean()), 6)

        return {
            "backend": self.backend,
            "n_windows": self.n_train,
            "final_loss": self.train_loss,
            "epochs": epochs if HAS_TORCH else 1,
        }

    # -- inference ----------------------------------------------------------

    def predict(self, last_scores: Sequence[float]) -> dict:
        window = [float(v) for v in last_scores][-self.seq_len:]
        if len(window) < self.seq_len:
            # Pad on the left with the earliest known value rather than zero —
            # a zero would look like a catastrophic day that never happened.
            pad = window[0] if window else self.mean
            window = [pad] * (self.seq_len - len(window)) + window

        arr = self._norm(np.array(window, dtype=float))

        if HAS_TORCH and self.net is not None:
            self.net.eval()
            with torch.no_grad():
                x = torch.tensor(arr, dtype=torch.float32).view(1, self.seq_len, 1)
                pred = float(self.net(x).item())
        elif self.coefs is not None:
            pred = float(arr @ self.coefs + self.intercept)
        else:
            # Untrained: naive persistence. This is also the baseline every
            # trained model must beat in docs/evaluation_protocol.md — if the
            # LSTM cannot beat last-value-carried-forward, that is a real
            # finding and gets reported as one.
            return {
                "predicted_score": round(window[-1], 1),
                "backend": "naive_persistence",
                "trend": "unknown",
                "trained": False,
            }

        predicted = round(float(np.clip(self._denorm(pred), 0, 100)), 1)
        delta = predicted - window[-1]

        return {
            "predicted_score": predicted,
            "last_score": round(window[-1], 1),
            "delta": round(delta, 1),
            "trend": "declining" if delta < -1.5 else "improving" if delta > 1.5 else "stable",
            "backend": self.backend,
            "trained": True,
        }

    # -- evaluation ---------------------------------------------------------

    def evaluate(self, series: Sequence[float]) -> dict:
        """MAE/RMSE against the naive last-value-carried-forward baseline."""
        X, y = self._windows(series)
        if len(X) == 0:
            return {"error": "not enough data"}

        preds = np.array([self.predict(list(row))["predicted_score"] for row in X])
        naive = X[:, -1]

        def mae(a, b): return float(np.abs(a - b).mean())
        def rmse(a, b): return float(np.sqrt(((a - b) ** 2).mean()))

        return {
            "n": int(len(y)),
            "model_mae": round(mae(preds, y), 3),
            "model_rmse": round(rmse(preds, y), 3),
            "naive_mae": round(mae(naive, y), 3),
            "naive_rmse": round(rmse(naive, y), 3),
            "beats_naive": bool(mae(preds, y) < mae(naive, y)),
            "backend": self.backend,
        }

    # -- persistence --------------------------------------------------------

    def save(self) -> Path:
        p = Path(MODEL_DIR) / f"lstm_{self.user_id}.pkl"
        p.parent.mkdir(parents=True, exist_ok=True)
        if HAS_TORCH and self.net is not None:
            state = {k: v.cpu().numpy() for k, v in self.net.state_dict().items()}
            joblib.dump({"meta": self._meta(), "torch_state": state}, p)
        else:
            joblib.dump({"meta": self._meta(), "coefs": self.coefs,
                         "intercept": self.intercept}, p)
        return p

    def _meta(self) -> dict:
        return {
            "user_id": self.user_id, "seq_len": self.seq_len,
            "backend": self.backend, "mean": self.mean, "scale": self.scale,
            "n_train": self.n_train, "train_loss": self.train_loss,
        }

    @staticmethod
    def load(user_id: str) -> Optional["LSTMPredictor"]:
        p = Path(MODEL_DIR) / f"lstm_{user_id}.pkl"
        if not p.exists():
            return None
        try:
            blob = joblib.load(p)
        except Exception:
            return None

        meta = blob["meta"]
        m = LSTMPredictor(meta["user_id"], meta["seq_len"])
        m.mean, m.scale = meta["mean"], meta["scale"]
        m.n_train, m.train_loss = meta["n_train"], meta["train_loss"]

        if "torch_state" in blob and HAS_TORCH:
            m.net = _LSTMNet()
            m.net.load_state_dict(
                {k: torch.tensor(v) for k, v in blob["torch_state"].items()}
            )
            m.backend = "lstm_torch"
        elif "coefs" in blob:
            m.coefs, m.intercept = blob["coefs"], blob["intercept"]
            m.backend = "ridge_fallback"
        return m
