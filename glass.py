"""
glass.py — the "glass" design layer for TaskTrail.

Everything visual that is not business logic lives here:

  * design tokens + a contrast-checked palette resolver            (GLASS, resolve_palette)
  * native window backdrops: Mica / Acrylic / Tabbed on Windows    (apply_backdrop)
  * painted depth: layered soft shadows, frosted fills, glow edges (GlassFrame, paint_card)
  * vector line icons that change opacity with focus state         (draw_icon, make_icon)
  * custom widgets: Sidebar/NavButton, GlowProgress, Toast, ...    (see classes)
  * in-window blur overlays (command palette) and glass menus      (GlassOverlay, GlassMenu)
  * a tiny async job runner so slow work never blocks the UI       (run_job)

Only PySide6 + the standard library are used.  Native blur is Windows-only (DWM); on every other
platform the same widgets render over a *simulated* glass backdrop (gradient + soft colour glows).
"""
import sys
import os
import itertools
import math

from PySide6.QtCore import (Qt, QObject, QRunnable, QThreadPool, QTimer, Signal, Slot, QRectF, QPointF, QRect, QSize,
                            QEvent, QEasingCurve, QVariantAnimation, QEventLoop, QPropertyAnimation, QAbstractAnimation)
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QBrush, QLinearGradient, QRadialGradient, QPixmap, QImage,
                           QIcon, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QCursor)
from PySide6.QtWidgets import (QApplication, QWidget, QFrame, QDialog, QMenu, QPushButton, QVBoxLayout, QHBoxLayout,
                               QGraphicsOpacityEffect, QGraphicsBlurEffect, QGraphicsScene, QGraphicsPixmapItem,
                               QGraphicsDropShadowEffect, QSizePolicy, QLabel)


# ═══════════════════════════════════════════════════════════════════════════
#  COLOUR MATHS  (WCAG 2.x relative luminance / contrast ratio)
# ═══════════════════════════════════════════════════════════════════════════
def qc(c, a=None):
    """QColor from '#rrggbb' / QColor, optional alpha 0..1."""
    q = QColor(c)
    if a is not None:
        q.setAlphaF(max(0.0, min(1.0, a)))
    return q


def rgba(c, a):
    """CSS rgba() string — Qt stylesheets do not accept #RRGGBBAA."""
    q = QColor(c)
    return f"rgba({q.red()},{q.green()},{q.blue()},{max(0.0, min(1.0, a)):.3f})"


def mix(a, b, t):
    """Linear mix of two colours; t=0 → a, t=1 → b.  Returns '#rrggbb'."""
    A, B = QColor(a), QColor(b)
    return QColor(round(A.red() + (B.red() - A.red()) * t), round(A.green() + (B.green() - A.green()) * t),
                  round(A.blue() + (B.blue() - A.blue()) * t)).name()


def over(fg, bg, a):
    """Composite fg at alpha a over an opaque bg → '#rrggbb'."""
    return mix(bg, fg, a)


def _lin(v):
    v /= 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(c):
    q = QColor(c)
    return 0.2126 * _lin(q.red()) + 0.7152 * _lin(q.green()) + 0.0722 * _lin(q.blue())


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg, bg, minimum=4.5, toward=None):
    """Nudge `fg` toward `toward` (default: white on dark bg, black on light bg) until contrast(fg, bg) >= minimum."""
    if toward is None:
        toward = "#ffffff" if luminance(bg) < 0.4 else "#000000"
    if contrast(fg, bg) >= minimum:
        return QColor(fg).name()
    for i in range(1, 41):
        c = mix(fg, toward, i / 40)
        if contrast(c, bg) >= minimum:
            return c
    return QColor(toward).name()


def readable_on(bg, preferred="#ffffff", minimum=4.5):
    """Text colour for a filled chip: `preferred` if it is readable on `bg`, else near-black / white."""
    if contrast(preferred, bg) >= minimum:
        return QColor(preferred).name()
    light, dark = "#ffffff", "#0d0e15"
    return light if contrast(light, bg) >= contrast(dark, bg) else dark


# ═══════════════════════════════════════════════════════════════════════════
#  DESIGN TOKENS
# ═══════════════════════════════════════════════════════════════════════════
VIOLET, CYAN = "#8b5cf6", "#06b6d4"
BASE = {
    "dark": dict(bg="#0d0e15", surface="#1a1c29", text="#f2f3f9", accent=VIOLET, accent2=CYAN),
    "light": dict(bg="#f5f6fa", surface="#ffffff", text="#14151f", accent="#7c3aed", accent2="#0891b2"),
}
# Opacity of the tint laid over the OS backdrop (spec: dark 85 %, light 80 %).
DEFAULT_TINT = {"dark": 0.85, "light": 0.80}
RADIUS = dict(control=10, card=10, panel=12, menu=8)
SPRING = 1.25          # overshoot of the "spring" easing used for layout transitions


def resolve_palette(theme, overrides=None):
    """Build the full token set for 'dark' | 'light', applying user overrides (bg/surface/text/accent).
    Secondary text colours are *derived* and contrast-checked against the card colour, so custom
    colours and presets can never produce unreadable text."""
    dark = theme == "dark"
    b = dict(BASE[theme])
    for k in ("bg", "surface", "text", "accent"):
        if overrides and overrides.get(k):
            b[k] = overrides[k]
    if overrides and overrides.get("accent") and not overrides.get("accent2"):
        b["accent2"] = b["accent2"]            # secondary glow stays cyan unless the user changes it
    bg, surface, text, accent = b["bg"], b["surface"], b["text"], b["accent"]
    card_a = 0.62 if dark else 0.74
    card = over(surface, bg, card_a)           # what a card really looks like (surface over backdrop)
    p = dict(dark=dark, bg=bg, surface=surface, text=text, accent=accent, accent2=b["accent2"], card=card)
    p["s1"] = mix(bg, surface, 0.35)
    p["s2"] = surface
    p["s3"] = mix(surface, text, 0.06)
    p["s4"] = mix(surface, text, 0.13)
    p["text2"] = ensure_contrast(mix(text, bg, 0.26), card, 7.0)
    p["text3"] = ensure_contrast(mix(text, bg, 0.46), card, 4.6)
    p["accent_text"] = ensure_contrast(accent, card, 4.5)            # accent used AS TEXT on glass
    p["accent2_text"] = ensure_contrast(b["accent2"], card, 4.5)
    # primary button: gradient whose lightest stop still carries white text at >= 4.5:1
    top = ensure_contrast(accent, "#ffffff", 4.5, toward="#000000") if contrast(accent, "#ffffff") < 4.5 else accent
    p["btn_top"], p["btn_bot"] = top, mix(top, "#2a1a6e" if dark else "#1b1050", 0.28)
    p["border_hi"] = qc("#ffffff", 0.20 if dark else 0.95)
    p["border_lo"] = qc("#ffffff", 0.05) if dark else qc("#1e2346", 0.10)
    p["hairline"] = qc("#ffffff", 0.09) if dark else qc("#1e2346", 0.10)
    p["shadow"] = "#000000" if dark else "#1b2050"
    p["danger"] = ensure_contrast("#ff6584", card, 4.5)
    p["ok"] = "#34d399" if dark else "#0f9b6c"
    return p


class GlassState:
    """Process-wide design state.  Widgets read it at paint time, so changing it + repainting re-themes them."""
    def __init__(self):
        self.motion = True
        self.native = ""            # "", "mica", "acrylic", "tabbed" — what the OS is actually providing right now
        self.tint = dict(DEFAULT_TINT)
        self.jobs = 0
        self.set_theme("dark")

    def set_theme(self, theme, overrides=None):
        self.theme = theme
        self.dark = theme == "dark"
        self.p = resolve_palette(theme, overrides)

    # --- fills (QColor, translucent) ---
    def card_fill(self, hover=0.0):
        p = self.p
        return qc(p["s2"], (0.62 if self.dark else 0.74) + 0.12 * hover)

    def sidebar_fill(self):
        return qc(self.p["s1"], 0.58 if self.dark else 0.50)

    def input_fill(self):
        return qc(self.p["s3"], 0.70 if self.dark else 0.80)

    def tint_alpha(self):
        return self.tint["dark" if self.dark else "light"]


GLASS = GlassState()


def pick_font_family():
    """Best available UI face: Segoe UI Variable (Win 11) → Inter → SF Pro (macOS) → Segoe UI → system."""
    have = set(QFontDatabase.families())
    for f in ("Segoe UI Variable Text", "Segoe UI Variable Display", "Inter", "SF Pro Text", "SF Pro Display",
              ".AppleSystemUIFont", "Segoe UI", "Helvetica Neue", "Noto Sans", "Ubuntu"):
        if f in have:
            return f
    return QApplication.font().family()


