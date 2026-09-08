"""In-process AI bridge: a loopback QTcpServer that lets the out-of-process MCP proxy
drive the live ProjectModel.

Everything runs on the GUI main thread — QTcpServer / QTcpSocket signals fire there — so
each command calls the model directly and the canvas repaints through the normal
``project_changed`` signal, with zero threading.

Protocol: newline-delimited JSON. Request ``{"op": str, "args": {…}, "id"?: any}``;
response ``{"ok": bool, "result"|"error": …, "id"?: any}``.
"""
from __future__ import annotations

import hmac
import json
import secrets

from PySide6.QtCore import QObject, QRectF, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QTcpServer

from core.bridge_discovery import bridge_info_path, clear_bridge_info, write_bridge_info
from core import bridge_dispatch
from core.bridge_dispatch import BRIDGE_PROTOCOL, dispatch, normalize_args

from . import theme as T

try:
    from core.version import __version__ as _APP_VERSION
except Exception:  # pragma: no cover
    _APP_VERSION = "0.0.0"

# Grid → scene mapping (mirrors ui/focus_node_item.py).
_GRID_X, _GRID_Y = 124, 158

# Refuse a single request line larger than this (no newline terminator) so a
# misbehaving local client can't exhaust memory. Generous: a project/event
# payload can carry base64-encoded art, but never tens of MB on one line.
_MAX_REQUEST_BYTES = 16 * 1024 * 1024

# After a graceful drop (error reply + disconnectFromHost), force-close the
# socket if the peer still hasn't drained the reply by then.
_DROP_FORCE_CLOSE_MS = 3000

# Read-only ops aren't narrated to the status bar (too chatty).
_QUIET_OPS = {
    "hello", "get_project", "list_focuses", "get_focus", "get_selection",
    "validate", "list_reward_presets", "list_condition_presets", "reference_data",
    "screenshot", "search_icons", "describe_op", "guide", "list_decisions",
    "list_ideas", "list_events", "tree_overview", "icon_jobs",
}

_GUI_OPS = ("screenshot", "search_icons", "generate_icons", "icon_jobs")

ICONS_OFF_TEXT = ("Icon generation is off (Assistant settings → 'Let the assistant generate "
                  "focus icons'). Use search_icons to pick a sprite instead.")
ICONS_NO_KEY_TEXT = ("Icon generation needs your own OpenRouter key for now — the hosted "
                     "allotment doesn't cover images. Use search_icons instead.")
ICONS_NO_RUNNER_TEXT = "Icon generation isn't available in this session (no icon runner)."
_MAX_ICON_ITEMS = 25
_ICON_THEMES = ("economy", "military", "politics", "research")


