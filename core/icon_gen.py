"""The image-generation call behind ``generate_icons`` — Qt-free.

One POST to OpenRouter's Images endpoint per icon. It reuses the assistant's
transport conventions (Bearer key, JSON, OpenRouter attribution headers,
``friendly_http_error``) so a 402 or 429 reads exactly like the chat loop's.
Documented as OpenRouter-only for now: any other base URL is still sent
``{base}/images`` and will most likely 404 — the settings dialog says so.
"""
from __future__ import annotations

import base64
import json
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .agent_loop import (
    AgentConfig,
    TransportError,
    default_extra_headers,
    friendly_http_error,
    provider_error_message,
)

DEFAULT_IMAGE_MODEL = "microsoft/mai-image-2.6-flash"
# What one icon roughly costs on the default model; shown to the model as an
# estimate before it commits a whole branch.
EST_COST_PER_ICON_USD = 0.03


@dataclass
class ImageConfig:
    base_url: str
    api_key: str
    model: str = DEFAULT_IMAGE_MODEL
    timeout_s: int = 120


@dataclass
class GeneratedImage:
    png_bytes: bytes
    cost_usd: Optional[float]
    model: str
    media_type: str = "image/png"


class OpenRouterImages:
    """``generate(prompt, cfg)`` -> :class:`GeneratedImage`. Raises
    :class:`TransportError` with a user-facing message on any failure."""

    def generate(self, prompt: str, cfg: ImageConfig) -> GeneratedImage:
        url = cfg.base_url.rstrip("/") + "/images"
        payload = {"model": cfg.model, "prompt": prompt, "n": 1, "aspect_ratio": "1:1"}
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "FocusForge-Assistant",
        }
        headers.update(default_extra_headers(cfg.base_url))
        body = json.dumps(payload).encode("utf-8")
        raw = self._send(Request(url, data=body, headers=headers, method="POST"), cfg)
        return self._parse(raw, cfg.model)

    @staticmethod
    def _send(request: Request, cfg: ImageConfig) -> str:
        try:
            with urlopen(request, timeout=cfg.timeout_s) as resp:
                return resp.read().decode("utf-8", "replace")
        except HTTPError as exc:
            try:
                err_body = exc.read().decode("utf-8", "replace")
            except Exception:
                err_body = ""
            raise TransportError(exc.code, friendly_http_error(exc.code, err_body)) from exc
        except (URLError, socket.timeout, OSError) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise TransportError(0, f"Couldn't reach the image provider ({reason}).") from exc

    @staticmethod
    def _parse(raw: str, model: str) -> GeneratedImage:
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise TransportError(0, "The image provider returned something that wasn't JSON.") from exc
        if not isinstance(data, dict):
            raise TransportError(0, "The image provider returned an unexpected response shape.")
        if "error" in data and not data.get("data"):
            raise TransportError(0, provider_error_message(raw) or "Image provider error")
        items = data.get("data") or []
        first = items[0] if items and isinstance(items[0], dict) else {}
        b64 = first.get("b64_json")
        if not isinstance(b64, str) or not b64:
            raise TransportError(0, "The image provider returned no image data.")
        try:
            png = base64.b64decode(b64)
        except (ValueError, TypeError) as exc:
            raise TransportError(0, "The image provider returned unreadable image data.") from exc
        usage = data.get("usage") or {}
        cost = usage.get("cost") if isinstance(usage, dict) else None
        try:
            cost = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost = None
        return GeneratedImage(png_bytes=png, cost_usd=cost,
                              model=str(data.get("model") or model),
                              media_type=str(first.get("media_type") or "image/png"))


def image_config_from_assistant(cfg: AgentConfig, image_model: str = "") -> "ImageConfig | None":
    """The image endpoint config implied by the assistant settings, or None
    when icons can't be generated: hosted mode (the relay's allotment doesn't
    cover images yet) or an own-key pane with no key."""
    if cfg is None or cfg.is_hosted() or not (cfg.api_key or "").strip():
        return None
    model = (image_model or getattr(cfg, "image_model", "") or DEFAULT_IMAGE_MODEL).strip()
    return ImageConfig(base_url=cfg.base_url or AgentConfig().base_url,
                       api_key=cfg.api_key.strip(), model=model or DEFAULT_IMAGE_MODEL,
                       timeout_s=int(getattr(cfg, "timeout_s", 120) or 120))
