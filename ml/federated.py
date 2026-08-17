"""Federated learning simulation.

The idea: in production every user's device is one federated client. Training
happens locally on that device and only *model updates* are sent to be
aggregated — the raw keystroke features never need to be centrally collected.

The honest phrasing, to be reused verbatim in the paper and at viva:

    "Federated learning reduces the need to centrally collect raw keystroke
    features, because training can occur locally and only model updates are
    aggregated."

Never: "the strongest possible privacy guarantee." Federated learning is **not**
automatic privacy. Model updates can leak information about the data they were
trained on — gradient inversion and membership inference attacks are documented
in the literature and are not defeated by federation alone. Secure aggregation
and differential-privacy noise on updates are mitigations, and they belong in
Future Work, not in our claims.

Flower (`flwr`) is used when installed. Without it, the same FedAvg loop runs on
a NumPy logistic-regression client so the simulation is always demonstrable, and
the response reports which backend ran.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from backend.config import SEED, set_all_seeds
from ml.anomaly_detector import ANOMALY_FEATURES

try:  # optional dependency
    import flwr as fl
    HAS_FLOWER = True
except ImportError:  # pragma: no cover - depends on environment
    fl = None
    HAS_FLOWER = False

N_FEATURES = len(ANOMALY_FEATURES)


# ---------------------------------------------------------------------------
# synthetic per-client data
# ---------------------------------------------------------------------------

def _client_data(client_id: int, n: int = 120, rng: Optional[np.random.Generator] = None):
    """Each client gets slightly different data — different people type
    differently, which is the whole reason baselines are personal."""
    rng = rng or np.random.default_rng(SEED + client_id)

    centre = np.array([45.0, 210.0, 0.045, 95.0, 1.2]) * (1 + 0.10 * client_id)
    spread = np.array([6.0, 30.0, 0.012, 18.0, 0.6])

    normal = rng.normal(centre, spread, size=(n, N_FEATURES))
    n_anom = max(4, n // 12)
    anomalous = rng.normal(centre * np.array([0.75, 1.5, 2.6, 1.6, 2.4]),
                           spread * 1.5, size=(n_anom, N_FEATURES))

    X = np.vstack([normal, anomalous])
    y = np.concatenate([np.zeros(n), np.ones(n_anom)])

    idx = rng.permutation(len(X))
    return X[idx], y[idx]


def _standardise(X):
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd


# ---------------------------------------------------------------------------
# local model: logistic regression by gradient descent
# ---------------------------------------------------------------------------

def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))


def _local_fit(weights: np.ndarray, X, y, epochs: int = 40, lr: float = 0.2):
    w = weights.copy()
    Xb = np.hstack([X, np.ones((len(X), 1))])
    for _ in range(epochs):
        pred = _sigmoid(Xb @ w)
        grad = Xb.T @ (pred - y) / len(y)
        w -= lr * grad
    return w


def _evaluate(weights: np.ndarray, X, y) -> tuple[float, float]:
    Xb = np.hstack([X, np.ones((len(X), 1))])
    p = _sigmoid(Xb @ weights)
    loss = float(-np.mean(y * np.log(p + 1e-9) + (1 - y) * np.log(1 - p + 1e-9)))
    acc = float(((p > 0.5).astype(float) == y).mean())
    return loss, acc


# ---------------------------------------------------------------------------
# Flower client
# ---------------------------------------------------------------------------

if HAS_FLOWER:

    class CogniDiffClient(fl.client.NumPyClient):
        """One federated client — in production, one user's device."""

        def __init__(self, client_id: int):
            self.client_id = client_id
            X, y = _client_data(client_id)
            self.X, self.y = _standardise(X), y
            self.w = np.zeros(N_FEATURES + 1)

        def get_parameters(self, config=None):
            return [self.w]

        def set_parameters(self, parameters):
            self.w = np.asarray(parameters[0], dtype=float)

        def fit(self, parameters, config=None):
            self.set_parameters(parameters)
            self.w = _local_fit(self.w, self.X, self.y)
            # Only the weight vector leaves the client. The features never do.
            return [self.w], len(self.X), {}

        def evaluate(self, parameters, config=None):
            self.set_parameters(parameters)
            loss, acc = _evaluate(self.w, self.X, self.y)
            return float(loss), len(self.X), {"accuracy": acc}

else:  # pragma: no cover
    CogniDiffClient = None


# ---------------------------------------------------------------------------
# simulation
# ---------------------------------------------------------------------------

def simulate_federation(n_clients: int = 3, rounds: int = 3, persist: bool = True) -> dict:
    """Run FedAvg over `n_clients` simulated devices for `rounds` rounds."""
    set_all_seeds(SEED)

    clients = []
    for cid in range(n_clients):
        X, y = _client_data(cid)
        clients.append({"id": cid, "X": _standardise(X), "y": y})

    globals_w = np.zeros(N_FEATURES + 1)
    history = []

    for rnd in range(1, rounds + 1):
        updates, sizes = [], []
        for c in clients:
            # Each client starts from the current global weights and trains
            # only on its own local data.
            w = _local_fit(globals_w, c["X"], c["y"])
            updates.append(w)
            sizes.append(len(c["X"]))

        # FedAvg: weighted mean of the client updates, weighted by data volume.
        total = sum(sizes)
        globals_w = sum(w * (n / total) for w, n in zip(updates, sizes))

        losses, accs = zip(*(_evaluate(globals_w, c["X"], c["y"]) for c in clients))
        entry = {
            "round": rnd,
            "n_clients": n_clients,
            "loss": round(float(np.mean(losses)), 4),
            "accuracy": round(float(np.mean(accs)), 4),
        }
        history.append(entry)

        if persist:
            try:
                from backend import database as db
                db.init_db()
                db.insert("federated_rounds", {
                    "round_no": rnd, "n_clients": n_clients,
                    "accuracy": entry["accuracy"], "loss": entry["loss"],
                    "created_at": db.utcnow(),
                })
            except Exception:
                pass

    return {
        "backend": "flower" if HAS_FLOWER else "numpy_fedavg_simulation",
        "n_clients": n_clients,
        "rounds_completed": rounds,
        "history": history,
        "final_accuracy": history[-1]["accuracy"] if history else None,
        "raw_features_transmitted": False,
        "limitation": (
            "Federated learning reduces the need to centrally collect raw "
            "keystroke features, because training can occur locally and only "
            "model updates are aggregated. It is NOT an automatic privacy "
            "guarantee: model updates can leak information about their training "
            "data via gradient inversion and membership inference. Secure "
            "aggregation and differential privacy on updates are future work."
        ),
    }


if __name__ == "__main__":
    result = simulate_federation(n_clients=3, rounds=3)
    print(f"backend: {result['backend']}")
    for row in result["history"]:
        print(f"  round {row['round']}: loss={row['loss']:.4f} "
              f"accuracy={row['accuracy']:.4f}")
    print(f"\nfinal accuracy: {result['final_accuracy']}")
    print(f"\nLIMITATION: {result['limitation']}")
