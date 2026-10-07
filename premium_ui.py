from __future__ import annotations

from PySide6.QtCore import QColor
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGraphicsDropShadowEffect


def premium_shadow(widget, color="#6c8aff", blur=18, x=0, y=8):
    """Apply a subtle premium glass-shadow to a widget."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(x)
    effect.setYOffset(y)
    effect.setColor(QColor(color))
    widget.setGraphicsEffect(effect)


def rgba(hex_color, alpha):
    """Convert a #RRGGBB color into rgba(..., alpha) CSS-friendly string."""
    h = (hex_color or "#000000").lstrip('#')
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def build_premium_qss(p, font_family="Segoe UI", font_size=13):
    """Premium dark/light glassmorphism stylesheet for TaskTrail."""
    return f"""
    QWidget {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                   stop:0 {p['bg']},
                                   stop:0.5 {p['s1']},
                                   stop:1 {p['bg']});
        color:{p['text']};
        font-family:"{font_family}";
        font-size:{font_size}px;
    }}

    QMainWindow, QDialog {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                   stop:0 {p['bg']},
                                   stop:1 {p['s1']});
    }}

    QFrame#sidebar {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                   stop:0 {rgba(p['s1'], 0.92)},
                                   stop:1 {rgba(p['s2'], 0.88)});
        border: 1px solid {rgba(p['accent'], 0.18)};
        border-radius: 24px;
        margin: 12px 0 12px 12px;
    }}

    QFrame#topbar {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                   stop:0 {rgba(p['s1'], 0.8)},
                                   stop:1 {rgba(p['s2'], 0.75)});
        border: 1px solid {rgba(p['accent'], 0.10)};
        border-radius: 18px;
        margin: 12px 12px 0 0;
    }}

    QLabel#brand {{
        font-size:{font_size+8}px;
        font-weight:800;
        color:{p['accent']};
        letter-spacing: 0.08em;
    }}

    QLabel#brandSub, QLabel#navSection {{
        color:{p['text3']};
        font-size:{font_size-4}px;
        letter-spacing:1px;
    }}

    QLabel#pageTitle {{
        font-size:{font_size+5}px;
        font-weight:700;
        color:{p['text']};
    }}

    QLabel#pageMonth {{
        color:{p['accent']};
        background:{rgba(p['accent'], 0.14)};
        border-radius:12px;
        padding: 4px 10px;
        font-weight:700;
    }}

    QPushButton#nav {{
        text-align:left;
        padding:10px 18px;
        border: 1px solid transparent;
        border-left:3px solid transparent;
        border-radius:12px;
        color:{p['text2']};
        background: transparent;
        font-weight:600;
    }}

    QPushButton#nav:hover {{
        color:{p['text']};
        background:{rgba(p['accent'], 0.08)};
        border-color:{rgba(p['accent'], 0.20)};
    }}

    QPushButton#nav:checked {{
        color:{p['accent']};
        background:{rgba(p['accent'], 0.12)};
        border-left:3px solid {p['accent']};
    }}

    QPushButton#month {{
        padding:6px 2px;
        border: 1px solid {p['border']};
        border-radius:10px;
        color:{p['text3']};
        background:transparent;
        font-size:{font_size-3}px;
        font-weight:700;
    }}

    QPushButton#month:hover {{
        border-color:{p['accent']};
        color:{p['accent']};
        background:{rgba(p['accent'], 0.08)};
    }}

    QPushButton#month:checked {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                   stop:0 {p['accent']},
                                   stop:1 {rgba(p['accent'], 0.75)});
        border-color:{p['accent']};
        color:#ffffff;
    }}

    QPushButton {{
        padding:8px 14px;
        border-radius:14px;
        border:1.5px solid {p['border']};
        background:rgba(255,255,255,0.02);
        color:{p['text2']};
        font-weight:700;
    }}

    QPushButton:hover {{
        color:{p['text']};
        border-color:{p['accent']};
        background:{rgba(p['accent'], 0.06)};
    }}

    QPushButton#primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                   stop:0 {p['accent']},
                                   stop:1 {rgba(p['accent'], 0.78)});
        border: 1px solid {p['accent']};
        color:#ffffff;
    }}

    QPushButton#primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                   stop:0 {rgba(p['accent'], 0.9)},
                                   stop:1 {p['accent']});
    }}

    QPushButton#danger {{
        color:#ff6584;
        border-color:#ff6584;
    }}

    QPushButton#ghost {{
        border:none;
        color:{p['text3']};
        padding:2px 6px;
    }}

    QPushButton#ghost:hover {{
        color:{p['text']};
        background:{p['s3']};
        border-radius:8px;
    }}

    QPushButton#addk {{
        border:1.5px dashed {p['border']};
        border-radius:12px;
        color:{p['text3']};
        background:{rgba(p['s1'], 0.3)};
        font-weight:600;
        text-align:left;
        padding:8px 14px;
    }}

    QPushButton#addk:hover {{
        border-color:{p['accent']};
        color:{p['accent']};
        background:{rgba(p['accent'], 0.08)};
    }}

    QLineEdit, QTextEdit, QComboBox, QDateEdit, QSpinBox, QFontComboBox {{
        background:{p['s3']};
        border:1.5px solid {p['border']};
        border-radius:10px;
        padding:7px 10px;
        color:{p['text']};
        selection-background-color:{p['accent']};
    }}

    QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus {{
        border-color:{p['accent']};
        background:{p['s2']};
    }}

    QComboBox QAbstractItemView {{
        background:{p['s2']};
        color:{p['text']};
        selection-background-color:{p['accent']};
        border:1px solid {p['border']};
    }}

    QFrame#panel, QFrame#kpi, QFrame#card, QFrame#colhead, QFrame#group {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                   stop:0 {rgba(p['s2'], 0.96)},
                                   stop:1 {rgba(p['s1'], 0.94)});
        border:1px solid {rgba(p['accent'], 0.12)};
        border-radius:18px;
    }}

    QFrame#card:hover {{
        border-color:{rgba(p['accent'], 0.42)};
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                   stop:0 {rgba(p['s2'], 0.98)},
                                   stop:1 {rgba(p['s1'], 0.96)});
    }}

    QFrame#detail {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                   stop:0 {rgba(p['s1'], 0.95)},
                                   stop:1 {rgba(p['s2'], 0.96)});
        border-left:1px solid {p['border']};
    }}

    QListWidget {{
        background:transparent;
        border:none;
        outline:0;
    }}

    QListWidget::item {{
        background:transparent;
        border:none;
        padding:0;
        margin:0 0 8px 0;
    }}

    QListWidget::item:selected {{
        background:transparent;
    }}

    QScrollBar:vertical {{
        width:10px;
        background:transparent;
    }}

    QScrollBar::handle {{
        background:{rgba(p['accent'], 0.35)};
        border-radius:5px;
        min-height:24px;
    }}

    QScrollBar::handle:hover {{
        background:{rgba(p['accent'], 0.55)};
    }}

    QMenu {{
        background:{p['s2']};
        border:1px solid {p['border']};
        border-radius:12px;
    }}

    QMenu::item:selected {{
        background:{p['accent']};
        color:#ffffff;
    }}

    QToolTip {{
        background:{p['s2']};
        color:{p['text']};
        border:1px solid {p['border']};
        border-radius:8px;
    }}

    QLabel, QCheckBox {{
        background: transparent;
    }}

    QLabel#muted {{
        color:{p['text3']};
    }}

    QLabel#muted2 {{
        color:{p['text2']};
    }}

    QLabel#kpiVal {{
        font-size:{font_size+16}px;
        font-weight:700;
    }}

    QLabel#kpiLabel {{
        color:{p['text2']};
        font-size:{font_size-3}px;
        letter-spacing:1px;
    }}

    QLabel#sectitle {{
        font-weight:700;
        font-size:{font_size+1}px;
    }}

    QLabel#badge {{
        border-radius:10px;
        padding:2px 8px;
        font-size:{font_size-4}px;
        font-weight:700;
    }}

    QCheckBox {{
        spacing:8px;
    }}

    QCheckBox::indicator {{
        width:16px;
        height:16px;
        border-radius:4px;
        border:2px solid {p['border2']};
        background:transparent;
    }}

    QCheckBox::indicator:checked {{
        background:{p['accent']};
        border-color:{p['accent']};
    }}
    """


def apply_premium_theme(window):
    """Apply premium vapour/glass styling to the app shell."""
    p = window.palette_dict()
    qss = build_premium_qss(p, window.appearance.get("font") or "Segoe UI", int(window.appearance.get("size", 13)))
    window.setStyleSheet(qss)

    if hasattr(window, "sidebar"):
        premium_shadow(window.sidebar, p["accent"], blur=26, y=12)
    if hasattr(window, "topbar"):
        premium_shadow(window.topbar, p["accent"], blur=18, y=8)
    if hasattr(window, "dock"):
        premium_shadow(window.dock, p["accent"], blur=24, y=0)


__all__ = ["premium_shadow", "rgba", "build_premium_qss", "apply_premium_theme"]
