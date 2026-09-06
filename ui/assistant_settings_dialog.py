"""Assistant settings: provider URL, API key, model, limits — persisted via QSettings.

The key is stored as typed (QSettings under ``assistant/``) — this is a
bring-your-own-key feature on the user's own machine, and the dialog says so
plainly. "Test connection" runs the one-token probe from ``core.agent_loop``
on a worker thread so a slow provider never freezes the dialog.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.agent_loop import (
    AgentConfig,
    TransportError,
    UrllibTransport,
    default_extra_headers,
    test_connection,
)
from core.agent_pricing import DEFAULT_MODEL

from . import theme as T
from .update_worker import run_in_thread
from .widgets import hint, panel_header

SETTINGS_GROUP = "assistant"
KNOWN_MODELS = (DEFAULT_MODEL, "meta/muse-spark-1.3")
_MAX_RECENT_MODELS = 8

PRIVACY_NOTE = ("Stored on this computer only. Prompts and your mod content are sent to "
                "the model provider you configure.")


def _settings() -> QSettings:
    s = QSettings("FocusForge", "FocusForge")
    s.beginGroup(SETTINGS_GROUP)
    return s


def load_config() -> AgentConfig:
    """The persisted assistant config (defaults for anything unset). Extra
    headers are derived from the base URL rather than stored."""
    defaults = AgentConfig()
    s = _settings()
    try:
        cfg = AgentConfig(
            base_url=str(s.value("base_url", defaults.base_url) or defaults.base_url),
            api_key=str(s.value("api_key", "") or ""),
            model=str(s.value("model", defaults.model) or defaults.model),
            max_rounds=_to_int(s.value("max_rounds"), defaults.max_rounds),
            temperature=_to_float(s.value("temperature"), defaults.temperature),
        )
    finally:
        s.endGroup()
    cfg.extra_headers = default_extra_headers(cfg.base_url)
    return cfg


def save_config(cfg: AgentConfig) -> None:
    s = _settings()
    try:
        s.setValue("base_url", cfg.base_url)
        s.setValue("api_key", cfg.api_key)
        s.setValue("model", cfg.model)
        s.setValue("max_rounds", int(cfg.max_rounds))
        s.setValue("temperature", float(cfg.temperature))
        recent = [m for m in [cfg.model] + recent_models(s) if m]
        s.setValue("recent_models", list(dict.fromkeys(recent))[:_MAX_RECENT_MODELS])
    finally:
        s.endGroup()
    s.sync()


def recent_models(settings: "QSettings | None" = None) -> list:
    """Model ids the user typed before (seeds the editable combo)."""
    own = settings is None
    s = _settings() if own else settings
    try:
        raw = s.value("recent_models", [])
    finally:
        if own:
            s.endGroup()
    if isinstance(raw, str):
        raw = [raw]
    return [str(m) for m in (raw or []) if m]


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class _TestConnectionWorker(QObject):
    """One probe request off the GUI thread. Emits exactly one of
    ``succeeded`` / ``failed``, then ``finished``."""

    succeeded = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, config: AgentConfig, transport) -> None:
        super().__init__()
        self._config = config
        self._transport = transport

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(test_connection(self._config, self._transport))
        except TransportError as exc:
            self.failed.emit(exc.message)
        except Exception as exc:  # never die silently off-thread
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


class AssistantSettingsDialog(QDialog):
    """Edit the assistant config. ``config()`` returns what the fields hold;
    ``accept`` persists it. ``transport_factory`` is injectable so tests can
    exercise "Test connection" without a network."""

    def __init__(self, config: "AgentConfig | None" = None, parent=None,
                 transport_factory=UrllibTransport, recent: "list | None" = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assistant settings")
        self.resize(*T.DIALOG_MD)
        self._transport_factory = transport_factory
        self._worker = None
        self._thread = None
        cfg = config or load_config()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(T.SPACE_LG, T.SPACE_LG, T.SPACE_LG, T.SPACE_LG)
        outer.setSpacing(T.SPACE_MD)
        outer.addWidget(panel_header("Assistant settings"))
        outer.addWidget(hint(
            "Bring your own key: the assistant talks to any OpenAI-compatible "
            "chat endpoint. OpenRouter is the default — get a key at openrouter.ai/keys."))

        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        outer.addLayout(form)

        self._base_url = QLineEdit(cfg.base_url)
        self._base_url.setPlaceholderText(AgentConfig().base_url)
        form.addRow("Base URL", self._base_url)

        key_row = QHBoxLayout()
        key_row.setSpacing(T.SPACE_XS)
        self._api_key = QLineEdit(cfg.api_key)
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("sk-or-…")
        self._show_key = QToolButton()
        self._show_key.setText("Show")
        self._show_key.setCheckable(True)
        self._show_key.setToolTip("Show / hide the key")
        self._show_key.toggled.connect(self._toggle_key_visible)
        key_row.addWidget(self._api_key, 1)
        key_row.addWidget(self._show_key)
        key_holder = QWidget()
        key_holder.setLayout(key_row)
        form.addRow("API key", key_holder)

        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.setInsertPolicy(QComboBox.NoInsert)
        seen = []
        for m in list(KNOWN_MODELS) + list(recent if recent is not None else recent_models()) + [cfg.model]:
            if m and m not in seen:
                seen.append(m)
                self._model.addItem(m)
        self._model.setCurrentText(cfg.model)
        form.addRow("Model", self._model)

        self._max_rounds = QSpinBox()
        self._max_rounds.setRange(1, 200)
        self._max_rounds.setValue(int(cfg.max_rounds))
        self._max_rounds.setToolTip("Tool rounds per request before the assistant pauses.")
        form.addRow("Max tool rounds", self._max_rounds)

        self._temperature = QDoubleSpinBox()
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setDecimals(2)
        self._temperature.setValue(float(cfg.temperature))
        form.addRow("Temperature", self._temperature)

        outer.addWidget(hint(PRIVACY_NOTE))

        test_row = QHBoxLayout()
        test_row.setSpacing(T.SPACE_SM)
        self._test_btn = QPushButton("Test connection")
        self._test_btn.clicked.connect(self._test)
        self._test_status = QLabel("")
        self._test_status.setObjectName("hint")
        self._test_status.setWordWrap(True)
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._test_status, 1)
        outer.addLayout(test_row)
        outer.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    # ----- api -----
    def config(self) -> AgentConfig:
        base_url = self._base_url.text().strip() or AgentConfig().base_url
        model = self._model.currentText().strip() or DEFAULT_MODEL
        return AgentConfig(
            base_url=base_url,
            api_key=self._api_key.text().strip(),
            model=model,
            max_rounds=self._max_rounds.value(),
            temperature=self._temperature.value(),
            extra_headers=default_extra_headers(base_url),
        )

    def accept(self) -> None:  # noqa: D401 (Qt override)
        save_config(self.config())
        super().accept()

    # ----- slots -----
    def _toggle_key_visible(self, show: bool) -> None:
        self._api_key.setEchoMode(QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password)
        self._show_key.setText("Hide" if show else "Show")

    def _test(self) -> None:
        if self._worker is not None:
            return
        self._test_btn.setEnabled(False)
        self._set_status("Testing…", ok=None)
        worker = _TestConnectionWorker(self.config(), self._transport_factory())
        worker.succeeded.connect(lambda msg: self._set_status(msg, ok=True))
        worker.failed.connect(lambda msg: self._set_status(msg, ok=False))
        worker.finished.connect(self._test_done)
        self._worker = worker
        self._thread = run_in_thread(worker, parent=self)

    def _test_done(self) -> None:
        self._worker = None
        self._thread = None
        self._test_btn.setEnabled(True)

    def _set_status(self, text: str, ok) -> None:
        self._test_status.setText(text)
        name = "hint" if ok is None else ("issueTextError" if ok is False else "pillOk")
        self._test_status.setObjectName(name)
        # Re-polish so the new object name picks up its stylesheet rule.
        self._test_status.style().unpolish(self._test_status)
        self._test_status.style().polish(self._test_status)
        self._test_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
