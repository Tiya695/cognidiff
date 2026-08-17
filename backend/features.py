"""Feature engineering — the cognitive signal is built here.

Every feature is defined once, in one place, with its formula, units and valid
range recorded in docs/feature_definitions.md. If a definition changes,
FEATURE_SCHEMA_VERSION in config.py must be bumped: scores computed under
different schema versions are not comparable.

Nothing in this module ever sees typed text. Its inputs are timing arrays and a
sequence of category codes (l/d/s/b/p) — five symbols, no characters.
"""

from __future__ import annotations

import statistics
from typing import Optional, Sequence

# Thresholds. All in milliseconds.
PAUSE_MS = 2_000          # gap that counts as a pause
LONG_PAUSE_MS = 3_000     # gap that counts as a long pause
BURST_MS = 150            # IKI below this is "fluent burst" typing
CORRECTION_GAP_MS = 2_000 # silence that ends a correction episode


# ---------------------------------------------------------------------------
# correction events
# ---------------------------------------------------------------------------

def detect_correction_events(
    key_categories: Sequence[str],
    timestamps: Sequence[float],
    gap_ms: int = CORRECTION_GAP_MS,
) -> dict:
    """Count delete-and-retype episodes.

    Counting *consecutive backspace pairs* is a bad proxy and CogniDiff does not
    use it. Typing "hello wrld", then three separate backspaces spread over a
    second, then retyping "o", is **one** correction — but it may contain no
    consecutive backspace pair at all.

    A correction event here is one continuous delete-and-retype episode:

      * it starts at the first backspace that follows a non-backspace keystroke;
      * it absorbs every backspace and every keystroke occurring within
        ``gap_ms`` of the last backspace;
      * it ends when normal typing resumes for longer than ``gap_ms``.

    One event may contain 1 backspace or 12.

    Returns ``correction_events``, ``mean_keystrokes_deleted_per_event`` and
    ``mean_correction_duration_ms``.
    """
    n = min(len(key_categories), len(timestamps))
    if n == 0:
        return {
            "correction_events": 0,
            "mean_keystrokes_deleted_per_event": 0.0,
            "mean_correction_duration_ms": 0.0,
        }

    events: list[dict] = []
    current: Optional[dict] = None
    prev_cat: Optional[str] = None

    for i in range(n):
        cat = key_categories[i]
        t = float(timestamps[i])

        if cat == "b":
            if current is None:
                # A backspace only *opens* an episode if it follows real typing.
                # A batch that opens on a backspace is a continuation of typing
                # we did not capture, so it is not a new correction.
                if prev_cat is not None and prev_cat != "b":
                    current = {"start": t, "last_backspace": t, "deleted": 1, "end": t}
            else:
                current["deleted"] += 1
                current["last_backspace"] = t
                current["end"] = t
        elif current is not None:
            if t - current["last_backspace"] <= gap_ms:
                # retyping inside the episode
                current["end"] = t
            else:
                events.append(current)
                current = None

        prev_cat = cat

    if current is not None:
        events.append(current)

    if not events:
        return {
            "correction_events": 0,
            "mean_keystrokes_deleted_per_event": 0.0,
            "mean_correction_duration_ms": 0.0,
        }

    return {
        "correction_events": len(events),
        "mean_keystrokes_deleted_per_event": round(
            sum(e["deleted"] for e in events) / len(events), 3
        ),
        "mean_correction_duration_ms": round(
            sum(e["end"] - e["start"] for e in events) / len(events), 2
        ),
    }


# ---------------------------------------------------------------------------
# individual features
# ---------------------------------------------------------------------------

def rhythm_variability(intervals: Sequence[float]) -> float:
    """Population standard deviation of inter-key intervals, in ms.

    Low variability means an even, automatic rhythm. High variability means the
    typing is starting and stopping — hesitation, word-finding, or divided
    attention. It is the feature most sensitive to *how* typing is produced
    rather than how fast.
    """
    clean = [float(i) for i in intervals if 0 < float(i) < 30_000]
    if len(clean) < 2:
        return 0.0
    return round(statistics.pstdev(clean), 2)


