"""Plain-language summaries via the Claude API.

This is the *only* place CogniDiff calls an external model, and it is used
sparingly, at most once per user per day. All the machine learning runs
locally at zero cost; Claude is the natural-language communication layer, not
the analysis layer.

What is sent: an already-computed score, feature *names* with percentage
changes, and a trend word. No keystroke data, no timing arrays, no identifiers
beyond a first name the user chose to enter. See docs/privacy_architecture.md.

If the SDK or key is absent, a deterministic local template is used instead and
the response says `source: "local_template"`, the user is never shown
machine-generated prose without knowing where it came from.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL

try:  # optional dependency
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:  # pragma: no cover - depends on environment
    anthropic = None
    HAS_ANTHROPIC = False


SYSTEM_PROMPT = """You are a compassionate health communication assistant for \
CogniDiff, a personal typing-rhythm monitoring tool.

You summarise cognitive monitoring data in simple, non-alarming language.

Hard rules:
- You never diagnose. You never suggest a diagnosis is likely.
- You never mention Alzheimer's, dementia, MCI, or any named condition, even if \
the user's data looks unusual and even if asked.
- You describe what changed in the person's typing, in everyday words.
- You note that sleep, stress, illness and a new keyboard commonly explain these \
changes.
- If a pattern has persisted for more than two weeks, you recommend a \
professional evaluation, calmly, once, without urgency language.
- You never tell the user to worry, and you never tell them not to.

Write 2 to 3 sentences. Second person. Calm, plain, specific. No bullet points, \
no headings, no emoji, no medical jargon."""


def _user_message(
    cogni_score: float,
    top_3_changes: Sequence[dict],
    trend_direction: str,
    user_first_name: Optional[str],
    confidence_band: str,
    days_persisted: int,
) -> str:
    changes = "\n".join(
        f"- {c.get('label', c.get('feature'))}: {c.get('text', '')}"
        for c in top_3_changes
    ) or "- No individual feature moved meaningfully."

    return (
        f"Name: {user_first_name or 'there'}\n"
        f"CogniScore today: {cogni_score:.0f} out of 100 "
        f"(100 = exactly matches their own baseline)\n"
        f"Confidence in today's reading: {confidence_band}\n"
        f"30-day trend: {trend_direction}\n"
        f"Days this pattern has persisted: {days_persisted}\n"
        f"Top changes versus their personal baseline:\n{changes}\n\n"
        f"Write their summary."
    )


def generate_summary(
    cogni_score: float,
    top_3_changes: Sequence[dict],
    trend_direction: str = "stable",
    user_first_name: Optional[str] = None,
    confidence_band: str = "HIGH",
    days_persisted: int = 0,
) -> dict:
    """Return ``{text, source, model}``. Never raises, falls back to a template."""
    if HAS_ANTHROPIC and ANTHROPIC_API_KEY:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300,
                temperature=0.4,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": _user_message(
                        cogni_score, top_3_changes, trend_direction,
                        user_first_name, confidence_band, days_persisted,
                    ),
                }],
            )
            text = "".join(
                block.text for block in response.content
                if getattr(block, "type", None) == "text"
            ).strip()
            if text:
                return {"text": text, "source": "claude_api", "model": CLAUDE_MODEL}
        except Exception as exc:  # network, auth, rate limit, degrade quietly
            return {
                **_template(cogni_score, top_3_changes, trend_direction,
                            user_first_name, confidence_band),
                "note": f"Claude API unavailable ({type(exc).__name__}); "
                        f"used the local template.",
            }

    return _template(cogni_score, top_3_changes, trend_direction,
                     user_first_name, confidence_band)


def _template(
    cogni_score: float,
    top_3_changes: Sequence[dict],
    trend_direction: str,
    user_first_name: Optional[str],
    confidence_band: str,
) -> dict:
    """Deterministic fallback. Same rules as the system prompt above, enforced
    by construction: it can only say the things written here."""
    name = user_first_name or "there"
    lead = top_3_changes[0] if top_3_changes else None

    if cogni_score >= 80:
        opening = (
            f"Hi {name}, your typing today looks much like your usual rhythm, "
            f"scoring {cogni_score:.0f} out of 100 against your own baseline."
        )
    elif cogni_score >= 60:
        opening = (
            f"Hi {name}, today's typing sits a little away from your usual "
            f"pattern, at {cogni_score:.0f} out of 100."
        )
    else:
        opening = (
            f"Hi {name}, today's typing differs noticeably from your usual "
            f"pattern, at {cogni_score:.0f} out of 100."
        )

    detail = (
        f" The clearest change was {lead['text'].lower()}." if lead and lead.get("text")
        else " No single aspect of your typing stood out."
    )

    if confidence_band == "LOW":
        closing = (
            " This reading is based on limited data today, so treat it as "
            "provisional rather than a firm result."
        )
    elif trend_direction == "declining":
        closing = (
            " Sleep, stress, illness and even a new keyboard commonly cause this. "
            "If the pattern continues for more than two weeks, it is worth "
            "mentioning to a healthcare professional."
        )
    else:
        closing = (
            " Day-to-day variation like this is normal and usually reflects "
            "sleep, stress or how busy the day was."
        )

    return {
        "text": opening + detail + closing,
        "source": "local_template",
        "model": None,
    }
