"""In-process AI bridge: a loopback QTcpServer that lets the out-of-process MCP proxy
drive the live ProjectModel.

Everything runs on the GUI main thread — QTcpServer / QTcpSocket signals fire there — so
each command calls the model directly and the canvas repaints through the normal
``project_changed`` signal, with zero threading.

Protocol: newline-delimited JSON. Request ``{"op": str, "args": {…}, "id"?: any}``;
response ``{"ok": bool, "result"|"error": …, "id"?: any}``.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtNetwork import QHostAddress, QTcpServer

from core.bridge_discovery import bridge_info_path, clear_bridge_info, write_bridge_info
from core.bridge_dispatch import BRIDGE_PROTOCOL, dispatch

from . import theme as T

try:
    from core.version import __version__ as _APP_VERSION
except Exception:  # pragma: no cover
    _APP_VERSION = "0.0.0"

# Grid → scene mapping (mirrors ui/focus_node_item.py).
_GRID_X, _GRID_Y = 124, 158

# Read-only ops aren't narrated to the status bar (too chatty).
_QUIET_OPS = {
    "hello", "get_project", "list_focuses", "get_focus", "get_selection",
    "validate", "list_reward_presets", "list_condition_presets", "reference_data",
    "screenshot",
}


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
        write_bridge_info(port, version=_APP_VERSION)
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
        self.client_changed.emit(self._clients > 0)

    def _on_ready_read(self, socket) -> None:
        buf = self._buffers.get(socket)
        if buf is None:
            return
        buf += bytes(socket.readAll().data())
        while b"\n" in buf:
            line, _, rest = buf.partition(b"\n")
            buf[:] = rest
            line = line.strip()
            if not line:
                continue
            response = self._handle_line(line)
            socket.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            socket.flush()

    def _handle_line(self, line: bytes) -> dict:
        try:
            request = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            return {"ok": False, "error": f"Bad JSON: {exc}"}
        op = request.get("op", "")
        args = request.get("args") or {}
        # `screenshot` is GUI-only (needs the scene) — handled here, not in core dispatch.
        result = self._screenshot(args) if op == "screenshot" else dispatch(self._model, op, args)
        if "id" in request:
            result["id"] = request["id"]
        if result.get("ok") and op not in _QUIET_OPS:
            self.op_applied.emit(self._summarize(op, result.get("result")))
        return result

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

            path = args.get("path") or str(bridge_info_path().with_name("canvas.png"))
            img.save(path, "PNG")
            in_view = {
                fid: [round(n.scenePos().x() / _GRID_X), round(n.scenePos().y() / _GRID_Y)]
                for fid, n in nodes.items() if src.intersects(n.sceneBoundingRect())
            }
            return {"ok": True, "result": {"path": path, "width": iw, "height": ih,
                                           "focuses_in_view": in_view}}
        except Exception as exc:
            return {"ok": False, "error": f"Screenshot failed: {type(exc).__name__}: {exc}"}

    @staticmethod
    def _summarize(op: str, result) -> str:
        detail = ""
        if isinstance(result, dict):
            for key in ("id", "deleted", "message", "updated", "selected", "saved"):
                if result.get(key):
                    detail = f" {result[key]}"
                    break
        return f"Agent: {op}{detail}".strip()
