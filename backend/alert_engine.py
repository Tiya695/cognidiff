"""Escalation logic, deliberately slow to alarm.

Cognitive performance varies naturally with stress, sleep, illness and a hundred
other things. A tool that alerts on one bad session is not sensitive; it is
broken, and it costs its user real anxiety for nothing. CogniDiff therefore
escalates only on *persistence*: patterns that survive across multiple days.

No message in this module uses diagnostic language. Nothing here names a disease
or asserts a cause, the strongest thing CogniDiff will ever say is that a
pattern has continued long enough to be worth a professional's opinion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

STATUS_STABLE = "STABLE"
STATUS_MONITOR = "MONITOR"
STATUS_SIGNIFICANT = "SIGNIFICANT_DEVIATION"
STATUS_PERSISTENT = "PERSISTENT_DEVIATION"
STATUS_RECALIBRATING = "RECALIBRATING"
STATUS_INSUFFICIENT = "INSUFFICIENT_DATA"

#: Colour is never the only signal, every state carries a text label and an
#: icon name too, because a red circle means nothing to a colourblind user and
#: nothing at all to a screen reader.
_PRESENTATION = {
    STATUS_STABLE:        ("green",  "Stable",              "check"),
    STATUS_MONITOR:       ("yellow", "Monitoring",          "eye"),
    STATUS_SIGNIFICANT:   ("orange", "Notable deviation",   "alert"),
    STATUS_PERSISTENT:    ("red",    "Persistent deviation", "flag"),
    STATUS_RECALIBRATING: ("blue",   "Recalibrating",       "sync"),
    STATUS_INSUFFICIENT:  ("grey",   "Not enough data",     "clock"),
}


@dataclass
class AlertResult:
    status_code: str
    color: str
    label: str
    icon: str
    user_message: str
    recommend_evaluation: bool = False
    anomalies_7d: int = 0
    trend_30d: Optional[str] = None
    provisional: bool = False

    def as_dict(self) -> dict:
        return {
            "status_code": self.status_code,
            "color": self.color,
            "label": self.label,
            "icon": self.icon,
            "user_message": self.user_message,
            "recommend_evaluation": self.recommend_evaluation,
            "anomalies_7d": self.anomalies_7d,
            "trend_30d": self.trend_30d,
            "provisional": self.provisional,
        }


class AlertEngine:
    """Turns recent scores and anomaly flags into a single presentable state."""

    MIN_SCORES = 3

    def evaluate(
        self,
        user_id: str,
        recent_scores: Sequence[float],
        recent_anomalies: Sequence[bool],
        trend_30d: Optional[str] = None,
        baseline_status: str = "ACTIVE",
        confidence_band: str = "HIGH",
    ) -> AlertResult:
        scores = [float(s) for s in recent_scores if s is not None]
        anomalies_7d = sum(1 for a in list(recent_anomalies)[-7:] if a)

        # --- states that suppress alerting entirely ------------------------

        if baseline_status == "RECALIBRATING":
            # A new keyboard must never be read as cognitive decline.
            return self._build(
                STATUS_RECALIBRATING,
                "Recalibrating to your new setup, scores are provisional and no "
                "alerts will be raised until your new baseline is established.",
                anomalies_7d=anomalies_7d, provisional=True,
            )

        if baseline_status == "INSUFFICIENT_DATA" or len(scores) < self.MIN_SCORES:
            return self._build(
                STATUS_INSUFFICIENT,
                "Still learning your typing patterns. Keep monitoring on for a "
                "couple of weeks and your baseline will settle.",
                anomalies_7d=anomalies_7d, provisional=True,
            )

        if confidence_band == "LOW":
            # A number without its reliability is a misleading number.
            return self._build(
                STATUS_INSUFFICIENT,
                "Today's reading is based on limited data, so it is shown as "
                "provisional. No alert is raised from a low-confidence day.",
                anomalies_7d=anomalies_7d, provisional=True,
            )

        # --- persistent decline: the only state that recommends evaluation --

        if trend_30d == "declining" and anomalies_7d >= 3:
            return self._build(
                STATUS_PERSISTENT,
                "Your typing patterns have shifted steadily over the past month "
                "and the change has persisted. This is worth discussing with a "
                "healthcare professional, bring your report with you.",
                recommend_evaluation=True, anomalies_7d=anomalies_7d,
                trend_30d=trend_30d,
            )

        # --- graded escalation on the 7-day anomaly count -------------------

        if anomalies_7d >= 5:
            return self._build(
                STATUS_SIGNIFICANT,
                "Several sessions this week differed noticeably from your usual "
                "pattern. Often this reflects sleep, stress or illness. If it "
                "continues for more than two weeks, consider a professional "
                "evaluation.",
                anomalies_7d=anomalies_7d, trend_30d=trend_30d,
            )

        if anomalies_7d >= 2:
            return self._build(
                STATUS_MONITOR,
                "A few sessions this week looked different from your baseline. "
                "This is within the range of normal variation, we are keeping "
                "an eye on it.",
                anomalies_7d=anomalies_7d, trend_30d=trend_30d,
            )

        return self._build(
            STATUS_STABLE,
            "Monitoring normally. Your typing patterns are consistent with your "
            "personal baseline.",
            anomalies_7d=anomalies_7d, trend_30d=trend_30d,
        )

    # -- helper -------------------------------------------------------------

    @staticmethod
    def _build(status: str, message: str, **kw) -> AlertResult:
        color, label, icon = _PRESENTATION[status]
        return AlertResult(
            status_code=status, color=color, label=label, icon=icon,
            user_message=message, **kw,
        )
