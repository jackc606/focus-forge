"""Assistant settings: hosted (Discord sign-in) or your own key — persisted via QSettings.

Two panes behind a radio choice. **Hosted** needs only a token from the relay
(the base URL and model are fixed by ``core.hosted``); **own key** is the
0.4.3 bring-your-own-key form. Both panes' values are always kept, so
flipping the radio never loses a key or a token — ``mode`` just says which
one the loop uses.

The key / token is stored as typed (QSettings under ``assistant/``) — this is
the user's own machine, and the dialog says so plainly. "Test connection"
runs the probe from ``core.agent_loop`` on a worker thread so a slow provider
never freezes the dialog.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
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
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.agent_loop import (
    MODE_HOSTED,
    MODE_OWN,
    AgentConfig,
    TransportError,
    UrllibTransport,
    default_extra_headers,
    test_connection,
)
from core.agent_pricing import DEFAULT_MODEL
from core.hosted import HOSTED_MODEL_LABEL, HOSTED_PRIVACY_NOTE, hosted_signin_url

from . import theme as T
from .update_worker import run_in_thread
from .widgets import hint, panel_header

SETTINGS_GROUP = "assistant"
KNOWN_MODELS = (DEFAULT_MODEL, "meta/muse-spark-1.3")
_MAX_RECENT_MODELS = 8

PRIVACY_NOTE = ("Stored on this computer only. Prompts and your mod content are sent to "
                "the model provider you configure.")
HOSTED_CHOICE_TEXT = "Focus Forge hosted — free monthly allotment, sign in with Discord"
OWN_CHOICE_TEXT = "My own key — OpenRouter or any OpenAI-compatible endpoint"
HOSTED_EXPLAINER = ("Focus Forge pays for a small monthly allotment per modder — enough for "
                    "a few dozen branches. Sign in with Discord, paste the token it shows "
                    "you, and you're done.")


def _settings() -> QSettings:
    return QSettings("FocusForge", "FocusForge")


def _default_mode(s: QSettings) -> str:
    """Nothing stored yet: hosted is the no-setup path, so a fresh install
    lands there. An install that already configured a key predates hosted
    mode and must keep working exactly as before."""
    return MODE_OWN if str(s.value("api_key", "") or "") else MODE_HOSTED


def load_config(store: "QSettings | None" = None) -> AgentConfig:
    """The persisted assistant config (defaults for anything unset). Extra
    headers are derived from the effective base URL rather than stored.
    ``store`` is injectable so tests never touch the real settings."""
    defaults = AgentConfig()
    s = store if store is not None else _settings()
    s.beginGroup(SETTINGS_GROUP)
    try:
        cfg = AgentConfig(
            base_url=str(s.value("base_url", defaults.base_url) or defaults.base_url),
            api_key=str(s.value("api_key", "") or ""),
            model=str(s.value("model", defaults.model) or defaults.model),
            max_rounds=_to_int(s.value("max_rounds"), defaults.max_rounds),
            temperature=_to_float(s.value("temperature"), defaults.temperature),
            mode=_valid_mode(s.value("mode"), _default_mode(s)),
            hosted_token=str(s.value("hosted_token", "") or ""),
        )
    finally:
        s.endGroup()
    cfg.extra_headers = default_extra_headers(cfg.effective_base_url())
    return cfg


def save_config(cfg: AgentConfig, store: "QSettings | None" = None) -> None:
    s = store if store is not None else _settings()
    s.beginGroup(SETTINGS_GROUP)
    try:
        s.setValue("base_url", cfg.base_url)
        s.setValue("api_key", cfg.api_key)
        s.setValue("model", cfg.model)
        s.setValue("mode", cfg.mode)
        s.setValue("hosted_token", cfg.hosted_token)
        s.setValue("max_rounds", int(cfg.max_rounds))
        s.setValue("temperature", float(cfg.temperature))
        recent = [m for m in [cfg.model] + recent_models(s) if m]
        s.setValue("recent_models", list(dict.fromkeys(recent))[:_MAX_RECENT_MODELS])
    finally:
        s.endGroup()
    s.sync()


def recent_models(settings: "QSettings | None" = None) -> list:
    """Model ids the user typed before (seeds the editable combo). With
    ``settings`` given, it must already be inside the ``assistant`` group."""
    own = settings is None
    s = _settings() if own else settings
    if own:
        s.beginGroup(SETTINGS_GROUP)
    try:
        raw = s.value("recent_models", [])
    finally:
        if own:
            s.endGroup()
    if isinstance(raw, str):
        raw = [raw]
    return [str(m) for m in (raw or []) if m]


def _valid_mode(value, default: str) -> str:
    return value if value in (MODE_OWN, MODE_HOSTED) else default


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


def _secret_row(edit: QLineEdit) -> "tuple[QWidget, QToolButton]":
    """A password field with a Show/Hide toggle beside it."""
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    toggle = QToolButton()
    toggle.setText("Show")
    toggle.setCheckable(True)
    toggle.setToolTip("Show / hide")

    def flip(show: bool) -> None:
        edit.setEchoMode(QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password)
        toggle.setText("Hide" if show else "Show")

    toggle.toggled.connect(flip)
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(T.SPACE_XS)
    row.addWidget(edit, 1)
    row.addWidget(toggle)
    holder = QWidget()
    holder.setLayout(row)
    return holder, toggle


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

        self._hosted_radio = QRadioButton(HOSTED_CHOICE_TEXT)
        self._own_radio = QRadioButton(OWN_CHOICE_TEXT)
        outer.addWidget(self._hosted_radio)
        outer.addWidget(self._own_radio)

        self._panes = QStackedWidget()
        self._panes.addWidget(self._build_hosted_pane(cfg))
        self._panes.addWidget(self._build_own_pane(cfg, recent))
        outer.addWidget(self._panes)
        self._hosted_radio.toggled.connect(self._sync_pane)
        (self._hosted_radio if cfg.is_hosted() else self._own_radio).setChecked(True)
        self._sync_pane()

        outer.addLayout(self._build_shared_form(cfg))

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

    # ----- panes -----
    def _build_hosted_pane(self, cfg: AgentConfig) -> QWidget:
        pane = QWidget()
        v = QVBoxLayout(pane)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(T.SPACE_SM)
        v.addWidget(hint(HOSTED_EXPLAINER))
        self._signin_btn = QPushButton("Sign in with Discord")
        self._signin_btn.setObjectName("primary")
        self._signin_btn.setToolTip("Opens your browser; the page shows a token to paste below")
        self._signin_btn.clicked.connect(self._sign_in)
        v.addWidget(self._signin_btn, 0, Qt.AlignLeft)

        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        self._hosted_token = QLineEdit(cfg.hosted_token)
        self._hosted_token.setPlaceholderText("ffa_…")
        holder, self._show_token = _secret_row(self._hosted_token)
        form.addRow("Paste your token", holder)
        self._hosted_model_label = QLabel(HOSTED_MODEL_LABEL)
        self._hosted_model_label.setObjectName("metaChip")
        form.addRow("Model", self._hosted_model_label)
        v.addLayout(form)
        v.addWidget(hint(HOSTED_PRIVACY_NOTE))
        return pane

    def _build_own_pane(self, cfg: AgentConfig, recent) -> QWidget:
        pane = QWidget()
        v = QVBoxLayout(pane)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(T.SPACE_SM)
        v.addWidget(hint(
            "Bring your own key: the assistant talks to any OpenAI-compatible "
            "chat endpoint. OpenRouter is the default — get a key at openrouter.ai/keys."))
        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
        self._base_url = QLineEdit(cfg.base_url)
        self._base_url.setPlaceholderText(AgentConfig().base_url)
        form.addRow("Base URL", self._base_url)

        self._api_key = QLineEdit(cfg.api_key)
        self._api_key.setPlaceholderText("sk-or-…")
        holder, self._show_key = _secret_row(self._api_key)
        form.addRow("API key", holder)

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
        v.addLayout(form)
        v.addWidget(hint(PRIVACY_NOTE))
        return pane

    def _build_shared_form(self, cfg: AgentConfig) -> QFormLayout:
        form = QFormLayout()
        form.setSpacing(T.SPACE_SM)
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
        return form

    # ----- api -----
    def mode(self) -> str:
        return MODE_HOSTED if self._hosted_radio.isChecked() else MODE_OWN

    def config(self) -> AgentConfig:
        base_url = self._base_url.text().strip() or AgentConfig().base_url
        model = self._model.currentText().strip() or DEFAULT_MODEL
        cfg = AgentConfig(
            base_url=base_url,
            api_key=self._api_key.text().strip(),
            model=model,
            mode=self.mode(),
            hosted_token=self._hosted_token.text().strip(),
            max_rounds=self._max_rounds.value(),
            temperature=self._temperature.value(),
        )
        cfg.extra_headers = default_extra_headers(cfg.effective_base_url())
        return cfg

    def accept(self) -> None:  # noqa: D401 (Qt override)
        save_config(self.config())
        super().accept()

    # ----- slots -----
    def _sync_pane(self) -> None:
        self._panes.setCurrentIndex(0 if self._hosted_radio.isChecked() else 1)

    def _sign_in(self) -> None:
        QDesktopServices.openUrl(QUrl(hosted_signin_url()))

    def _test(self) -> None:
        if self._worker is not None:
            return
        self._test_btn.setEnabled(False)
        self._set_status("Testing…", ok=None)
        worker = _TestConnectionWorker(self.config(), self._transport_factory())
        # Bound @Slot methods, not lambdas: a lambda has no thread affinity, so
        # Qt would call it on the worker thread and the QLabel restyle below
        # would touch a widget off the GUI thread. A slot on this dialog is
        # queued to the thread the dialog lives on.
        worker.succeeded.connect(self._on_test_succeeded)
        worker.failed.connect(self._on_test_failed)
        worker.finished.connect(self._test_done)
        self._worker = worker
        self._thread = run_in_thread(worker, parent=self)

    @Slot(str)
    def _on_test_succeeded(self, msg: str) -> None:
        self._set_status(msg, ok=True)

    @Slot(str)
    def _on_test_failed(self, msg: str) -> None:
        self._set_status(msg, ok=False)

    @Slot()
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
