"""Per-model token prices for the in-app assistant's running cost label — Qt-free.

Prices are USD per million tokens (input, output). They're only an estimate
shown next to the token counts so the user has a feel for what a session is
costing; billing truth is the provider's dashboard. Unknown models show "~$?"
rather than a made-up number.
"""
from __future__ import annotations

# model id -> (price_in_per_m, price_out_per_m, price_cached_in_per_m), USD per 1M
# tokens. Cached input is what the provider charges for prompt-cache hits — on
# Muse Spark contributor it is 50x cheaper than fresh input, which is the whole
# reason the label shows the cached share.
MODEL_PRICES: dict = {
    "meta/muse-spark-1.3-contributor": (0.10, 0.20, 0.002),
    "meta/muse-spark-1.3": (0.10, 0.20, 0.002),
}

DEFAULT_MODEL = "meta/muse-spark-1.3-contributor"


def prices_for(model: str):
    """``(in, out, cached_in)`` per-million prices for ``model``, or None when unknown.
    OpenRouter variant suffixes (``:free``, ``:nitro``) fall back to the base id."""
    if not model:
        return None
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    base = model.split(":", 1)[0]
    return MODEL_PRICES.get(base)


def _short_tokens(n: int) -> str:
    """12345 -> '12.3k'; 999 -> '999'; 2_400_000 -> '2.4M'."""
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def format_cost(usage, model: str) -> str:
    """'~$0.002' from a :class:`core.agent_loop.Usage`, or '~$?' for unknown models."""
    prices = prices_for(model)
    if prices is None:
        return "~$?"
    cost = usage.cost_usd(*prices)
    if cost >= 0.01:
        return f"~${cost:.2f}"
    return f"~${cost:.3f}"


def format_tokens(usage) -> str:
    """'12.4k in · 2.1k out', with the cached share when the provider reported
    prompt-cache hits: '1.0M in (82% cached) · 30.0k out'. The hosted header
    uses this alone — the relay's allotment is the bill there, not an estimate."""
    prompt = int(usage.prompt_tokens or 0)
    cached = int(getattr(usage, "cached_tokens", 0) or 0)
    writes = int(getattr(usage, "cache_write_tokens", 0) or 0)
    if prompt and cached:
        cached_note = f" ({round(100 * cached / prompt)}% cached)"
    elif writes:
        cached_note = " (cache primed)"   # written this session, not read back yet
    else:
        cached_note = ""
    return f"{_short_tokens(prompt)} in{cached_note} · {_short_tokens(usage.completion_tokens)} out"


def format_usage(usage, model: str) -> str:
    """The own-key header label: '12.4k in · 2.1k out · ~$0.002'."""
    return f"{format_tokens(usage)} · {format_cost(usage, model)}"