# ═══════════════════════════════════════════════════════════════════════════
#  PAINTING PRIMITIVES: layered soft shadows, frosted fill, glass border
# ═══════════════════════════════════════════════════════════════════════════
def rounded(r, radius):
    path = QPainterPath()
    path.addRoundedRect(QRectF(r), radius, radius)
    return path


_SHADOW_CACHE = {}


def _shadow_pixmap(w, h, radius, layers, dpr):
    """Pre-rendered stack of soft shadow layers around a w×h rounded rect (cached: cards repaint on every hover tick)."""
    key = (w, h, radius, tuple(layers), dpr)
    pm = _SHADOW_CACHE.get(key)
    if pm is not None:
        return pm
    pad = int(max(s + abs(dy) for s, dy, _, _ in layers)) + 2
    pm = QPixmap(int((w + 2 * pad) * dpr), int((h + 2 * pad) * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    for spread, dy, alpha, color in layers:
        n = max(4, int(spread * 1.2))
        a = 1 - (1 - min(0.95, alpha)) ** (1.0 / n)        # n stacked layers accumulate to `alpha` at the edge
        for i in range(n, 0, -1):
            g = spread * (i / n) ** 0.85
            c = QColor(color)
            c.setAlphaF(a)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(pad - g, pad - g + dy, w + 2 * g, h + 2 * g), radius + g, radius + g)
    p.end()
    if len(_SHADOW_CACHE) > 160:
        _SHADOW_CACHE.clear()
    _SHADOW_CACHE[key] = (pm, pad)
    return _SHADOW_CACHE[key]


def shadow_layers(elev, hover=0.0, glow=None, pads=None):
    """Two-part shadow (wide ambient + tight key light) scaled by elevation 1..3; optional accent glow.
    pads=(side, top, bottom): free pixels around the card.  Each layer is scaled down to fit, otherwise the
    shadow would be clipped by the widget edge into a visible rectangle."""
    p = GLASS.p
    col = p["shadow"]
    k = 1.0 if GLASS.dark else 0.34
    e = {0: 0, 1: 1.0, 2: 1.6, 3: 2.4}[elev]
    hover = round(hover * 8) / 8.0
    raw = [(4 * e + 2, 1.5 * e, 0.16 * k * (1 + 0.5 * hover), col),
           (11 * e, 5 * e, 0.22 * k * (1 + 0.4 * hover), col)]
    if glow is not None and hover > 0.02:
        raw.append((10 + 4 * e, 0, 0.30 * hover * (1 if GLASS.dark else 0.8), glow))
    out = []
    for spread, dy, alpha, c in raw:
        if pads is not None:
            side, top, bot = pads
            f = min(1.0, side / spread, bot / max(spread + dy, 1e-6), top / max(spread - dy, 1e-6))
            spread, dy = spread * max(f, 0.0), dy * max(f, 0.0)
        if spread >= 0.8:
            out.append((round(spread, 1), round(dy, 1), alpha, c))
    return out


def paint_shadow(p, r, radius, layers, dpr=1.0, clip_inside=True):
    """Draw `layers` around rounded rect r.  The card body is clipped out so a translucent fill never
    shows the shadow through itself (which is what makes cheap glass look muddy)."""
    if not layers:
        return
    pm, pad = _shadow_pixmap(int(r.width()), int(r.height()), radius, layers, dpr)
    p.save()
    if clip_inside:
        outer = QPainterPath()
        outer.addRect(r.adjusted(-60, -60, 60, 60))
        p.setClipPath(outer.subtracted(rounded(r, radius)))
    p.drawPixmap(QPointF(r.x() - pad, r.y() - pad), pm)
    p.restore()


def paint_glass(p, r, radius, fill, sheen=None, border=True, hover=0.0, border_color=None):
    """Frosted fill + top sheen + 1px gradient edge (bright top-left, dim bottom-right)."""
    g = GLASS
    path = rounded(r, radius)
    p.fillPath(path, fill)
    sh = (0.075 if g.dark else 0.55) if sheen is None else sheen
    grad = QLinearGradient(r.topLeft(), r.bottomLeft())
    grad.setColorAt(0, qc("#ffffff", sh + 0.03 * hover))
    grad.setColorAt(0.55, qc("#ffffff", 0))
    p.fillPath(path, grad)
    if border:
        inner = rounded(r.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5)
        if border_color is not None:
            pen = QPen(border_color, 1)
        else:
            bg = QLinearGradient(r.topLeft(), r.bottomRight())
            hi, lo = g.p["border_hi"], g.p["border_lo"]
            bg.setColorAt(0, hi)
            bg.setColorAt(1, lo)
            pen = QPen(QBrush(bg), 1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(inner)


def paint_edge(p, r, radius, color, side="left"):
    """Illuminated accent edge inside a card: a solid 3px bar plus a soft colour wash fading into the card."""
    p.save()
    p.setClipPath(rounded(r, radius))
    c = QColor(color)
    if side == "left":
        p.fillRect(QRectF(r.left(), r.top(), 3, r.height()), c)
        g = QLinearGradient(r.left() + 3, 0, r.left() + 44, 0)
        g.setColorAt(0, qc(c, 0.20 if GLASS.dark else 0.14))
        g.setColorAt(1, qc(c, 0))
        p.fillRect(QRectF(r.left() + 3, r.top(), 41, r.height()), g)
    else:                                                    # bottom
        g = QLinearGradient(r.left(), 0, r.right(), 0)
        g.setColorAt(0, qc(c, 0.15)); g.setColorAt(0.12, c); g.setColorAt(0.88, c); g.setColorAt(1, qc(c, 0.15))
        p.fillRect(QRectF(r.left(), r.bottom() - 3, r.width(), 3), g)
        v = QLinearGradient(0, r.bottom() - 34, 0, r.bottom())
        v.setColorAt(0, qc(c, 0)); v.setColorAt(1, qc(c, 0.16 if GLASS.dark else 0.12))
        p.fillRect(QRectF(r.left(), r.bottom() - 34, r.width(), 31), v)
    p.restore()


def paint_backdrop(p, rect, native):
    """Window background.  native=True → translucent tint over the OS Mica/Acrylic backdrop;
    otherwise an opaque *simulated* glass backdrop (base colour + soft violet/cyan glows)."""
    g = GLASS
    P = g.p
    r = QRectF(rect)
    if native:
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(r, qc(P["bg"], g.tint_alpha()))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        glow_a = 0.10 if g.dark else 0.10
    else:
        p.fillRect(r, QColor(P["bg"]))
        glow_a = 0.30 if g.dark else 0.20
    w, h = r.width(), r.height()
    for (cx, cy, rad, col, a) in ((0.10, -0.05, 0.75, P["accent"], glow_a), (1.02, 1.05, 0.70, P["accent2"], glow_a * 0.78),
                                  (0.78, 0.05, 0.38, P["accent"], glow_a * 0.35)):
        rg = QRadialGradient(QPointF(r.left() + w * cx, r.top() + h * cy), max(w, h) * rad)
        rg.setColorAt(0, qc(col, a))
        rg.setColorAt(1, qc(col, 0))
        p.fillRect(r, rg)


# ═══════════════════════════════════════════════════════════════════════════
#  LINE ICONS  (24×24 design grid, 1.7 stroke, round caps — drawn with QPainter, so always crisp)
# ═══════════════════════════════════════════════════════════════════════════
def _rr(path, x, y, w, h, r):
    path.addRoundedRect(QRectF(x, y, w, h), r, r)


def _poly(path, pts):
    path.moveTo(*pts[0])
    for pt in pts[1:]:
        path.lineTo(*pt)


def _icon_path(name):
    P = QPainterPath()
    if name == "dashboard":
        _rr(P, 3.5, 3.5, 7, 9, 2); _rr(P, 13.5, 3.5, 7, 5, 2); _rr(P, 13.5, 11.5, 7, 9, 2); _rr(P, 3.5, 15.5, 7, 5, 2)
    elif name == "board":
        _rr(P, 3.5, 4, 4.5, 16, 1.6); _rr(P, 9.75, 4, 4.5, 10, 1.6); _rr(P, 16, 4, 4.5, 13, 1.6)
    elif name == "list":
        for y in (6.5, 12, 17.5):
            P.moveTo(9.5, y); P.lineTo(20.5, y)
            P.addEllipse(QPointF(4.8, y), 0.9, 0.9)
    elif name == "calendar":
        _rr(P, 3.5, 5, 17, 15.5, 3); P.moveTo(3.5, 10); P.lineTo(20.5, 10); P.moveTo(8, 3); P.lineTo(8, 6.8); P.moveTo(16, 3); P.lineTo(16, 6.8)
    elif name == "rollover":
        P.arcMoveTo(QRectF(4, 4, 16, 16), 150); P.arcTo(QRectF(4, 4, 16, 16), 150, -280)
        _poly(P, [(17.4, 3.2), (18.6, 7.6)]); P.moveTo(18.6, 7.6); P.lineTo(14.2, 8.6)
    elif name == "backup":
        _rr(P, 3.5, 13, 17, 7, 2.4); P.moveTo(12, 3.5); P.lineTo(12, 11); _poly(P, [(8.8, 7.8), (12, 11), (15.2, 7.8)])
        P.addEllipse(QPointF(7.4, 16.5), 0.8, 0.8)
    elif name == "palette":
        P.addEllipse(QPointF(12, 12), 8.5, 8.5)
        for (x, y) in ((8.2, 10.4), (12, 7.6), (15.8, 10.4)):
            P.addEllipse(QPointF(x, y), 0.9, 0.9)
        P.moveTo(12, 20.5); P.cubicTo(9.5, 20.5, 10, 17, 12.2, 16.2); P.cubicTo(14.6, 15.4, 17, 16.4, 20, 14.5)
    elif name == "search":
        P.addEllipse(QPointF(10.6, 10.6), 6.6, 6.6); P.moveTo(15.5, 15.5); P.lineTo(20.8, 20.8)
    elif name == "plus":
        P.moveTo(12, 5); P.lineTo(12, 19); P.moveTo(5, 12); P.lineTo(19, 12)
    elif name == "sun":
        P.addEllipse(QPointF(12, 12), 4, 4)
        for k in range(8):
            a = k * math.pi / 4
            P.moveTo(12 + 6.8 * math.cos(a), 12 + 6.8 * math.sin(a)); P.lineTo(12 + 9 * math.cos(a), 12 + 9 * math.sin(a))
    elif name == "moon":
        P.moveTo(19.5, 14.5); P.cubicTo(13.6, 17.2, 7.2, 12.6, 9.2, 5); P.cubicTo(5.2, 6.2, 3.2, 11.2, 5.6, 15.4)
        P.cubicTo(8, 19.6, 14.4, 20.6, 19.5, 14.5)
    elif name == "system":
        _rr(P, 3.5, 4.5, 17, 11.5, 2.4); P.moveTo(9, 20); P.lineTo(15, 20); P.moveTo(12, 16); P.lineTo(12, 20)
    elif name == "chevron-left":
        _poly(P, [(14.5, 6), (8.5, 12), (14.5, 18)])
    elif name == "chevron-right":
        _poly(P, [(9.5, 6), (15.5, 12), (9.5, 18)])
    elif name == "menu":
        for y in (6.5, 12, 17.5):
            P.moveTo(4.5, y); P.lineTo(19.5, y)
    elif name == "check":
        _poly(P, [(5, 12.8), (9.8, 17.4), (19, 7)])
    elif name == "check-circle":
        P.addEllipse(QPointF(12, 12), 8.5, 8.5); _poly(P, [(8.2, 12.3), (11, 15), (15.9, 9.4)])
    elif name == "circle":
        P.addEllipse(QPointF(12, 12), 8.5, 8.5)
    elif name == "close":
        P.moveTo(6, 6); P.lineTo(18, 18); P.moveTo(18, 6); P.lineTo(6, 18)
    elif name == "edit":
        _poly(P, [(4.5, 19.5), (5.2, 15.4), (15.8, 4.8), (19.2, 8.2), (8.6, 18.8), (4.5, 19.5)]); P.moveTo(13.6, 7); P.lineTo(17, 10.4)
    elif name == "dots":
        for x in (5.5, 12, 18.5):
            P.addEllipse(QPointF(x, 12), 1.1, 1.1)
    elif name == "tag":
        _poly(P, [(3.8, 12.2), (3.8, 4.8), (11.2, 4.8), (20.2, 13.8), (13.8, 20.2), (3.8, 12.2)]); P.addEllipse(QPointF(8.2, 9.2), 1.2, 1.2)
    elif name == "bolt":
        _poly(P, [(13.5, 3), (5.5, 13.5), (11.5, 13.5), (10.5, 21), (18.5, 10.5), (12.5, 10.5), (13.5, 3)])
    elif name == "download":
        P.moveTo(12, 3.8); P.lineTo(12, 15); _poly(P, [(7.6, 10.8), (12, 15.2), (16.4, 10.8)]); _poly(P, [(4.5, 16.5), (4.5, 19.8), (19.5, 19.8), (19.5, 16.5)])
    elif name == "trash":
        P.moveTo(4.5, 7); P.lineTo(19.5, 7); _poly(P, [(9, 7), (9, 4.5), (15, 4.5), (15, 7)]); _poly(P, [(6.5, 7), (7.4, 19.8), (16.6, 19.8), (17.5, 7)])
    elif name == "target":
        P.addEllipse(QPointF(12, 12), 8.5, 8.5); P.addEllipse(QPointF(12, 12), 4.2, 4.2); P.addEllipse(QPointF(12, 12), 0.6, 0.6)
    elif name == "keyboard":
        _rr(P, 2.8, 6.2, 18.4, 11.6, 2.4)
        for x in (6.6, 10.2, 13.8, 17.4):
            P.moveTo(x, 10); P.lineTo(x + 0.01, 10)
        P.moveTo(7.2, 14); P.lineTo(16.8, 14)
    elif name == "repeat":
        _poly(P, [(17, 3.5), (20, 6.5), (17, 9.5)]); P.moveTo(20, 6.5); P.lineTo(8, 6.5); P.cubicTo(5.5, 6.5, 4, 8, 4, 10.5)
        _poly(P, [(7, 20.5), (4, 17.5), (7, 14.5)]); P.moveTo(4, 17.5); P.lineTo(16, 17.5); P.cubicTo(18.5, 17.5, 20, 16, 20, 13.5)
    elif name == "arrow-right":
        P.moveTo(4.5, 12); P.lineTo(19, 12); _poly(P, [(13.5, 6.5), (19, 12), (13.5, 17.5)])
    elif name == "alert":
        _poly(P, [(12, 4), (21, 19.5), (3, 19.5), (12, 4)]); P.moveTo(12, 10); P.lineTo(12, 14.2); P.moveTo(12, 16.8); P.lineTo(12.01, 16.8)
    elif name == "report":
        _rr(P, 5, 3, 14, 18, 2.4); P.moveTo(8.5, 8); P.lineTo(15.5, 8); P.moveTo(8.5, 12); P.lineTo(15.5, 12); _poly(P, [(8.5, 17), (10.8, 14.8), (12.6, 16.2), (15.5, 13.6)])
    elif name == "logo":                       # the TaskTrail mark: a check that leaves a trail
        _poly(P, [(5.2, 12.8), (9.6, 17), (18.8, 7.2)]); P.moveTo(3.2, 18.4); P.lineTo(6.4, 18.4)
    else:                                      # unknown name → empty square (visible, so typos are noticed)
        _rr(P, 4, 4, 16, 16, 3)
    return P


_ICON_PATHS = {}


def draw_icon(p, name, rect, color, opacity=1.0, stroke=1.7):
    """Stroke a named icon into `rect` (QRectF).  `opacity` is how focus state is expressed."""
    path = _ICON_PATHS.get(name)
    if path is None:
        path = _ICON_PATHS[name] = _icon_path(name)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    c = QColor(color)
    c.setAlphaF(c.alphaF() * max(0.0, min(1.0, opacity)))
    s = rect.width() / 24.0
    p.translate(rect.x(), rect.y())
    p.scale(s, s)
    pen = QPen(c, stroke)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.restore()


def icon_pixmap(name, color, size=18, opacity=1.0, dpr=2.0):
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    draw_icon(p, name, QRectF(0, 0, size, size), color, opacity)
    p.end()
    return pm


_ICON_CACHE = {}


def make_icon(name, size=18, color=None, dim=0.62):
    """QIcon whose idle state is dimmed and whose hover/active/checked state is full strength
    (Qt picks the Active pixmap on mouse-over, Selected when checked)."""
    c = color or GLASS.p["text"]
    key = (name, size, c, dim, GLASS.p["accent_text"])
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    ic = _ICON_CACHE[key] = QIcon()
    ic.addPixmap(icon_pixmap(name, c, size, dim), QIcon.Normal, QIcon.Off)
    ic.addPixmap(icon_pixmap(name, c, size, 1.0), QIcon.Active, QIcon.Off)
    ic.addPixmap(icon_pixmap(name, GLASS.p["accent_text"], size, 1.0), QIcon.Normal, QIcon.On)
    ic.addPixmap(icon_pixmap(name, c, size, 0.3), QIcon.Disabled, QIcon.Off)
    return ic


class IconRegistry:
    """Buttons register (button, icon name); when the theme changes `refresh()` repaints every icon in the new colours."""
    def __init__(self):
        self.items = []

    def bind(self, btn, name, size=18):
        self.items.append((btn, name, size))
        btn.setIcon(make_icon(name, size)); btn.setIconSize(QSize(size, size))
        return btn

    def rebind(self, btn, name):
        for i, (b, n, s) in enumerate(self.items):
            if b is btn:
                self.items[i] = (b, name, s); b.setIcon(make_icon(name, s)); return

    def refresh(self):
        alive = []
        for btn, name, size in self.items:
            try:
                btn.setIcon(make_icon(name, size)); alive.append((btn, name, size))
            except RuntimeError:                      # C++ object already deleted
                pass
        self.items = alive


ICONS = IconRegistry()


# ═══════════════════════════════════════════════════════════════════════════
#  MOTION
# ═══════════════════════════════════════════════════════════════════════════
def spring_curve(overshoot=SPRING):
    """Spring-loaded feel: overshoots the target slightly, then settles."""
    c = QEasingCurve(QEasingCurve.OutBack)
    c.setOvershoot(overshoot)
    return c


def tween(owner, key, start, end, ms, on_value, curve=None, on_done=None):
    """Animate start→end calling on_value(v).  One live animation per (owner, key); respects GLASS.motion."""
    live = owner.__dict__.setdefault("_tweens", {})
    old = live.pop(key, None)
    if old is not None:
        try:
            old.stop()
        except RuntimeError:
            pass
    if not GLASS.motion or ms <= 0:
        on_value(end)
        if on_done:
            on_done()
        return None
    a = QVariantAnimation(owner)
    a.setStartValue(start); a.setEndValue(end); a.setDuration(int(ms))
    a.setEasingCurve(curve or QEasingCurve(QEasingCurve.OutCubic))
    a.valueChanged.connect(lambda v: on_value(v))
    def _fin():
        live.pop(key, None)
        if on_done:
            on_done()
    a.finished.connect(_fin)
    live[key] = a
    a.start(QAbstractAnimation.DeleteWhenStopped)
    return a


# ═══════════════════════════════════════════════════════════════════════════
#  GLASS CARD / PANEL
# ═══════════════════════════════════════════════════════════════════════════
class GlassFrame(QFrame):
    """A frosted, elevated surface.  Painted (not QSS) so it can carry layered shadows, an illuminated edge
    and a hover 'lift + glow'.  The widget reserves a transparent margin for its shadow, so its *visual*
    card is `contentsRect()`; layouts placed inside are inset automatically.
    elev: 0 flat · 1 card · 2 panel · 3 floating."""
    MARGIN = {0: 0, 1: 8, 2: 14, 3: 20}

    def __init__(self, elev=1, radius=None, hoverable=False, edge=None, edge_side="left", lift=2.0, margins=None):
        super().__init__()
        self.elev, self.radius, self.hoverable = elev, radius or RADIUS["card"], hoverable
        self.edge, self.edge_side, self.lift = edge, edge_side, lift
        self._h = 0.0
        m = self.MARGIN[elev]
        l, t, r, b = margins or (m, round(m * 0.55), m, m)      # the shadow falls downward → needs less room above
        self.setContentsMargins(l, t, r, b)

    # hooks for subclasses
    def fill(self, t):
        return GLASS.card_fill(t)

    def glow_color(self):
        return GLASS.p["accent"] if self.hoverable else None

    def border_state(self):
        """Return a QColor to override the border, or None."""
        return None

    def _set_h(self, v):
        self._h = float(v)
        self.update()

    def enterEvent(self, e):
        if self.hoverable:
            tween(self, "h", self._h, 1.0, 170, self._set_h)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.hoverable:
            tween(self, "h", self._h, 0.0, 240, self._set_h)
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._h
        r = QRectF(self.contentsRect())
        cm = self.contentsMargins()
        g = max(0.0, min(self.lift * t, cm.left() - 1, cm.top() - 1)) if self.elev else 0
        r = r.adjusted(-g, -g, g, g)
        if self.elev:
            side = max(1.0, min(cm.left(), cm.right()) - self.lift - 1)
            pads = (side, max(1.0, cm.top() - self.lift - 1), max(1.0, cm.bottom() - self.lift - 1))
            paint_shadow(p, r, self.radius, shadow_layers(self.elev, t, self.glow_color(), pads), self.devicePixelRatioF())
        paint_glass(p, r, self.radius, self.fill(t), hover=t, border_color=self.border_state())
        if t > 0.01 and self.hoverable:                          # illuminated border
            p.setPen(QPen(qc(GLASS.p["accent"], 0.62 * t), 1))
            p.setBrush(Qt.NoBrush)
            p.drawPath(rounded(r.adjusted(0.5, 0.5, -0.5, -0.5), self.radius - 0.5))
        if self.edge:
            paint_edge(p, r, self.radius, self.edge, self.edge_side)
        p.end()


# ═══════════════════════════════════════════════════════════════════════════
#  GLOW PROGRESS  (neon glow instead of a solid fill; indeterminate sweep or determinate value)
# ═══════════════════════════════════════════════════════════════════════════
class GlowProgress(QWidget):
    def __init__(self, thin=False):
        super().__init__()
        self.thin = thin
        self.value = -1.0           # <0 → indeterminate
        self._shown = 0.0
        self._phase = 0.0
        self.setFixedHeight(4 if thin else 20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._sweep = QVariantAnimation(self)
        self._sweep.setStartValue(0.0); self._sweep.setEndValue(1.0); self._sweep.setDuration(1500); self._sweep.setLoopCount(-1)
        self._sweep.setEasingCurve(QEasingCurve(QEasingCurve.InOutSine))
        self._sweep.valueChanged.connect(self._tick)

    def _tick(self, v):
        self._phase = float(v)
        self.update()

    def setIndeterminate(self):
        self.value = -1.0
        self._sync()

    def setValue(self, v):
        self.value = max(0.0, min(1.0, float(v)))
        self._sync()
        tween(self, "val", self._shown, self.value, 240, self._set_shown)

    def _set_shown(self, v):
        self._shown = float(v)
        self.update()

    def _sync(self):
        run = self.isVisible() and self.value < 0 and GLASS.motion
        if run and self._sweep.state() != QAbstractAnimation.Running:
            self._sweep.start()
        elif not run and self._sweep.state() == QAbstractAnimation.Running:
            self._sweep.stop()
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._sweep.stop()

    def paintEvent(self, e):
        P = GLASS.p
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pad = 0 if self.thin else 7
        r = QRectF(self.rect()).adjusted(pad, pad, -pad, -pad)
        rad = r.height() / 2
        p.fillPath(rounded(r, rad), qc(P["accent"], 0.16))
        a, b = QColor(P["accent"]), QColor(P["accent2"])
        if self.value < 0:                                          # indeterminate: travelling comet
            seg = r.width() * 0.38
            x = r.left() - seg + (r.width() + seg) * self._phase
            seg_rect = QRectF(x, r.top(), seg, r.height())
            fill_rect = seg_rect.intersected(r)
            glow_rect = seg_rect
            grad = QLinearGradient(seg_rect.left(), 0, seg_rect.right(), 0)
            grad.setColorAt(0, qc(a, 0)); grad.setColorAt(0.5, a); grad.setColorAt(0.85, b); grad.setColorAt(1, qc(b, 0))
        else:
            w = max(r.height(), r.width() * self._shown) if self._shown > 0.001 else 0
            fill_rect = QRectF(r.left(), r.top(), w, r.height())
            glow_rect = fill_rect
            grad = QLinearGradient(r.left(), 0, max(r.right(), r.left() + 1), 0)
            grad.setColorAt(0, a); grad.setColorAt(1, b)
        if fill_rect.width() > 0.5:
            if not self.thin:                                       # halo: wide, faint layers → neon glow
                for i, al in ((3, 0.07), (2, 0.11), (1, 0.18)):
                    gr = QLinearGradient(glow_rect.left(), 0, glow_rect.right(), 0)
                    gr.setColorAt(0, qc(a, al)); gr.setColorAt(1, qc(b, al))
                    p.save(); p.setClipRect(QRectF(r.left() - pad, 0, r.width() + 2 * pad, self.height()))
                    p.fillPath(rounded(glow_rect.adjusted(-i * 1.5, -i * 1.5, i * 1.5, i * 1.5), rad + i * 1.5), gr)
                    p.restore()
            p.save(); p.setClipPath(rounded(r, rad))
            p.fillPath(rounded(fill_rect, rad), grad)
            p.restore()
        p.end()


# ═══════════════════════════════════════════════════════════════════════════
#  SIDEBAR  (collapsible, translucent, spring animation, painted nav buttons)
# ═══════════════════════════════════════════════════════════════════════════
ICON_CX = 36        # icons sit at the same x in both states, so nothing slides sideways while the width animates


class Sidebar(QFrame):
    W_OPEN, W_CLOSED = 232, 72

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self.t = 1.0                   # 0 = collapsed, 1 = expanded (may overshoot slightly: spring)
        self.expanded = True
        self.fading = []               # widgets that repaint with t
        self.on_t = None               # callback(t) for show/hide of non-painted children
        self.setFixedWidth(self.W_OPEN)

    def set_expanded(self, on, animate=True):
        self.expanded = bool(on)
        target = 1.0 if on else 0.0
        if not animate:
            self._set_t(target)
            return
        tween(self, "w", self.t, target, 420 if on else 260, self._set_t, spring_curve(0.9) if on else QEasingCurve(QEasingCurve.OutCubic))

    def _set_t(self, t):
        self.t = float(t)
        self.setFixedWidth(max(self.W_CLOSED, round(self.W_CLOSED + (self.W_OPEN - self.W_CLOSED) * self.t)))
        for w in self.fading:
            w.update()
        if self.on_t:
            self.on_t(self.t)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        r = QRectF(self.rect())
        p.fillRect(r, GLASS.sidebar_fill())
        g = QLinearGradient(0, 0, 0, r.height())                     # borderless: a hairline that fades at both ends
        h = GLASS.p["hairline"]
        g.setColorAt(0, qc(h, 0)); g.setColorAt(0.5, h); g.setColorAt(1, qc(h, 0))
        p.fillRect(QRectF(r.right() - 1, 0, 1, r.height()), g)
        p.end()


class NavButton(QPushButton):
    """Painted nav item: line icon + label + optional count.  Active = rounded accent pill with a glowing bar."""
    def __init__(self, bar, icon, label, checkable=True):
        super().__init__()
        self.bar, self.icon_name, self.label, self.badge, self.badge_hot = bar, icon, label, "", False
        self.setObjectName("navbtn")
        self.setCheckable(checkable)
        self.setFixedHeight(40)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setToolTip(label)
        self._h = 0.0
        bar.fading.append(self)

    def set_label(self, label, badge="", hot=False):
        if (label, badge, hot) != (self.label, self.badge, self.badge_hot):
            self.label, self.badge, self.badge_hot = label, badge, hot
            self.setToolTip(label + (f"  ({badge})" if badge else ""))
            self.update()

    def _set_h(self, v):
        self._h = float(v)
        self.update()

    def enterEvent(self, e):
        tween(self, "h", self._h, 1.0, 140, self._set_h)
        super().enterEvent(e)

    def leaveEvent(self, e):
        tween(self, "h", self._h, 0.0, 200, self._set_h)
        super().leaveEvent(e)

    def paintEvent(self, e):
        P = GLASS.p
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = max(0.0, min(1.0, self.bar.t))
        pill = QRectF(8, 2, self.width() - 16, self.height() - 4)
        path = rounded(pill, RADIUS["control"])
        on, h = self.isChecked(), self._h
        if on:
            p.fillPath(path, qc(P["accent"], 0.20 if GLASS.dark else 0.13))
            g = QLinearGradient(pill.left(), 0, pill.right(), 0)
            g.setColorAt(0, qc(P["accent"], 0.30 if GLASS.dark else 0.18)); g.setColorAt(1, qc(P["accent"], 0))
            p.fillPath(path, g)
            p.setPen(QPen(qc(P["accent"], 0.34), 1)); p.setBrush(Qt.NoBrush)
            p.drawPath(rounded(pill.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS["control"] - 0.5))
            cy = pill.center().y()
            p.setPen(Qt.NoPen)
            for i, al in ((4, 0.06), (3, 0.10), (2, 0.16), (1, 0.26)):            # glow around the indicator bar
                p.setBrush(qc(P["accent"], al))
                p.drawRoundedRect(QRectF(pill.left() - 1 - i, cy - 9 - i, 3 + 2 * i, 18 + 2 * i), 2 + i, 2 + i)
            p.setBrush(QColor(P["accent"]))
            p.drawRoundedRect(QRectF(pill.left() - 1, cy - 9, 3, 18), 1.5, 1.5)
            col, op = QColor(P["accent_text"]), 1.0
        else:
            if h > 0.01:
                p.fillPath(path, qc(P["text"], 0.07 * h))
            col, op = QColor(P["text"]), 0.58 + 0.37 * h
        icon_r = QRectF(ICON_CX - 10, self.height() / 2 - 10, 20, 20)
        draw_icon(p, self.icon_name, icon_r, col, op)
        if t > 0.02:
            f = QFont(self.font())
            f.setWeight(QFont.DemiBold if on else QFont.Medium)
            p.setFont(f)
            tc = QColor(P["accent_text"] if on else (P["text"] if h > 0.3 else P["text2"]))
            tc.setAlphaF(min(1.0, t * t))
            p.setPen(tc)
            right = pill.right() - 12 - (self._badge_w(p) + 6 if self.badge else 0)
            lab = QFontMetricsF(f).elidedText(self.label, Qt.ElideRight, max(10, right - 58))
            p.drawText(QRectF(58, 0, max(10, right - 58), self.height()), Qt.AlignVCenter | Qt.AlignLeft, lab)
            if self.badge:
                self._paint_badge(p, pill, t)
        elif self.badge and self.badge_hot:                       # collapsed: a dot on the icon for urgent counts only
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(P["danger"] if self.badge_hot else P["accent"]))
            p.drawEllipse(QPointF(ICON_CX + 9, self.height() / 2 - 9), 3.4, 3.4)
        p.end()

    def _badge_w(self, p):
        f = QFont(self.font()); f.setPixelSize(max(9, f.pixelSize() - 2)); f.setWeight(QFont.DemiBold)
        return QFontMetricsF(f).horizontalAdvance(self.badge) + 14

    def _paint_badge(self, p, pill, t):
        P = GLASS.p
        f = QFont(self.font()); f.setPixelSize(max(9, f.pixelSize() - 2)); f.setWeight(QFont.DemiBold)
        w = QFontMetricsF(f).horizontalAdvance(self.badge) + 14
        rr = QRectF(pill.right() - 10 - w, self.height() / 2 - 9, w, 18)
        base = QColor(P["danger"] if self.badge_hot else P["text"])
        p.setPen(Qt.NoPen)
        p.setBrush(qc(base, (0.18 if self.badge_hot else 0.10) * t))
        p.drawRoundedRect(rr, 9, 9)
        p.setFont(f)
        c = QColor(P["danger"] if self.badge_hot else P["text2"]); c.setAlphaF(t)
        p.setPen(c)
        p.drawText(rr, Qt.AlignCenter, self.badge)


class Brand(QWidget):
    def __init__(self, bar, name, sub):
        super().__init__()
        self.bar, self.name, self.sub = bar, name, sub
        self.setFixedHeight(58)
        bar.fading.append(self)

    def paintEvent(self, e):
        P = GLASS.p
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = max(0.0, min(1.0, self.bar.t))
        mark = QRectF(ICON_CX - 16, 13, 32, 32)
        paint_shadow(p, mark, 10, [(8, 2, 0.50, P["accent"])], self.devicePixelRatioF(), clip_inside=True)
        g = QLinearGradient(mark.topLeft(), mark.bottomRight())
        g.setColorAt(0, QColor(P["accent"])); g.setColorAt(1, QColor(P["accent2"]))
        p.fillPath(rounded(mark, 10), g)
        p.setPen(QPen(qc("#ffffff", 0.35), 1)); p.setBrush(Qt.NoBrush); p.drawPath(rounded(mark.adjusted(.5, .5, -.5, -.5), 9.5))
        draw_icon(p, "logo", mark.adjusted(5, 5, -5, -5), QColor("#ffffff"), 1.0, 2.0)
        if t > 0.05:
            f = QFont(self.font()); f.setPixelSize(f.pixelSize() + 3); f.setWeight(QFont.Bold)
            c = QColor(P["text"]); c.setAlphaF(t * t)
            p.setFont(f); p.setPen(c)
            p.drawText(QRectF(ICON_CX + 26, 11, 150, 20), Qt.AlignVCenter | Qt.AlignLeft, self.name)
            f2 = QFont(self.font()); f2.setPixelSize(max(8, f2.pixelSize() - 4)); f2.setLetterSpacing(QFont.AbsoluteSpacing, 1.4)
            c2 = QColor(P["text3"]); c2.setAlphaF(t * t)
            p.setFont(f2); p.setPen(c2)
            p.drawText(QRectF(ICON_CX + 26, 31, 150, 14), Qt.AlignVCenter | Qt.AlignLeft, self.sub)
        p.end()


class SectionLabel(QWidget):
    """'WORKSPACE' caption that cross-fades into a short hairline when the sidebar collapses."""
    def __init__(self, bar, text):
        super().__init__()
        self.bar, self.text = bar, text
        self.setFixedHeight(28)
        bar.fading.append(self)

    def paintEvent(self, e):
        P = GLASS.p
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = max(0.0, min(1.0, self.bar.t))
        if t > 0.05:
            f = QFont(self.font()); f.setPixelSize(max(8, f.pixelSize() - 3)); f.setWeight(QFont.DemiBold); f.setLetterSpacing(QFont.AbsoluteSpacing, 1.3)
            c = QColor(P["text3"]); c.setAlphaF(t * t)
            p.setFont(f); p.setPen(c)
            p.drawText(QRectF(22, 6, self.width() - 30, self.height() - 6), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        if t < 0.95:
            p.setPen(QPen(qc(P["hairline"], (1 - t) * 1.0), 1))
            p.drawLine(QPointF(ICON_CX - 12, self.height() / 2 + 2), QPointF(ICON_CX + 12, self.height() / 2 + 2))
        p.end()


# ═══════════════════════════════════════════════════════════════════════════
#  ROW BUTTON / TOAST / GLOW HELPERS
# ═══════════════════════════════════════════════════════════════════════════
class RowButton(QPushButton):
    """A clickable list row: coloured edge, title on the left, meta on the right, hover highlight."""
    def __init__(self, title, meta="", edge=None, urgent=False, icon=None, done=False):
        super().__init__()
        self.title, self.meta, self.edge, self.urgent, self.icon_name, self.done = title, meta, edge, urgent, icon, done
        self.setObjectName("rowbtn")
        self.setFixedHeight(38)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self._h = 0.0

    def _set_h(self, v):
        self._h = float(v)
        self.update()

    def enterEvent(self, e):
        tween(self, "h", self._h, 1.0, 130, self._set_h)
        super().enterEvent(e)

    def leaveEvent(self, e):
        tween(self, "h", self._h, 0.0, 200, self._set_h)
        super().leaveEvent(e)

    def paintEvent(self, e):
        P = GLASS.p
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        path = rounded(r, RADIUS["control"])
        p.fillPath(path, qc(P["text"], 0.035 + 0.07 * self._h))
        if self.edge:
            p.save(); p.setClipPath(path)
            p.fillRect(QRectF(r.left(), r.top(), 3, r.height()), QColor(self.edge))
            g = QLinearGradient(r.left() + 3, 0, r.left() + 50, 0)
            g.setColorAt(0, qc(self.edge, 0.16 + 0.08 * self._h)); g.setColorAt(1, qc(self.edge, 0))
            p.fillRect(QRectF(r.left() + 3, r.top(), 47, r.height()), g)
            p.restore()
        x = 14
        if self.icon_name:
            draw_icon(p, self.icon_name, QRectF(x, r.center().y() - 8, 16, 16), QColor(P["ok"] if self.done else P["text2"]), 0.9 if self.done else 0.7, 1.8)
            x += 26
        meta_w = QFontMetricsF(self.font()).horizontalAdvance(self.meta) + 12 if self.meta else 0
        f = QFont(self.font()); f.setWeight(QFont.Medium)
        p.setFont(f)
        tc = QColor(P["danger"] if self.urgent else (P["text3"] if self.done else P["text"]))
        p.setPen(tc)
        title = QFontMetricsF(f).elidedText(self.title, Qt.ElideRight, max(20, r.width() - x - meta_w - 12))
        p.drawText(QRectF(x, r.top(), r.width() - x - meta_w - 8, r.height()), Qt.AlignVCenter | Qt.AlignLeft, title)
        if self.meta:
            p.setFont(self.font())
            p.setPen(QColor(P["danger"] if self.urgent else P["text2"]))
            p.drawText(QRectF(r.right() - meta_w - 8, r.top(), meta_w, r.height()), Qt.AlignVCenter | Qt.AlignRight, self.meta)
        p.end()


class Toast(QWidget):
    """Floating glass notification.  In 'job' mode it also shows a glowing progress bar."""
    MAXW = 480

    def __init__(self, parent):
        super().__init__(parent)
        self._text, self._icon, self._job, self._tw = "", "check-circle", False, 200
        self.bar = GlowProgress()
        self.bar.setParent(self)
        self.bar.hide()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def setText(self, s, icon=None):
        self._text = s
        if icon:
            self._icon = icon

    def set_job(self, on):
        self._job = on
        self.bar.setVisible(on)

    def adjustSize(self):
        fm = QFontMetricsF(self.font())
        tw = min(self.MAXW - 74, fm.horizontalAdvance(self._text) + 4)
        self._tw = max(120, tw)
        th = fm.boundingRect(QRectF(0, 0, self._tw, 4000), Qt.TextWordWrap, self._text).height()
        self.resize(int(self._tw + 74), int(max(20, th) + 2 * 14 + 2 * 12 + (22 if self._job else 0)))

    def resizeEvent(self, e):
        c = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        self.bar.setGeometry(int(c.left() + 14), int(c.bottom() - 26), int(c.width() - 28), 20)
        super().resizeEvent(e)

    def paintEvent(self, e):
        P = GLASS.p
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        layers = shadow_layers(3, pads=(13, 11, 13)) + [(9, 0, 0.22, P["accent2"])]
        paint_shadow(p, c, RADIUS["panel"], layers, self.devicePixelRatioF())
        paint_glass(p, c, RADIUS["panel"], qc(mix(P["s2"], P["bg"], 0.25), 0.92), border_color=qc(P["accent2"], 0.50))
        draw_icon(p, self._icon, QRectF(c.left() + 14, c.top() + 12, 20, 20), QColor(P["accent2_text"]), 1.0, 1.8)
        p.setPen(QColor(P["text"]))
        p.drawText(QRectF(c.left() + 44, c.top() + 12, self._tw, c.height() - 24 - (22 if self._job else 0)), Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, self._text)
        p.end()


class _GlowFilter(QObject):
    """Animates a QGraphicsDropShadowEffect on hover/focus: radius `lo`→`hi`."""
    def __init__(self, widget, eff, lo, hi, on_events, off_events):
        super().__init__(widget)
        self.w, self.eff, self.lo, self.hi, self.on, self.off = widget, eff, lo, hi, on_events, off_events
        widget.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() in self.on:
            tween(self, "g", self.eff.blurRadius(), self.hi, 180, self.eff.setBlurRadius)
        elif e.type() in self.off:
            tween(self, "g", self.eff.blurRadius(), self.lo, 260, self.eff.setBlurRadius)
        return False


GLOWS = []


def add_glow(widget, which="accent", lo=18, hi=34, alpha=0.50, dy=4, on=(QEvent.Enter,), off=(QEvent.Leave,)):
    """Neon halo behind a widget (primary buttons).  `which` is a palette key so it follows the accent."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setOffset(0, dy); eff.setBlurRadius(lo); eff.setColor(qc(GLASS.p[which], alpha))
    widget.setGraphicsEffect(eff)
    widget._glow_filter = _GlowFilter(widget, eff, lo, hi, on, off)
    GLOWS.append((eff, which, alpha))


def add_focus_glow(widget, which="accent2"):
    add_glow(widget, which, lo=0, hi=20, alpha=0.55, dy=0, on=(QEvent.FocusIn,), off=(QEvent.FocusOut,))


def refresh_glows():
    alive = []
    for eff, which, alpha in GLOWS:
        try:
            eff.setColor(qc(GLASS.p[which], alpha)); alive.append((eff, which, alpha))
        except RuntimeError:
            pass
    GLOWS[:] = alive


# ═══════════════════════════════════════════════════════════════════════════
#  NATIVE BACKDROP  (Windows DWM: Mica / Acrylic / Tabbed)   — no-op elsewhere
# ═══════════════════════════════════════════════════════════════════════════
def native_glass_possible():
    return sys.platform.startswith("win") and os.environ.get("TASKTRAIL_GLASS", "").lower() != "off"


def windows_build():
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def apply_backdrop(widget, kind="mica", dark=True):
    """Ask the OS to draw `kind` behind a *translucent* top-level window.
    Returns the effect that is really active ('mica' | 'acrylic' | 'tabbed') or '' when unavailable.
      Win 11 22H2+ (build ≥ 22621) → DWMWA_SYSTEMBACKDROP_TYPE (Mica 2 / Acrylic 3 / Tabbed 4)
      Win 11 21H2  (build 22000)   → legacy DWMWA_MICA_EFFECT
      Win 10 1803+ (build ≥ 17134) → SetWindowCompositionAttribute acrylic-blur-behind
    """
    if not native_glass_possible() or kind in ("", "off"):
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = int(widget.winId())
        build = windows_build()
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

        def put(attr, val):
            v = ctypes.c_int(val)
            return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4) == 0

        put(20, 1 if dark else 0) or put(19, 1 if dark else 0)           # immersive dark title bar (20; 19 on old builds)
        if build >= 22000:
            put(33, 2)                                                    # rounded corners
        class MARGINS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]
        dwm.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(MARGINS(-1, -1, -1, -1)))   # let the backdrop reach the client area
        if build >= 22621:
            if put(38, {"mica": 2, "acrylic": 3, "tabbed": 4}.get(kind, 2)):
                return kind
        if build >= 22000 and kind in ("mica", "tabbed") and put(1029, 1):
            return "mica"
        if build >= 17134:
            return "acrylic" if _win10_acrylic(hwnd, dark) else ""
    except Exception:
        return ""
    return ""


def _win10_acrylic(hwnd, dark):
    import ctypes
    from ctypes import wintypes
    class ACCENT(ctypes.Structure):
        _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint), ("anim", ctypes.c_int)]
    class WCAD(ctypes.Structure):
        _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]
    tint = QColor(GLASS.p["bg"])
    abgr = (0x99 << 24) | (tint.blue() << 16) | (tint.green() << 8) | tint.red()
    acc = ACCENT(4, 2, abgr, 0)                                           # 4 = ACCENT_ENABLE_ACRYLICBLURBEHIND
    d = WCAD(19, ctypes.cast(ctypes.pointer(acc), ctypes.c_void_p), ctypes.sizeof(acc))
    f = ctypes.windll.user32.SetWindowCompositionAttribute
    f.argtypes = [wintypes.HWND, ctypes.POINTER(WCAD)]
    return bool(f(hwnd, ctypes.byref(d)))


class GlassWindow:
    """Mixin for top-level QMainWindow / QDialog: translucent window + backdrop paint + DWM hookup.
    Put it FIRST in the bases:  class MainWindow(GlassWindow, QMainWindow)."""
    glass_kind_default = "mica"
    _glass_native = ""

    def glass_init(self):
        self.setAttribute(Qt.WA_TranslucentBackground, native_glass_possible())

    def glass_kind(self):
        return getattr(GLASS, "kind", "mica") if self.glass_kind_default == "mica" else (
            "off" if getattr(GLASS, "kind", "mica") == "off" else self.glass_kind_default)

    def glass_apply(self):
        self._glass_native = apply_backdrop(self, self.glass_kind(), GLASS.dark) if self.isVisible() or self.windowHandle() else ""
        self.update()
        return self._glass_native

    def showEvent(self, e):
        super().showEvent(e)
        self.glass_apply()

    def paintEvent(self, e):
        p = QPainter(self)
        paint_backdrop(p, self.rect(), bool(self._glass_native))
        p.end()


class GlassDialog(GlassWindow, QDialog):
    """Dialog with the same frosted backdrop (Acrylic on Windows — the transient-window material)."""
    glass_kind_default = "acrylic"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("glassDialog")
        self.glass_init()


# ═══════════════════════════════════════════════════════════════════════════
#  REAL IN-APP BLUR  (command palette / quick add / menus)
# ═══════════════════════════════════════════════════════════════════════════
def blur_pixmap(pm, radius=18):
    """Gaussian-style blur.  Done at 1/4 resolution (≈16× cheaper, visually the same at these radii)."""
    if pm.isNull():
        return pm
    k = 4
    small = pm.scaled(max(1, pm.width() // k), max(1, pm.height() // k), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(small)
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(max(1.0, radius / k)); eff.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(eff)
    scene.addItem(item)
    img = QImage(small.size(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    qp = QPainter(img)
    scene.render(qp, QRectF(img.rect()), QRectF(small.rect()))
    qp.end()
    out = QPixmap.fromImage(img).scaled(pm.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out.setDevicePixelRatio(pm.devicePixelRatio())
    return out


class _OverlayPanel(GlassFrame):
    def __init__(self):
        super().__init__(elev=0, radius=RADIUS["panel"] + 4)

    def fill(self, t):
        return qc(mix(GLASS.p["s2"], GLASS.p["bg"], 0.2), 0.80 if GLASS.dark else 0.84)


class GlassOverlay(QWidget):
    """Modal overlay *inside* the main window: the app stays visible beneath, out of focus (blurred + dimmed);
    a floating glass panel drops in with a spring.  API mirrors QDialog (exec / accept / reject)."""
    def __init__(self, win, width=640, top=84):
        super().__init__(win)
        self.win, self.panel_w, self.top = win, width, top
        self.setFocusPolicy(Qt.StrongFocus)
        self.panel = _OverlayPanel()
        self.panel.setParent(self)
        self.body = QVBoxLayout(self.panel)
        self.body.setContentsMargins(14, 14, 14, 12); self.body.setSpacing(8)
        self._t, self._sharp, self._blur, self._result, self._loop, self._closing = 0.0, QPixmap(), QPixmap(), 0, None, False
        self._prev_focus = None
        win.installEventFilter(self)
        self.hide()

    # ---- lifecycle ----
    def exec(self):
        w = self.win
        self._prev_focus = QApplication.focusWidget()
        self._sharp = w.grab()
        self._blur = blur_pixmap(self._sharp, 20)
        self.setGeometry(w.rect())
        self.panel.setFixedWidth(self.panel_w)
        self.panel.adjustSize()
        self._place(0.0)
        for child in (w.centralWidget(),) + tuple(getattr(w, "overlay_disable", ())):
            if child is not None:
                child.setEnabled(False)
        w.overlay = self
        eff = QGraphicsOpacityEffect(self.panel); eff.setOpacity(0.0); self.panel.setGraphicsEffect(eff)
        self.show(); self.raise_(); self.setFocus()
        tween(self, "open", 0.0, 1.0, 380, lambda v: self._set_t(v, eff), spring_curve(1.1),
              on_done=lambda: self.panel.setGraphicsEffect(None))
        self._loop = QEventLoop(self)
        self._loop.exec()
        return self._result

    def accept(self):
        self._finish(1)

    def reject(self):
        self._finish(0)

    def _finish(self, code):
        if self._closing:
            return
        self._closing, self._result = True, code
        w = self.win
        for child in (w.centralWidget(),) + tuple(getattr(w, "overlay_disable", ())):
            if child is not None:
                child.setEnabled(True)
        w.overlay = None
        w.removeEventFilter(self)
        if self._prev_focus is not None:
            try:
                self._prev_focus.setFocus()
            except RuntimeError:
                pass
        eff = QGraphicsOpacityEffect(self.panel); self.panel.setGraphicsEffect(eff)
        tween(self, "open", self._t, 0.0, 130, lambda v: self._set_t(v, eff), on_done=self._dispose)
        if self._loop is not None:
            self._loop.quit()

    def _dispose(self):
        self.hide()
        self.deleteLater()

    # ---- painting / layout ----
    def _set_t(self, t, eff=None):
        self._t = float(t)
        if eff is not None:
            try:
                eff.setOpacity(max(0.0, min(1.0, self._t)))
            except RuntimeError:
                pass
        self._place(self._t)
        self.update()

    def _place(self, t):
        pw, ph = self.panel.width(), self.panel.sizeHint().height()
        if ph != self.panel.height():
            self.panel.setFixedHeight(ph)
        self.panel.move(int((self.width() - pw) / 2), int(self.top - 26 * (1 - min(t, 1.0))))

    def eventFilter(self, obj, e):
        if obj is self.win and e.type() == QEvent.Resize and self.isVisible():
            self.setGeometry(self.win.rect()); self._place(self._t)
        return super().eventFilter(obj, e)

    def paintEvent(self, e):
        P = GLASS.p
        p = QPainter(self)
        r = QRectF(self.rect())
        t = max(0.0, min(1.0, self._t))
        p.setCompositionMode(QPainter.CompositionMode_Source)      # replace (not blend with) the live window beneath
        p.drawPixmap(self.rect(), self._sharp)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setOpacity(t)
        p.drawPixmap(self.rect(), self._blur)                      # out-of-focus app
        p.fillRect(r, qc(P["bg"], 0.38 if GLASS.dark else 0.22))   # dim
        p.setOpacity(t)
        p.setRenderHint(QPainter.Antialiasing)
        g = self.panel.geometry()
        paint_shadow(p, QRectF(g), self.panel.radius, shadow_layers(3) + [(26, 8, 0.20, P["accent"])], self.devicePixelRatioF())
        p.end()

    def mousePressEvent(self, e):
        if not self.panel.geometry().contains(e.position().toPoint()):
            self.reject()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.reject()
        else:
            super().keyPressEvent(e)


class GlassMenu(QMenu):
    """Context menu with a genuinely blurred backdrop: on show, the pixels of the window beneath it are
    grabbed, blurred and used as the menu's frosted background."""
    PAD = 10

    def __init__(self, title="", parent=None):
        super().__init__(title, parent)
        self.setObjectName("glassMenu")
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._frost = None

    def showEvent(self, e):
        super().showEvent(e)
        self._frost = None
        win = QApplication.activeWindow()
        if win is not None and not isinstance(win, GlassMenu) and not self.parent_is_menu():
            try:
                g = self.geometry()
                tl = win.mapFromGlobal(g.topLeft())
                pad = 28
                src = QRect(tl.x() - pad, tl.y() - pad, g.width() + 2 * pad, g.height() + 2 * pad)
                pm = win.grab(src)
                pm = blur_pixmap(pm, 16)
                dpr = pm.devicePixelRatio()
                self._frost = pm.copy(int(pad * dpr), int(pad * dpr), int(g.width() * dpr), int(g.height() * dpr))
                self._frost.setDevicePixelRatio(dpr)
            except Exception:
                self._frost = None

    def parent_is_menu(self):
        return isinstance(self.parent(), QMenu)

    def paintEvent(self, e):
        P = GLASS.p
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
        paint_shadow(p, r, RADIUS["menu"] + 2, shadow_layers(2, pads=(self.PAD - 1, self.PAD - 3, self.PAD - 1)), self.devicePixelRatioF())
        path = rounded(r, RADIUS["menu"] + 2)
        p.save(); p.setClipPath(path)
        p.fillRect(r, QColor(mix(P["s2"], P["bg"], 0.3)))              # opaque plate: legible even if the grab failed
        if self._frost is not None:
            p.setOpacity(0.9)
            p.drawPixmap(QPointF(0, 0), self._frost)
            p.setOpacity(1.0)
        p.restore()
        p.fillPath(path, qc(mix(P["s2"], P["bg"], 0.3), 0.74 if self._frost is not None else 0.0))
        paint_glass(p, r, RADIUS["menu"] + 2, QColor(0, 0, 0, 0), sheen=0.06 if GLASS.dark else 0.30)
        p.end()
        super().paintEvent(e)                                           # items (QSS: transparent bg, rounded hover)


# ═══════════════════════════════════════════════════════════════════════════
#  THEME CROSS-FADE
# ═══════════════════════════════════════════════════════════════════════════
def crossfade(win, apply_fn, ms=300):
    """Snapshot the window, apply the new theme, fade the snapshot out → colours dissolve instead of snapping."""
    if not GLASS.motion or not win.isVisible():
        apply_fn()
        return
    pm = win.grab()
    apply_fn()
    lab = QLabel(win)
    lab.setPixmap(pm); lab.setGeometry(win.rect()); lab.setAttribute(Qt.WA_TransparentForMouseEvents)
    eff = QGraphicsOpacityEffect(lab); lab.setGraphicsEffect(eff)
    lab.show(); lab.raise_()
    tween(lab, "fade", 1.0, 0.0, ms, eff.setOpacity, on_done=lab.deleteLater)


# ═══════════════════════════════════════════════════════════════════════════
#  ASYNC JOBS  — non-blocking workers whose results are delivered on the UI thread
# ═══════════════════════════════════════════════════════════════════════════
class _JobHub(QObject):
    progress = Signal(int, float, str)
    done = Signal(int, object)
    failed = Signal(int, str)
    count_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self._ids = itertools.count(1)
        self._cb = {}
        self.progress.connect(self._on_progress, Qt.QueuedConnection)      # emitted from a worker thread → queued
        self.done.connect(self._on_done, Qt.QueuedConnection)
        self.failed.connect(self._on_failed, Qt.QueuedConnection)

    @Slot(int, float, str)
    def _on_progress(self, jid, frac, msg):
        cb = self._cb.get(jid)
        if cb and cb[2]:
            cb[2](frac, msg)

    @Slot(int, object)
    def _on_done(self, jid, result):
        cb = self._cb.pop(jid, None)
        GLASS.jobs = len(self._cb)
        self.count_changed.emit(GLASS.jobs)
        if cb and cb[0]:
            cb[0](result)

    @Slot(int, str)
    def _on_failed(self, jid, msg):
        cb = self._cb.pop(jid, None)
        GLASS.jobs = len(self._cb)
        self.count_changed.emit(GLASS.jobs)
        if cb and cb[1]:
            cb[1](msg)


class _Job(QRunnable):
    def __init__(self, hub, jid, fn):
        super().__init__()
        self.hub, self.jid, self.fn = hub, jid, fn

    def run(self):
        try:
            res = self.fn(lambda frac, msg="": self.hub.progress.emit(self.jid, float(frac), str(msg)))
        except Exception as ex:                                              # noqa: BLE001 — reported to the UI thread
            self.hub.failed.emit(self.jid, f"{type(ex).__name__}: {ex}")
            return
        self.hub.done.emit(self.jid, res)


_HUB = None


def job_hub():
    global _HUB
    if _HUB is None:
        _HUB = _JobHub()
    return _HUB


def run_job(fn, on_done=None, on_error=None, on_progress=None):
    """Run fn(progress) on a worker thread.  `progress(fraction, message)` may be called from fn.
    Callbacks run on the UI thread.  Never touch widgets or the live Store inside fn — pass it a snapshot."""
    hub = job_hub()
    jid = next(hub._ids)
    hub._cb[jid] = (on_done, on_error, on_progress)
    GLASS.jobs = len(hub._cb)
    hub.count_changed.emit(GLASS.jobs)
    QThreadPool.globalInstance().start(_Job(hub, jid, fn))
    return jid


# ═══════════════════════════════════════════════════════════════════════════
#  SEARCH PILL / FOCUS FILTER
# ═══════════════════════════════════════════════════════════════════════════
class SearchPill(QPushButton):
    """Top-bar search affordance: glass pill with icon, placeholder and a 'Ctrl K' keycap.  Opens the palette."""
    def __init__(self, text, keycap):
        super().__init__()
        self.text_, self.keycap, self._h = text, keycap, 0.0
        self.setObjectName("rowbtn")
        self.setFixedSize(300, 38)
        self.setCursor(QCursor(Qt.PointingHandCursor))

    def _set_h(self, v):
        self._h = float(v); self.update()

    def enterEvent(self, e):
        tween(self, "h", self._h, 1.0, 140, self._set_h); super().enterEvent(e)

    def leaveEvent(self, e):
        tween(self, "h", self._h, 0.0, 200, self._set_h); super().leaveEvent(e)

    def paintEvent(self, e):
        P = GLASS.p
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        paint_glass(p, r, RADIUS["control"], GLASS.input_fill(), sheen=0.03, border_color=qc(P["accent"], 0.15 + 0.5 * self._h) if self._h > 0.01 else None)
        draw_icon(p, "search", QRectF(r.left() + 12, r.center().y() - 8, 16, 16), QColor(P["text"]), 0.55 + 0.35 * self._h)
        p.setPen(QColor(P["text3"] if self._h < 0.5 else P["text2"]))
        p.drawText(QRectF(r.left() + 36, r.top(), r.width() - 110, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text_)
        f = QFont(self.font()); f.setPixelSize(max(9, f.pixelSize() - 2)); f.setWeight(QFont.DemiBold); p.setFont(f)
        w = QFontMetricsF(f).horizontalAdvance(self.keycap) + 14
        k = QRectF(r.right() - w - 8, r.center().y() - 10, w, 20)
        p.setPen(QPen(qc(P["text"], 0.18), 1)); p.setBrush(qc(P["text"], 0.06)); p.drawRoundedRect(k, 6, 6)
        p.setPen(QColor(P["text2"])); p.drawText(k, Qt.AlignCenter, self.keycap)
        p.end()


class ButtonFocusFilter(QObject):
    """Buttons take focus from Tab only, so the accent focus ring means 'keyboard focus' and does not stick after a click."""
    def eventFilter(self, obj, e):
        if e.type() == QEvent.Show and isinstance(obj, QPushButton) and obj.focusPolicy() == Qt.StrongFocus:
            obj.setFocusPolicy(Qt.TabFocus)
        return False