def burst_ratio(intervals: Sequence[float]) -> float:
    """Fraction of keystrokes produced inside fluent bursts (IKI < 150 ms).

    High burst ratio means chunks of text arrive as practised motor sequences.
    Range 0.0–1.0.
    """
    clean = [float(i) for i in intervals if float(i) >= 0]
    if not clean:
        return 0.0
    return round(sum(1 for i in clean if i < BURST_MS) / len(clean), 4)


def time_slot(hour: int) -> str:
    """Bucket the hour of day. Baselines are also fitted per slot, because a
    person's 2am typing is not comparable to their 10am typing."""
    h = int(hour) % 24
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"


def _offsets_to_intervals(offsets: Sequence[float]) -> list[float]:
    return [float(offsets[i]) - float(offsets[i - 1]) for i in range(1, len(offsets))]


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

def enrich_batch(raw_batch: dict) -> dict:
    """Turn a raw 60-second extension batch into a full feature row.

    Accepts the extension's field names and normalises them to the database
    schema. Missing timing arrays degrade gracefully: features that cannot be
    computed become 0.0 and the DataQualityEngine will see the gap and mark the
    session MISSING_FEATURES rather than letting a hollow row into the models.
    """
    total = int(raw_batch.get("total_keystrokes", 0) or 0)
    backspaces = int(raw_batch.get("backspace_count", 0) or 0)

    categories = raw_batch.get("key_categories") or ""
    offsets = raw_batch.get("offsets_ms") or []

    intervals = raw_batch.get("intervals_ms")
    if not intervals and len(offsets) >= 2:
        intervals = _offsets_to_intervals(offsets)
    intervals = [float(i) for i in (intervals or [])]

    # error_rate — proportion of keystrokes that were deletions. 0.0–1.0.
    error_rate = round(backspaces / total, 4) if total else 0.0

    corrections = detect_correction_events(categories, offsets)
    correction_rate = (
        round(corrections["correction_events"] / total, 4) if total else 0.0
    )

    long_pauses = raw_batch.get("long_pause_count")
    if long_pauses is None:
        long_pauses = sum(1 for i in intervals if i > LONG_PAUSE_MS)

    pause_count = raw_batch.get("pause_count")
    if pause_count is None:
        pause_count = sum(1 for i in intervals if i > PAUSE_MS)

    hour = int(raw_batch.get("hour", 0) or 0)

    return {
        # passed through from the extension
        "wpm_estimate": float(raw_batch.get("wpm_estimate", 0.0) or 0.0),
        "avg_iki_ms": float(raw_batch.get("avg_inter_key_interval_ms", 0.0) or 0.0),
        "avg_hold_ms": float(raw_batch.get("avg_hold_duration_ms", 0.0) or 0.0),
        "backspace_count": backspaces,
        "total_keystrokes": total,
        "pause_count": int(pause_count),
        "session_minute": int(raw_batch.get("session_minute", 0) or 0),
        "duration_ms": int(raw_batch.get("duration_ms", 0) or 0),
        "device_fingerprint": raw_batch.get("device_fingerprint"),
        "hour": hour,

        # computed here
        "error_rate": error_rate,
        "correction_rate": correction_rate,
        "correction_events": corrections["correction_events"],
        "mean_keys_deleted": corrections["mean_keystrokes_deleted_per_event"],
        "mean_correction_ms": corrections["mean_correction_duration_ms"],
        "rhythm_variability": rhythm_variability(intervals),
        "long_pause_count": int(long_pauses),
        "burst_ratio": burst_ratio(intervals),
        "time_slot": time_slot(hour),

        # retained only for the quality gate, never stored
        "_intervals": intervals,
        "_n_intervals": len(intervals),
    }
