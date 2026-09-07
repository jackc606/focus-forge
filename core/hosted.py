"""The hosted assistant relay: where it lives and how its allotment is shown — Qt-free.

Why a separate module: the relay's base URL, allowed model and endpoint paths
are the only things the app must agree with the Worker on (see
``docs/HOSTED_ASSISTANT.md``). Keeping them in one place means attaching a
custom domain later is a one-line change, and the settings dialog, the panel
header and the tests all read the same constants instead of each spelling
the URL.
"""
from __future__ import annotations

import datetime as _dt

HOSTED_BASE_URL = "https://focusforge-assistant.jackclasen02.workers.dev"
HOSTED_MODEL_LABEL = "Focus Forge hosted model"
# The one model the relay allow-lists. Sent as the payload's ``model`` so the
# request shape is identical to own-key mode; the relay rejects anything else.
HOSTED_MODEL_ID = "meta/muse-spark-1.3-contributor"

# Error codes the relay uses (OpenAI envelope ``error.code``). Its messages are
# already plain language, so the app shows them verbatim.
HOSTED_ERROR_CODES = frozenset({
    "bad_token", "allotment_used", "rate_limited", "budget_exhausted", "unsupported",
})

HOSTED_PRIVACY_NOTE = ("Prompts and the parts of your mod the assistant reads are sent to "
                       "Meta through OpenRouter; the contributor tier may use them for training.")


def hosted_chat_base() -> str:
    """The OpenAI-compatible base the loop posts ``/chat/completions`` to."""
    return HOSTED_BASE_URL + "/v1"


def hosted_signin_url() -> str:
    return HOSTED_BASE_URL + "/auth/discord/start"


def hosted_me_url() -> str:
    return HOSTED_BASE_URL + "/v1/me"


def parse_quota_headers(headers) -> "dict | None":
    """``{"used_cents", "limit_cents", "reset"}`` from a response's lower-cased
    header dict, or None when the allotment headers aren't there (own-key
    providers never send them)."""
    if not isinstance(headers, dict):
        return None
    used = _to_float(headers.get("x-ff-used-cents"))
    limit = _to_float(headers.get("x-ff-limit-cents"))
    if used is None or limit is None:
        return None
    return {"used_cents": used, "limit_cents": limit,
            "reset": str(headers.get("x-ff-reset") or "")}


def format_dollars(cents) -> str:
    """``8 -> '$0.08'``; ``50 -> '$0.50'``. Cents keep the relay's precision
    without the app pretending to know sub-cent billing."""
    try:
        return f"${float(cents) / 100:.2f}"
    except (TypeError, ValueError):
        return "$?"


def format_reset(reset: str) -> str:
    """ISO date (or datetime) -> 'Oct 1'; anything unparsable is shown as is."""
    text = str(reset or "").strip()
    try:
        day = _dt.date.fromisoformat(text[:10])
    except ValueError:
        return text
    return f"{day.strftime('%b')} {day.day}"


def format_allotment(quota: dict) -> str:
    """The header fragment after a ``quota`` event: '$0.08 of $0.50 used · resets Oct 1'."""
    text = f"{format_dollars(quota.get('used_cents'))} of {format_dollars(quota.get('limit_cents'))} used"
    reset = format_reset(quota.get("reset") or "")
    return f"{text} · resets {reset}" if reset else text


def _to_float(value) -> "float | None":
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
