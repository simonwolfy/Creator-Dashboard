from __future__ import annotations

import re

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

DEFAULT_ACCENT = "#7137c8"
ACCENT_PRESETS = (
    ("Creator purple", DEFAULT_ACCENT),
    ("Ocean blue", "#2563eb"),
    ("Emerald", "#059669"),
    ("Sunset orange", "#ea580c"),
    ("Rose", "#e11d48"),
)

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_valid_accent(value: str) -> bool:
    return bool(_HEX_COLOR.fullmatch(str(value or "")))


def normalize_accent(value: str) -> str:
    return str(value).lower() if is_valid_accent(value) else DEFAULT_ACCENT


def resolve_theme(theme: str) -> str:
    requested = str(theme or "dark").lower()
    if requested in {"dark", "light"}:
        return requested
    app = QApplication.instance()
    if app is None:
        return "dark"
    window_color = app.palette().color(QPalette.ColorRole.Window)
    return "dark" if window_color.lightness() < 128 else "light"


def _accent_variant(accent: str, factor: int) -> str:
    color = QColor(normalize_accent(accent))
    varied = color.lighter(factor) if factor >= 100 else color.darker(200 - factor)
    return varied.name()


def build_stylesheet(theme: str, accent: str) -> str:
    mode = resolve_theme(theme)
    accent = normalize_accent(accent)
    accent_hover = _accent_variant(accent, 116 if mode == "dark" else 88)
    accent_pressed = _accent_variant(accent, 82 if mode == "dark" else 76)
    accent_text = "#111827" if QColor(accent).lightness() > 165 else "#ffffff"

    if mode == "light":
        background = "#f4f6fb"
        surface = "#ffffff"
        surface_alt = "#eef2f8"
        field = "#ffffff"
        text = "#172033"
        muted = "#5f6b82"
        border = "#cfd7e7"
        header = "#e5eaf3"
        disabled = "#a7afbf"
    else:
        background = "#0d1018"
        surface = "#131827"
        surface_alt = "#171d2d"
        field = "#171d2d"
        text = "#eef1ff"
        muted = "#aab3d2"
        border = "#303a5e"
        header = "#202841"
        disabled = "#626b82"

    return f"""
QMainWindow, QDialog, QWidget {{
    background: {background}; color: {text}; font-size: 13px;
}}
QTreeWidget {{
    background: {surface}; border: none; padding: 8px 6px; font-size: 14px;
    outline: none;
}}
QTreeWidget::item {{ padding: 8px 7px; border-radius: 7px; }}
QTreeWidget::item:hover {{ background: {surface_alt}; }}
QTreeWidget::item:selected {{ background: {accent}; color: {accent_text}; }}
QTreeWidget::branch {{ background: transparent; }}
QPushButton, QToolButton {{
    background: {accent}; color: {accent_text}; border: none;
    padding: 9px 14px; border-radius: 7px; font-weight: 600;
}}
QPushButton:hover, QToolButton:hover {{ background: {accent_hover}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {accent_pressed}; }}
QPushButton:disabled, QToolButton:disabled {{
    background: {surface_alt}; color: {disabled}; border: 1px solid {border};
}}
QToolButton::menu-indicator {{ subcontrol-position: right center; right: 7px; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit,
QPlainTextEdit, QTextEdit {{
    background: {field}; color: {text}; border: 1px solid {border};
    padding: 7px; border-radius: 6px;
}}
QComboBox QAbstractItemView {{
    background: {surface}; color: {text}; selection-background-color: {accent};
    selection-color: {accent_text};
}}
QTableView, QTableWidget {{
    background: {surface}; color: {text}; gridline-color: {border};
    alternate-background-color: {surface_alt}; selection-background-color: {accent};
    selection-color: {accent_text}; border: 1px solid {border};
}}
QHeaderView::section {{
    background: {header}; color: {text}; padding: 9px 10px;
    border: none; border-right: 1px solid {border}; font-weight: 600;
}}
QTabWidget::pane {{ border: 1px solid {border}; top: -1px; }}
QTabBar::tab {{
    background: {surface}; color: {muted}; padding: 9px 12px;
    border: 1px solid {border}; border-bottom: none;
}}
QTabBar::tab:selected {{ background: {surface_alt}; color: {text}; }}
QGroupBox {{
    border: 1px solid {border}; border-radius: 8px; margin-top: 10px;
    padding-top: 12px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
QMenu {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 5px; }}
QMenu::item {{ padding: 8px 24px 8px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {accent}; color: {accent_text}; }}
QStatusBar {{ background: {surface}; color: {muted}; }}
QScrollBar:horizontal, QScrollBar:vertical {{ background: {background}; border: none; }}
#pageTitle {{ font-size: 27px; font-weight: 700; padding: 8px 0 14px 0; }}
#metricCard {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; padding: 8px; }}
#metricTitle {{ color: {muted}; font-weight: 600; }}
#metricValue {{ font-size: 24px; font-weight: 700; }}
#metricSubtitle {{ color: {muted}; }}
#navigationGroup {{ font-weight: 700; color: {muted}; }}
#accentPreview {{ background: {accent}; border: 1px solid {border}; border-radius: 6px; }}
"""