class AgentBridge(QObject):
    state_changed = Signal(bool, int)    # listening?, port
    client_changed = Signal(bool)        # a client connected / disconnected
    op_applied = Signal(str)             # human summary of a mutating op

    def __init__(self, model, scene=None, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._scene = scene        # GraphScene — lets the agent screenshot the canvas
        self._server: QTcpServer | None = None
        self._buffers: dict = {}   # socket -> bytearray
        self._clients = 0
        self._token = ""           # shared secret; only a process that can read
                                   # the per-user discovery file knows it
        # Icon generation is optional wiring (MainWindow injects the runner);
        # without it generate_icons refuses politely instead of crashing.
        self._icon_runner = None
        self._config_loader = None
        # Lets core reject an unresolved icon WITH suggestions (the sprite index
        # is a UI-layer object; core only sees this callable).
        bridge_dispatch.set_icon_search_provider(self._sprite_names)

    def set_icon_runner(self, runner, config_loader=None) -> None:
        """``runner`` is an ``IconJobRunner``; ``config_loader`` returns the
        current ``AgentConfig`` (defaults to the persisted assistant settings,
        read at call time so a change in the dialog applies immediately)."""
        self._icon_runner = runner
        self._config_loader = config_loader

    # ----- lifecycle -----
    def is_listening(self) -> bool:
        return self._server is not None and self._server.isListening()

    def port(self) -> int:
        return self._server.serverPort() if self.is_listening() else 0

    def start(self) -> bool:
        if self.is_listening():
            return True
        server = QTcpServer(self)
        if not server.listen(QHostAddress(QHostAddress.LocalHost), 0):
            return False
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        port = server.serverPort()
        # Per-session secret. It's published only in the per-user discovery file
        # (private appdata), so connecting requires read access to that file —
        # a blind port scanner or a web page can't authenticate.
        self._token = secrets.token_hex(32)
        write_bridge_info(port, version=_APP_VERSION, token=self._token)
        self.state_changed.emit(True, port)
        return True

    def stop(self) -> None:
        for socket in list(self._buffers):
            try:
                socket.close()
            except RuntimeError:
                pass
        self._buffers.clear()
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        self._clients = 0
        self._token = ""
        clear_bridge_info()
        self.state_changed.emit(False, 0)
        self.client_changed.emit(False)

    # ----- connections -----
    def _on_new_connection(self) -> None:
        while self._server and self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(lambda s=socket: self._on_disconnected(s))
            self._clients += 1
            self.client_changed.emit(True)

    def _on_disconnected(self, socket) -> None:
        self._buffers.pop(socket, None)
        try:
            socket.deleteLater()
        except RuntimeError:
            pass  # C++ object already gone (teardown race) — harmless
        self._clients = max(0, self._clients - 1)
        try:
            self.client_changed.emit(self._clients > 0)
        except RuntimeError:
            pass  # bridge C++ object gone during app teardown — harmless

    def _drop(self, socket, error: str) -> None:
        self._buffers.pop(socket, None)
        try:
            socket.write((json.dumps({"ok": False, "error": error}) + "\n").encode("utf-8"))
            socket.flush()
            # Graceful: disconnectFromHost() lets pending writes drain first, so
            # the client actually receives the error JSON instead of a bare
            # connection reset. An immediate close() would discard the reply.
            socket.disconnectFromHost()
        except RuntimeError:
            return  # socket's C++ object already gone
        # Fallback: if the peer never reads (so the write never drains), force
        # the socket closed after a grace period.
        QTimer.singleShot(_DROP_FORCE_CLOSE_MS, lambda: self._force_close(socket))

    @staticmethod
    def _force_close(socket) -> None:
        try:
            if socket.state() != QAbstractSocket.SocketState.UnconnectedState:
                socket.abort()
        except RuntimeError:
            pass  # already deleted — nothing to close

    def _on_ready_read(self, socket) -> None:
        buf = self._buffers.get(socket)
        if buf is None:
            return
        buf += bytes(socket.readAll().data())
        if len(buf) > _MAX_REQUEST_BYTES and b"\n" not in buf:
            # One oversized, unterminated line — refuse and drop the client.
            self._drop(socket, "Request too large.")
            return
        while b"\n" in buf:
            line, _, rest = buf.partition(b"\n")
            buf[:] = rest
            line = line.strip()
            if not line:
                continue
            response = self._handle_line(line)
            socket.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            socket.flush()

    def _authorized(self, token) -> bool:
        # Constant-time compare; a bridge with no token (shouldn't happen while
        # listening) authorizes nothing.
        return (bool(self._token) and isinstance(token, str)
                and hmac.compare_digest(token, self._token))

    def _handle_line(self, line: bytes) -> dict:
        try:
            request = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return {"ok": False, "error": f"Bad JSON: {exc}"}
        if not isinstance(request, dict):
            return {"ok": False, "error": "Bad request: expected a JSON object."}
        if not self._authorized(request.get("token")):
            resp = {"ok": False, "error": "Unauthorized: missing or invalid bridge token."}
            if "id" in request:
                resp["id"] = request["id"]
            return resp
        op = request.get("op", "")
        args = request.get("args") or {}
        result = self.run_op(op, args)
        if "id" in request:
            result["id"] = request["id"]
        return result

    # ----- shared op path (TCP clients AND the in-app assistant) -----
    def run_op(self, op: str, args: dict) -> dict:
        """Run one op on the GUI thread and narrate it to the status bar exactly
        as a TCP request would — the in-app assistant calls this directly so
        both drivers share one code path (and it needs no listening server)."""
        if op in _GUI_OPS:
            result = self.run_gui_op(op, args)
        else:
            result = dispatch(self._model, op, args)
        if result.get("ok") and op not in _QUIET_OPS:
            self.op_applied.emit(self._summarize(op, result.get("result")))
        return result

    def run_gui_op(self, op: str, args: dict) -> dict:
        """`screenshot`/`search_icons`/`generate_icons`/`icon_jobs` are GUI-only
        (need the scene / the sprite index provider / the icon runner) — handled
        here, not in core dispatch. They still get the same alias / unknown-arg
        treatment as every other op."""
        try:
            args = normalize_args(op, args or {})
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if op == "screenshot":
            return self._screenshot(args)
        if op == "search_icons":
            return self._search_icons(args)
        if op == "generate_icons":
            return self._generate_icons(args)
        if op == "icon_jobs":
            return self._icon_jobs()
        return {"ok": False, "error": f"'{op}' is not a GUI op."}

    # ----- icon generation -----
    def _icon_config(self):
        """The image endpoint config, or a refusal string the model can act on."""
        from core.icon_gen import image_config_from_assistant
        loader = self._config_loader
        if loader is None:
            from .assistant_settings_dialog import load_config as loader
        cfg = loader()
        if not getattr(cfg, "icons_enabled", False):
            return None, ICONS_OFF_TEXT
        image_cfg = image_config_from_assistant(cfg, getattr(cfg, "image_model", ""))
        if image_cfg is None:
            return None, ICONS_NO_KEY_TEXT
        return image_cfg, ""

    def _icon_items(self, items) -> list:
        """Validate the request and build one prompt per focus. Raises
        ValueError with a sentence naming the bad entry."""
        from core.icon_prompt import (accent_for, build_icon_prompt, default_subject,
                                      palette_for, theme_for_filters)
        if not isinstance(items, list) or not items:
            raise ValueError("items must be a non-empty list of {focus_id, subject}.")
        if len(items) > _MAX_ICON_ITEMS:
            raise ValueError(f"items holds {len(items)} entries; at most {_MAX_ICON_ITEMS} "
                             "per call — split the branch.")
        tag = getattr(self._model.project, "countryTag", "")
        out = []
        for n, item in enumerate(items, 1):
            if not isinstance(item, dict):
                raise ValueError(f"items[{n}] must be an object with focus_id and subject.")
            fid = str(item.get("focus_id") or item.get("id") or "").strip()
            focus = self._model.find_focus(fid) if fid else None
            if focus is None:
                raise ValueError(f"items[{n}]: no focus '{fid}'. Add the focus first, "
                                 "then generate its icon.")
            theme = str(item.get("theme") or "").strip().lower()
            if theme and theme not in _ICON_THEMES:
                raise ValueError(f"items[{n}]: theme must be one of {', '.join(_ICON_THEMES)}.")
            subject = str(item.get("subject") or "").strip() or default_subject(focus)
            prompt = build_icon_prompt(
                subject, object_count=item.get("object_count", 2),
                palette=palette_for(theme or theme_for_filters(focus.filters)),
                accent=str(item.get("accent") or "").strip() or accent_for(tag))
            out.append({"focus_id": fid, "subject": subject, "prompt": prompt})
        return out

    def _generate_icons(self, args: dict) -> dict:
        """Queue background icon jobs and return at once — the model keeps
        building while they render (see ui/icon_jobs.py)."""
        from core.icon_gen import EST_COST_PER_ICON_USD
        if self._icon_runner is None:
            return {"ok": False, "error": ICONS_NO_RUNNER_TEXT}
        image_cfg, refusal = self._icon_config()
        if image_cfg is None:
            return {"ok": False, "error": refusal}
        try:
            items = self._icon_items(args.get("items"))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        active = self._icon_runner.active_ids()
        already = [i["focus_id"] for i in items if i["focus_id"] in active]
        created = self._icon_runner.queue(items, image_cfg)
        queued = [j["focus_id"] for j in created]
        return {"ok": True, "result": {
            "queued": queued, "already_running": already,
            "estimated_cost_usd": round(len(queued) * EST_COST_PER_ICON_USD, 2),
            "note": "Icons generate in the background (~20 s each, 2 at a time). Keep "
                    "building; call icon_jobs before you finish."}}

    def _icon_jobs(self) -> dict:
        if self._icon_runner is None:
            return {"ok": True, "result": {"jobs": [], "summary": {
                "queued": 0, "running": 0, "done": 0, "failed": 0}, "cost_usd": 0.0}}
        return {"ok": True, "result": self._icon_runner.status()}

    # ----- canvas screenshot -----
    def _screenshot(self, args: dict) -> dict:
        """Render a region of the focus-tree canvas to a PNG so the agent can see the
        actual layout. Region: a focus + margin, a set of focuses, or the whole tree."""
        scene = self._scene
        if scene is None:
            return {"ok": False, "error": "No canvas available (headless)."}
        nodes = getattr(scene, "_nodes", {})
        if not nodes:
            return {"ok": False, "error": "The canvas has no focuses."}
        try:
            margin = int(args.get("margin", 3))
            if args.get("focus_ids"):
                rects = [nodes[i].sceneBoundingRect() for i in args["focus_ids"] if i in nodes]
                if not rects:
                    return {"ok": False, "error": "None of those focuses are on the canvas."}
                src = rects[0]
                for r in rects[1:]:
                    src = src.united(r)
            elif args.get("focus_id"):
                fid = args["focus_id"]
                if fid not in nodes:
                    return {"ok": False, "error": f"No focus '{fid}'."}
                src = nodes[fid].sceneBoundingRect()
            else:  # whole tree
                src = scene.itemsBoundingRect()
            src = src.adjusted(-margin * _GRID_X, -margin * _GRID_Y,
                               margin * _GRID_X, margin * _GRID_Y)

            max_px = int(args.get("max_px", 1800))
            scale = min(max_px / max(src.width(), 1.0), max_px / max(src.height(), 1.0), 2.0)
            iw, ih = max(1, int(src.width() * scale)), max(1, int(src.height() * scale))
            img = QImage(iw, ih, QImage.Format_RGB32)
            img.fill(QColor(T.BG_BASE))
            painter = QPainter(img)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.TextAntialiasing)
            scene.render(painter, QRectF(0, 0, iw, ih), src)
            painter.end()

            # App-owned, fixed location only — never a client-supplied path, so
            # the screenshot op can't be turned into an arbitrary-file-write
            # primitive. The agent reads the returned path to view the image.
            path = str(bridge_info_path().with_name("canvas.png"))
            img.save(path, "PNG")
            in_view = {
                fid: [round(n.scenePos().x() / _GRID_X), round(n.scenePos().y() / _GRID_Y)]
                for fid, n in nodes.items() if src.intersects(n.sceneBoundingRect())
            }
            return {"ok": True, "result": {"path": path, "width": iw, "height": ih,
                                           "focuses_in_view": in_view}}
        except Exception as exc:
            return {"ok": False, "error": f"Screenshot failed: {type(exc).__name__}: {exc}"}

    # ----- icon search -----
    @staticmethod
    def _sprite_names() -> list:
        from .icon_provider import provider  # lazy: may build the sprite index
        return [name for name, _path in provider().focus_sprites()]

    @staticmethod
    def _search_icons(args: dict) -> dict:
        """Substring-search the indexed focus-icon sprite names, so the agent can
        pick icons that actually resolve instead of guessing GFX_ names."""
        query = args.get("query")
        if not isinstance(query, str) or len(query.strip()) < 2:
            return {"ok": False, "error": "query must be a string of at least 2 characters."}
        query = query.strip()
        try:
            limit = max(1, min(int(args.get("limit", 30)), 100))
        except (TypeError, ValueError):
            return {"ok": False, "error": f"limit must be an integer (got {args.get('limit')!r})."}
        try:
            from .icon_provider import provider  # lazy: may build the sprite index
            sprites = provider().focus_sprites()
            if not sprites:
                return {"ok": True, "result": {
                    "icons": [], "total_matches": 0,
                    "note": "No icon roots configured in Focus Forge "
                            "(Settings -> In-game Icons)."}}
            q = query.lower()
            matches = [name for name, _path in sprites if q in name.lower()]
            # An exact hit goes first — agents use it to verify a guessed name.
            exact = next((n for n in matches if n.lower() == q), None)
            if exact is not None:
                matches = [exact] + [n for n in matches if n != exact]
            shown = matches[:limit]
            result = {"icons": shown, "total_matches": len(matches), "shown": len(shown)}
            if exact is not None:
                result["exact"] = True
            return {"ok": True, "result": result}
        except Exception as exc:
            return {"ok": False, "error": f"search_icons failed: {type(exc).__name__}: {exc}"}

    @staticmethod
    def _summarize(op: str, result) -> str:
        detail = ""
        if op == "generate_icons" and isinstance(result, dict):
            n = len(result.get("queued") or [])
            return f"Generating {n} icon{'s' if n != 1 else ''}…"
        if isinstance(result, dict):
            for key in ("id", "deleted", "message", "updated", "selected", "saved"):
                if result.get(key):
                    detail = f" {result[key]}"
                    break
        return f"Agent: {op}{detail}".strip()
