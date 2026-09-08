"""Assistant-driven focus icon generation: prompt builder, chroma key / trim /
fit, the OpenRouter Images call (urlopen mocked — never a real API), the
background job runner (offscreen, fake generator), the two bridge ops, settings
round-trip, the panel card and the export path of a generated icon."""
from __future__ import annotations

import base64
import io
import json
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QBuffer, QIODevice, QSettings
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core import icon_gen
from core.agent_loop import (
    CAPABILITIES_TEXT,
    AgentConfig,
    TransportError,
    default_tools,
)
from core.bridge_dispatch import OP_SPECS, dispatch, tool_schemas
from core.bridge_specs import GUI_ONLY_OPS
from core.icon_gen import (
    GeneratedImage,
    ImageConfig,
    OpenRouterImages,
    image_config_from_assistant,
)
from core.icon_image import is_magenta_like, key_image
from core.icon_prompt import (
    ACCENTS,
    FALLBACK_ACCENT,
    ICON_PROMPT_TEMPLATE,
    PALETTES,
    accent_for,
    build_icon_prompt,
    default_subject,
    theme_for_filters,
)
from core.md_focus_guide import MD_FOCUS_GUIDE, PROCEDURE
from core.types import ExportSettings, FocusForgeProject, FocusNodeData

MAGENTA = QColor(255, 0, 255)
GREY = QColor(120, 120, 130)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ----- synthetic images -------------------------------------------------------------

