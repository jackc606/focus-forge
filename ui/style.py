"""Dark-theme QSS, built from the design tokens in ``ui/theme.py``.

Call :func:`build_qss` to get the stylesheet string. ``DARK_QSS`` is kept as a
module-level convenience (and for backward compatibility with existing imports).
"""
from __future__ import annotations

from . import theme as T


def build_qss() -> str:
    return f"""
* {{
    color: {T.TEXT_PRIMARY};
    font-family: {T.FONT_UI};
    font-size: {T.TEXT_BODY}px;
}}

QMainWindow, QWidget {{ background-color: {T.BG_BASE}; }}

/* ----- Tooltips (dark, readable — the global * rule lightens text, so the
   default light tooltip background must be overridden explicitly) ----- */
QToolTip {{
    background-color: {T.BG_ELEVATED};
    color: {T.TEXT_PRIMARY};
    border: 1px solid {T.BORDER_HOVER};
    border-radius: {T.RADIUS_INPUT}px;
    padding: 5px 7px;
}}

/* ----- Toolbar ----- */
QToolBar {{
    background-color: {T.BG_PANEL};
    border: 0;
    border-bottom: 1px solid {T.BORDER_SUBTLE};
    padding: {T.SPACE_SM}px;
    spacing: {T.SPACE_SM}px;
}}
QToolBar QToolButton, QToolBar QPushButton {{
    background-color: {T.BG_ELEVATED};
    color: {T.TEXT_PRIMARY};
    border: 1px solid {T.BORDER_STRONG};
    border-radius: {T.RADIUS_CARD}px;
    padding: 6px 14px;
}}
QToolBar QToolButton:hover, QToolBar QPushButton:hover {{
    background-color: {T.BG_HOVER};
    border-color: {T.BORDER_HOVER};
}}
QToolBar QToolButton:pressed, QToolBar QPushButton:pressed {{
    background-color: {T.BG_INSET};
}}
QToolBar QToolButton:disabled, QToolBar QPushButton:disabled {{
    color: {T.TEXT_DISABLED};
    background-color: {T.BG_PANEL};
    border-color: {T.BORDER_SUBTLE};
}}
QToolBar QToolButton#danger {{
    color: {T.STATUS_ERROR};
    border-color: {T.STATUS_ERROR_BORDER};
}}
QToolBar QToolButton#danger:hover {{
    background-color: {T.STATUS_ERROR_BG};
    border-color: {T.STATUS_ERROR};
    color: {T.STATUS_ERROR};
}}
QToolBar::separator {{
    background-color: {T.BORDER_SUBTLE};
    width: 1px;
    margin: 4px 6px;
}}

/* ----- Primary (accent) button ----- */
QPushButton#primary, QToolBar QToolButton#primary {{
    background-color: {T.ACCENT_DIM};
    border: 1px solid {T.ACCENT};
    color: {T.TEXT_PRIMARY};
    font-weight: {T.WEIGHT_SEMIBOLD};
    padding: 6px 16px;
    border-radius: {T.RADIUS_CARD}px;
}}
QPushButton#primary:hover, QToolBar QToolButton#primary:hover {{
    background-color: #3a8862;
    border-color: {T.ACCENT_HOVER};
}}
QPushButton#primary:pressed, QToolBar QToolButton#primary:pressed {{
    background-color: {T.ACCENT_DIM};
}}

QPushButton {{
    background-color: {T.BG_ELEVATED};
    color: {T.TEXT_PRIMARY};
    border: 1px solid {T.BORDER_STRONG};
    border-radius: {T.RADIUS_CARD}px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background-color: {T.BG_HOVER}; border-color: {T.BORDER_HOVER}; }}
QPushButton:pressed {{ background-color: {T.BG_INSET}; }}
QPushButton:disabled {{ color: {T.TEXT_DISABLED}; border-color: {T.BORDER_SUBTLE}; }}
QPushButton#link {{ background: transparent; border: none; color: {T.TEXT_MUTED};
    padding: 6px 4px; text-decoration: underline; }}
QPushButton#link:hover {{ color: {T.ACCENT}; background: transparent; }}

/* ----- Splitter ----- */
QSplitter::handle {{ background-color: {T.BG_BASE}; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:hover {{ background-color: {T.BORDER_SUBTLE}; }}

/* ----- Status bar ----- */
QStatusBar {{
    background-color: {T.BG_PANEL};
    color: {T.TEXT_SECONDARY};
    border-top: 1px solid {T.BORDER_SUBTLE};
}}
QStatusBar::item {{ border: 0; }}
QLabel#versionLabel {{ color: {T.TEXT_MUTED}; font-size: {T.TEXT_MICRO}px; padding: 0 6px 0 2px; }}
QLabel#versionLabel:hover {{ color: {T.ACCENT}; text-decoration: underline; }}

/* ----- Tabs ----- */
QTabWidget::pane {{ background-color: {T.BG_PANEL}; border: 1px solid {T.BORDER_SUBTLE}; }}
QTabBar::tab {{
    background-color: {T.BG_PANEL};
    color: {T.TEXT_SECONDARY};
    padding: 7px 14px;
    border: 1px solid {T.BORDER_SUBTLE};
    border-bottom: 0;
    font-weight: {T.WEIGHT_SEMIBOLD};
}}
QTabBar::tab:hover {{ color: {T.TEXT_PRIMARY}; background-color: {T.BG_ELEVATED}; }}
QTabBar::tab:selected {{
    background-color: {T.BG_ELEVATED};
    color: {T.TEXT_PRIMARY};
    border-bottom: 2px solid {T.ACCENT};
}}

/* ----- Inputs ----- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: {T.BG_INSET};
    color: {T.TEXT_PRIMARY};
    border: 1px solid {T.BORDER_STRONG};
    border-radius: {T.RADIUS_INPUT}px;
    padding: 6px 8px;
    selection-background-color: {T.ACCENT_DIM};
    selection-color: {T.TEXT_PRIMARY};
}}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QSpinBox:hover,
QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {T.BORDER_HOVER}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QComboBox:focus {{ border: 2px solid {T.ACCENT}; padding: 5px 7px; }}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {T.TEXT_SECONDARY};
    width: 0; height: 0;
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {T.BG_PANEL};
    color: {T.TEXT_PRIMARY};
    border: 1px solid {T.BORDER_STRONG};
    selection-background-color: {T.ACCENT_SOFT};
    selection-color: {T.TEXT_PRIMARY};
    padding: 2px;
    outline: 0;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background-color: {T.BG_ELEVATED};
    border: 0;
    width: 16px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {T.BG_HOVER};
}}

/* ----- Lists / trees ----- */
QListView, QListWidget, QTreeView {{
    background-color: {T.BG_INSET};
    color: {T.TEXT_PRIMARY};
    border: 1px solid {T.BORDER_SUBTLE};
    border-radius: {T.RADIUS_INPUT}px;
    selection-background-color: {T.ACCENT_SOFT};
    selection-color: {T.TEXT_PRIMARY};
    outline: 0;
}}
QListWidget::item {{ padding: 7px 9px; border-radius: {T.RADIUS_INPUT}px; }}
QListWidget::item:hover {{ background-color: {T.BG_HOVER}; }}
QListWidget::item:selected {{ background-color: {T.ACCENT_SOFT}; }}

/* ----- Group box ----- */
QGroupBox {{
    background-color: {T.BG_PANEL};
    border: 1px solid {T.BORDER_SUBTLE};
    border-radius: {T.RADIUS_CARD}px;
    margin-top: 14px;
    padding: {T.SPACE_MD}px {T.SPACE_MD}px {T.SPACE_MD}px {T.SPACE_MD}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 2px 8px;
    color: {T.ACCENT};
    font-weight: {T.WEIGHT_SEMIBOLD};
    font-size: {T.TEXT_LABEL}px;
}}

/* ----- Checkbox ----- */
QCheckBox {{ color: {T.TEXT_SECONDARY}; spacing: 8px; padding: 2px 0; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {T.BORDER_STRONG};
    border-radius: {T.RADIUS_INPUT}px;
    background-color: {T.BG_INSET};
}}
QCheckBox::indicator:hover {{ border-color: {T.ACCENT}; }}
QCheckBox::indicator:checked {{
    background-color: {T.ACCENT_DIM};
    border-color: {T.ACCENT};
}}

/* ----- Scrollbars ----- */
QScrollBar:vertical {{ background: {T.BG_INSET}; width: 11px; border: 0; margin: 0; }}
QScrollBar::handle:vertical {{ background: {T.BORDER_STRONG}; min-height: 28px; border-radius: 5px; }}
QScrollBar::handle:vertical:hover {{ background: {T.BORDER_HOVER}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: {T.BG_INSET}; height: 11px; border: 0; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {T.BORDER_STRONG}; min-width: 28px; border-radius: 5px; }}
QScrollBar::handle:horizontal:hover {{ background: {T.BORDER_HOVER}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

QScrollArea {{ border: 0; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ----- Semantic label classes ----- */
QLabel#panelHeader {{
    color: {T.TEXT_PRIMARY};
    font-size: {T.TEXT_HEADER}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    letter-spacing: 1px;
    padding-bottom: 2px;
}}
QLabel#sectionHeader {{
    color: {T.ACCENT};
    font-weight: {T.WEIGHT_SEMIBOLD};
    font-size: {T.TEXT_LABEL}px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QLabel#hint {{ color: {T.TEXT_MUTED}; font-size: {T.TEXT_BODY}px; }}
QLabel#muted {{ color: {T.TEXT_MUTED}; }}

/* ----- Help tab cards ----- */
QFrame#helpCard {{ background-color: {T.BG_ELEVATED}; border: 1px solid {T.BORDER_SUBTLE}; border-radius: {T.RADIUS_CARD}px; }}
QLabel#helpTitle {{ color: {T.TEXT_PRIMARY}; font-weight: {T.WEIGHT_SEMIBOLD}; font-size: {T.TEXT_LABEL}px; }}
QLabel#helpBody {{ color: {T.TEXT_SECONDARY}; font-size: {T.TEXT_BODY}px; }}
QLabel#iconPreview {{ background-color: {T.BG_INSET}; border: 1px solid {T.BORDER_SUBTLE}; border-radius: {T.RADIUS_INPUT}px; }}

/* ----- Event editor ----- */
QFrame#optionCard {{ background-color: {T.BG_ELEVATED}; border: 1px solid {T.BORDER_SUBTLE}; border-radius: {T.RADIUS_CARD}px; }}
QPlainTextEdit#scriptPreview {{ font-family: {T.FONT_MONO}; color: {T.TEXT_SECONDARY}; background-color: {T.BG_INSET}; }}

QFrame#divider {{ background-color: {T.BORDER_SUBTLE}; max-height: 1px; min-height: 1px; border: 0; }}

/* ----- Chips (multi-select selector) ----- */
QFrame#chip {{ background-color: {T.ACCENT_SOFT}; border: 1px solid {T.ACCENT_DIM}; border-radius: 10px; }}
QFrame#chip QLabel {{ color: {T.TEXT_PRIMARY}; font-size: {T.TEXT_MICRO}px; }}
QPushButton#chipClose {{ background: transparent; border: 0; color: {T.TEXT_MUTED}; padding: 0; font-size: {T.TEXT_LABEL}px; font-weight: {T.WEIGHT_BOLD}; }}
QPushButton#chipClose:hover {{ color: {T.STATUS_ERROR}; }}

/* Row delete buttons (× to remove a party / leader / modifier row) */
QPushButton#deleteButton {{ color: {T.TEXT_SECONDARY}; font-size: {T.TEXT_TITLE}px; font-weight: {T.WEIGHT_BOLD}; padding: 0; }}
QPushButton#deleteButton:hover {{ color: {T.STATUS_ERROR}; border-color: {T.STATUS_ERROR_BORDER}; background-color: {T.STATUS_ERROR_BG}; }}

/* ----- Count pills ----- */
QLabel#pillOk, QLabel#pillError, QLabel#pillWarn, QLabel#pillNeutral {{
    border-radius: 9px;
    padding: 2px 10px;
    font-size: {T.TEXT_MICRO}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
}}
QLabel#pillNeutral {{ background-color: {T.BG_ELEVATED}; color: {T.TEXT_SECONDARY}; }}
QLabel#pillOk {{ background-color: {T.ACCENT_SOFT}; color: {T.STATUS_OK}; }}
QLabel#pillError {{ background-color: {T.STATUS_ERROR_BG}; color: {T.STATUS_ERROR}; }}
QLabel#pillWarn {{ background-color: {T.STATUS_WARN_BG}; color: {T.STATUS_WARN}; }}
QLabel#bridgePill {{
    border-radius: 9px;
    padding: 2px 10px;
    font-size: {T.TEXT_MICRO}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    background-color: {T.BG_ELEVATED};
    color: {T.TEXT_MUTED};
}}
QLabel#bridgePill[active="true"] {{ background-color: {T.ACCENT_SOFT}; color: {T.STATUS_OK}; }}

/* ----- Issue cards ----- */
QFrame#issueCardError {{ background-color: {T.STATUS_ERROR_BG}; border: 1px solid {T.STATUS_ERROR_BORDER}; border-radius: {T.RADIUS_CARD}px; }}
QFrame#issueCardWarning {{ background-color: {T.STATUS_WARN_BG}; border: 1px solid {T.STATUS_WARN_BORDER}; border-radius: {T.RADIUS_CARD}px; }}
QLabel#issueTextError {{ color: {T.STATUS_ERROR}; }}
QLabel#issueTextWarning {{ color: {T.STATUS_WARN}; }}
QLabel#issueSymbolError {{ color: {T.STATUS_ERROR}; font-weight: {T.WEIGHT_BOLD}; }}
QLabel#issueSymbolWarning {{ color: {T.STATUS_WARN}; font-weight: {T.WEIGHT_BOLD}; }}

/* ----- Graphics view ----- */
QGraphicsView {{ background-color: {T.BG_BASE}; border: 1px solid {T.BORDER_SUBTLE}; }}
"""


DARK_QSS = build_qss()