def _png(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _subject_png(size=256, stripe=True) -> bytes:
    """Magenta canvas, a grey rectangle, and a small magenta stripe INSIDE it."""
    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(MAGENTA)
    p = QPainter(img)
    p.fillRect(size // 5, size // 4, size * 3 // 5, size // 2, GREY)
    if stripe:
        p.fillRect(size * 2 // 5, size // 2 - size // 32, size // 5, size // 16, MAGENTA)
    p.end()
    return _png(img)


def _empty_png(size=64) -> bytes:
    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(MAGENTA)
    return _png(img)


def _load(png: bytes) -> QImage:
    img = QImage()
    assert img.loadFromData(png)
    return img.convertToFormat(QImage.Format_ARGB32)


# ----- prompt builder ------------------------------------------------------------------

def test_template_is_intact_and_filled():
    text = build_icon_prompt("a control tower and a passenger jet", object_count=2,
                             palette=PALETTES["economy"], accent="Mexican green")
    assert "Only 2 object(s) and nothing else: a control tower and a passenger jet." in text
    assert "pure magenta (#FF00FF)" in text and "95 by 85 pixels" in text
    assert "Square image, 1024 by 1024." in text
    assert "steel grey, faded navy, warm concrete tan, one accent of Mexican green" in text
    assert "{" not in text and "}" not in text
    assert ICON_PROMPT_TEMPLATE.count("{") == 4


def test_object_count_is_clamped_and_subject_cleaned():
    lo = build_icon_prompt("  a tank\n on tracks. ", object_count=0, palette="p", accent="a")
    hi = build_icon_prompt("a tank", object_count=7, palette="p", accent="a")
    bad = build_icon_prompt("a tank", object_count="x", palette="p", accent="a")
    assert "Only 1 object(s) and nothing else: a tank on tracks." in lo
    assert "Only 2 object(s)" in hi and "Only 2 object(s)" in bad


def test_palette_and_accent_lookup():
    assert theme_for_filters(["FOCUS_FILTER_ARMY"]) == "military"
    assert theme_for_filters(["FOCUS_FILTER_MILITARY_LAWS"]) == "military"
    assert theme_for_filters(["FOCUS_FILTER_INTERNAL_AFFAIRS"]) == "politics"
    assert theme_for_filters(["FOCUS_FILTER_FOREIGN_POLICY"]) == "politics"
    assert theme_for_filters(["FOCUS_FILTER_RESEARCH"]) == "research"
    assert theme_for_filters(["FOCUS_FILTER_INDUSTRY"]) == "economy"
    assert theme_for_filters([]) == "economy"
    assert PALETTES["default"] == PALETTES["economy"]
    assert accent_for("MEX") == ACCENTS["MEX"] == "Mexican green"
    assert accent_for("mex") == "Mexican green"
    assert accent_for("ZZZ") == FALLBACK_ACCENT and accent_for("") == FALLBACK_ACCENT


def test_default_subject_from_title_and_first_sentence():
    f = FocusNodeData(id="MEX_air", title="Airport Expansion",
                      description="A new terminal opens at Benito Juárez. Traffic doubles.")
    assert default_subject(f) == "Airport Expansion: A new terminal opens at Benito Juárez"
    assert default_subject(FocusNodeData(id="MEX_x", title="Only Title")) == "Only Title"


# ----- chroma key / trim / fit -----------------------------------------------------------

def test_magenta_test_matches_spec_bounds():
    assert is_magenta_like(255, 0, 255)
    assert is_magenta_like(255, 128, 255)        # pink, S=0.5
    assert not is_magenta_like(0, 0, 255)        # blue, hue 240
    assert not is_magenta_like(255, 0, 0)        # red, hue 0
    assert not is_magenta_like(200, 180, 220)    # lavender, S < 0.35
    assert not is_magenta_like(50, 0, 50)        # too dark, V < 0.25
    assert not is_magenta_like(120, 120, 130)    # the grey subject


def test_key_image_keeps_interior_magenta_and_reports_fraction():
    w = h = 16
    px = bytearray(b"\xff\x00\xff\xff" * (w * h))
    for y in range(4, 12):
        for x in range(4, 12):
            o = (y * w + x) * 4
            px[o:o + 4] = bytes([120, 120, 130, 255])
    px[(8 * w + 8) * 4:(8 * w + 8) * 4 + 4] = b"\xff\x00\xff\xff"   # interior stripe pixel
    res = key_image(bytes(px), w, h)
    assert res.bbox == (4, 4, 12, 12)
    assert res.rgba[3] == 0                                    # corner transparent
    inner = (8 * w + 8) * 4
    assert res.rgba[inner + 3] == 255 and res.rgba[inner] == 255   # stripe kept
    assert abs(res.background_fraction - (256 - 64) / 256) < 1e-9


def test_process_icon_keys_trims_fits_and_keeps_interior_stripe(qapp):
    from ui.icon_image import process_icon
    out = _load(process_icon(_subject_png()))
    assert (out.width(), out.height()) == (95, 85)
    for x, y in ((0, 0), (94, 0), (0, 84), (94, 84)):
        assert out.pixelColor(x, y).alpha() == 0
    # Subject (3:2) fills the width; centred vertically with a symmetric transparent band.
    assert out.pixelColor(47, 42).alpha() == 255
    top = next(y for y in range(85) if out.pixelColor(47, y).alpha() > 0)
    bottom = next(y for y in range(84, -1, -1) if out.pixelColor(47, y).alpha() > 0)
    assert abs(top - (84 - bottom)) <= 1
    # The interior magenta stripe survived (not border-connected) — some
    # strongly magenta opaque pixels remain inside the subject.
    kept = [out.pixelColor(x, y) for y in range(top, bottom + 1) for x in range(20, 75)]
    assert any(c.alpha() == 255 and c.red() > 200 and c.green() < 80 and c.blue() > 200
               for c in kept)


def test_process_icon_custom_target_and_empty_detection(qapp):
    from ui.icon_image import EmptyImageError, is_mostly_background, process_icon
    out = _load(process_icon(_subject_png(stripe=False), target=(100, 88)))
    assert (out.width(), out.height()) == (100, 88)
    assert is_mostly_background(_empty_png()) is True
    assert is_mostly_background(_subject_png()) is False
    assert is_mostly_background(b"not a png") is True
    with pytest.raises(EmptyImageError):
        process_icon(_empty_png())
    with pytest.raises(ValueError):
        process_icon(b"garbage")


# ----- OpenRouter images call (urlopen mocked) -------------------------------------------

class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(monkeypatch, body: dict, status=None, seen=None):
    from urllib.error import HTTPError

    def fake(request, timeout=None):
        if seen is not None:
            seen.append((request, timeout))
        raw = json.dumps(body).encode("utf-8")
        if status is not None:
            raise HTTPError(request.full_url, status, "err", {}, io.BytesIO(raw))
        return _FakeResponse(raw)

    monkeypatch.setattr(icon_gen, "urlopen", fake)


def test_generate_posts_expected_body_and_headers(monkeypatch):
    seen = []
    png = _empty_png()
    _fake_urlopen(monkeypatch, {"data": [{"b64_json": base64.b64encode(png).decode(),
                                          "media_type": "image/png"}],
                                "usage": {"cost": 0.031}, "model": "microsoft/mai-image-2.6-flash"},
                  seen=seen)
    cfg = ImageConfig(base_url="https://openrouter.ai/api/v1", api_key="sk-or-x", timeout_s=77)
    image = OpenRouterImages().generate("draw a tower", cfg)
    assert isinstance(image, GeneratedImage)
    assert image.png_bytes == png and image.cost_usd == 0.031
    assert image.model == "microsoft/mai-image-2.6-flash" and image.media_type == "image/png"
    request, timeout = seen[0]
    assert request.full_url == "https://openrouter.ai/api/v1/images"
    assert request.get_method() == "POST" and timeout == 77
    body = json.loads(request.data.decode("utf-8"))
    assert body == {"model": "microsoft/mai-image-2.6-flash", "prompt": "draw a tower",
                    "n": 1, "aspect_ratio": "1:1"}
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["authorization"] == "Bearer sk-or-x"
    assert headers["content-type"] == "application/json"
    assert headers["http-referer"] == "https://focusforgemod.com"
    assert headers["x-title"] == "Focus Forge"


def test_generate_without_openrouter_base_has_no_attribution_headers(monkeypatch):
    seen = []
    _fake_urlopen(monkeypatch, {"data": [{"b64_json": base64.b64encode(b"x").decode()}]},
                  seen=seen)
    cfg = ImageConfig(base_url="https://example.com/v1", api_key="k")
    image = OpenRouterImages().generate("p", cfg)
    assert image.cost_usd is None
    headers = {k.lower() for k, _ in seen[0][0].header_items()}
    assert "http-referer" not in headers and seen[0][0].full_url == "https://example.com/v1/images"


@pytest.mark.parametrize("status, text", [(402, "Out of credits"), (429, "Rate limited")])
def test_http_errors_map_to_friendly_transport_errors(monkeypatch, status, text):
    _fake_urlopen(monkeypatch, {"error": {"message": "nope"}}, status=status)
    with pytest.raises(TransportError) as info:
        OpenRouterImages().generate("p", ImageConfig(base_url="https://openrouter.ai/api/v1",
                                                     api_key="k"))
    assert info.value.status == status and info.value.message.startswith(text)
    assert "nope" in info.value.message


def test_bad_payloads_are_transport_errors(monkeypatch):
    cfg = ImageConfig(base_url="https://openrouter.ai/api/v1", api_key="k")
    _fake_urlopen(monkeypatch, {"data": []})
    with pytest.raises(TransportError, match="no image data"):
        OpenRouterImages().generate("p", cfg)
    _fake_urlopen(monkeypatch, {"error": {"message": "model offline"}})
    with pytest.raises(TransportError, match="model offline"):
        OpenRouterImages().generate("p", cfg)


def test_image_config_from_assistant_own_vs_hosted():
    own = AgentConfig(mode="own", api_key=" sk-or-a ", base_url="https://openrouter.ai/api/v1",
                      image_model="google/gemini-2.5-flash-image")
    cfg = image_config_from_assistant(own, own.image_model)
    assert cfg == ImageConfig(base_url="https://openrouter.ai/api/v1", api_key="sk-or-a",
                              model="google/gemini-2.5-flash-image", timeout_s=120)
    assert image_config_from_assistant(own).model == "google/gemini-2.5-flash-image"
    assert image_config_from_assistant(AgentConfig(mode="hosted", hosted_token="ffa_x",
                                                   api_key="sk-or-a")) is None
    assert image_config_from_assistant(AgentConfig(mode="own", api_key="")) is None


# ----- job runner (offscreen, fake generator) -------------------------------------------

class _FakeGenerator:
    """Blocks each call on a gate so tests control timing and see concurrency."""

    def __init__(self, png_for=None, fail_for=()) -> None:
        self.png_for = png_for or {}
        self.fail_for = set(fail_for)
        self.gate = threading.Event()
        self.gate.set()
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.prompts: list = []

    def __call__(self, prompt, cfg):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.prompts.append(prompt)
        try:
            self.gate.wait(5)
            fid = next((k for k in self.png_for if k in prompt), None)
            if fid in self.fail_for:
                raise TransportError(402, "Out of credits")
            return GeneratedImage(png_bytes=self.png_for.get(fid, _subject_png()),
                                  cost_usd=0.03, model="fake")
        finally:
            with self.lock:
                self.active -= 1


def _pump(qapp, runner, until, timeout=10.0):
    t0 = time.time()
    while not until() and time.time() - t0 < timeout:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert until(), "runner did not reach the expected state in time"


def _runner(qapp, gen, **kw):
    from ui.icon_jobs import IconJobRunner
    from ui.project_model import ProjectModel
    model = ProjectModel()
    ids = [f.id for f in model.project.focuses]
    runner = IconJobRunner(model, generate=gen, **kw)
    return runner, model, ids


def _cfg():
    return ImageConfig(base_url="https://openrouter.ai/api/v1", api_key="k")


def test_runner_lifecycle_applies_icon_data_and_emits(qapp):
    gen = _FakeGenerator()
    runner, model, ids = _runner(qapp, gen)
    ready, changed = [], []
    runner.icon_ready.connect(ready.append)
    runner.jobs_changed.connect(lambda: changed.append(1))
    gen.gate.clear()
    created = runner.queue([{"focus_id": ids[0], "subject": "a tower",
                             "prompt": f"tower {ids[0]}"}], _cfg())
    assert created[0]["focus_id"] == ids[0] and created[0]["state"] == "queued"
    qapp.processEvents()
    job = runner.status()["jobs"][0]
    assert job["state"] == "running" and job["started"] is not None
    assert runner.active_ids() == {ids[0]}
    gen.gate.set()
    _pump(qapp, runner, lambda: runner.status()["summary"]["done"] == 1)
    focus = model.find_focus(ids[0])
    assert focus.icon == "" and focus.iconData
    img = _load(base64.b64decode(focus.iconData))
    assert (img.width(), img.height()) == (95, 85)
    assert ready == [ids[0]] and changed
    status = runner.status()
    assert status["summary"] == {"queued": 0, "running": 0, "done": 1, "failed": 0}
    assert status["cost_usd"] == 0.03 and status["jobs"][0]["finished"] is not None
    assert set(status["jobs"][0]) == {"focus_id", "subject", "state", "reason",
                                      "cost_usd", "started", "finished"}
    assert runner.active_ids() == set()


def test_runner_failure_paths_never_raise(qapp):
    gen = _FakeGenerator(png_for={"A": _empty_png(), "B": _subject_png()}, fail_for={"B"})
    runner, model, ids = _runner(qapp, gen)
    failed = []
    runner.icon_failed.connect(lambda fid, reason: failed.append((fid, reason)))
    before = model.find_focus(ids[0]).iconData
    runner.queue([{"focus_id": ids[0], "subject": "s", "prompt": "A"},
                  {"focus_id": ids[1], "subject": "s", "prompt": "B"}], _cfg())
    _pump(qapp, runner, lambda: runner.status()["summary"]["failed"] == 2)
    reasons = dict(failed)
    assert reasons[ids[0]] == "the image came back empty"
    assert reasons[ids[1]].startswith("Out of credits")
    assert model.find_focus(ids[0]).iconData == before
    jobs = {j["focus_id"]: j for j in runner.status()["jobs"]}
    assert jobs[ids[0]]["reason"] == "the image came back empty"
    assert runner.status()["cost_usd"] == 0


def test_runner_runs_two_at_a_time_and_skips_active(qapp):
    gen = _FakeGenerator()
    runner, model, ids = _runner(qapp, gen)
    gen.gate.clear()
    items = [{"focus_id": fid, "subject": "s", "prompt": f"p {fid}"} for fid in ids[:3]]
    created = runner.queue(items, _cfg())
    assert len(created) == 3
    _pump(qapp, runner, lambda: gen.active == 2)
    summary = runner.status()["summary"]
    assert summary["running"] == 2 and summary["queued"] == 1
    # Re-queueing an active focus is a no-op.
    assert runner.queue([items[0]], _cfg()) == []
    gen.gate.set()
    _pump(qapp, runner, lambda: runner.status()["summary"]["done"] == 3)
    assert gen.max_active == 2
    assert len(gen.prompts) == 3
    assert all(model.find_focus(fid).iconData for fid in ids[:3])


# ----- bridge ops --------------------------------------------------------------------------

def _bridge(qapp, runner=None, cfg=None):
    from ui.agent_bridge import AgentBridge
    from ui.project_model import ProjectModel
    b = AgentBridge.__new__(AgentBridge)
    b._model = runner._model if runner is not None else ProjectModel()
    b._scene = None
    b._token = "t"
    b._icon_runner = runner
    b._config_loader = (lambda: cfg) if cfg is not None else None
    return b


def _own_cfg(enabled=True):
    return AgentConfig(mode="own", api_key="sk-or-k", icons_enabled=enabled)


def test_generate_icons_refusals(qapp):
    gen = _FakeGenerator()
    runner, model, ids = _runner(qapp, gen)
    items = [{"focus_id": ids[0], "subject": "a tower"}]
    off = _bridge(qapp, runner, _own_cfg(enabled=False)).run_gui_op("generate_icons", {"items": items})
    assert off["ok"] is False and "Icon generation is off" in off["error"]
    assert "search_icons" in off["error"]
    hosted = AgentConfig(mode="hosted", hosted_token="ffa_x", icons_enabled=True)
    no_key = _bridge(qapp, runner, hosted).run_gui_op("generate_icons", {"items": items})
    assert no_key["ok"] is False and "own OpenRouter key" in no_key["error"]
    none = _bridge(qapp, None, _own_cfg()).run_gui_op("generate_icons", {"items": items})
    assert none["ok"] is False and "icon runner" in none["error"]
    assert gen.prompts == []


def test_generate_icons_validates_items(qapp):
    gen = _FakeGenerator()
    runner, model, ids = _runner(qapp, gen)
    b = _bridge(qapp, runner, _own_cfg())
    for bad, needle in (({}, "items"), ({"items": []}, "non-empty"),
                        ({"items": ["x"]}, "items[1]"),
                        ({"items": [{"focus_id": "NOPE", "subject": "s"}]}, "no focus 'NOPE'"),
                        ({"items": [{"focus_id": ids[0], "subject": "s", "theme": "space"}]},
                         "theme must be one of"),
                        ({"items": [{"focus_id": ids[0]}] * 26}, "at most 25"),
                        ({"itemz": []}, "Unknown arg")):
        resp = b.run_gui_op("generate_icons", bad)
        assert resp["ok"] is False and needle in resp["error"], (bad, resp)
    assert gen.prompts == [] and runner.status()["jobs"] == []


def test_generate_icons_queues_immediately_and_builds_prompts(qapp):
    gen = _FakeGenerator()
    gen.gate.clear()
    runner, model, ids = _runner(qapp, gen)
    model.update_project_meta(countryTag="MEX")
    model.update_focus(ids[0], filters=["FOCUS_FILTER_ARMY"])
    b = _bridge(qapp, runner, _own_cfg())
    t0 = time.time()
    resp = b.run_gui_op("generate_icons", {"items": [
        {"focus_id": ids[0], "subject": "a tank", "object_count": 1},
        {"focus_id": ids[1], "subject": "a ballot box", "theme": "politics", "accent": "gold"},
        {"focus_id": ids[2]},
    ]})
    assert time.time() - t0 < 2.0, "generate_icons must not wait for the images"
    assert resp["ok"], resp
    r = resp["result"]
    assert r["queued"] == ids[:3] and r["already_running"] == []
    assert r["estimated_cost_usd"] == 0.09 and "icon_jobs" in r["note"]
    _pump(qapp, runner, lambda: gen.active == 2)
    prompts = "\n".join(gen.prompts)
    assert "Only 1 object(s) and nothing else: a tank." in prompts
    assert PALETTES["military"] in prompts and "Mexican green" in prompts
    # Re-request while running: reported, not duplicated.
    again = b.run_gui_op("generate_icons", {"items": [{"focus_id": ids[0], "subject": "x"}]})
    assert again["result"]["queued"] == [] and again["result"]["already_running"] == [ids[0]]
    gen.gate.set()
    _pump(qapp, runner, lambda: runner.status()["summary"]["done"] == 3)
    prompts = "\n".join(gen.prompts)
    assert PALETTES["politics"] in prompts and "one accent of gold" in prompts
    # The third item had no subject: the title-based fallback was used.
    third = [j for j in runner.status()["jobs"] if j["focus_id"] == ids[2]][0]
    assert third["subject"].startswith(model.find_focus(ids[2]).title)
    jobs = b.run_gui_op("icon_jobs", {})
    assert jobs["ok"] and set(jobs["result"]) == {"jobs", "summary", "cost_usd"}
    assert jobs["result"]["summary"] == {"queued": 0, "running": 0, "done": 3, "failed": 0}
    assert jobs["result"]["cost_usd"] == pytest.approx(0.09)


def test_icon_jobs_without_runner_and_quiet_and_narration(qapp):
    from ui.agent_bridge import _QUIET_OPS, AgentBridge
    b = _bridge(qapp, None, _own_cfg())
    resp = b.run_gui_op("icon_jobs", {})
    assert resp["ok"] and resp["result"]["jobs"] == [] and resp["result"]["cost_usd"] == 0.0
    assert "icon_jobs" in _QUIET_OPS and "generate_icons" not in _QUIET_OPS
    assert AgentBridge._summarize("generate_icons", {"queued": ["a", "b"]}) == "Generating 2 icons…"
    assert AgentBridge._summarize("generate_icons", {"queued": ["a"]}) == "Generating 1 icon…"


def test_real_bridge_run_op_routes_and_narrates(qapp):
    from ui.agent_bridge import AgentBridge
    gen = _FakeGenerator()
    runner, model, ids = _runner(qapp, gen)
    bridge = AgentBridge(model)
    bridge.set_icon_runner(runner, config_loader=_own_cfg)
    narrated = []
    bridge.op_applied.connect(narrated.append)
    resp = bridge.run_op("generate_icons", {"items": [{"focus_id": ids[0], "subject": "s"}]})
    assert resp["ok"] and resp["result"]["queued"] == [ids[0]]
    assert narrated == ["Generating 1 icon…"]
    _pump(qapp, runner, lambda: runner.status()["summary"]["done"] == 1)
    jobs = bridge.run_op("icon_jobs", {})
    assert jobs["ok"] and jobs["result"]["summary"]["done"] == 1
    assert narrated == ["Generating 1 icon…"]          # icon_jobs is quiet


def test_headless_dispatch_reports_gui_only_like_screenshot():
    from ui.project_model import ProjectModel
    for op in ("generate_icons", "icon_jobs", "screenshot"):
        resp = dispatch(ProjectModel(), op, {})
        assert resp["ok"] is False and "Unknown op" in resp["error"]


# ----- specs, tools, guide ------------------------------------------------------------------

def test_specs_tools_and_guide_mention_icon_generation():
    assert "generate_icons" in OP_SPECS and "icon_jobs" in OP_SPECS
    assert "generate_icons" in GUI_ONLY_OPS and "icon_jobs" in GUI_ONLY_OPS
    names = {t["function"]["name"] for t in tool_schemas()}
    assert {"generate_icons", "icon_jobs"} <= names
    assert {"generate_icons", "icon_jobs"} <= {t["function"]["name"] for t in default_tools()}
    gen = next(t for t in tool_schemas() if t["function"]["name"] == "generate_icons")
    assert gen["function"]["parameters"]["required"] == ["items"]
    assert "4. As soon as the ids and titles are fixed" in PROCEDURE
    assert "call `generate_icons` ONCE for the whole branch" in PROCEDURE
    assert "call `icon_jobs`; for any `failed` job" in PROCEDURE
    assert "8. NEVER call `save`" in PROCEDURE
    assert "generate_icons" in MD_FOCUS_GUIDE.split("## Icons")[1].split("##")[0]
    assert "draw a matching icon for each focus when icon generation is on" in CAPABILITIES_TEXT


# ----- settings ------------------------------------------------------------------------------

def _ini(tmp_path):
    return QSettings(str(tmp_path / "ff.ini"), QSettings.IniFormat)


def test_settings_round_trip_image_fields(qapp, tmp_path):
    from ui.assistant_settings_dialog import load_config, save_config
    fresh = load_config(_ini(tmp_path))
    assert fresh.icons_enabled is False and fresh.image_model == "microsoft/mai-image-2.6-flash"
    cfg = AgentConfig(mode="own", api_key="sk", icons_enabled=True,
                      image_model="google/gemini-2.5-flash-image")
    save_config(cfg, _ini(tmp_path))
    back = load_config(_ini(tmp_path))
    assert back.icons_enabled is True and back.image_model == "google/gemini-2.5-flash-image"
    cfg.icons_enabled = False
    save_config(cfg, _ini(tmp_path))
    assert load_config(_ini(tmp_path)).icons_enabled is False


def test_settings_dialog_own_pane_controls_and_hosted_note(qapp):
    from ui.assistant_settings_dialog import (
        HOSTED_ICONS_NOTE,
        ICONS_CHECKBOX_TEXT,
        AssistantSettingsDialog,
    )
    cfg = AgentConfig(mode="own", api_key="sk", icons_enabled=True, image_model="custom/img")
    dlg = AssistantSettingsDialog(cfg, recent=[], transport_factory=lambda: None)
    assert dlg._icons_enabled.text() == ICONS_CHECKBOX_TEXT and dlg._icons_enabled.isChecked()
    assert dlg._image_model.currentText() == "custom/img"
    seeded = {dlg._image_model.itemText(i) for i in range(dlg._image_model.count())}
    assert {"microsoft/mai-image-2.6-flash", "google/gemini-2.5-flash-image", "custom/img"} <= seeded
    assert dlg._hosted_icons_note.text() == HOSTED_ICONS_NOTE
    dlg._icons_enabled.setChecked(False)
    dlg._image_model.setCurrentText("  ")
    out = dlg.config()
    assert out.icons_enabled is False and out.image_model == "microsoft/mai-image-2.6-flash"


# ----- panel card ----------------------------------------------------------------------------

def test_panel_renders_icon_ready_and_failed_cards(qapp):
    from PySide6.QtWidgets import QLabel
    from ui.assistant_panel import AssistantPanel
    from ui.icon_jobs import IconJobRunner
    from ui.project_model import ProjectModel

    class _Stub:
        def run_op(self, op, args):
            return dispatch(model, op, args)

    model = ProjectModel()
    fid = model.project.focuses[0].id
    runner = IconJobRunner(model, generate=_FakeGenerator())
    panel = AssistantPanel(model, _Stub(), config_loader=lambda: AgentConfig(api_key="k"),
                           transport_factory=lambda: None, icon_runner=runner)
    from ui.icon_image import process_icon
    model.update_focus(fid, iconData=base64.b64encode(process_icon(_subject_png())).decode(),
                       icon="")
    lay = panel._transcript_layout
    before = lay.count()
    runner.icon_ready.emit(fid)
    runner.icon_failed.emit(fid, "Out of credits")
    qapp.processEvents()
    assert lay.count() == before + 2
    ready_card = lay.itemAt(before - 1).widget()
    labels = ready_card.findChildren(QLabel)
    assert any(lbl.text() == f"Icon ready · {fid}" for lbl in labels)
    pix = next(lbl.pixmap() for lbl in labels if lbl.objectName() == "iconPreview")
    assert (pix.width(), pix.height()) == (190, 170)
    failed_card = lay.itemAt(before).widget()
    assert failed_card.text() == f"Icon failed · {fid} — Out of credits"
    assert failed_card.objectName() == "hint"


# ----- export path ---------------------------------------------------------------------------

def test_generated_icon_exports_like_a_custom_icon(qapp, tmp_path):
    from core.export_check import smoke_check
    from core.exporters import export_focus_tree, export_project_files
    from ui.country_export import export_focus_icon_assets
    from ui.icon_image import process_icon

    png = process_icon(_subject_png())
    focus = FocusNodeData(id="MEX_tower", title="Tower", icon="",
                          iconData=base64.b64encode(png).decode("ascii"))
    project = FocusForgeProject(
        countryTag="MEX", projectName="Mexico", treeId="mex_focus", focuses=[focus],
        exportSettings=ExportSettings(modPrefix="MEX", focusFileName="mex_focus",
                                      localisationPrefix="MEX_forge"))
    tree = export_focus_tree(project)
    assert "icon = GFX_MEX_tower_focus_icon" in tree
    files = export_project_files(project)
    gfx = next(f for f in files if f.relativePath.endswith("focus_icons.gfx"))
    assert 'texturefile = "gfx/interface/goals/MEX_tower.dds"' in gfx.content
    errors = [i for i in smoke_check(files) if i.severity == "error"]
    assert errors == [], [i.message for i in errors]

    assert export_focus_icon_assets(project, str(tmp_path)) == 1
    dds = (tmp_path / "gfx" / "interface" / "goals" / "MEX_tower.dds").read_bytes()
    from core.dds_decode import decode_dds
    w, h, bgra = decode_dds(dds)
    assert (w, h) == (95, 85) and len(bgra) == 95 * 85 * 4
    assert bgra[3] == 0                                   # corner stays transparent
    centre = ((42 * 95) + 47) * 4
    assert bgra[centre + 3] == 255
