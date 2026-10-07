#!/usr/bin/env python3
"""
TaskTrail — task planner, to-do list and status tracker (Python / PySide6 edition)

Data-compatible with the Electron TaskTrail: same JSON format, same file
(%APPDATA%\\TaskTrail\\flowboard_data.json on Windows), same backups.

v2.3 adds the "glass" design layer (see glass.py): Mica / Acrylic window backdrop, frosted cards with layered
shadows, a collapsible sidebar, blurred command palette, glass context menus, OS dark/light following,
glow progress + async export/backup.

Run:     python tasktrail.py
Build:   see README.md (build_win.bat / GitHub Actions)
"""
import calendar
import html
import report as REPORT
import copy
import datetime as dt
import json
import os
import re
import shutil
import sys
import time
import uuid

from PySide6.QtCore import (Qt, QTimer, QSize, QRect, QRectF, QPoint, Signal, QDate, QEvent, QMimeData, QVariantAnimation,
                            QPropertyAnimation, QEasingCurve, QAbstractAnimation, QThreadPool)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QPainter, QPixmap, QBrush, QPen, QPainterPath,
                           QFontDatabase, QCursor, QShortcut, QKeySequence, QDrag, QLinearGradient,
                           QFontMetricsF, QGuiApplication)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QPushButton, QFrame, QStackedWidget, QListWidget, QListWidgetItem,
                               QAbstractItemView, QScrollArea, QLineEdit, QComboBox, QTextEdit, QDialog,
                               QDialogButtonBox, QCheckBox, QDateEdit, QColorDialog, QFileDialog, QMessageBox,
                               QSystemTrayIcon, QMenu, QSizePolicy, QToolButton, QDockWidget, QSpinBox,
                               QFontComboBox, QSlider, QInputDialog, QSplitter, QGraphicsOpacityEffect, QStyledItemDelegate, QStyle,
                               QButtonGroup)

from glass import (GLASS, BASE, VIOLET, CYAN, RADIUS, GlassFrame, GlassDialog, GlassWindow, GlassOverlay, GlassMenu,
                   GlowProgress, Sidebar, NavButton, Brand, SectionLabel, RowButton, Toast, ICONS, make_icon, draw_icon,
                   paint_backdrop, qc, mix, rgba as _rgba, ensure_contrast, readable_on, contrast, pick_font_family,
                   add_glow, add_focus_glow, refresh_glows, crossfade, tween, spring_curve, run_job, job_hub,
                   rounded, paint_shadow, shadow_layers, paint_glass, SearchPill)

APP_NAME = "TaskTrail"
VERSION = "2.4.1"
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
               'September', 'October', 'November', 'December']
DEFAULT_COLS = [
    {"id": "todo", "label": "To Do", "color": "#6c8aff", "icon": "📋"},
    {"id": "today", "label": "Today's", "color": "#ffb347", "icon": "☀️"},
    {"id": "wip", "label": "WIP", "color": "#b48aff", "icon": "⚡"},
    {"id": "done", "label": "Done", "color": "#3ddbbf", "icon": "✅"},
]
BUILTIN = {"todo", "today", "wip", "done"}
LEGACY_YEAR = 2026
LABEL_PALETTE = ['#6c8aff', '#ffb347', '#b48aff', '#3ddbbf', '#ff6584', '#26de81',
                 '#fd9644', '#a55eea', '#2bcbba', '#eb3b5a', '#f7b731', '#778ca3']
PRI_LABEL = {"high": "🔴 High", "med": "🟡 Med", "low": "🟢 Low"}
PRI_COLOR = {"high": "#ff6584", "med": "#ffb347", "low": "#3ddbbf"}

THEME_MODES = ("system", "light", "dark")           # "system" follows the OS dark/light setting live
THEMES = {k: dict(bg=v["bg"], text=v["text"], accent=v["accent"]) for k, v in BASE.items()}     # swatch colours for the preset buttons
PRESETS = [
    ("Violet · dark", "dark", {}),
    ("Cyan · dark", "dark", dict(accent=CYAN)),
    ("Violet · light", "light", {}),
    ("Cyan · light", "light", dict(accent="#0891b2")),
    ("Midnight", "dark", dict(bg="#0a1020", surface="#121a30", text="#e8ecff", accent="#7c9cff")),
    ("Forest", "dark", dict(bg="#0b1410", surface="#12211a", text="#e6f2ec", accent="#3ddbbf")),
    ("Ember", "dark", dict(bg="#16100d", surface="#241a16", text="#f7ece6", accent="#ff8c5a")),
    ("Paper", "light", dict(bg="#f5f2ea", surface="#fffdf8", text="#25231f", accent="#b5622e")),
    ("Ocean", "dark", dict(bg="#061420", surface="#0d2233", text="#e3f1fb", accent="#35c2ff")),
    ("Rose", "dark", dict(bg="#1a0f14", surface="#26161d", text="#fbe9ef", accent="#ff6584")),
    ("Sunset", "dark", dict(bg="#1a1208", surface="#2a1f10", text="#fff1dd", accent="#ffb347")),
    ("Graphite", "dark", dict(bg="#141414", surface="#1e1e1e", text="#ececec", accent="#9aa0bc")),
    ("Amethyst", "dark", dict(bg="#120d1f", surface="#1b1430", text="#efe9ff", accent="#b48aff")),
    ("Lavender", "light", dict(bg="#f3f0fa", surface="#ffffff", text="#2a2340", accent="#7c5cd6")),
    ("Mint", "light", dict(bg="#eef7f3", surface="#ffffff", text="#16302a", accent="#1fa27a")),
    ("Sky", "light", dict(bg="#eaf3fb", surface="#ffffff", text="#14243a", accent="#2b7de9")),
    ("Slate", "light", dict(bg="#e9ecf1", surface="#f7f9fc", text="#1f2937", accent="#4f6b8f")),
    ("Peach", "light", dict(bg="#fdf1ea", surface="#fffaf7", text="#3a2a22", accent="#f26b4e")),
]


def C(name):
    """Current design-token colour, e.g. C('text2').  Read at build time → always follows the active theme."""
    return GLASS.p[name]


_T_CACHE = {}


def T(color):
    """A semantic colour (priority, label, column…) made readable as TEXT on the current card surface."""
    k = (color, GLASS.p["card"])
    if k not in _T_CACHE:
        if len(_T_CACHE) > 400: _T_CACHE.clear()
        _T_CACHE[k] = ensure_contrast(color, GLASS.p["card"], 4.5)
    return _T_CACHE[k]


def system_is_dark():
    """OS dark/light preference (Qt ≥ 6.5 reports it on Windows, macOS and most Linux desktops)."""
    try:
        cs = QGuiApplication.styleHints().colorScheme()
        if cs == Qt.ColorScheme.Dark: return True
        if cs == Qt.ColorScheme.Light: return False
    except Exception:
        pass
    return QApplication.palette().window().color().lightness() < 128


# ═══════════════════════════════════════════════════════════════════════════
#  AUTO-PRIORITY  (priority follows the due date — escalates only, never lowers, skips manual overrides)
# ═══════════════════════════════════════════════════════════════════════════
PRI_RANK = {"low": 0, "med": 1, "high": 2}
AUTO_RULES = ((1, "high"), (7, "med"))      # due in ≤ N days (overdue counts) → at least this priority


def due_phrase(n):
    return "overdue" if n < 0 else "due today" if n == 0 else "due tomorrow" if n == 1 else f"due in {n} days"


def auto_priority_for(card, today=None):
    """(priority, reason) this card should have *at least*, or None.  Done, undated and manually-locked cards are skipped."""
    if card.get("done") or not card.get("dueDate") or card.get("prioLock"): return None
    try: n = (dt.date.fromisoformat(card["dueDate"]) - (today or dt.date.today())).days
    except ValueError: return None
    for days, pri in AUTO_RULES:
        if n <= days: return pri, due_phrase(n)
    return None


def apply_auto_priority(store, today=None, months=None):
    """Raise priorities on every open card (all years, or only `months` = [(year, month_index)]).  Returns [(card, old, new)]."""
    out = []; ids = [c["id"] for c in store.columns if c["id"] != "done"]
    pairs = months if months is not None else [(y, m) for y in store.years() for m in range(12)]
    for y, m in pairs:
        kd = store.kanban(m, y)
        for cid in ids:
            for card in kd.get(cid, []):
                r = auto_priority_for(card, today)
                if r and PRI_RANK[r[0]] > PRI_RANK.get(card.get("priority", "med"), 1):
                    old = card.get("priority", "med"); card["priority"] = r[0]; card["updatedAt"] = now_iso()
                    store.log(card, f"Priority auto-raised {PRI_LABEL[old].split(' ', 1)[1]} → {PRI_LABEL[r[0]].split(' ', 1)[1]} ({r[1]})"); out.append((card, old, r[0]))
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  PATHS & SETTINGS
# ═══════════════════════════════════════════════════════════════════════════
def user_data_dir():
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


USER_DATA = user_data_dir()
DB_FILE = os.path.join(USER_DATA, "flowboard_data.json")
SETTINGS_FILE = os.path.join(USER_DATA, "settings.json")
DEFAULT_BACKUP_DIR = os.path.join(USER_DATA, "backups")


def read_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


def get_backup_dir():
    d = read_settings().get("backupDir") or DEFAULT_BACKUP_DIR
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        os.makedirs(DEFAULT_BACKUP_DIR, exist_ok=True)
        return DEFAULT_BACKUP_DIR


def detect_onedrive():
    for p in (os.environ.get("OneDriveCommercial"), os.environ.get("OneDriveConsumer"),
              os.environ.get("OneDrive"), os.path.join(os.path.expanduser("~"), "OneDrive")):
        if p and os.path.isdir(p):
            return p
    return None


rgba = _rgba


def uid():
    return uuid.uuid4().hex[:12]


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def fmt_date(s):
    try:
        return dt.date.fromisoformat(s).strftime("%b %d").replace(" 0", " ")
    except Exception:
        return s or ""


def fmt_dt(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "")).strftime("%b %d, %H:%M")
    except Exception:
        return ""


def is_overdue(d, done):
    if not d or done:
        return False
    try:
        return dt.date.fromisoformat(d) < dt.date.today()
    except Exception:
        return False


REPEATS = [("", "No repeat"), ("daily", "Every day"), ("weekdays", "Every weekday"), ("weekly", "Every week"), ("monthly", "Every month"), ("yearly", "Every year")]
REPEAT_SHORT = {"daily": "daily", "weekdays": "weekdays", "weekly": "weekly", "monthly": "monthly", "yearly": "yearly"}


def repeat_step(d, repeat):
    """The occurrence after date `d` for a repeat rule."""
    if repeat == "daily": return d + dt.timedelta(1)
    if repeat == "weekdays":
        d += dt.timedelta(1)
        while d.weekday() > 4: d += dt.timedelta(1)
        return d
    if repeat == "weekly": return d + dt.timedelta(7)
    if repeat == "monthly":
        y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))
    if repeat == "yearly": return dt.date(d.year + 1, d.month, min(d.day, calendar.monthrange(d.year + 1, d.month)[1]))
    return None


def next_due(iso, repeat, after=None):
    """Next occurrence strictly after `after` (default: the due date itself). None if the rule is empty/invalid."""
    try: d = dt.date.fromisoformat(iso)
    except (TypeError, ValueError): return None
    after = after or d
    while d <= after:
        d = repeat_step(d, repeat)
        if d is None: return None
    return d


def occurrences(card, start, end):
    """Projected future dates of a recurring card inside [start, end], after its current due date (which is shown as the real card)."""
    if not card.get("repeat") or not card.get("dueDate"): return []
    try: d = dt.date.fromisoformat(card["dueDate"]); until = dt.date.fromisoformat(card["repeatUntil"]) if card.get("repeatUntil") else None
    except ValueError: return []
    out = []
    while True:
        d = repeat_step(d, card["repeat"])
        if d is None or d > end or (until and d > until) or len(out) > 62: break
        if d >= start: out.append(d)
    return out


DOW = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']     # date.weekday(): Mon = 0


def parse_date_token(tok, year, month):
    """@today · @tomorrow · @+3 · @fri · @15 (day of the shown month) · @2026-10-01 → ISO date or None."""
    t = tok.lower(); today = dt.date.today()
    if t in ("today", "tod"): return today.isoformat()
    if t in ("tomorrow", "tmr", "tom"): return (today + dt.timedelta(1)).isoformat()
    if re.fullmatch(r"\+\d+", t): return (today + dt.timedelta(int(t[1:]))).isoformat()
    di = next((i for i, d in enumerate(DOW) if t.startswith(d)), -1)
    if di >= 0: return (today + dt.timedelta((di - today.weekday()) % 7)).isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        try: return dt.date.fromisoformat(t).isoformat()
        except ValueError: return None
    if re.fullmatch(r"\d{1,2}", t) and 1 <= int(t) <= calendar.monthrange(year, month + 1)[1]:
        return dt.date(year, month + 1, int(t)).isoformat()
    return None


def parse_quick(store, text, create=True):
    """'Renew SSL !high #ops @fri' → dict(title, priority, dueDate, labels). #label creates the label if needed
    (create=False: don't create, list the would-be-new names under 'new' instead — used by the live preview)."""
    out = dict(title="", priority="med", dueDate="", labels=[]); keep = []
    for w in text.split():
        sig, val = w[0], w[1:]
        if sig not in "!#@*" or not val: keep.append(w); continue
        v = val.lower()
        if sig == "*":
            rp = {"daily": "daily", "day": "daily", "weekdays": "weekdays", "weekday": "weekdays", "weekly": "weekly", "week": "weekly", "monthly": "monthly", "month": "monthly", "yearly": "yearly", "year": "yearly"}.get(v)
            if rp: out["repeat"] = rp
            else: keep.append(w)
        elif sig == "!":
            pri = {"high": "high", "h": "high", "hi": "high", "urgent": "high", "low": "low", "l": "low", "med": "med", "m": "med", "medium": "med"}.get(v)
            if pri: out["priority"] = pri
            else: keep.append(w)
        elif sig == "@":
            d = parse_date_token(val, store.year, store.month)
            if d: out["dueDate"] = d
            else: keep.append(w)
        else:
            l = next((x for x in store.labels if x["name"].lower() == v), None)
            if not l and not create:
                if val not in out.setdefault("new", []): out["new"].append(val)
                continue
            if not l:
                l = {"id": uid(), "name": val, "color": LABEL_PALETTE[len(store.labels) % len(LABEL_PALETTE)]}; store.labels.append(l)
            if l["id"] not in out["labels"]: out["labels"].append(l["id"])
    out["title"] = " ".join(keep).strip()
    if out.get("repeat") and not out["dueDate"]: out["dueDate"] = dt.date.today().isoformat()      # a repeat needs a date to count from
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  STORE — same JSON schema as the Electron app
# ═══════════════════════════════════════════════════════════════════════════
class Store:
    def __init__(self):
        self.db = {}
        self.year = dt.date.today().year
        self.month = dt.date.today().month - 1
        self.load()
        if not os.path.exists(DB_FILE):
            self.save()                 # make sure the file exists from the first run so backups work

    # ---- load / save ----
    def load(self):
        raw = None
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:
                raw = None
        self.db = self.normalize(raw)
        self.ensure_year(self.year); self.merged_count = 0
        if not self.db["meta"].get("checklistMerged"):        # one-time: checklist → board (backup of the old file first)
            if raw is not None: self.backup_now()
            self.merged_count = self.merge_checklist(); self.save()

    @staticmethod
    def normalize(raw):
        d = raw if isinstance(raw, dict) else {}
        if not isinstance(d.get("years"), dict):
            d["years"] = {}
            if d.get("kanban") or d.get("checklist"):
                d["years"][str(LEGACY_YEAR)] = {"kanban": d.get("kanban") or {}, "checklist": d.get("checklist") or {}}
        d.pop("kanban", None)
        d.pop("checklist", None)
        if not isinstance(d.get("columns"), list) or not d["columns"]:
            d["columns"] = copy.deepcopy(DEFAULT_COLS)
        for dc in DEFAULT_COLS:
            if not any(c["id"] == dc["id"] for c in d["columns"]):
                d["columns"].append(dict(dc))
        d.setdefault("labels", [])
        d.setdefault("migrations", [])
        for m in d["migrations"]:
            m.setdefault("fromYear", LEGACY_YEAR)
            m.setdefault("toYear", LEGACY_YEAR)
        if not isinstance(d.get("meta"), dict):
            d["meta"] = {}
        return d

    def ensure_year(self, y):
        Y = self.db["years"].setdefault(str(y), {"kanban": {}})
        Y.setdefault("kanban", {})
        for mi in range(12):
            k = Y["kanban"].setdefault(str(mi), {})
            for c in self.db["columns"]:
                k.setdefault(c["id"], [])
        return Y

    def merge_checklist(self):
        """Checklist groups become labels; their tasks become board cards (To Do, or Done if ticked). Runs once, also for restored old backups."""
        moved = 0
        for y, Y in list(self.db["years"].items()):
            for mi, groups in list((Y.get("checklist") or {}).items()):
                for g in groups or []:
                    if not g.get("tasks"): continue
                    l = next((x for x in self.labels if x["name"].lower() == g["name"].strip().lower()), None)
                    if not l:
                        l = {"id": uid(), "name": g["name"].strip(), "color": LABEL_PALETTE[len(self.labels) % len(LABEL_PALETTE)]}; self.labels.append(l)
                    kd = self.kanban(int(mi), int(y))
                    for t in g["tasks"]:
                        done = bool(t.get("done"))
                        card = dict(id=t.get("id") or uid(), title=t.get("title", ""), desc="", priority=t.get("priority", "med"), dueDate=t.get("dueDate", ""), done=done,
                                    subs=t.get("subs", []), labels=[l["id"]], comments=[], activity=[], createdAt=t.get("createdAt") or now_iso(), month=MONTHS[int(mi)], year=int(y))
                        if t.get("migratedFrom"): card["migratedFrom"] = t["migratedFrom"]
                        self.log(card, f'Merged from checklist group "{g["name"]}"'); kd.setdefault("done" if done else "todo", []).append(card); moved += 1
            Y.pop("checklist", None)
        self.db["meta"]["checklistMerged"] = now_iso(); self.db["meta"]["checklistMergedCount"] = moved
        return moved

    def complete_recurring(self, card):
        """Ticking a recurring card advances its due date instead of finishing it. Returns the new date, or None if the rule ended."""
        today = dt.date.today()
        try: due = dt.date.fromisoformat(card["dueDate"])
        except (TypeError, ValueError): return None
        nd = next_due(card["dueDate"], card["repeat"], after=max(due, today))
        if nd is None or (card.get("repeatUntil") and nd.isoformat() > card["repeatUntil"]):
            card["repeat"] = ""; return None
        card.setdefault("completions", []).append(today.isoformat()); del card["completions"][:-120]
        card["dueDate"] = nd.isoformat(); card["updatedAt"] = now_iso(); self.log(card, f"Completed ↻ next due {fmt_date(card['dueDate'])}")
        return card["dueDate"]

    def save(self):
        self.db["meta"]["updatedAt"] = int(time.time() * 1000)
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.db, f)
        os.replace(tmp, DB_FILE)

    # ---- accessors ----
    @property
    def columns(self):
        return self.db["columns"]

    @property
    def labels(self):
        return self.db["labels"]

    def col(self, cid):
        return next((c for c in self.columns if c["id"] == cid), None)

    def kanban(self, mi=None, year=None):
        Y = self.ensure_year(year or self.year)
        return Y["kanban"][str(self.month if mi is None else mi)]

    def years(self):
        return sorted(int(y) for y in self.db["years"])

    def find_card(self, cid, col_id=None):
        kd = self.kanban()
        for c in self.columns:
            if col_id and c["id"] != col_id:
                continue
            for card in kd.get(c["id"], []):
                if card["id"] == cid:
                    return card, c["id"]
        return None, None

    @staticmethod
    def log(card, text):
        card.setdefault("activity", []).append({"at": now_iso(), "text": text})
        del card["activity"][:-60]

    def move_card(self, cid, from_col, to_col, before_id="TOP"):
        src = self.kanban()[from_col]
        idx = next((i for i, c in enumerate(src) if c["id"] == cid), -1)
        if idx < 0:
            return None
        card = src.pop(idx)
        dst = self.kanban().setdefault(to_col, [])
        if before_id == "TOP":
            at = 0
        elif before_id is None:
            at = len(dst)
        else:
            at = next((i for i, c in enumerate(dst) if c["id"] == before_id), len(dst))
        dst.insert(at, card)
        if to_col == "done" and from_col != "done" and card.get("repeat") and card.get("dueDate"):
            if self.complete_recurring(card):                       # stays in its column with the next date
                dst.pop(at); src.insert(idx, card); card["recurred"] = True; return card
        card.pop("recurred", None)
        if from_col != to_col:
            card["done"] = to_col == "done"
            if to_col == "done":
                card["completedAt"] = now_iso()
            self.log(card, f"Moved from {self.col(from_col)['label']} to {self.col(to_col)['label']}")
        return card

    # ---- rollover ----
    def incomplete_col_ids(self):
        return [c["id"] for c in self.columns if c["id"] != "done"]

    def incomplete_cards(self, mi, year):
        kd = self.kanban(mi, year)
        return [c for cid in self.incomplete_col_ids() for c in kd.get(cid, []) if not c.get("done")]

    @staticmethod
    def month_past(mi, year):
        last = dt.date(year + (1 if mi == 11 else 0), 1 if mi == 11 else mi + 2, 1) - dt.timedelta(days=1)
        return dt.date.today() > last

    def past_periods(self):
        today = dt.date.today()
        out = []
        for y in self.years():
            if y > today.year:
                continue
            last_m = 11 if y < today.year else today.month - 2
            for mi in range(0, last_m + 1):
                if self.month_past(mi, y):
                    out.append((y, mi))
        return out

    def migrate_month(self, mi, year, auto=False):
        ty, tm = (year + 1, 0) if mi >= 11 else (year, mi + 1)
        self.ensure_year(year); self.ensure_year(ty)
        src, tgt = self.kanban(mi, year), self.kanban(tm, ty)
        label = f"{MONTHS[mi]} {year}"
        moved_k = moved_c = 0
        for cid in self.incomplete_col_ids():
            arr = src.get(cid, [])
            for c in [c for c in arr if not c.get("done")]:
                m = copy.deepcopy(c)
                m.update(id=uid(), migratedFrom=label, migratedAt=now_iso(), originalId=c["id"])
                self.log(m, f"Rolled over from {label}")
                tgt.setdefault("todo" if cid == "today" else cid, []).insert(0, m)
                moved_k += 1
            src[cid] = [c for c in arr if c.get("done")]
        self.db["migrations"].append({"fromYear": year, "from": mi, "toYear": ty, "to": tm, "kanban": moved_k,
                                      "checklist": moved_c, "at": now_iso(), "auto": auto})
        self.save()
        return moved_k, moved_c

    def auto_migrate(self):
        total = 0
        for y, mi in self.past_periods():
            if not self.incomplete_cards(mi, y):
                continue
            if any(m.get("fromYear") == y and m["from"] == mi and m.get("auto") for m in self.db["migrations"]):
                continue
            k, c = self.migrate_month(mi, y, auto=True)
            total += k + c
        return total

    def pending_rollover(self):
        return any(self.incomplete_cards(mi, y) for y, mi in self.past_periods())

    # ---- backups ----
    def backup_now(self):
        if not os.path.exists(DB_FILE):
            return None
        d = get_backup_dir()
        dest = os.path.join(d, "flowboard_backup_" + dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + ".json")
        shutil.copyfile(DB_FILE, dest)
        files = sorted([f for f in os.listdir(d) if f.startswith("flowboard_backup_") and f.endswith(".json")],
                       key=lambda f: os.path.getmtime(os.path.join(d, f)), reverse=True)
        for f in files[30:]:
            try:
                os.remove(os.path.join(d, f))
            except Exception:
                pass
        return dest

    @staticmethod
    def backup_list():
        d = get_backup_dir()
        out = []
        for f in os.listdir(d):
            if f.endswith(".json"):
                p = os.path.join(d, f)
                out.append((f, os.path.getsize(p), os.path.getmtime(p)))
        return sorted(out, key=lambda x: x[2], reverse=True)

    def restore_file(self, path):
        with open(path, encoding="utf-8") as f:
            parsed = json.load(f)
        if not isinstance(parsed, dict) or not (parsed.get("kanban") or parsed.get("years")):
            raise ValueError("Not a TaskTrail / FlowBoard backup file.")
        data = open(path, "rb").read()          # read first: the safety backup must never clobber the source
        self.backup_now()
        with open(DB_FILE, "wb") as f:
            f.write(data)
        self.load()
        self.save()


# ═══════════════════════════════════════════════════════════════════════════
#  THEME / STYLESHEET
# ═══════════════════════════════════════════════════════════════════════════
def check_icon_path():
    """White tick used inside checked checkboxes (so 'done' is not conveyed by colour alone)."""
    from glass import icon_pixmap
    d = os.path.join(USER_DATA, "cache"); os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "check.png")
    if not os.path.exists(path):
        icon_pixmap("check", "#ffffff", 14, 1.0, 2.0).save(path)
    return path.replace("\\", "/")


def build_qss(p, font_family, font_size):
    """Global stylesheet from the design tokens.  Surfaces are translucent (rgba) so the window backdrop shows
    through; radii follow Fluent guidance (controls 10px, cards 10–12px, menus 8px)."""
    fs = font_size; dark = p["dark"]; acc = p["accent"]
    hair = rgba(p["text"], 0.11 if dark else 0.13)
    hair2 = rgba(p["text"], 0.20 if dark else 0.24)
    ctl = rgba(p["text"], 0.06 if dark else 0.05)
    ctl_h = rgba(p["text"], 0.11 if dark else 0.09)
    inp = rgba(p["s3"], 0.70 if dark else 0.80)
    pop = mix(p["s2"], p["bg"], 0.25)
    btn_h = (mix(p["btn_top"], "#ffffff", 0.14), mix(p["btn_bot"], "#ffffff", 0.10))
    grad = f"qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {p['btn_top']}, stop:1 {p['btn_bot']})"
    grad_h = f"qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {btn_h[0]}, stop:1 {btn_h[1]})"
    chk = check_icon_path()
    return f"""
    QWidget {{ background:transparent; color:{p['text']}; font-family:"{font_family}"; font-size:{fs}px; }}
    QMainWindow {{ background:transparent; }}
    QDialog {{ background:{p['bg']}; }}
    QDialog#glassDialog {{ background:transparent; }}
    QToolTip {{ background:{pop}; color:{p['text']}; border:1px solid {hair2}; border-radius:8px; padding:6px 10px; }}
    QFrame#topbar {{ background:transparent; border:none; border-bottom:1px solid {hair}; }}
    QFrame#sidebar {{ background:transparent; border:none; }}
    QFrame#detail {{ background:{rgba(p['s1'], 0.62 if dark else 0.72)}; border:none; border-left:1px solid {hair}; }}
    QDockWidget::title {{ background:transparent; padding:10px 16px; font-weight:600; border-bottom:1px solid {hair}; }}
    QLabel#pageTitle {{ font-size:{fs+6}px; font-weight:700; }}
    QLabel#pageMonth {{ color:{p['accent_text']}; background:{rgba(acc, 0.16)}; border:1px solid {rgba(acc, 0.32)}; border-radius:10px; font-weight:600; }}
    QLabel#navSection, QLabel#brandSub {{ color:{p['text3']}; font-size:{fs-3}px; font-weight:600; letter-spacing:1px; }}
    QLabel#muted {{ color:{p['text3']}; }} QLabel#muted2 {{ color:{p['text2']}; }}
    QLabel#kpiVal {{ font-size:{fs+17}px; font-weight:700; }}
    QLabel#kpiLabel {{ color:{p['text2']}; font-size:{fs-3}px; font-weight:600; letter-spacing:1px; }}
    QLabel#sectitle {{ font-weight:650; font-size:{fs+1}px; }}
    QLabel#badge {{ border-radius:8px; padding:1px 7px; font-size:{fs-3}px; font-weight:600; }}
    QLabel, QCheckBox {{ background:transparent; }}

    QPushButton {{ padding:7px 14px; border-radius:10px; border:1px solid {hair}; background:{ctl}; color:{p['text']}; font-weight:600; }}
    QPushButton:hover {{ background:{ctl_h}; border-color:{hair2}; }}
    QPushButton:pressed {{ background:{rgba(p['text'], 0.03)}; }}
    QPushButton:focus {{ border-color:{rgba(acc, 0.85)}; }}
    QPushButton:disabled {{ color:{p['text3']}; }}
    QPushButton#primary {{ background:{grad}; border:1px solid {rgba('#ffffff', 0.30)}; color:#ffffff; }}
    QPushButton#primary:hover {{ background:{grad_h}; border-color:{rgba('#ffffff', 0.5)}; }}
    QPushButton#primary:pressed {{ background:{p['btn_bot']}; }}
    QPushButton#danger {{ color:{p['danger']}; border-color:{rgba(p['danger'], 0.5)}; background:transparent; }}
    QPushButton#danger:hover {{ background:{rgba(p['danger'], 0.12)}; }}
    QPushButton#ghost {{ border:none; background:transparent; color:{p['text3']}; padding:3px 7px; border-radius:8px; }}
    QPushButton#ghost:hover {{ color:{p['text']}; background:{ctl_h}; }}
    QPushButton#iconbtn {{ padding:7px; border:1px solid transparent; background:transparent; border-radius:10px; }}
    QPushButton#iconbtn:hover {{ background:{ctl_h}; border-color:{hair}; }}
    QPushButton#addk {{ border:1px dashed {hair2}; border-radius:10px; background:transparent; color:{p['text3']}; font-weight:500; text-align:left; padding:8px 14px; }}
    QPushButton#addk:hover {{ border-color:{rgba(acc, 0.8)}; color:{p['accent_text']}; background:{rgba(acc, 0.08)}; }}
    QPushButton#month {{ padding:4px 2px; border:1px solid {hair}; border-radius:8px; color:{p['text2']}; background:transparent; font-size:{fs-2}px; font-weight:600; }}
    QPushButton#month:hover {{ border-color:{rgba(acc, 0.8)}; color:{p['accent_text']}; }}
    QPushButton#month:checked {{ background:{grad}; border-color:{rgba('#ffffff', 0.3)}; color:#ffffff; }}
    QPushButton#navbtn, QPushButton#rowbtn {{ background:transparent; border:none; padding:0; }}
    QPushButton#chip {{ padding:4px 12px; border-radius:12px; font-weight:600; color:{p['text2']}; }}
    QPushButton#chip:checked {{ background:{rgba(acc, 0.22)}; border-color:{rgba(acc, 0.7)}; color:{p['accent_text']}; }}

    QLineEdit, QTextEdit, QComboBox, QDateEdit, QSpinBox, QFontComboBox {{ background:{inp}; border:1px solid {hair}; border-radius:10px; padding:7px 11px; color:{p['text']}; selection-background-color:{acc}; selection-color:#ffffff; }}
    QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover {{ border-color:{hair2}; }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{ border:1px solid {acc}; }}
    QComboBox QAbstractItemView {{ background:{pop}; color:{p['text']}; selection-background-color:{rgba(acc, 0.35)}; selection-color:{p['text']}; border:1px solid {hair2}; border-radius:8px; outline:0; padding:4px; }}
    QListWidget {{ background:transparent; border:none; outline:0; }}
    QListWidget::item {{ background:transparent; border:none; padding:0; margin:0; }}
    QListWidget::item:selected {{ background:transparent; }}
    QScrollArea {{ border:none; background:transparent; }}
    QScrollBar:vertical {{ width:12px; margin:2px; background:transparent; }} QScrollBar:horizontal {{ height:12px; margin:2px; background:transparent; }}
    QScrollBar::handle {{ background:{rgba(p['text'], 0.20)}; border-radius:4px; min-height:28px; min-width:28px; }}
    QScrollBar::handle:hover {{ background:{rgba(p['text'], 0.36)}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
    QCheckBox {{ spacing:8px; }}
    QCheckBox::indicator {{ width:17px; height:17px; border-radius:5px; border:1.5px solid {rgba(p['text'], 0.45)}; background:transparent; }}
    QCheckBox::indicator:hover {{ border-color:{acc}; }}
    QCheckBox::indicator:checked {{ background:{p['ok']}; border-color:{p['ok']}; image:url({chk}); }}
    QSlider::groove:horizontal {{ height:6px; background:{rgba(p['text'], 0.16)}; border-radius:3px; }}
    QSlider::sub-page:horizontal {{ background:{grad}; border-radius:3px; }}
    QSlider::handle:horizontal {{ width:16px; height:16px; margin:-5px 0; border-radius:9px; background:#ffffff; border:2px solid {acc}; }}

    QMenu {{ background:{pop}; border:1px solid {hair2}; border-radius:8px; padding:4px; }}
    QMenu::item {{ padding:6px 22px 6px 14px; border-radius:5px; margin:1px 2px; }}
    QMenu::item:selected {{ background:{p['btn_top']}; color:#ffffff; }}
    QMenu#glassMenu {{ background:transparent; border:none; margin:10px; padding:6px; }}
    QMenu#glassMenu::item {{ padding:7px 26px 7px 10px; border-radius:7px; margin:1px 4px; color:{p['text']}; background:transparent; }}
    QMenu#glassMenu::item:selected {{ background:{rgba(acc, 0.30)}; color:{p['text']}; }}
    QMenu#glassMenu::item:disabled {{ color:{p['text3']}; }}
    QMenu#glassMenu::separator {{ height:1px; background:{hair}; margin:5px 12px; }}
    QMenu#glassMenu::icon {{ padding-left:8px; }}
    """


# ═══════════════════════════════════════════════════════════════════════════
#  SMALL WIDGETS
# ═══════════════════════════════════════════════════════════════════════════
def badge(text, color, bg=None):
    """Small pill.  Text colour is always chosen for contrast (≥ 4.5:1): on a filled chip it picks white/near-black,
    on a tinted chip it nudges the colour toward the readable side of the current theme."""
    l = QLabel(text)
    l.setObjectName("badge")
    if bg:
        fg, back = readable_on(bg, color), bg
    else:
        fg, back = T(color), rgba(color, 0.16)
    l.setStyleSheet(f"QLabel#badge{{color:{fg};background:{back};}}")
    l.setMargin(2)
    return l


def hline():
    f = QFrame(); f.setFrameShape(QFrame.HLine); f.setStyleSheet(f"color:{rgba(C('text'), 0.12)};")
    return f


class BarChart(QWidget):
    """Tasks per month (current year): gradient bars, the shown month glows, hover shows the exact count.
    Click a bar to open that month."""
    clicked = Signal(int)

    def __init__(self, get_values, accent=None):
        super().__init__(); self.get_values = get_values; self.current = -1; self.progress = 1.0; self.hover = -1
        self.setMinimumHeight(130); self.setMouseTracking(True); self.setCursor(QCursor(Qt.PointingHandCursor))

    def _slot(self, x):
        return int(x / (self.width() / 12))

    def mouseMoveEvent(self, e):
        i = self._slot(e.position().x()); i = i if 0 <= i < 12 else -1
        if i != self.hover:
            self.hover = i; self.update()
            self.setToolTip(f"{MONTHS_LONG[i]}: {self.get_values()[i]} task(s)" if i >= 0 else "")

    def leaveEvent(self, e):
        self.hover = -1; self.update()

    def paintEvent(self, e):
        P = GLASS.p; vals = self.get_values(); mx = max(1, max(vals))
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w = self.width(); h = self.height() - 22; gap = 6; bw = (w - 11 * gap) / 12
        for i, v in enumerate(vals):
            bh = max(5.0, v / mx * (h - 16) * self.progress); x = i * (bw + gap); r = QRectF(x, h - bh, bw, bh)
            on = i == self.current; hov = i == self.hover; a = 1.0 if on else 0.82 if hov else 0.42
            if on:                                                              # neon halo around the shown month
                p.setPen(Qt.NoPen)
                for k, al in ((6, 0.05), (4, 0.09), (2, 0.16)):
                    p.setBrush(qc(P["accent"], al)); p.drawRoundedRect(r.adjusted(-k, -k, k, k), 4 + k, 4 + k)
            g = QLinearGradient(r.topLeft(), r.bottomLeft()); g.setColorAt(0, qc(P["accent2"], a)); g.setColorAt(1, qc(P["accent"], a))
            p.setPen(Qt.NoPen); p.setBrush(QBrush(g)); p.drawRoundedRect(r, 4, 4)
            if (hov or on) and v:
                p.setPen(QColor(P["text"])); f = p.font(); f.setBold(True); f.setPixelSize(11); p.setFont(f)
                p.drawText(QRectF(x - 6, r.top() - 17, bw + 12, 15), Qt.AlignCenter, str(v))
            p.setPen(QColor(P["accent_text"] if on else P["text3"])); f = p.font(); f.setBold(on); f.setPixelSize(11); p.setFont(f)
            p.drawText(QRectF(x - 4, h + 4, bw + 8, 16), Qt.AlignCenter, MONTHS[i][0])
        p.end()

    def mousePressEvent(self, e):
        i = self._slot(e.position().x())
        if 0 <= i < 12: self.clicked.emit(i)


class WeekAhead(QWidget):
    """Next 7 days: open tasks due per day as glowing bars.  Click → Calendar."""
    clicked = Signal()

    def __init__(self, get_days):
        super().__init__(); self.get_days = get_days; self.progress = 1.0; self.setMinimumHeight(112)
        self.setCursor(QCursor(Qt.PointingHandCursor)); self.setMouseTracking(True)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self.clicked.emit()

    def paintEvent(self, e):
        P = GLASS.p; days = self.get_days(); mx = max(1, max(d[2] for d in days))
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        n = len(days); gap = 8; w = self.width(); bw = (w - gap * (n - 1)) / n; top = 16; base = self.height() - 34
        for i, (lab, num, cnt, today, over) in enumerate(days):
            x = i * (bw + gap); bh = max(4.0, cnt / mx * (base - top) * self.progress) if cnt else 4.0; r = QRectF(x, base - bh, bw, bh)
            col = P["danger"] if over else P["accent2"]
            if cnt:
                if today:
                    p.setPen(Qt.NoPen)
                    for k, al in ((6, 0.05), (4, 0.09), (2, 0.16)):
                        p.setBrush(qc(col, al)); p.drawRoundedRect(r.adjusted(-k, -k, k, k), 4 + k, 4 + k)
                g = QLinearGradient(r.topLeft(), r.bottomLeft()); g.setColorAt(0, qc(col, 0.95 if today else 0.6)); g.setColorAt(1, qc(P["accent"], 0.95 if today else 0.5))
                p.setPen(Qt.NoPen); p.setBrush(QBrush(g)); p.drawRoundedRect(r, 4, 4)
                f = p.font(); f.setPixelSize(11); f.setBold(True); p.setFont(f); p.setPen(QColor(P["text"]))
                p.drawText(QRectF(x - 4, r.top() - 16, bw + 8, 14), Qt.AlignCenter, str(cnt))
            else:
                p.setPen(Qt.NoPen); p.setBrush(qc(P["text"], 0.10)); p.drawRoundedRect(r, 2, 2)
            f = p.font(); f.setPixelSize(10); f.setBold(today); p.setFont(f); p.setPen(QColor(P["accent_text"] if today else P["text3"]))
            p.drawText(QRectF(x - 6, base + 5, bw + 12, 13), Qt.AlignCenter, lab)
            p.drawText(QRectF(x - 6, base + 18, bw + 12, 13), Qt.AlignCenter, str(num))
        p.end()


class Ring(QWidget):
    """Completion ring (0–100) with a soft neon halo.  `value` is animated by the dashboard."""
    def __init__(self, color):
        super().__init__(); self.color = color; self.value = 0; self.setFixedSize(68, 68)

    def paintEvent(self, e):
        P = GLASS.p; p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); r = QRectF(9, 9, 50, 50)
        p.setPen(QPen(qc(P["text"], 0.12), 6)); p.drawEllipse(r)
        span = -int(360 * 16 * self.value / 100)
        if self.value > 0.5:
            for wd, al in ((14, 0.05), (10, 0.09), (8, 0.16)):
                pen = QPen(qc(self.color, al), wd); pen.setCapStyle(Qt.RoundCap); p.setPen(pen); p.drawArc(r, 90 * 16, span)
            pen = QPen(QColor(self.color), 6); pen.setCapStyle(Qt.RoundCap); p.setPen(pen); p.drawArc(r, 90 * 16, span)
        p.setPen(QColor(T(self.color))); f = p.font(); f.setBold(True); f.setPixelSize(13); p.setFont(f); p.drawText(r, Qt.AlignCenter, f"{int(self.value)}%"); p.end()


class PriMix(QWidget):
    """Open tasks by priority as one segmented glow bar."""
    def __init__(self):
        super().__init__(); self.counts = (0, 0, 0); self.setFixedHeight(20)

    def paintEvent(self, e):
        P = GLASS.p; tot = sum(self.counts); p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
        bar = QRectF(0, 5, self.width(), 10)
        if not tot:
            p.setBrush(qc(P["text"], 0.12)); p.drawRoundedRect(bar, 5, 5); p.end(); return
        segs = [(n, c) for n, c in zip(self.counts, (PRI_COLOR["high"], PRI_COLOR["med"], PRI_COLOR["low"])) if n]
        gap = 3; avail = self.width() - gap * (len(segs) - 1); x = 0.0
        for n, c in segs:
            wd = avail * n / tot; r = QRectF(x, 5, wd, 10)
            for k, al in ((4, 0.06), (2, 0.12)):
                p.setBrush(qc(c, al)); p.drawRoundedRect(r.adjusted(-k, -k, k, k), 5 + k, 5 + k)
            p.setBrush(QColor(c)); p.drawRoundedRect(r, 5, 5); x += wd + gap
        p.end()


class CardWidget(GlassFrame):
    """A task card on the board: frosted glass, coloured edge, lifts + glows on hover, right-click menu."""
    clicked = Signal(str, str)      # cid, col
    edit = Signal(str, str)
    delete = Signal(str, str)
    toggle = Signal(str, str)
    context = Signal(str, str, object)

    def __init__(self, store, card, col, compact=False):
        super().__init__(elev=1, radius=RADIUS["card"], hoverable=True, edge=col["color"], margins=(8, 2, 8, 5) if compact else None); self.card = card; self.col_id = col["id"]
        self.setCursor(QCursor(Qt.PointingHandCursor))
        v = QVBoxLayout(self); v.setContentsMargins(14, 6 if compact else 10, 10, 6 if compact else 10); v.setSpacing(4 if compact else 6)
        labels = [l for l in store.labels if l["id"] in card.get("labels", [])] if not compact else []
        if labels:
            lr = QHBoxLayout(); lr.setSpacing(4)
            for l in labels:
                lr.addWidget(badge(l["name"], "#ffffff", l["color"]))
            lr.addStretch(); v.addLayout(lr)
        top = QHBoxLayout(); top.setSpacing(8)
        done = card.get("done") or self.col_id == "done"
        cb = QCheckBox(); cb.setChecked(done); cb.setToolTip("Complete / reopen")
        cb.clicked.connect(lambda: self.toggle.emit(card["id"], self.col_id))
        title = QLabel(card["title"]); title.setWordWrap(True); title.setStyleSheet("font-weight:500;" + (f"text-decoration:line-through;color:{C('text3')};" if done else ""))
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        eb = QPushButton(); eb.setObjectName("ghost"); eb.setToolTip("Edit"); eb.setIcon(make_icon("edit", 14)); eb.setIconSize(QSize(14, 14)); eb.clicked.connect(lambda: self.edit.emit(card["id"], self.col_id))
        db_ = QPushButton(); db_.setObjectName("ghost"); db_.setToolTip("Delete"); db_.setIcon(make_icon("close", 14)); db_.setIconSize(QSize(14, 14)); db_.clicked.connect(lambda: self.delete.emit(card["id"], self.col_id))
        for w in (cb, title, eb, db_):
            top.addWidget(w)
        v.addLayout(top)
        meta = QHBoxLayout(); meta.setSpacing(5)
        meta.addWidget(badge(PRI_LABEL[card.get("priority", "med")], PRI_COLOR[card.get("priority", "med")]))
        if card.get("dueDate"):
            od = is_overdue(card["dueDate"], done)
            meta.addWidget(badge(("⚠ " if od else "📅 ") + fmt_date(card["dueDate"]), PRI_COLOR["high"] if od else C("text2")))
        meta.addStretch(); v.addLayout(meta)
        if compact:
            if card.get("repeat"): meta.insertWidget(meta.count() - 1, badge("↻", C("accent")))
            return
        if card.get("repeat") or card.get("migratedFrom"):      # second row so narrow columns don't clip the badges
            m2 = QHBoxLayout(); m2.setSpacing(5)
            if card.get("repeat"): m2.addWidget(badge("↻ " + REPEAT_SHORT.get(card["repeat"], card["repeat"]), C("accent")))
            if card.get("migratedFrom"): m2.addWidget(badge("↪ " + card["migratedFrom"], C("text2")))
            m2.addStretch(); v.addLayout(m2)
        if card.get("desc"):
            d = QLabel(card["desc"][:160] + ("…" if len(card["desc"]) > 160 else "")); d.setObjectName("muted2"); d.setWordWrap(True); v.addWidget(d)
        subs = card.get("subs", [])
        if subs:
            sd = sum(1 for s in subs if s.get("done"))
            v.addWidget(QLabel(f"☑ {sd}/{len(subs)} sub-tasks", objectName="muted"))
        if card.get("comments"):
            v.addWidget(QLabel(f"💬 {len(card['comments'])}", objectName="muted"))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.card["id"], self.col_id)
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        self.context.emit(self.card["id"], self.col_id, e.globalPos()); e.accept()


class CardList(QListWidget):
    """Column list with drag & drop between/within columns. The drop updates the model
    and asks the board to re-render, so item widgets are always rebuilt."""
    dropped = Signal(str, str, str, object)   # cid, from_col, to_col, before_id(None=end)

    def __init__(self, col_id):
        super().__init__(); self.col_id = col_id
        self.setDragDropMode(QAbstractItemView.DragDrop); self.setDefaultDropAction(Qt.MoveAction)
        self.setAcceptDrops(True); self.setDragEnabled(True); self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel); self.setSpacing(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setUniformItemSizes(False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit_items()

    def fit_items(self):
        """Size every card to the column width so wrapped text and borders are never clipped."""
        w = self.viewport().width() - 2
        if w < 60:
            return
        for i in range(self.count()):
            it = self.item(i)
            wd = self.itemWidget(it)
            if wd is None:
                continue
            wd.setFixedWidth(w)
            h = wd.heightForWidth(w) if wd.layout() and wd.layout().hasHeightForWidth() else wd.sizeHint().height()
            it.setSizeHint(QSize(w, max(h, wd.sizeHint().height())))

    def dropEvent(self, e):
        src = e.source()
        if not isinstance(src, CardList) or not src.currentItem():
            e.ignore(); return
        cid = src.currentItem().data(Qt.UserRole)
        pos = e.position().toPoint() if hasattr(e, "position") else e.pos()
        item = self.itemAt(pos)
        before = None
        if item is not None:
            r = self.visualItemRect(item)
            if pos.y() < r.center().y():
                before = item.data(Qt.UserRole)
            else:
                nxt = self.item(self.row(item) + 1)
                before = nxt.data(Qt.UserRole) if nxt else None
        e.setDropAction(Qt.IgnoreAction); e.accept()
        self.dropped.emit(cid, src.col_id, self.col_id, before)


class ListRow(GlassFrame):
    """One task in the list view — the same card as on the board, one line."""
    clicked = Signal(str, str); toggle = Signal(str, str); context = Signal(str, str, object)

    def __init__(self, store, card, col):
        super().__init__(elev=1, radius=RADIUS["card"], hoverable=True, edge=col["color"], lift=1.5, margins=(4, 2, 4, 5)); self.card = card; self.col_id = col["id"]; self.setCursor(QCursor(Qt.PointingHandCursor))
        h = QHBoxLayout(self); h.setContentsMargins(14, 6, 10, 6); h.setSpacing(8)
        done = card.get("done") or col["id"] == "done"; cb = QCheckBox(); cb.setChecked(done); cb.setToolTip("Complete / reopen"); cb.clicked.connect(lambda: self.toggle.emit(card["id"], col["id"])); h.addWidget(cb)
        t = QLabel(card["title"]); t.setWordWrap(True); t.setStyleSheet("font-weight:500;" + (f"text-decoration:line-through;color:{C('text3')};" if done else "")); h.addWidget(t, 1)
        subs = card.get("subs", [])
        if subs: h.addWidget(badge(f"☑ {sum(1 for x in subs if x.get('done'))}/{len(subs)}", C("text2")))
        for l in (x for x in store.labels if x["id"] in card.get("labels", [])): h.addWidget(badge(l["name"], "#ffffff", l["color"]))
        if card.get("repeat"): h.addWidget(badge("↻ " + REPEAT_SHORT.get(card["repeat"], card["repeat"]), C("accent")))
        if card.get("dueDate"): od = is_overdue(card["dueDate"], done); h.addWidget(badge(("⚠ " if od else "📅 ") + fmt_date(card["dueDate"]), PRI_COLOR["high"] if od else C("text2")))
        h.addWidget(badge(PRI_LABEL[card.get("priority", "med")], PRI_COLOR[card.get("priority", "med")]))
        h.addWidget(badge(f"{col.get('icon', '')} {col['label']}", "#ffffff", col["color"]))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton: self.clicked.emit(self.card["id"], self.col_id)

    def contextMenuEvent(self, e):
        self.context.emit(self.card["id"], self.col_id, e.globalPos()); e.accept()


class CalChip(QLabel):
    """A task on the calendar. Board cards (drag_id set) can be dragged onto a day or the Unscheduled tray."""
    def __init__(self, text, color, drag_id=None, done=False, overdue=False, dashed=False, on_click=None, ghost=False, pri=None):
        super().__init__(text); self.drag_id = drag_id; self.on_click = on_click; self._press = None
        self.setToolTip(text + (" — drag to reschedule" if drag_id else " — future occurrence; complete the task to move it here" if ghost else " — click to open")); self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)      # clip long titles instead of widening the day
        if pri == "high" and not ghost and not done:                    # high priority = a red dot, readable at a glance
            self.setTextFormat(Qt.RichText); self.setText(f'<span style="color:{PRI_COLOR["high"]}">●</span> ' + html.escape(text))
        self.setStyleSheet(f"QLabel{{border-left:3px {'dashed' if dashed else 'solid'} {color};border-radius:5px;padding:2px 6px;background:{rgba(color, 0.05 if ghost else 0.14)};"
                           + (f"color:{C('text2')};" if ghost else f"text-decoration:line-through;color:{C('text3')};" if done else f"color:{C('danger')};font-weight:600;" if overdue else "") + "}")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or not self.drag_id or (e.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance(): return
        self._press = None; md = QMimeData(); md.setText(self.drag_id); d = QDrag(self); d.setMimeData(md); d.setPixmap(self.grab()); d.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, e):
        if self._press is not None and self.on_click: self.on_click()
        self._press = None


class CalDay(GlassFrame):
    """A calendar day (or, with iso='', the Unscheduled tray) that accepts dropped CalChips.
    State comes from dynamic properties: out (other month), today; drag-over is handled internally."""
    dropped = Signal(str, str)      # cid, iso ('' clears the due date)
    added = Signal(str)             # iso — double-clicked

    def __init__(self, iso, tray=False):
        super().__init__(elev=1 if tray else 0, radius=RADIUS["panel"] if tray else RADIUS["card"], hoverable=bool(iso), lift=0.0,
                         margins=None if tray else (0, 0, 0, 0)); self.iso = iso; self.setAcceptDrops(True); self._over_on = False

    def fill(self, t):
        P = GLASS.p
        if self._over_on: return qc(P["accent"], 0.18)
        if self.property("out"): return qc(P["s2"], 0.16 if GLASS.dark else 0.30)
        return qc(P["s2"], ((0.50 if GLASS.dark else 0.62) - (0.14 if self.property("weekend") else 0)) + 0.14 * t)

    def border_state(self):
        if self._over_on or self.property("today"): return qc(GLASS.p["accent"], 0.95)
        return None

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.property("today") or self._over_on:                 # soft outer glow on the ring
            p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5); p.setBrush(Qt.NoBrush)
            for wd, al in ((6, 0.05), (4, 0.09), (2.4, 0.15)):
                p.setPen(QPen(qc(GLASS.p["accent"], al), wd)); p.drawRoundedRect(r, self.radius, self.radius)
            p.end()

    def _over(self, on):
        self._over_on = on; self.update()

    def dragEnterEvent(self, e):
        if e.mimeData().hasText(): e.acceptProposedAction(); self._over(True)

    def dragLeaveEvent(self, e): self._over(False)

    def dropEvent(self, e):
        self._over(False); e.acceptProposedAction(); self.dropped.emit(e.mimeData().text(), self.iso)

    def mouseDoubleClickEvent(self, e):
        if self.iso: self.added.emit(self.iso)


# ═══════════════════════════════════════════════════════════════════════════
#  DIALOGS
# ═══════════════════════════════════════════════════════════════════════════
class TaskDialog(GlassDialog):
    def __init__(self, parent, store, card=None, col_id="todo", preset=None):
        super().__init__(parent); self.store = store; self.card = card
        self.setWindowTitle("Edit Task" if card else "New Task"); self.setMinimumWidth(540)
        v = QVBoxLayout(self); v.setSpacing(10)
        self.title = QLineEdit(card["title"] if card else ""); self.title.setPlaceholderText("What needs to be done?")
        self.desc = QTextEdit(card.get("desc", "") if card else ""); self.desc.setPlaceholderText("Details or notes…"); self.desc.setFixedHeight(70)
        self.col = QComboBox()
        for c in store.columns:
            self.col.addItem(f"{c.get('icon', '')} {c['label']}", c["id"])
        self.col.setCurrentIndex(max(0, self.col.findData(col_id)))
        self.pri = QComboBox()
        for k, lab in PRI_LABEL.items():
            self.pri.addItem(lab, k)
        self.pri.setCurrentIndex(self.pri.findData(card.get("priority", "med") if card else "med"))
        self.has_date = QCheckBox("Due date"); self.date = QDateEdit(QDate.currentDate()); self.date.setCalendarPopup(True); self.date.setDisplayFormat("yyyy-MM-dd"); self.date.setMinimumWidth(150)
        if card and card.get("dueDate"):
            self.has_date.setChecked(True); self.date.setDate(QDate.fromString(card["dueDate"], "yyyy-MM-dd"))
        self.date.setEnabled(self.has_date.isChecked()); self.has_date.toggled.connect(self.date.setEnabled)
        self.rep = QComboBox()
        for k, lab in REPEATS: self.rep.addItem(("↻ " if k else "") + lab, k)
        self.rep.setCurrentIndex(max(0, self.rep.findData(card.get("repeat", "") if card else "")))
        self.has_until = QCheckBox("until"); self.until = QDateEdit(QDate.currentDate().addMonths(3)); self.until.setCalendarPopup(True); self.until.setDisplayFormat("yyyy-MM-dd"); self.until.setMinimumWidth(150)
        if card and card.get("repeatUntil"): self.has_until.setChecked(True); self.until.setDate(QDate.fromString(card["repeatUntil"], "yyyy-MM-dd"))
        def rep_changed():
            on = bool(self.rep.currentData()); self.has_until.setEnabled(on); self.until.setEnabled(on and self.has_until.isChecked())
            if on and not self.has_date.isChecked(): self.has_date.setChecked(True)
        self.rep.currentIndexChanged.connect(rep_changed); self.has_until.toggled.connect(rep_changed); rep_changed()
        v.addWidget(QLabel("Title *")); v.addWidget(self.title)
        v.addWidget(QLabel("Description")); v.addWidget(self.desc)
        g = QGridLayout(); g.addWidget(QLabel("Column"), 0, 0); g.addWidget(QLabel("Priority"), 0, 1)
        g.addWidget(self.col, 1, 0); g.addWidget(self.pri, 1, 1); v.addLayout(g)
        dr = QHBoxLayout(); dr.addWidget(self.has_date); dr.addWidget(self.date); dr.addSpacing(16); dr.addWidget(QLabel("Repeat")); dr.addWidget(self.rep); dr.addWidget(self.has_until); dr.addWidget(self.until); dr.addStretch(); v.addLayout(dr)
        # labels
        lr = QHBoxLayout(); lr.addWidget(QLabel("Labels")); mb = QPushButton("Manage"); mb.clicked.connect(self.manage_labels); lr.addWidget(mb); lr.addStretch(); v.addLayout(lr)
        self.label_box = QWidget(); self.label_layout = QHBoxLayout(self.label_box); self.label_layout.setContentsMargins(0, 0, 0, 0)
        self.sel_labels = set(card.get("labels", [])) if card else set(); self.rebuild_labels(); v.addWidget(self.label_box)
        # subtasks
        v.addWidget(QLabel("Sub-tasks   (double-click an item to edit it)"))
        self.subs = [dict(s) for s in (card.get("subs", []) if card else [])]
        self.sub_list = QListWidget(); self.sub_list.setFixedHeight(130); self.sub_list.setWordWrap(True); self.sub_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sub_list.setStyleSheet("QListWidget::item{padding:3px 6px;margin:0 0 2px 0;border-radius:6px;}QListWidget::item:selected{background:rgba(128,128,128,0.25);color:palette(text);}")
        self.sub_list.itemDoubleClicked.connect(lambda it: self.edit_sub(self.sub_list.row(it))); self.rebuild_subs(); v.addWidget(self.sub_list)
        sr = QHBoxLayout(); self.sub_inp = QLineEdit(); self.sub_inp.setPlaceholderText("Add sub-task… (Enter)")
        self.sub_inp.returnPressed.connect(self.add_sub); ab = QPushButton("+"); ab.clicked.connect(self.add_sub); rb = QPushButton("Remove selected"); rb.clicked.connect(self.remove_sub)
        sr.addWidget(self.sub_inp); sr.addWidget(ab); sr.addWidget(rb); v.addLayout(sr)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setObjectName("primary"); bb.button(QDialogButtonBox.Save).setText("Save changes" if card else "Save task")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); v.addWidget(bb)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.accept)
        if preset:      # from quick-add / calendar / palette
            self.title.setText(preset.get("title", "")); self.pri.setCurrentIndex(self.pri.findData(preset.get("priority", "med")))
            if preset.get("dueDate"): self.has_date.setChecked(True); self.date.setDate(QDate.fromString(preset["dueDate"], "yyyy-MM-dd"))
            self.sel_labels = set(preset.get("labels", [])); self.rebuild_labels()
            if preset.get("repeat"): self.rep.setCurrentIndex(max(0, self.rep.findData(preset["repeat"])))

    def rebuild_labels(self):
        while self.label_layout.count():
            w = self.label_layout.takeAt(0).widget()
            if w: w.deleteLater()
        if not self.store.labels:
            self.label_layout.addWidget(QLabel("No labels yet", objectName="muted"))
        for l in self.store.labels:
            b = QPushButton(l["name"]); b.setCheckable(True); b.setChecked(l["id"] in self.sel_labels)
            b.setStyleSheet(f"QPushButton{{border-color:{l['color']};color:{l['color']};}}QPushButton:checked{{background:{l['color']};color:#fff;}}")
            b.toggled.connect(lambda on, lid=l["id"]: self.sel_labels.add(lid) if on else self.sel_labels.discard(lid))
            self.label_layout.addWidget(b)
        self.label_layout.addStretch()

    def manage_labels(self):
        LabelDialog(self, self.store).exec(); self.rebuild_labels()

    def rebuild_subs(self):
        self.sub_list.clear()
        for s in self.subs:
            self.sub_list.addItem(("✓ " if s.get("done") else "○ ") + s["text"])

    def add_sub(self):
        t = self.sub_inp.text().strip()
        if t:
            self.subs.append({"id": uid(), "text": t, "done": False}); self.sub_inp.clear(); self.rebuild_subs()

    def remove_sub(self):
        r = self.sub_list.currentRow()
        if r >= 0:
            del self.subs[r]; self.rebuild_subs()

    def edit_sub(self, r):
        if not 0 <= r < len(self.subs): return
        t, ok = QInputDialog.getMultiLineText(self, "Edit sub-task", "Text:", self.subs[r]["text"])
        if ok and t.strip(): self.subs[r]["text"] = t.strip(); self.rebuild_subs(); self.sub_list.setCurrentRow(r)

    def accept(self):
        if not self.title.text().strip():
            self.title.setFocus(); return
        super().accept()

    def values(self):
        return dict(title=self.title.text().strip(), desc=self.desc.toPlainText().strip(), col=self.col.currentData(),
                    priority=self.pri.currentData(), dueDate=self.date.date().toString("yyyy-MM-dd") if self.has_date.isChecked() else "",
                    subs=self.subs, labels=list(self.sel_labels), repeat=self.rep.currentData() or "",
                    repeatUntil=self.until.date().toString("yyyy-MM-dd") if self.rep.currentData() and self.has_until.isChecked() else "")


class LabelDialog(GlassDialog):
    def __init__(self, parent, store):
        super().__init__(parent); self.store = store; self.setWindowTitle("Labels"); self.setMinimumWidth(420)
        self.v = QVBoxLayout(self); self.list_box = QVBoxLayout(); self.v.addLayout(self.list_box)
        r = QHBoxLayout(); self.inp = QLineEdit(); self.inp.setPlaceholderText("New label name"); self.inp.returnPressed.connect(self.add)
        self.color = LABEL_PALETTE[len(store.labels) % len(LABEL_PALETTE)]
        self.cbtn = QPushButton("Colour"); self.cbtn.clicked.connect(self.pick); ab = QPushButton("Add"); ab.setObjectName("primary"); ab.clicked.connect(self.add)
        r.addWidget(self.inp); r.addWidget(self.cbtn); r.addWidget(ab); self.v.addLayout(r)
        cb = QPushButton("Close"); cb.clicked.connect(self.accept); self.v.addWidget(cb)
        self.rebuild()

    def pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Label colour")
        if c.isValid():
            self.color = c.name(); self.cbtn.setStyleSheet(f"background:{self.color};color:#fff;")

    def rebuild(self):
        while self.list_box.count():
            w = self.list_box.takeAt(0).widget()
            if w: w.deleteLater()
        if not self.store.labels:
            self.list_box.addWidget(QLabel("No labels yet — add one below, e.g. Client, Urgent, Personal.", objectName="muted"))
        for l in self.store.labels:
            row = QHBoxLayout(); w = QWidget(); w.setLayout(row)
            sw = QPushButton(); sw.setFixedSize(26, 22); sw.setStyleSheet(f"background:{l['color']};border-radius:6px;")
            sw.clicked.connect(lambda _, lab=l: self.recolor(lab))
            name = QLineEdit(l["name"]); name.editingFinished.connect(lambda lab=l, ed=name: self.rename(lab, ed.text()))
            n = self.usage(l["id"]); cnt = QLabel(f"{n} tasks", objectName="muted")
            dl = QPushButton("✕"); dl.setObjectName("ghost"); dl.clicked.connect(lambda _, lab=l: self.delete(lab))
            for x in (sw, name, cnt, dl):
                row.addWidget(x)
            self.list_box.addWidget(w)

    def usage(self, lid):
        n = 0
        for Y in self.store.db["years"].values():
            for kd in Y["kanban"].values():
                for arr in kd.values():
                    n += sum(1 for c in arr if lid in c.get("labels", []))
        return n

    def add(self):
        t = self.inp.text().strip()
        if not t: return
        self.store.labels.append({"id": "l_" + uid(), "name": t, "color": self.color}); self.inp.clear()
        self.color = LABEL_PALETTE[len(self.store.labels) % len(LABEL_PALETTE)]; self.cbtn.setStyleSheet("")
        self.store.save(); self.rebuild()

    def rename(self, lab, t):
        if t.strip() and t.strip() != lab["name"]:
            lab["name"] = t.strip(); self.store.save()

    def recolor(self, lab):
        c = QColorDialog.getColor(QColor(lab["color"]), self, "Label colour")
        if c.isValid():
            lab["color"] = c.name(); self.store.save(); self.rebuild()

    def delete(self, lab):
        if QMessageBox.question(self, "Delete label", f"Delete label \"{lab['name']}\"? It will be removed from {self.usage(lab['id'])} task(s).") != QMessageBox.Yes:
            return
        for Y in self.store.db["years"].values():
            for kd in Y["kanban"].values():
                for arr in kd.values():
                    for c in arr:
                        if "labels" in c: c["labels"] = [x for x in c["labels"] if x != lab["id"]]
        self.store.labels.remove(lab); self.store.save(); self.rebuild()


class ColumnDialog(GlassDialog):
    def __init__(self, parent, store, col_id=None):
        super().__init__(parent); self.store = store; self.col = store.col(col_id) if col_id else None; self.result_action = None
        self.setWindowTitle("Column settings" if self.col else "New column"); self.setMinimumWidth(400)
        v = QVBoxLayout(self)
        self.name = QLineEdit(self.col["label"] if self.col else ""); self.name.setPlaceholderText("e.g. Review, Blocked, Waiting")
        self.icon = QLineEdit(self.col.get("icon", "") if self.col else "📌"); self.icon.setMaxLength(4); self.icon.setFixedWidth(60)
        self.color = self.col["color"] if self.col else LABEL_PALETTE[len(store.columns) % len(LABEL_PALETTE)]
        self.cbtn = QPushButton("Colour"); self.cbtn.setStyleSheet(f"background:{self.color};color:#fff;"); self.cbtn.clicked.connect(self.pick)
        r = QHBoxLayout(); r.addWidget(self.name); r.addWidget(self.icon); r.addWidget(self.cbtn); v.addWidget(QLabel("Name *")); v.addLayout(r)
        if self.col and self.col["id"] in BUILTIN:
            v.addWidget(QLabel("Built-in column: rename, recolour and move it, but it can't be deleted — the dashboard and month rollover depend on it.", objectName="muted", wordWrap=True))
        br = QHBoxLayout()
        if self.col:
            for txt, act in (("◀ Move left", "left"), ("Move right ▶", "right")):
                b = QPushButton(txt); b.clicked.connect(lambda _, a=act: self.finish(a)); br.addWidget(b)
            if self.col["id"] not in BUILTIN:
                d = QPushButton("Delete"); d.setObjectName("danger"); d.clicked.connect(lambda: self.finish("delete")); br.addWidget(d)
        br.addStretch(); sv = QPushButton("Save"); sv.setObjectName("primary"); sv.clicked.connect(lambda: self.finish("save")); cn = QPushButton("Cancel"); cn.clicked.connect(self.reject)
        br.addWidget(sv); br.addWidget(cn); v.addLayout(br)

    def pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Column colour")
        if c.isValid():
            self.color = c.name(); self.cbtn.setStyleSheet(f"background:{self.color};color:#fff;")

    def finish(self, action):
        if action == "save" and not self.name.text().strip():
            self.name.setFocus(); return
        self.result_action = action; self.accept()


class QuickAdd(GlassOverlay):
    """Floating quick-add: type once, see the parsed priority / labels / due date live.
    Enter saves into the chosen column; Shift+Enter (or 'Full form') opens TaskDialog pre-filled."""
    def __init__(self, win, col_id="todo"):
        super().__init__(win, 640, 120); self.win = win
        v = self.body; top = QHBoxLayout(); top.setSpacing(8)
        self.inp = QLineEdit(); self.inp.setPlaceholderText("What needs to be done?   !high  #label  @fri"); self.inp.textChanged.connect(self.preview); self.inp.returnPressed.connect(self.save)
        add_focus_glow(self.inp)
        self.col = QComboBox()
        for c in win.store.columns: self.col.addItem(f"{c.get('icon', '')} {c['label']}", c["id"])
        self.col.setCurrentIndex(max(0, self.col.findData(col_id))); top.addWidget(self.inp, 1); top.addWidget(self.col); v.addLayout(top)
        self.chips = QHBoxLayout(); self.chips.setSpacing(6); v.addLayout(self.chips)
        foot = QHBoxLayout(); foot.addWidget(QLabel("Enter save · Shift+Enter full form · Esc close     !high !low · #label · @today @tomorrow @fri @15 @+3 @2026-10-01 · *daily", objectName="muted")); foot.addStretch()
        fb = QPushButton("Full form"); fb.setObjectName("ghost"); fb.setIcon(make_icon("arrow-right", 14)); fb.setLayoutDirection(Qt.RightToLeft); fb.clicked.connect(self.full); foot.addWidget(fb); v.addLayout(foot)
        QShortcut(QKeySequence("Shift+Return"), self, activated=self.full); self.preview(); QTimer.singleShot(60, self.inp.setFocus)

    def preview(self, _=None):
        MainWindow._clear(self.chips); s = self.win.store; p = parse_quick(s, self.inp.text(), create=False)
        self.chips.addWidget(badge(PRI_LABEL[p["priority"]], PRI_COLOR[p["priority"]]))
        if p["dueDate"]: self.chips.addWidget(badge("📅 " + fmt_date(p["dueDate"]), C("text2")))
        for l in (x for x in s.labels if x["id"] in p["labels"]): self.chips.addWidget(badge(l["name"], "#ffffff", l["color"]))
        for n in p.get("new", []): self.chips.addWidget(badge("+ " + n, C("text2")))
        if p.get("repeat"): self.chips.addWidget(badge("↻ " + p["repeat"], C("accent")))
        t = QLabel(p["title"] or "Title…", objectName="muted2"); t.setStyleSheet("font-weight:600;"); self.chips.addWidget(t); self.chips.addStretch()

    def save(self):
        if self.win.qa_submit(self.col.currentData(), self.inp.text()): self.accept()

    def full(self):
        col, text = self.col.currentData(), self.inp.text(); self.accept(); self.win.add_task(col, parse_quick(self.win.store, text))


class DayOverlay(GlassOverlay):
    """All tasks due on one day (the '+N more' target): glass panel over the blurred calendar."""
    def __init__(self, win, iso):
        super().__init__(win, 520, 110); self.win = win; self.iso = iso
        d = dt.date.fromisoformat(iso); v = self.body; v.setContentsMargins(16, 14, 16, 14)
        hr = QHBoxLayout(); t = QLabel(d.strftime("%A, %d %B %Y").replace(" 0", " ")); t.setObjectName("sectitle"); t.setStyleSheet("font-size:16px;"); hr.addWidget(t); hr.addStretch()
        ab = QPushButton(" Add task"); ab.setObjectName("primary"); ab.setIcon(make_icon("plus", 14, "#ffffff", dim=1.0)); ab.clicked.connect(lambda: (self.accept(), win.add_task("todo", dict(dueDate=iso)))); hr.addWidget(ab); v.addLayout(hr)
        rows = [(c, k) for yy, mi, c, k in win.iter_cards() if k.get("dueDate") == iso]; rows.sort(key=lambda t: (bool(t[1].get("done") or t[0]["id"] == "done"), -PRI_RANK.get(t[1].get("priority", "med"), 1)))
        inner = QWidget(); il = QVBoxLayout(inner); il.setContentsMargins(0, 0, 4, 0); il.setSpacing(4)
        for c, k in rows:
            done = bool(k.get("done") or c["id"] == "done"); b = RowButton(k["title"], f"{c['label']} · {k.get('priority', 'med').title()}", c["color"], urgent=is_overdue(iso, done), icon="check-circle" if done else "circle", done=done)
            b.clicked.connect(lambda _, kid=k["id"]: (self.accept(), win.open_anywhere(kid))); il.addWidget(b)
        if not rows: il.addWidget(QLabel("Nothing due this day.", objectName="muted"))
        il.addStretch(); sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(inner); sa.setFixedHeight(min(380, 46 * max(1, len(rows)) + 10)); v.addWidget(sa)
        v.addWidget(QLabel(f"{len(rows)} task(s) · Esc to close", objectName="muted"))


class PaletteDelegate(QStyledItemDelegate):
    """Paints command-palette rows: section captions, rounded accent selection with glow, vector icon, title, meta."""
    def sizeHint(self, opt, idx):
        d = idx.data(Qt.UserRole)
        return QSize(opt.rect.width(), 28 if d and d["kind"] == "head" else 42)

    def paint(self, p, opt, idx):
        d = idx.data(Qt.UserRole)
        if not d: return
        P = GLASS.p; p.save(); p.setRenderHint(QPainter.Antialiasing); r = QRectF(opt.rect).adjusted(2, 1, -2, -1)
        if d["kind"] == "head":
            f = QFont(opt.font); f.setPixelSize(max(9, f.pixelSize() - 2)); f.setWeight(QFont.DemiBold); f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
            p.setFont(f); p.setPen(QColor(P["text3"])); p.drawText(r.adjusted(12, 8, 0, 0), Qt.AlignLeft | Qt.AlignTop, d["text"].upper()); p.restore(); return
        sel = bool(opt.state & QStyle.State_Selected); hov = bool(opt.state & QStyle.State_MouseOver)
        path = rounded(r, RADIUS["control"])
        if sel:
            p.fillPath(path, qc(P["accent"], 0.24 if GLASS.dark else 0.16))
            g = QLinearGradient(r.left(), 0, r.right(), 0); g.setColorAt(0, qc(P["accent"], 0.26)); g.setColorAt(1, qc(P["accent"], 0)); p.fillPath(path, g)
            p.setPen(QPen(qc(P["accent"], 0.45), 1)); p.setBrush(Qt.NoBrush); p.drawPath(rounded(r.adjusted(.5, .5, -.5, -.5), RADIUS["control"] - .5))
        elif hov:
            p.fillPath(path, qc(P["text"], 0.06))
        icon_c = QColor(P["accent_text"] if sel else P["text"])
        draw_icon(p, d["icon"], QRectF(r.left() + 12, r.center().y() - 9, 18, 18), icon_c, 1.0 if sel else 0.65)
        meta_w = 0
        if d.get("meta"):
            f = QFont(opt.font); f.setPixelSize(max(9, f.pixelSize() - 1)); fm = QFontMetricsF(f)
            meta = fm.elidedText(d["meta"], Qt.ElideRight, r.width() * 0.4); meta_w = fm.horizontalAdvance(meta) + 16
            chip = QRectF(r.right() - meta_w - 8, r.center().y() - 10, meta_w, 20)
            p.setPen(Qt.NoPen); p.setBrush(qc(P["text"], 0.08)); p.drawRoundedRect(chip, 6, 6)
            p.setFont(f); p.setPen(QColor(P["text2"])); p.drawText(chip, Qt.AlignCenter, meta); meta_w += 12
        f = QFont(opt.font); f.setWeight(QFont.Medium if not sel else QFont.DemiBold); p.setFont(f); p.setPen(QColor(P["text"]))
        txt = QFontMetricsF(f).elidedText(d["text"], Qt.ElideRight, max(40, r.width() - 48 - meta_w - 12))
        p.drawText(QRectF(r.left() + 42, r.top(), r.width() - 48 - meta_w, r.height()), Qt.AlignVCenter | Qt.AlignLeft, txt)
        p.restore()


class Palette(GlassOverlay):
    """Ctrl+K: search tasks across every month and year, or run a command.  The app stays visible but blurred beneath."""
    def __init__(self, win):
        super().__init__(win, 660, 84); self.win = win; self.items = []
        v = self.body; v.setContentsMargins(12, 12, 12, 10)
        head = QHBoxLayout(); head.setSpacing(8); head.setContentsMargins(6, 0, 6, 0)
        ic = QLabel(); ic.setPixmap(make_icon("search", 20).pixmap(20, 20, QIcon.Active)); head.addWidget(ic)
        self.inp = QLineEdit(); self.inp.setPlaceholderText("Search tasks across every month, or type a command…"); self.inp.setStyleSheet("QLineEdit{border:none;background:transparent;font-size:16px;padding:8px 2px;}QLineEdit:focus{border:none;}")
        self.inp.textChanged.connect(self.render); self.inp.returnPressed.connect(self.run); self.inp.installEventFilter(self); head.addWidget(self.inp, 1)
        esc = QLabel("Esc"); esc.setStyleSheet(f"color:{C('text3')};border:1px solid {rgba(C('text'), 0.16)};border-radius:6px;padding:1px 7px;font-size:11px;"); head.addWidget(esc, 0, Qt.AlignVCenter); v.addLayout(head)
        v.addWidget(hline())
        self.list = QListWidget(); self.list.setFixedHeight(380); self.list.setMouseTracking(True); self.list.setItemDelegate(PaletteDelegate(self.list)); self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(lambda _: self.run()); self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        v.addWidget(self.list); v.addWidget(QLabel("↑↓ move  ·  Enter open  ·  Esc close  ·  tasks come from every month and year", objectName="muted"))
        self.render(""); QTimer.singleShot(60, self.inp.setFocus)

    def commands(self):
        w = self.win; mode = w.appearance.get("theme", "system")
        nxt = THEME_MODES[(THEME_MODES.index(mode) + 1) % 3] if mode in THEME_MODES else "dark"
        cmds = [("plus", "New task", "Ctrl N", lambda: w.add_task()), ("bolt", "Quick add", "!high #label @fri", w.open_quick_add),
                ("dashboard", "Go to Dashboard", "Alt 1", lambda: w.show_page("dashboard")), ("board", "Go to Task Board", "Alt 2", lambda: w.show_page("kanban")),
                ("list", "Go to Task List", "Alt 3", lambda: w.show_page("list")), ("calendar", "Go to Calendar", "Alt 4", lambda: w.show_page("calendar")),
                ("target", "Jump to today", f"{MONTHS_LONG[dt.date.today().month - 1]} {dt.date.today().year}", w.go_today),
                ({"system": "system", "light": "sun", "dark": "moon"}[nxt], f"Theme: switch to {nxt}", "", w.cycle_theme),
                ("menu", "Collapse / expand sidebar", "Ctrl B", w.toggle_sidebar),
                ("report", "Generate performance report (Word)", "", w.open_report), ("bolt", "Toggle auto-priority by due date", "on" if w.auto_prio_on() else "off", lambda: (w.set_auto_prio(not w.auto_prio_on()), w.toast("Auto-priority " + ("on" if w.auto_prio_on() else "off"), 1800, "bolt"))), ("download", "Export to Excel", "", w.export_excel), ("rollover", "Month rollover", "", w.open_rollover), ("tag", "Manage labels", "", w.manage_labels), ("palette", "Appearance", "", w.open_appearance),
                ("backup", "Backup now", "Ctrl Shift B", w.backup_now_ui), ("backup", "Backup & restore", "", w.open_backup), ("keyboard", "Keyboard shortcuts", "?", w.open_shortcuts)]
        cmds += [("calendar", f"Open {ml} {w.store.year}", "Switch month", lambda i=i: w.switch_month(i)) for i, ml in enumerate(MONTHS_LONG)]
        return [dict(kind="cmd", icon=i, text=t, meta=m, run=r) for i, t, m, r in cmds]

    def tasks(self, q):
        w = self.win; s = w.store; cur = (s.year, s.month); out = []
        def score(title, desc="", subs=()):
            t = title.lower()
            if not q: return 1
            return 4 if t.startswith(q) else 3 if q in t else 2 if q in desc.lower() else 1 if any(q in x.get("text", "").lower() for x in subs) else 0
        for y in s.years():
            for mi in range(12):
                for c in s.columns:
                    for k in s.kanban(mi, y).get(c["id"], []):
                        sc = score(k.get("title", ""), k.get("desc", ""), k.get("subs", []))
                        if sc: out.append(dict(kind="task", icon="check-circle" if k.get("done") else "circle", text=k["title"], meta=f"{MONTHS[mi]} {y} · {c['label']}", score=sc + 0.5 * ((y, mi) == cur) + 0.2 * (not k.get("done")),
                                              ts=k.get("updatedAt") or k.get("createdAt") or "", run=lambda y=y, mi=mi, kid=k["id"], cid=c["id"]: w.goto(y, mi, "kanban", lambda: w.open_detail(kid, cid))))
        out.sort(key=lambda i: i["ts"], reverse=True); out.sort(key=lambda i: -i["score"]); return out

    def render(self, q):
        raw = q.strip(); q = raw.lower(); self.list.clear(); tasks = self.tasks(q)
        cmds = [c for c in self.commands() if q in c["text"].lower()] if q else self.commands()
        groups = [("Commands", cmds), ("Tasks", tasks[:40])] if q else [("Recent tasks", tasks[:8]), ("Commands", cmds)]
        rows = []
        for name, its in groups:
            if its: rows.append(dict(kind="head", text=name)); rows += its
        if q and not (cmds or tasks): rows = [dict(kind="cmd", icon="plus", text=f"Create task “{raw}”", meta="in To Do", run=lambda t=raw: self.win.qa_submit("todo", t))]
        first = None
        for i, d in enumerate(rows):
            it = QListWidgetItem(); it.setData(Qt.UserRole, d)
            if d["kind"] == "head": it.setFlags(Qt.NoItemFlags)
            elif first is None: first = i
            self.list.addItem(it)
        self.items = rows
        if first is not None: self.list.setCurrentRow(first)

    def eventFilter(self, obj, e):
        if obj is self.inp and e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown): self.list.keyPressEvent(e); return True
        return super().eventFilter(obj, e)

    def run(self):
        it = self.list.currentItem(); d = it.data(Qt.UserRole) if it else None
        if d and d["kind"] != "head": self.accept(); d["run"]()


class ReportDialog(GlassDialog):
    """Monthly performance report → Word (list view, same structure as your own report).
    Step 1: month, cover details, AI.  Step 2: review and edit every statement, then export."""
    FIELDS = (("name", "Prepared by", "Your name"), ("code", "Employee code", "e.g. 8052"), ("appraiser", "Appraiser", "Reporting manager"),
              ("program", "Program", "Program / project name"), ("joined", "Joining date", "e.g. September 01, 2022"), ("classification", "Classification", "Internal"))

    def __init__(self, win):
        super().__init__(win); self.win = win; self.facts = None; self.narr = None; self.setWindowTitle("Monthly performance report"); self.setMinimumWidth(680)
        cfg = {"name": "", "code": "", "appraiser": "", "program": "", "joined": "", "classification": "Internal", "tone": "professional", "ai": True, "model": REPORT.DEFAULT_MODEL, "key": "", **win.settings.get("report", {})}; self.cfg = cfg
        root = QVBoxLayout(self); root.setSpacing(8); self.stack = QStackedWidget(); root.addWidget(self.stack)
        # ---- step 1
        p1 = QWidget(); v = QVBoxLayout(p1); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(8)
        v.addWidget(QLabel("Monthly performance report", objectName="sectitle")); v.addWidget(QLabel("A cover page, then your tasks as bullet lists under category headings (your labels). Sub-tasks appear as nested bullets; unfinished tasks show what is already done and what is pending.", objectName="muted2", wordWrap=True))
        r = QHBoxLayout(); self.month = QComboBox(); [self.month.addItem(f"{n}", i) for i, n in enumerate(REPORT.MONTHS_LONG)]
        self.year = QSpinBox(); self.year.setRange(2000, 2100); t = dt.date.today(); pm = (t.year, t.month - 1) if t.day > 10 else ((t.year, t.month - 2) if t.month > 1 else (t.year - 1, 11))
        self.year.setValue(pm[0]); self.month.setCurrentIndex(pm[1]); r.addWidget(QLabel("Month")); r.addWidget(self.month, 1); r.addWidget(self.year); v.addLayout(r)
        self.quick = QLabel(objectName="muted2", wordWrap=True); v.addWidget(self.quick); self.month.currentIndexChanged.connect(self._quick); self.year.valueChanged.connect(self._quick)
        v.addWidget(QLabel("COVER PAGE", objectName="navSection")); g = QGridLayout(); g.setHorizontalSpacing(10); self.fields = {}
        for i, (k, lab, ph) in enumerate(self.FIELDS):
            e = QLineEdit(cfg.get(k, "")); e.setPlaceholderText(ph); g.addWidget(QLabel(lab), i, 0); g.addWidget(e, i, 1); self.fields[k] = e
        self.tone = QComboBox(); [self.tone.addItem(txt, k) for k, txt in REPORT.TONES.items()]; self.tone.setCurrentIndex(max(0, self.tone.findData(cfg["tone"]))); g.addWidget(QLabel("Writing style"), len(self.FIELDS), 0); g.addWidget(self.tone, len(self.FIELDS), 1)
        v.addLayout(g)
        v.addWidget(QLabel("AI WRITING", objectName="navSection")); self.use_ai = QCheckBox("Write the statements with AI (Claude)"); self.use_ai.setChecked(bool(cfg["ai"])); v.addWidget(self.use_ai)
        self.ai_box = QWidget(); ag = QGridLayout(self.ai_box); ag.setContentsMargins(22, 0, 0, 0); self.key = QLineEdit(cfg["key"]); self.key.setEchoMode(QLineEdit.Password); self.key.setPlaceholderText("Anthropic API key  (or set the ANTHROPIC_API_KEY environment variable)")
        self.model = QLineEdit(cfg["model"]); ag.addWidget(QLabel("API key"), 0, 0); ag.addWidget(self.key, 0, 1); ag.addWidget(QLabel("Model"), 1, 0); ag.addWidget(self.model, 1, 1)
        note = QLabel("Privacy: only the selected month's task titles, notes, sub-tasks, dates and counts are sent to Anthropic's API to write the statements. Your name, employee code and other cover details stay on this PC. The key is saved in settings.json in plain text. Without a key — or if the AI is unreachable — an offline template writes the text instead. Tip: put a short note in a task's description (what it was for / the outcome) and the AI will use it.", objectName="muted", wordWrap=True)
        ag.addWidget(note, 2, 0, 1, 2); v.addWidget(self.ai_box); self.use_ai.toggled.connect(self.ai_box.setVisible); self.ai_box.setVisible(self.use_ai.isChecked())
        self.prog1 = GlowProgress(); self.prog1.hide(); v.addWidget(self.prog1); self.msg1 = QLabel(objectName="muted2", wordWrap=True); v.addWidget(self.msg1)
        b = QHBoxLayout(); b.addStretch(); c = QPushButton("Cancel"); c.clicked.connect(self.reject); self.go = QPushButton(" Generate preview"); self.go.setObjectName("primary"); self.go.setIcon(make_icon("bolt", 16, "#ffffff", dim=1.0)); self.go.clicked.connect(self.generate); b.addWidget(c); b.addWidget(self.go)
        sc1 = QScrollArea(); sc1.setWidgetResizable(True); sc1.setFrameShape(QFrame.NoFrame); sc1.setWidget(p1); sc1.setMinimumHeight(380)
        page1 = QWidget(); pv = QVBoxLayout(page1); pv.setContentsMargins(0, 0, 0, 0); pv.addWidget(sc1, 1); pv.addLayout(b); self.stack.addWidget(page1)       # buttons stay visible while the form scrolls
        scr = QApplication.primaryScreen(); self.setMaximumHeight(int(scr.availableGeometry().height() * 0.92)) if scr else None
        # ---- step 2
        p2 = QWidget(); v2 = QVBoxLayout(p2); v2.setContentsMargins(0, 0, 0, 0); v2.setSpacing(6); self.head2 = QLabel(objectName="sectitle"); v2.addWidget(self.head2); self.src = QLabel(objectName="muted2", wordWrap=True); v2.addWidget(self.src)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setMinimumHeight(420); inner = QWidget(); self.iv = QVBoxLayout(inner); self.iv.setContentsMargins(0, 0, 6, 0); self.edits = {}; self.stmt = {}
        for key, lab, h in (("overview", "OVERVIEW  (one bullet per line)", 84), ("challenges", "CHALLENGES AND OBSERVATIONS", 70), ("next_focus", "PLAN FOR NEXT MONTH", 70)):
            self.iv.addWidget(QLabel(lab, objectName="navSection")); e = QTextEdit(); e.setAcceptRichText(False); e.setFixedHeight(h); self.iv.addWidget(e); self.edits[key] = e
        self.stmt_box = QVBoxLayout(); self.iv.addLayout(self.stmt_box); self.iv.addStretch(); sc.setWidget(inner); v2.addWidget(sc, 1)
        self.prog2 = GlowProgress(); self.prog2.hide(); v2.addWidget(self.prog2)
        b2 = QHBoxLayout(); bk = QPushButton("Back"); bk.clicked.connect(lambda: self.stack.setCurrentIndex(0)); b2.addWidget(bk); b2.addStretch(); self.exp = QPushButton(" Export to Word…"); self.exp.setObjectName("primary"); self.exp.setIcon(make_icon("download", 16, "#ffffff", dim=1.0)); self.exp.clicked.connect(self.export); b2.addWidget(self.exp); v2.addLayout(b2)
        self.stack.addWidget(p2); self._quick()

    def _quick(self, *_):
        try:
            f = REPORT.collect(self.win.store, self.year.value(), self.month.currentData()); m = f["metrics"]
            self.quick.setText(f"{f['title']}:  {m['total']} tasks · {m['completed']} completed · {m['incomplete']} incomplete · {m['subs_done']}/{m['subs_total']} sub-tasks done" if m["total"] else f"{f['title']}: no tasks recorded for this month.")
        except Exception as e: self.quick.setText(f"Could not read this month: {e}")

    def _save_cfg(self):
        self.cfg.update({k: e.text().strip() for k, e in self.fields.items()}); self.cfg["classification"] = self.cfg["classification"] or "Internal"
        self.cfg.update(tone=self.tone.currentData(), ai=self.use_ai.isChecked(), model=self.model.text().strip() or REPORT.DEFAULT_MODEL, key=self.key.text().strip())
        st = read_settings(); st["report"] = self.cfg; write_settings(st); self.win.settings["report"] = dict(self.cfg)

    def generate(self):
        self._save_cfg(); c = self.cfg; self.facts = REPORT.collect(self.win.store, self.year.value(), self.month.currentData())
        if not self.facts["metrics"]["total"]: self.msg1.setText("There are no tasks in that month to report on."); return
        key = c["key"] or os.environ.get("ANTHROPIC_API_KEY", ""); facts = self.facts; self.go.setEnabled(False); self.prog1.show(); self.prog1.setIndeterminate()
        def work(prog):
            prog(0.1, "Collecting your tasks…")
            if c["ai"] and key:
                try: return REPORT.ai_narrative(facts, api_key=key, model=c["model"], tone=c["tone"], progress=prog)
                except REPORT.ReportAIError as e: n = REPORT.template_narrative(facts, c["tone"]); n["ai_error"] = str(e); return n
            n = REPORT.template_narrative(facts, c["tone"])
            if c["ai"]: n["ai_error"] = "No API key set"
            return n
        self.msg1.setText("Writing…"); run_job(work, self._ready, lambda m: (self._fail(m)), lambda f, m: (self.msg1.setText(m), None)[1])

    def _fail(self, m):
        self.go.setEnabled(True); self.prog1.hide(); self.msg1.setText("Something went wrong: " + m)

    def _ready(self, narr):
        self.narr = narr; self.go.setEnabled(True); self.prog1.hide(); self.msg1.setText(""); f = self.facts; ai_ok = narr.get("source") == "ai"
        self.head2.setText(f"{f['title']} — review the wording")
        self.src.setText((f"✓ Written by AI ({narr.get('model')}). Review every line — the AI only phrases your data, but you are signing this report." if ai_ok else
                          "Written by the offline template" + (f" — AI unavailable: {narr['ai_error']}." if narr.get("ai_error") else ".") + " Edit freely."))
        self.src.setStyleSheet(f"color:{C('ok') if ai_ok else C('text2')};")
        for k, e in self.edits.items(): e.setPlainText("\n".join(narr.get(k, [])))
        MainWindow._clear(self.stmt_box); self.stmt = {}
        cap = 250
        for title, key, tasks in (("COMPLETED TASKS", "completed", f["completed"]), ("IN PROGRESS / CARRIED FORWARD", "incomplete", f["incomplete"])):
            if not tasks: continue
            self.stmt_box.addWidget(QLabel(f"{title}  ·  one statement per task", objectName="navSection"))
            for t in tasks[:cap]:
                e = QLineEdit(narr[key].get(t["id"], "")); e.setCursorPosition(0); e.setToolTip(", ".join(t["labels"]) or "no label"); self.stmt_box.addWidget(e); self.stmt[(key, t["id"])] = e
            if len(tasks) > cap: self.stmt_box.addWidget(QLabel(f"+{len(tasks) - cap} more tasks use their generated statements.", objectName="muted"))
        self.stack.setCurrentIndex(1)

    def export(self):
        n = dict(self.narr); f = self.facts
        for k, e in self.edits.items(): n[k] = [x.strip() for x in e.toPlainText().splitlines() if x.strip()]
        n["completed"], n["incomplete"] = dict(self.narr["completed"]), dict(self.narr["incomplete"])
        for (key, tid), e in self.stmt.items():
            if e.text().strip(): n[key][tid] = e.text().strip()
        default = os.path.join(os.path.expanduser("~"), "Documents" if os.path.isdir(os.path.join(os.path.expanduser("~"), "Documents")) else "", f"Performance_Report_{f['month_name']}_{f['year']}.docx")
        p, _ = QFileDialog.getSaveFileName(self, "Save performance report", default, "Word document (*.docx)")
        if not p: return
        meta = {k: self.cfg.get(k, "") for k, _, _ in self.FIELDS}; order = [l["name"] for l in self.win.store.labels]; self.exp.setEnabled(False); self.prog2.show(); self.prog2.setIndeterminate()
        def done(path): self.exp.setEnabled(True); self.prog2.hide(); self.accept(); self.win.toast("📄 Report saved: " + os.path.basename(path), 4000, "report"); self.win.open_path(path)
        def fail(m):
            self.exp.setEnabled(True); self.prog2.hide()
            QMessageBox.critical(self, "Could not create the Word file", ("The 'python-docx' package is missing — run:  pip install python-docx\n\n" if "docx" in m and "No module" in m else "") + m)
        run_job(lambda prog: REPORT.build_docx(p, f, n, meta, order), done, fail)


class ExportDialog(GlassDialog):
    def __init__(self, parent, store):
        super().__init__(parent); self.store = store; self.setWindowTitle("Export to Excel"); self.setMinimumWidth(460)
        v = QVBoxLayout(self); v.addWidget(QLabel(f"Select months to export ({store.year})", objectName="sectitle"))
        g = QGridLayout(); self.checks = []
        for i, m in enumerate(MONTHS):
            cb = QCheckBox(m); cb.setChecked(i == store.month)
            kd = store.kanban(i); has = any(kd.get(c["id"]) for c in store.columns)
            if has: cb.setText(m + " •")
            g.addWidget(cb, i // 4, i % 4); self.checks.append(cb)
        v.addLayout(g)
        r = QHBoxLayout()
        for txt, fn in (("All", lambda: [c.setChecked(True) for c in self.checks]), ("None", lambda: [c.setChecked(False) for c in self.checks]),
                        ("With data", lambda: [c.setChecked("•" in c.text()) for c in self.checks])):
            b = QPushButton(txt); b.clicked.connect(fn); r.addWidget(b)
        r.addStretch(); v.addLayout(r)
        self.inc_board = QCheckBox("Board tasks (with sub-tasks)"); self.inc_board.setChecked(True)
        self.inc_sum = QCheckBox("Month-wise summary sheet"); self.inc_sum.setChecked(True)
        self.inc_done = QCheckBox("Include completed tasks"); self.inc_done.setChecked(True)
        for cb in (self.inc_board, self.inc_sum, self.inc_done): v.addWidget(cb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); bb.button(QDialogButtonBox.Ok).setText("Export…"); bb.button(QDialogButtonBox.Ok).setObjectName("primary")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); v.addWidget(bb)

    def months(self):
        return [i for i, c in enumerate(self.checks) if c.isChecked()]


def export_excel(store, path, months, inc_board, inc_sum, inc_done, progress=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook(); wb.remove(wb.active)
    total = (len(months) if inc_board else 0) + (1 if inc_sum else 0) + 1; step = [0]
    def tick(msg):
        step[0] += 1
        if progress: progress(min(0.98, step[0] / total), msg)
    if progress: progress(0.02, "Preparing…")
    hdr = Font(bold=True, color="FFFFFF"); fill = PatternFill("solid", fgColor="2B3563"); title = Font(bold=True, size=13)
    lname = lambda c: ", ".join(l["name"] for l in store.labels if l["id"] in c.get("labels", []))
    if inc_board:
        for mi in months:
            ws = wb.create_sheet(f"{MONTHS[mi]}-Board"); ws.append([f"{APP_NAME} — Board Tasks — {MONTHS[mi]} {store.year}"]); ws["A1"].font = title
            kd = store.kanban(mi)
            for c in store.columns:
                cards = [x for x in kd.get(c["id"], []) if inc_done or not x.get("done")]
                if not cards or (c["id"] == "done" and not inc_done): continue
                ws.append([]); ws.append([f"{c.get('icon', '')} {c['label'].upper()}"]); ws.cell(ws.max_row, 1).font = Font(bold=True, color=c["color"].lstrip("#"))
                ws.append(["#", "Task Title", "Description", "Labels", "Priority", "Due Date", "Repeat", "Status", "Migrated From", "Sub-tasks", "Done/Total", "Created"])
                for cell in ws[ws.max_row]: cell.font = hdr; cell.fill = fill
                for n, x in enumerate(cards, 1):
                    subs = x.get("subs", []); sd = sum(1 for s in subs if s.get("done"))
                    ws.append([n, x["title"], x.get("desc", ""), lname(x), PRI_LABEL[x.get("priority", "med")], x.get("dueDate", ""), x.get("repeat", ""),
                               "Completed" if x.get("done") or c["id"] == "done" else c["label"], x.get("migratedFrom", ""),
                               " | ".join(("[✓] " if s.get("done") else "[ ] ") + s["text"] for s in subs), f"{sd}/{len(subs)}" if subs else "", (x.get("createdAt") or "")[:10]])
            for col, w in zip("ABCDEFGHIJKL", (4, 30, 28, 16, 10, 12, 10, 12, 13, 36, 10, 12)): ws.column_dimensions[col].width = w
            tick(f"{MONTHS[mi]} board")
    if inc_sum:
        ws = wb.create_sheet("Summary"); ws.append([f"{APP_NAME} — Month-wise Summary — {store.year}"]); ws["A1"].font = title; ws.append([])
        ws.append(["Month", "Year", "To Do", "Today's", "In Progress", "Completed", "Total", "Completion %"])
        for cell in ws[ws.max_row]: cell.font = hdr; cell.fill = fill
        ip = [c["id"] for c in store.columns if c["id"] not in ("todo", "today", "done")]
        for mi in range(12):
            kd = store.kanban(mi); todo, today, done = len(kd.get("todo", [])), len(kd.get("today", [])), len(kd.get("done", []))
            wip = sum(len(kd.get(i, [])) for i in ip); tot = todo + today + wip + done
            ws.append([MONTHS[mi], store.year, todo, today, wip, done, tot, f"{round(done / tot * 100) if tot else 0}%"])
    if inc_sum: tick("Summary")
    if not wb.sheetnames: wb.create_sheet("Empty").append(["Nothing selected"])
    if progress: progress(0.98, "Saving…")
    wb.save(path)
    if progress: progress(1.0, "Done")


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════
class MainWindow(GlassWindow, QMainWindow):
    def __init__(self, store):
        super().__init__(); self.glass_init(); self.store = store; self.setWindowTitle(APP_NAME); self.resize(1400, 880); self.setMinimumSize(980, 620)
        self.detail_ref = None; self.filter_q = ""; self.filter_pri = ""; self.filter_labels = set(); self.overlay = None
        self.filter_flags = set(); self.col_limit = {}; self.list_limit = {}
        self.settings = read_settings(); self.view = {"sort": "manual", "density": "comfortable", **self.settings.get("view", {})}; self.appearance = {**dict(theme="system", font="", size=13, text="", accent="", bg="", surface="", motion=True, glass="mica", tint={}), **self.settings.get("appearance", {}), **self.store.db["meta"].get("appearance_py", {})}
        self._sb_manual = self.settings.get("sidebar") in ("open", "closed")
        self._build(); self.apply_appearance(); self._tray(); self.show_page("dashboard")
        if self.settings.get("sidebar") == "closed": self.sidebar.set_expanded(False, animate=False)
        sh = QGuiApplication.styleHints()
        if hasattr(sh, "colorSchemeChanged"): sh.colorSchemeChanged.connect(self._on_system_scheme)       # follow OS dark/light live
        job_hub().count_changed.connect(self._on_jobs)
        if store.merged_count: QTimer.singleShot(800, lambda: self.toast(f"Checklist merged into the board: {store.merged_count} tasks now carry their group as a label. A backup of the old file was saved first.", 7000))
        moved = self.store.auto_migrate()
        if moved:
            self.toast(f"🔄 {moved} incomplete task(s) auto-moved to the next month"); self.refresh()
        self.backup_timer = QTimer(self); self.backup_timer.timeout.connect(lambda: self.store.backup_now()); self.backup_timer.start(30 * 60 * 1000)
        self._prio_day = dt.date.today(); self.prio_timer = QTimer(self); self.prio_timer.timeout.connect(self._prio_tick); self.prio_timer.start(10 * 60 * 1000)     # catches midnight while the app stays open
        QTimer.singleShot(1200, lambda: (self.run_auto_priority(all_months=True, announce=True), self.refresh()))
        free = lambda fn: (lambda: fn() if self.overlay is None else None)         # no shortcuts behind an open overlay
        QShortcut(QKeySequence("Ctrl+N"), self, activated=free(lambda: self.add_task()))
        QShortcut(QKeySequence("Ctrl+Shift+B"), self, activated=free(self.backup_now_ui))
        QShortcut(QKeySequence("Ctrl+K"), self, activated=free(self.open_palette))
        QShortcut(QKeySequence("Ctrl+B"), self, activated=free(self.toggle_sidebar))
        QShortcut(QKeySequence("["), self, activated=free(lambda: self.step_month(-1))); QShortcut(QKeySequence("]"), self, activated=free(lambda: self.step_month(1)))
        QShortcut(QKeySequence("?"), self, activated=free(self.open_shortcuts))
        for i, k in enumerate(("dashboard", "kanban", "list", "calendar")): QShortcut(QKeySequence(f"Alt+{i + 1}"), self, activated=free(lambda k=k: self.show_page(k)))

    # ---------- layout ----------
    def _build(self):
        root = QWidget(); self.setCentralWidget(root); h = QHBoxLayout(root); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)
        sb = self.sidebar = Sidebar(); sv = QVBoxLayout(sb); sv.setContentsMargins(0, 8, 0, 14); sv.setSpacing(2)
        sv.addWidget(Brand(sb, APP_NAME, "PLAN · DO · TRACK")); sv.addSpacing(8)
        sv.addWidget(SectionLabel(sb, "WORKSPACE")); self.nav_btns = {}
        for key, icon, txt in (("dashboard", "dashboard", "Dashboard"), ("kanban", "board", "Task Board"), ("list", "list", "Task List"), ("calendar", "calendar", "Calendar")):
            nb = NavButton(sb, icon, txt); nb.clicked.connect(lambda _, k=key: self.show_page(k)); sv.addWidget(nb); self.nav_btns[key] = nb
        sv.addSpacing(8); sv.addWidget(SectionLabel(sb, "TOOLS"))
        self.roll_btn = NavButton(sb, "rollover", "Month Rollover", checkable=False); self.roll_btn.clicked.connect(self.open_rollover); sv.addWidget(self.roll_btn)
        for icon, txt, fn, badge_txt in (("report", "Performance Report", self.open_report, ""), ("backup", "Backup & Restore", self.open_backup, ""), ("palette", "Appearance", self.open_appearance, ""), ("search", "Search", self.open_palette, "Ctrl K")):
            nb = NavButton(sb, icon, txt, checkable=False); nb.set_label(txt, badge_txt); nb.clicked.connect(lambda _, f=fn: f()); sv.addWidget(nb)
        sv.addStretch()
        self.period = QWidget(); pv = QVBoxLayout(self.period); pv.setContentsMargins(0, 0, 0, 0); pv.setSpacing(4)         # year switcher + month grid (hidden when collapsed)
        yr = QHBoxLayout(); yr.setContentsMargins(16, 0, 16, 2)
        pb = QPushButton(); pb.setObjectName("ghost"); ICONS.bind(pb, "chevron-left", 16); pb.clicked.connect(lambda: self.switch_year(-1)); self.year_lbl = QLabel(str(self.store.year)); self.year_lbl.setAlignment(Qt.AlignCenter); self.year_lbl.setStyleSheet("font-weight:700;font-size:15px;")
        nb2 = QPushButton(); nb2.setObjectName("ghost"); ICONS.bind(nb2, "chevron-right", 16); nb2.clicked.connect(lambda: self.switch_year(1)); yr.addWidget(pb); yr.addWidget(self.year_lbl, 1); yr.addWidget(nb2); pv.addLayout(yr)
        mg = QGridLayout(); mg.setContentsMargins(16, 0, 16, 0); mg.setSpacing(4); self.month_btns = []
        for i, m in enumerate(MONTHS):
            mb = QPushButton(m); mb.setObjectName("month"); mb.setCheckable(True); mb.clicked.connect(lambda _, i=i: self.switch_month(i)); mg.addWidget(mb, i // 3, i % 3); self.month_btns.append(mb)
        pv.addLayout(mg); sv.addWidget(self.period); sb.on_t = lambda t: self.period.setVisible(t > 0.55)
        h.addWidget(sb)
        main = QVBoxLayout(); main.setContentsMargins(0, 0, 0, 0); main.setSpacing(0)
        tb = QFrame(); tb.setObjectName("topbar"); tb.setFixedHeight(64); th = QHBoxLayout(tb); th.setContentsMargins(14, 0, 22, 0); th.setSpacing(8)
        self.menu_btn = QPushButton(); self.menu_btn.setObjectName("iconbtn"); self.menu_btn.setToolTip("Collapse / expand sidebar  (Ctrl B)"); ICONS.bind(self.menu_btn, "menu", 20); self.menu_btn.clicked.connect(self.toggle_sidebar)
        self.page_title = QLabel("Dashboard"); self.page_title.setObjectName("pageTitle"); self.page_month = QLabel(); self.page_month.setObjectName("pageMonth"); self.page_month.setMargin(6)
        th.addWidget(self.menu_btn); th.addSpacing(4); th.addWidget(self.page_title); th.addWidget(self.page_month, 0, Qt.AlignVCenter); th.addStretch()
        self.search_pill = SearchPill("Search or run a command…", "Ctrl K"); self.search_pill.clicked.connect(self.open_palette); th.addWidget(self.search_pill); th.addSpacing(6)
        self.theme_btn = QPushButton(); self.theme_btn.setObjectName("iconbtn"); self.theme_btn.clicked.connect(self.cycle_theme); ICONS.bind(self.theme_btn, "moon", 20)
        ex = QPushButton(" Export"); ex.setToolTip("Export to Excel"); ICONS.bind(ex, "download", 16); ex.clicked.connect(self.export_excel)
        ad = QPushButton(" Add Task"); ad.setObjectName("primary"); ad.setToolTip("New task (Ctrl N)"); ad.setIcon(make_icon("plus", 16, "#ffffff", dim=1.0)); ad.setIconSize(QSize(16, 16)); ad.clicked.connect(lambda: self.add_task()); add_glow(ad)
        th.addWidget(self.theme_btn); th.addWidget(ex); th.addWidget(ad); main.addWidget(tb)
        self.stack = QStackedWidget(); main.addWidget(self.stack, 1)
        self.pages = {}
        for key, build in (("dashboard", self._build_dashboard), ("kanban", self._build_board), ("list", self._build_list), ("calendar", self._build_calendar)):
            self.pages[key] = build(); self.stack.addWidget(self.pages[key])
        w = QWidget(); w.setLayout(main); h.addWidget(w, 1); self.topbar = tb
        # detail dock
        self.dock = QDockWidget("Task", self); self.dock.setAllowedAreas(Qt.RightDockWidgetArea); self.dock.setFeatures(QDockWidget.DockWidgetClosable); self.dock.setMinimumWidth(440)
        self.detail = QFrame(); self.detail.setObjectName("detail"); self.detail_layout = QVBoxLayout(self.detail); self.dock.setWidget(self.detail); self.addDockWidget(Qt.RightDockWidgetArea, self.dock); self.dock.hide()
        self.dock.visibilityChanged.connect(lambda vis: setattr(self, "detail_ref", None) if not vis else None); self.overlay_disable = (self.dock,)
        self.toast_lbl = Toast(self); self.job_toast = Toast(self); self.job_toast.set_job(True)
        self._toast_timer = QTimer(self); self._toast_timer.setSingleShot(True); self._toast_timer.timeout.connect(self.toast_lbl.hide)
        self.activity = GlowProgress(thin=True); self.activity.setParent(root); self.activity.hide()          # thin neon line under the top bar while jobs run

    def _scroll(self, inner):
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(inner); return sa

    def _build_dashboard(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(10, 8, 10, 12); v.setSpacing(0)
        self.kpi_row = QHBoxLayout(); self.kpi_row.setSpacing(-4); v.addLayout(self.kpi_row)
        row = QHBoxLayout(); row.setSpacing(-4); v.addLayout(row, 1)
        pad = lambda lay: lay.setContentsMargins(18, 14, 18, 16)
        p0 = GlassFrame(elev=2, radius=RADIUS["panel"]); l0 = QVBoxLayout(p0); pad(l0); hr = QHBoxLayout(); hr.addWidget(QLabel("Needs attention", objectName="sectitle")); self.attn_sub = QLabel(objectName="muted"); hr.addStretch(); hr.addWidget(self.attn_sub); l0.addLayout(hr)
        self.attn_box = QVBoxLayout(); self.attn_box.setSpacing(4); l0.addLayout(self.attn_box); l0.addStretch()
        l0.addWidget(QLabel("Open tasks by priority", objectName="muted")); self.pri_mix = PriMix(); l0.addWidget(self.pri_mix); self.pri_legend = QLabel(objectName="muted"); l0.addWidget(self.pri_legend); row.addWidget(p0, 3)
        p1 = GlassFrame(elev=2, radius=RADIUS["panel"]); l1 = QVBoxLayout(p1); pad(l1); l1.addWidget(QLabel("Recent Activity", objectName="sectitle")); self.activity_box = QVBoxLayout(); self.activity_box.setSpacing(4); l1.addLayout(self.activity_box); l1.addStretch(); row.addWidget(p1, 3)
        p2 = GlassFrame(elev=2, radius=RADIUS["panel"]); l2 = QVBoxLayout(p2); pad(l2); l2.addWidget(QLabel("Tasks / Month", objectName="sectitle"))
        self.chart = BarChart(lambda: [sum(len(self.store.kanban(i).get(c["id"], [])) for c in self.store.columns) for i in range(12)]); self.chart.clicked.connect(self.switch_month); l2.addWidget(self.chart); l2.addWidget(QLabel("Click a bar to open that month", objectName="muted"))
        l2.addSpacing(8); l2.addWidget(hline()); l2.addSpacing(4); wr = QHBoxLayout(); wr.addWidget(QLabel("Next 7 days", objectName="sectitle")); wr.addStretch(); self.week_sub = QLabel(objectName="muted"); wr.addWidget(self.week_sub); l2.addLayout(wr)
        self.week = WeekAhead(self._week_days); self.week.clicked.connect(lambda: self.show_page("calendar")); l2.addWidget(self.week); l2.addStretch(); row.addWidget(p2, 2)
        return self._scroll(w)

    def _week_days(self):
        """(weekday, day-of-month, open tasks due, is_today, overdue) for today + the next 6 days."""
        s = self.store; today = dt.date.today(); out = []; years = set(s.years())
        for i in range(7):
            d = today + dt.timedelta(i); iso = d.isoformat(); n = 0
            if d.year in years:
                kd = s.kanban(d.month - 1, d.year)
                n = sum(1 for c in s.columns if c["id"] != "done" for x in kd.get(c["id"], []) if x.get("dueDate") == iso and not x.get("done"))
            out.append((DOW[d.weekday()][:3].title(), d.day, n, i == 0, False))
        return out

    def _build_board(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(24, 14, 24, 14); v.setSpacing(12)
        tbar = QHBoxLayout(); self.search = QLineEdit(); self.search.setPlaceholderText("Search tasks…"); self.search.setMinimumWidth(160); self.search.setMaximumWidth(260); self.search.textChanged.connect(self.on_search)
        self.pri_filter = QComboBox(); self.pri_filter.setMinimumWidth(140); self.pri_filter.addItem("All priorities", "")
        for k, lab in PRI_LABEL.items(): self.pri_filter.addItem(lab, k)
        self.pri_filter.currentIndexChanged.connect(lambda: (setattr(self, "filter_pri", self.pri_filter.currentData()), self.render_board()))
        self.label_bar = QHBoxLayout(); tbar.addWidget(self.search); tbar.addWidget(self.pri_filter); tbar.addLayout(self.label_bar); tbar.addStretch()
        lb = QPushButton(" Labels"); ICONS.bind(lb, "tag", 16); lb.clicked.connect(self.manage_labels); cb = QPushButton(" Column"); ICONS.bind(cb, "plus", 16); cb.clicked.connect(lambda: self.column_dialog(None)); tbar.addWidget(lb); tbar.addWidget(cb); v.addLayout(tbar)
        t2 = QHBoxLayout(); t2.setSpacing(6); t2.addWidget(QLabel("Quick filters", objectName="muted")); self.flag_btns = {}
        for key, txt in (("overdue", "Overdue"), ("week", "Due ≤ 7 days"), ("high", "High priority")):
            b = QPushButton(txt); b.setCheckable(True); b.setObjectName("chip"); b.toggled.connect(lambda on, k=key: (self.filter_flags.add(k) if on else self.filter_flags.discard(k), self.col_limit.clear(), self.render_board())); t2.addWidget(b); self.flag_btns[key] = b
        t2.addStretch(); t2.addWidget(QLabel("Sort", objectName="muted")); self.sort_box = QComboBox()
        for k, t in (("manual", "Manual order"), ("due", "Due date"), ("priority", "Priority"), ("newest", "Newest first")): self.sort_box.addItem(t, k)
        self.sort_box.setCurrentIndex(max(0, self.sort_box.findData(self.view["sort"]))); self.sort_box.currentIndexChanged.connect(self._view_changed); t2.addWidget(self.sort_box)
        self.dens_btn = QPushButton(" Compact"); self.dens_btn.setCheckable(True); self.dens_btn.setChecked(self.view["density"] == "compact"); self.dens_btn.setToolTip("Compact cards: title + due date only — best with hundreds of tasks"); ICONS.bind(self.dens_btn, "list", 16); self.dens_btn.toggled.connect(self._view_changed); t2.addWidget(self.dens_btn); v.addLayout(t2)
        self.board_host = QWidget(); self.board_layout = QHBoxLayout(self.board_host); self.board_layout.setContentsMargins(0, 0, 0, 0); self.board_layout.setSpacing(12); self.board_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        sa = QScrollArea(); sa.setWidgetResizable(True); sa.setWidget(self.board_host); v.addWidget(sa, 1)
        return w

    def _build_list(self):
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(24, 14, 24, 14); v.setSpacing(12); tb = QHBoxLayout()
        tb.addWidget(QLabel("Group by", objectName="muted")); self.list_group = QComboBox()
        for k, t in (("column", "Column"), ("due", "Due date"), ("label", "Label"), ("priority", "Priority")): self.list_group.addItem(t, k)
        self.list_group.currentIndexChanged.connect(self._list_changed); tb.addWidget(self.list_group)
        self.list_search = QLineEdit(); self.list_search.setPlaceholderText("Search tasks…"); self.list_search.setFixedWidth(240); self.list_search.textChanged.connect(self._list_changed); tb.addWidget(self.list_search)
        self.list_hide_done = QCheckBox("Hide completed"); self.list_hide_done.toggled.connect(self._list_changed); tb.addWidget(self.list_hide_done)
        self.list_stat = QLabel(objectName="muted"); tb.addWidget(self.list_stat); tb.addStretch(); tb.addWidget(QLabel("Same tasks as the board · tick = done · click a row to open", objectName="muted")); v.addLayout(tb)
        self.list_host = QWidget(); self.list_layout = QVBoxLayout(self.list_host); self.list_layout.setAlignment(Qt.AlignTop); self.list_layout.setSpacing(0); v.addWidget(self._scroll(self.list_host), 1); return w

    def _build_calendar(self):
        self.cal_mode = "month"; self.cal_anchor = dt.date.today()
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(24, 14, 24, 14); v.setSpacing(12); tb = QHBoxLayout(); tb.setSpacing(6)
        for icon, fn, tip in (("chevron-left", lambda: self.cal_step(-1), "Previous  [ "), ("chevron-right", lambda: self.cal_step(1), "Next  ] ")):
            b = QPushButton(); b.setObjectName("iconbtn"); b.setToolTip(tip); ICONS.bind(b, icon, 18); b.clicked.connect(fn); tb.addWidget(b)
        tdy = QPushButton("Today"); tdy.setToolTip("Jump to today"); tdy.clicked.connect(self.cal_today); tb.addWidget(tdy)
        self.cal_title = QLabel(); self.cal_title.setObjectName("sectitle"); self.cal_title.setStyleSheet("font-size:17px;"); tb.addSpacing(6); tb.addWidget(self.cal_title); tb.addSpacing(10)
        grp = QButtonGroup(w); self.cal_mode_btns = {}
        for k, t in (("month", "Month"), ("week", "Week")):
            b = QPushButton(t); b.setCheckable(True); b.setObjectName("chip"); b.setChecked(k == "month"); grp.addButton(b); b.clicked.connect(lambda _, k=k: self.cal_set_mode(k)); tb.addWidget(b); self.cal_mode_btns[k] = b
        self.cal_hide_done = QCheckBox("Hide completed"); self.cal_hide_done.toggled.connect(lambda _: self.render_calendar()); tb.addSpacing(8); tb.addWidget(self.cal_hide_done)
        self.cal_stat = QLabel(objectName="muted"); tb.addSpacing(8); tb.addWidget(self.cal_stat); tb.addStretch()
        tb.addWidget(QLabel("Drag to reschedule · ● high priority", objectName="muted")); v.addLayout(tb)
        row = QHBoxLayout(); row.setSpacing(14); gw = QWidget(); self.cal_grid = QGridLayout(gw); self.cal_grid.setSpacing(6); self.cal_grid.setAlignment(Qt.AlignTop); row.addWidget(self._scroll(gw), 1)
        sw = QWidget(); self.cal_side = QVBoxLayout(sw); self.cal_side.setContentsMargins(0, 0, 0, 0); self.cal_side.setAlignment(Qt.AlignTop); ss = self._scroll(sw); ss.setFixedWidth(260); row.addWidget(ss); v.addLayout(row, 1); return w

    # ---------- tray ----------
    def _tray(self):
        pm = QPixmap(64, 64); pm.fill(Qt.transparent); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); g = QLinearGradient(4, 4, 60, 60); g.setColorAt(0, QColor(VIOLET)); g.setColorAt(1, QColor(CYAN)); p.setBrush(QBrush(g)); p.setPen(Qt.NoPen); p.drawRoundedRect(4, 4, 56, 56, 15, 15)
        draw_icon(p, "logo", QRectF(14, 14, 36, 36), QColor("#ffffff"), 1.0, 2.2); p.end()
        self.setWindowIcon(QIcon(pm)); self.tray = QSystemTrayIcon(QIcon(pm), self); m = QMenu()
        m.addAction(f"Open {APP_NAME}", self.show_window); m.addAction("Minimize to tray", self.hide); m.addSeparator(); m.addAction("Backup Data Now", self.backup_now_ui)
        m.addAction("Open Backup Folder", lambda: self.open_path(get_backup_dir())); m.addAction("Open Data Folder", lambda: self.open_path(USER_DATA)); m.addSeparator()
        self.close_to_tray_act = QAction("Keep running in tray when window is closed", m, checkable=True); self.close_to_tray_act.setChecked(bool(self.settings.get("close_to_tray", False)))
        self.close_to_tray_act.toggled.connect(self.set_close_to_tray); m.addAction(self.close_to_tray_act); m.addAction("Quit", self.quit_app)
        self.tray.setContextMenu(m); self.tray.activated.connect(lambda r: self.show_window() if r in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger) else None); self.tray.setToolTip(APP_NAME); self.tray.show()
        self.quitting = False; self._last_close = 0; self._hint_shown = False

    def set_close_to_tray(self, on):
        self.settings["close_to_tray"] = bool(on); st = read_settings(); st["close_to_tray"] = bool(on); write_settings(st)

    def show_window(self):
        self.show(); self.raise_(); self.activateWindow()

    def quit_app(self):
        self.quitting = True; self.store.save(); self.store.backup_now(); QApplication.quit()

    def closeEvent(self, e):
        if self.quitting: e.accept(); return
        if not self.settings.get("close_to_tray", False) or time.time() - self._last_close < 3:
            self.quitting = True; self.store.save(); QThreadPool.globalInstance().waitForDone(4000); self.store.backup_now(); e.accept(); QApplication.quit(); return
        self._last_close = time.time(); e.ignore(); self.hide()
        if not self._hint_shown:
            self._hint_shown = True; self.tray.showMessage(APP_NAME, "Still running in the system tray. Right-click the tray icon and choose Quit to exit.")

    @staticmethod
    def open_path(p):
        try:
            if sys.platform.startswith("win"): os.startfile(p)
            elif sys.platform == "darwin": os.system(f'open "{p}"')
            else: os.system(f'xdg-open "{p}" &')
        except Exception:
            pass

    # ---------- helpers ----------
    def toast(self, msg, ms=2600, icon="check-circle"):
        t = self.toast_lbl; t.setText(msg, icon); t.adjustSize(); self._place_toast(); t.show(); t.raise_()
        if self.motion():       # spring up from just below its resting spot
            end = t.pos(); self.animate(t, b"pos", end + QPoint(0, 26), end, 360, spring_curve(1.5))
        self._toast_timer.start(ms)

    def start_job(self, label, fn, done_msg=None, on_done=None, icon="download"):
        """Run fn(progress) on a worker thread with a glowing progress toast; the UI never blocks."""
        jt = self.job_toast; jt.set_job(True); jt.setText(label + "…", icon); jt.bar.setIndeterminate(); jt.adjustSize(); self._place_toast(); jt.show(); jt.raise_()
        def prog(frac, msg=""):
            jt.setText(f"{label} — {msg}" if msg else label + "…"); jt.adjustSize(); self._place_toast(); jt.bar.setValue(frac)
        def fin(res):
            jt.bar.setValue(1.0); QTimer.singleShot(420, jt.hide)
            if done_msg: self.toast(done_msg.format(res=res) if isinstance(done_msg, str) else done_msg(res))
            if on_done: on_done(res)
        def err(msg):
            jt.hide(); QMessageBox.critical(self, f"{label} failed", msg)
        run_job(fn, fin, err, prog)

    def _on_jobs(self, n):
        self.activity.setVisible(n > 0)
        if n > 0: self.activity.setIndeterminate(); self._place_toast(); self.activity.raise_()

    def motion(self):
        return bool(self.appearance.get("motion", True))

    def animate(self, target, prop, start, end, ms=260, easing=QEasingCurve.OutCubic, on_value=None, on_done=None):
        """One helper for every transition: QVariantAnimation calling on_value(v), or QPropertyAnimation on `prop`.
        The animation is a child of `target`, so a re-render that deletes the widget also stops the animation."""
        for old in target.findChildren(QAbstractAnimation): old.stop()      # one animation per target at a time
        if not self.motion():       # jump straight to the final state
            on_value(end) if on_value else target.setProperty(prop, end)
            if on_done: on_done()
            return None
        a = QVariantAnimation(target) if on_value else QPropertyAnimation(target, prop, target)
        a.setStartValue(start); a.setEndValue(end); a.setDuration(ms); a.setEasingCurve(easing)
        if on_value: a.valueChanged.connect(on_value)
        if on_done: a.finished.connect(on_done)
        a.start(QAbstractAnimation.DeleteWhenStopped); return a

    def fade_in(self, w, ms=180):
        if not self.motion(): return
        eff = QGraphicsOpacityEffect(w); w.setGraphicsEffect(eff)
        self.animate(eff, b"opacity", 0.0, 1.0, ms, QEasingCurve.OutQuad, on_done=lambda: w.setGraphicsEffect(None))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast_lbl.isVisible() or self.job_toast.isVisible(): self._place_toast()
        if not self._sb_manual:         # responsive: below ~1100px the sidebar folds into an icon rail
            want = self.width() >= 1100
            if want != self.sidebar.expanded: self.sidebar.set_expanded(want)

    def _place_toast(self):
        c = self.centralWidget().geometry(); y = c.bottom() - 4
        for t in (self.toast_lbl, self.job_toast):
            if t.isVisible(): y -= t.height() - 8; t.move(c.right() - t.width() + 8, y)
        self.activity.setGeometry(self.sidebar.width(), self.topbar.height(), max(0, self.centralWidget().width() - self.sidebar.width()), 4)

    def toggle_sidebar(self):
        self._sb_manual = True; on = not self.sidebar.expanded; self.sidebar.set_expanded(on)
        st = read_settings(); st["sidebar"] = "open" if on else "closed"; write_settings(st); self.settings["sidebar"] = st["sidebar"]

    def _prio_tick(self):
        if dt.date.today() != self._prio_day:
            self._prio_day = dt.date.today()
            if self.run_auto_priority(all_months=True, announce=True): self.refresh()

    def open_palette(self):
        if self.overlay is None: Palette(self).exec()

    def open_report(self):
        ReportDialog(self).exec()

    def open_quick_add(self, col_id="todo"):
        if self.overlay is None: QuickAdd(self, col_id).exec()

    def show_page(self, key):
        changed = getattr(self, "page", None) != key; self.page = key
        for k, b in self.nav_btns.items(): b.setChecked(k == key)
        self.stack.setCurrentWidget(self.pages[key]); self.page_title.setText({"dashboard": "Dashboard", "kanban": "Task Board", "list": "Task List", "calendar": "Calendar"}[key]); self.refresh()
        if changed: self.fade_in(self.pages[key])

    def refresh(self):
        if getattr(self, "_in_refresh", False): return
        self.run_auto_priority()
        s = self.store; self.page_month.setText(f"{MONTHS_LONG[s.month]} {s.year}"); self.year_lbl.setText(str(s.year))
        for i, b in enumerate(self.month_btns): b.setChecked(i == s.month)
        kd = s.kanban(); n = sum(len(kd.get(c["id"], [])) for c in s.columns); nopen = sum(1 for c in s.columns if c["id"] != "done" for x in kd.get(c["id"], []) if not x.get("done"))
        self.nav_btns["kanban"].set_label("Task Board", str(n)); self.nav_btns["list"].set_label("Task List", str(nopen))
        self.overdue_n = sum(1 for c in s.columns if c["id"] != "done" for x in kd.get(c["id"], []) if is_overdue(x.get("dueDate"), x.get("done")))
        self.nav_btns["calendar"].set_label("Calendar", str(self.overdue_n) if self.overdue_n else "", hot=bool(self.overdue_n))
        self.roll_btn.set_label("Month Rollover", "!" if s.pending_rollover() else "", hot=True)
        {"dashboard": self.render_dashboard, "kanban": self.render_board, "list": self.render_list, "calendar": self.render_calendar}[self.page]()
        if self.detail_ref: self.render_detail()

    def switch_month(self, i):
        self.store.month = i; self.close_detail(); self.refresh()

    def switch_year(self, d):
        ys = self.store.years(); ry = dt.date.today().year; lo, hi = min(ys[0] if ys else ry, ry - 1), max(ys[-1] if ys else ry, ry + 1)
        ny = self.store.year + d
        if lo <= ny <= hi: self.store.year = ny; self.store.ensure_year(ny); self.close_detail(); self.refresh()
        else: self.toast(f"Years available: {lo} – {hi}")

    def step_month(self, d):
        nm = self.store.month + d
        if 0 <= nm <= 11: self.switch_month(nm); return
        before = self.store.year; self.switch_year(d)
        if self.store.year != before: self.switch_month(11 if nm < 0 else 0)

    def go_today(self):
        t = dt.date.today(); self.store.year = t.year; self.store.ensure_year(t.year); self.switch_month(t.month - 1)

    def goto(self, year, mi, page, then=None):
        """Palette: jump to a task's month/year, open its page, then run `then` (e.g. open the detail panel)."""
        self.store.year = year; self.store.ensure_year(year); self.store.month = mi; self.close_detail(); self.show_page(page)
        if then: then()

    def open_shortcuts(self):
        QMessageBox.information(self, "Keyboard shortcuts", "Ctrl K\tSearch & commands\nCtrl N\tNew task\n[  ]\tPrevious / next month\nAlt 1–4\tDashboard · Board · List · Calendar\n"
                                "Enter\tQuick-add: save task\nShift Enter\tQuick-add: open full form\nCtrl Enter\tSave the open form\n?\tThis sheet\nCtrl Shift B\tBackup now\n\n"
                                "Quick-add syntax:  !high / !low priority  ·  #label assigns (or creates) a label  ·  @today @tomorrow @fri @15 @+3 @2026-10-01 due date  ·  *daily *weekdays *weekly *monthly *yearly repeat")

    @staticmethod
    def _clear(layout):
        while layout.count():
            it = layout.takeAt(0)
            if it.widget(): w = it.widget(); w.hide(); w.setParent(None); w.deleteLater()
            elif it.layout(): MainWindow._clear(it.layout())

    # ---------- dashboard ----------
    def render_dashboard(self):
        s = self.store; kd = s.kanban(); self._clear(self.kpi_row); P = GLASS.p
        todo, today, done = len(kd.get("todo", [])), len(kd.get("today", [])), len(kd.get("done", []))
        wip = sum(len(kd.get(c["id"], [])) for c in s.columns if c["id"] not in ("todo", "today", "done")); total = todo + today + wip + done
        pct = round(done / total * 100) if total else 0
        overdue = self.overdue_n
        for lab, val, sub, color in (("TOTAL TASKS", total, f"{overdue} overdue" if overdue else "This month", P["accent"]), ("TODAY'S FOCUS", today, "Tasks for today", "#ffb347"),
                                     ("IN PROGRESS", wip, "Currently working", P["accent2"]), ("COMPLETED", done, f"{pct}% of month", P["ok"])):
            f = GlassFrame(elev=2, radius=RADIUS["panel"], hoverable=True, edge=color, edge_side="bottom"); fh = QHBoxLayout(f); fh.setContentsMargins(18, 12, 14, 16); fv = QVBoxLayout(); fv.setSpacing(2); fv.addWidget(QLabel(lab, objectName="kpiLabel")); vl = QLabel("0", objectName="kpiVal"); fv.addWidget(vl)
            sl = QLabel(sub); sl.setObjectName("muted")
            if "overdue" in sub: sl.setStyleSheet(f"color:{P['danger']};font-weight:600;")
            fv.addWidget(sl); fh.addLayout(fv, 1); self.kpi_row.addWidget(f)
            self.animate(vl, None, 0, val, 520, on_value=lambda n, l=vl: l.setText(str(int(n))))
            if lab == "COMPLETED":
                ring = Ring(color); fh.addWidget(ring, 0, Qt.AlignVCenter); self.animate(ring, None, 0.0, float(pct), 700, on_value=lambda x, r=ring: (setattr(r, "value", x), r.update()))
        self._clear(self.attn_box); items = []; today = dt.date.today()
        def days_to(iso):
            try: return (dt.date.fromisoformat(iso) - today).days
            except Exception: return None
        for c in s.columns:
            for k in kd.get(c["id"], []) if c["id"] != "done" else []:
                df = days_to(k["dueDate"]) if k.get("dueDate") and not k.get("done") else None
                if df is not None and df <= 7: items.append((df, k.get("priority") != "high", k["title"], c["color"], lambda cid=k["id"], col=c["id"]: (self.show_page("kanban"), self.open_detail(cid, col))))
        items.sort(key=lambda x: x[:2]); over = sum(1 for i in items if i[0] < 0)
        self.attn_sub.setText(f"{over} overdue · {len(items) - over} due this week" if items else "")
        if not items: self.attn_box.addWidget(QLabel("Nothing is overdue or due in the next 7 days. Add due dates to tasks and they show up here.", objectName="muted", wordWrap=True))
        for df, _, title, color, fn in items[:8]:
            when = f"{-df}d overdue" if df < 0 else "Today" if df == 0 else "Tomorrow" if df == 1 else (today + dt.timedelta(df)).strftime("%a") if df <= 6 else fmt_date((today + dt.timedelta(df)).isoformat())
            b = RowButton(title, when, color, urgent=df < 0); b.clicked.connect(lambda _, f=fn: f()); self.attn_box.addWidget(b)
        if len(items) > 8: self.attn_box.addWidget(QLabel(f"+{len(items) - 8} more in the calendar", objectName="muted"))
        open_ = [x for c in s.columns if c["id"] != "done" for x in kd.get(c["id"], [])]; n = {k: sum(1 for x in open_ if x.get("priority", "med") == k) for k in ("high", "med", "low")}
        self.pri_mix.counts = (n["high"], n["med"], n["low"]); self.pri_mix.update()
        self.pri_legend.setText(f"<b style='color:{T(PRI_COLOR['high'])}'>{n['high']}</b> high &nbsp; <b style='color:{T(PRI_COLOR['med'])}'>{n['med']}</b> medium &nbsp; <b style='color:{T(PRI_COLOR['low'])}'>{n['low']}</b> low" if open_ else "No open tasks")
        self._clear(self.activity_box)
        cards = [(x, c) for c in s.columns for x in kd.get(c["id"], [])]
        cards.sort(key=lambda t: t[0].get("updatedAt") or t[0].get("createdAt") or "", reverse=True)
        if not cards: self.activity_box.addWidget(QLabel("No tasks this month yet.", objectName="muted"))
        for x, c in cards[:6]:
            isdone = bool(x.get("done") or c["id"] == "done")
            b = RowButton(x["title"], f"{c['label']} · {x.get('priority', 'med').title()}", c["color"], icon="check-circle" if isdone else "circle", done=isdone)
            b.clicked.connect(lambda _, cid=x["id"], col=c["id"]: (self.show_page("kanban"), self.open_detail(cid, col))); self.activity_box.addWidget(b)
        self.chart.current = s.month; self.animate(self.chart, None, 0.0, 1.0, 600, on_value=lambda x: (setattr(self.chart, "progress", x), self.chart.update()))
        days = self._week_days(); nweek = sum(d[2] for d in days); self.week_sub.setText(f"{nweek} due" if nweek else "all clear")
        self.animate(self.week, None, 0.0, 1.0, 600, on_value=lambda x: (setattr(self.week, "progress", x), self.week.update()))

    # ---------- board ----------
    def on_search(self, t):
        self.filter_q = t.lower(); self.col_limit.clear(); self.render_board()

    PAGE, DONE_PAGE = 30, 10

    def _view_changed(self, *_):
        self.view["sort"] = self.sort_box.currentData(); self.view["density"] = "compact" if self.dens_btn.isChecked() else "comfortable"; self.col_limit.clear()
        st = read_settings(); st["view"] = self.view; write_settings(st); self.render_board()

    def sort_cards(self, cards):
        m = self.view["sort"]
        if m == "due": return sorted(cards, key=lambda c: (c.get("dueDate") or "9999", -PRI_RANK.get(c.get("priority", "med"), 1)))
        if m == "priority": return sorted(cards, key=lambda c: (-PRI_RANK.get(c.get("priority", "med"), 1), c.get("dueDate") or "9999"))
        if m == "newest": return sorted(cards, key=lambda c: c.get("createdAt") or "", reverse=True)
        return cards

    def card_matches(self, c):
        if self.filter_flags:
            done = c.get("done"); n = None
            try: n = (dt.date.fromisoformat(c["dueDate"]) - dt.date.today()).days if c.get("dueDate") else None
            except ValueError: pass
            if "overdue" in self.filter_flags and not (n is not None and n < 0 and not done): return False
            if "week" in self.filter_flags and not (n is not None and n <= 7 and not done): return False
            if "high" in self.filter_flags and c.get("priority") != "high": return False
        if self.filter_pri and c.get("priority") != self.filter_pri: return False
        if self.filter_labels and not self.filter_labels <= set(c.get("labels", [])): return False
        if self.filter_q:
            hay = " ".join([c.get("title", ""), c.get("desc", "")] + [s["text"] for s in c.get("subs", [])]).lower()
            if self.filter_q not in hay: return False
        return True

    def render_board(self):
        s = self.store; self._clear(self.label_bar)
        for l in s.labels:
            b = QPushButton(l["name"]); b.setCheckable(True); b.setChecked(l["id"] in self.filter_labels)
            b.setStyleSheet(f"QPushButton{{border-color:{l['color']};color:{T(l['color'])};padding:3px 10px;}}QPushButton:checked{{background:{l['color']};color:{readable_on(l['color'])};}}")
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            b.toggled.connect(lambda on, lid=l["id"]: (self.filter_labels.add(lid) if on else self.filter_labels.discard(lid), self.render_board())); self.label_bar.addWidget(b)
        self._clear(self.board_layout); kd = s.kanban()
        for col in s.columns:
            cw = QWidget(); cw.setMinimumWidth(176); cw.setMaximumWidth(380); cv = QVBoxLayout(cw); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(8)
            head = GlassFrame(elev=1, radius=RADIUS["card"], margins=(8, 3, 8, 6)); hh = QHBoxLayout(head); hh.setContentsMargins(12, 8, 8, 8)
            dot = QLabel("●"); dot.setStyleSheet(f"color:{col['color']};"); t = QLabel(f"{col.get('icon', '')} {col['label']}"); t.setStyleSheet("font-weight:700;")
            pal = self.palette_dict(); allc = kd.get(col["id"], []); cards = self.sort_cards([c for c in allc if self.card_matches(c)])
            limit = self.col_limit.get(col["id"], self.DONE_PAGE if col["id"] == "done" else self.PAGE); shown = cards[:limit]; hidden = len(cards) - len(shown)
            cnt = badge(str(len(allc)) if len(cards) == len(allc) else f"{len(cards)}/{len(allc)}", pal["text2"], pal["s4"]); mb = QPushButton(); mb.setObjectName("ghost"); mb.setIcon(make_icon("dots", 16)); mb.setIconSize(QSize(16, 16)); mb.setToolTip("Column options"); mb.setFixedWidth(30); mb.clicked.connect(lambda _, cid=col["id"]: self.column_dialog(cid))
            hh.addWidget(dot); hh.addWidget(t); hh.addStretch(); hh.addWidget(cnt); hh.addWidget(mb); cv.addWidget(head)
            lst = CardList(col["id"]); lst.dropped.connect(self.on_drop)
            if not kd.get(col["id"]):
                it = QListWidgetItem("📭  Empty"); it.setFlags(Qt.NoItemFlags); it.setTextAlignment(Qt.AlignCenter); lst.addItem(it)
            elif not cards:
                it = QListWidgetItem("🔍  No matches"); it.setFlags(Qt.NoItemFlags); it.setTextAlignment(Qt.AlignCenter); lst.addItem(it)
            compact = self.view["density"] == "compact"
            for c in shown:
                it = QListWidgetItem(); it.setData(Qt.UserRole, c["id"]); w = CardWidget(s, c, col, compact); it.setSizeHint(w.sizeHint()); lst.addItem(it); lst.setItemWidget(it, w)
                w.clicked.connect(self.open_detail); w.edit.connect(self.edit_task); w.delete.connect(self.delete_task); w.toggle.connect(self.toggle_done); w.context.connect(self.card_menu)
            if hidden > 0:
                step = self.PAGE; mb2 = QPushButton(f"Show {min(step, hidden)} more  ·  {hidden} hidden"); mb2.setObjectName("addk"); mb2.setCursor(QCursor(Qt.PointingHandCursor))
                mb2.clicked.connect(lambda _, cid=col["id"], lim=limit: (self.col_limit.__setitem__(cid, lim + step), self.render_board()))
                it = QListWidgetItem(); it.setFlags(Qt.ItemIsEnabled); it.setSizeHint(QSize(100, 44)); lst.addItem(it); lst.setItemWidget(it, mb2)
            lst.fit_items(); cv.addWidget(lst, 1)
            ab = QPushButton("+ Add Task"); ab.setObjectName("addk"); ab.setToolTip("New task in this column  ·  Ctrl K → Quick add for the !high #label @fri syntax"); ab.clicked.connect(lambda _, cid=col["id"]: self.add_task(cid)); cv.addWidget(ab); self.board_layout.addWidget(cw, 1)
        addc = QPushButton("+"); addc.setObjectName("addk"); addc.setFixedWidth(44); addc.setToolTip("Add column"); addc.clicked.connect(lambda: self.column_dialog(None)); self.board_layout.addWidget(addc, 0, Qt.AlignTop)

    def on_drop(self, cid, from_col, to_col, before):
        if before == cid: return
        if self.view["sort"] != "manual":                       # a sorted view has no manual order to drop into
            if from_col == to_col: return
            before = None
        card = self.store.move_card(cid, from_col, to_col, before)
        if card:
            self.store.save(); self.refresh()
            if self.detail_ref and self.detail_ref[0] == cid: self.detail_ref = (cid, to_col); self.render_detail()
            if card.pop("recurred", False): self.toast(f"↻ Done for now — next due {fmt_date(card['dueDate'])}")
            elif to_col == "done" and from_col != "done": self.toast("✅ Task completed!")

    def _create_card(self, col_id, title, priority="med", dueDate="", labels=None, desc="", subs=None, repeat="", repeatUntil=""):
        s = self.store; card = dict(id=uid(), title=title, desc=desc, priority=priority, dueDate=dueDate, done=col_id == "done", subs=subs or [], labels=labels or [],
                                    repeat=repeat, repeatUntil=repeatUntil, comments=[], activity=[], createdAt=now_iso(), month=MONTHS[s.month], year=s.year)
        s.log(card, f"Created in {s.col(col_id)['label']}"); s.kanban().setdefault(col_id, []).insert(0, card); s.save(); self.refresh(); return card

    def add_task(self, col_id="todo", preset=None):
        d = TaskDialog(self, self.store, None, col_id, preset)
        if d.exec() != QDialog.Accepted: return
        v = d.values(); self._create_card(v.pop("col"), **v); self.toast("Task added!")

    def qa_submit(self, col_id, text):
        """Quick-add: 'Renew SSL !high #ops @fri' → new card in col_id (returns it, or None if there's no title)."""
        p = parse_quick(self.store, text)
        if not p["title"]: return None
        card = self._create_card(col_id, **p); self.toast(f"Added “{p['title']}”" + (f" · due {fmt_date(p['dueDate'])}" if p["dueDate"] else "")); return card

    def edit_task(self, cid, col_id):
        card, col_id = self.store.find_card(cid, col_id)
        if not card: return
        d = TaskDialog(self, self.store, card, col_id)
        if d.exec() != QDialog.Accepted: return
        v = d.values()
        if v["priority"] != card.get("priority"): card["prioLock"] = True
        changes = [n for n, k in (("title", "title"), ("description", "desc"), ("priority", "priority"), ("due date", "dueDate"), ("repeat", "repeat")) if (card.get(k) or "") != v[k]]
        card.update(title=v["title"], desc=v["desc"], priority=v["priority"], dueDate=v["dueDate"], subs=v["subs"], labels=v["labels"], repeat=v["repeat"], repeatUntil=v["repeatUntil"], updatedAt=now_iso())
        if changes: self.store.log(card, "Edited " + ", ".join(changes))
        if v["col"] != col_id: self.store.move_card(cid, col_id, v["col"])
        elif v["col"] == "done": card["done"] = True
        if self.detail_ref and self.detail_ref[0] == cid: self.detail_ref = (cid, v["col"])
        self.store.save(); self.refresh(); self.toast("Task updated")

    def delete_task(self, cid, col_id):
        if QMessageBox.question(self, "Delete task", "Delete this task? This cannot be undone.") != QMessageBox.Yes: return
        kd = self.store.kanban(); kd[col_id] = [c for c in kd.get(col_id, []) if c["id"] != cid]
        if self.detail_ref and self.detail_ref[0] == cid: self.close_detail()
        self.store.save(); self.refresh()

    def toggle_done(self, cid, col_id):
        to = "done" if col_id != "done" else "todo"; card = self.store.move_card(cid, col_id, to)
        if card:
            self.store.save(); rec = card.pop("recurred", False)
            if self.detail_ref and self.detail_ref[0] == cid: self.detail_ref = (cid, col_id if rec else to)
            self.refresh(); self.toast(f"↻ Done for now — next due {fmt_date(card['dueDate'])}" if rec else "✅ Moved to Completed!" if to == "done" else "↩ Moved to To Do")

    def skip_occurrence(self, cid, col_id):
        card, _ = self.store.find_card(cid, col_id)
        if not card or not card.get("repeat") or not card.get("dueDate"): return
        nd = next_due(card["dueDate"], card["repeat"])
        if nd is None or (card.get("repeatUntil") and nd.isoformat() > card["repeatUntil"]): card["repeat"] = ""; self.toast("Repeat ended")
        else: self.store.log(card, f"Skipped {fmt_date(card['dueDate'])} → {fmt_date(nd.isoformat())}"); card["dueDate"] = nd.isoformat(); self.toast(f"Skipped — next due {fmt_date(card['dueDate'])}")
        card["updatedAt"] = now_iso(); self.store.save(); self.refresh()

    def auto_prio_on(self):
        return bool(self.settings.get("autoPriority", True))

    def set_auto_prio(self, on):
        self.settings["autoPriority"] = bool(on); st = read_settings(); st["autoPriority"] = bool(on); write_settings(st)
        if on: self.run_auto_priority(all_months=True, announce=True)

    def run_auto_priority(self, all_months=False, announce=False):
        if not self.auto_prio_on(): return 0
        s = self.store; ch = apply_auto_priority(s, months=None if all_months else [(s.year, s.month)])
        if ch:
            s.save()
            if announce: self.toast(f"⚡ Auto-priority raised {len(ch)} task(s) as deadlines approach", 4200, "bolt")
        return len(ch)

    def unlock_priority(self, cid, col_id):
        card, _ = self.store.find_card(cid, col_id)
        if not card: return
        card.pop("prioLock", None); self.store.log(card, "Priority back to automatic"); self.store.save(); self.run_auto_priority(all_months=True); self.refresh()
        if self.detail_ref and self.detail_ref[0] == cid: self.render_detail()

    def set_priority(self, cid, col_id, pri):
        card, _ = self.store.find_card(cid, col_id)
        if not card or card.get("priority") == pri: return
        card["priority"] = pri; card["prioLock"] = True; card["updatedAt"] = now_iso(); self.store.log(card, f"Priority set to {PRI_LABEL[pri]} (manual — auto-priority off for this task)"); self.store.save(); self.refresh()
        if self.detail_ref and self.detail_ref[0] == cid: self.render_detail()

    @staticmethod
    def _dot_icon(color, size=16):
        pm = QPixmap(size * 2, size * 2); pm.setDevicePixelRatio(2); pm.fill(Qt.transparent); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen); p.setBrush(QColor(color)); p.drawEllipse(QRectF(4, 4, size - 8, size - 8)); p.end(); return QIcon(pm)

    def card_menu(self, cid, col_id, gpos):
        """Right-click menu for a task (board card or list row): frosted glass with a blurred backdrop."""
        card, col_id = self.store.find_card(cid, col_id)
        if not card: return
        done = card.get("done") or col_id == "done"; m = GlassMenu(parent=self)
        def add(menu, icon, text, fn):
            a = menu.addAction(make_icon(icon, 16) if isinstance(icon, str) else icon, text); a.triggered.connect(lambda *_: fn()); return a
        add(m, "arrow-right", "Open", lambda: self.open_detail(cid, col_id)); add(m, "edit", "Edit…", lambda: self.edit_task(cid, col_id))
        add(m, "check-circle", "Reopen" if done else "Mark complete", lambda: self.toggle_done(cid, col_id)); m.addSeparator()
        mv = GlassMenu("Move to", m); mv.setIcon(make_icon("board", 16))
        for c in self.store.columns:
            if c["id"] != col_id: add(mv, self._dot_icon(c["color"]), f"{c.get('icon', '')} {c['label']}".strip(), lambda to=c["id"]: self.on_drop(cid, col_id, to, None))
        m.addMenu(mv)
        pr = GlassMenu("Priority", m); pr.setIcon(make_icon("alert", 16))
        for k, lab in PRI_LABEL.items():
            a = add(pr, self._dot_icon(PRI_COLOR[k]), lab.split(" ", 1)[1], lambda k=k: self.set_priority(cid, col_id, k)); a.setCheckable(True); a.setChecked(card.get("priority", "med") == k)
        pr.addSeparator(); add(pr, "bolt", "Auto — follow due date", lambda: self.unlock_priority(cid, col_id)); m.addMenu(pr)
        if card.get("repeat"): add(m, "repeat", "Skip this occurrence", lambda: self.skip_occurrence(cid, col_id))
        m.addSeparator(); add(m, "trash", "Delete", lambda: self.delete_task(cid, col_id)); m.exec(gpos)

    def manage_labels(self):
        LabelDialog(self, self.store).exec(); self.filter_labels &= {l["id"] for l in self.store.labels}; self.refresh()

    def column_dialog(self, col_id):
        d = ColumnDialog(self, self.store, col_id)
        if d.exec() != QDialog.Accepted: return
        s = self.store; cols = s.columns; a = d.result_action
        if a == "save":
            if d.col: d.col.update(label=d.name.text().strip(), icon=d.icon.text().strip(), color=d.color); self.toast("Column updated")
            else: cols.append({"id": "c_" + uid(), "label": d.name.text().strip(), "icon": d.icon.text().strip(), "color": d.color}); [s.ensure_year(y) for y in s.years()]; self.toast("Column added")
        elif a in ("left", "right"):
            i = cols.index(d.col); j = i + (-1 if a == "left" else 1)
            if 0 <= j < len(cols): cols[i], cols[j] = cols[j], cols[i]
        elif a == "delete":
            n = sum(len(kd.get(d.col["id"], [])) for Y in s.db["years"].values() for kd in Y["kanban"].values())
            if QMessageBox.question(self, "Delete column", f"Delete column \"{d.col['label']}\"?" + (f" Its {n} task(s) across all months will move to To Do." if n else "")) != QMessageBox.Yes: return
            for Y in s.db["years"].values():
                for kd in Y["kanban"].values():
                    arr = kd.pop(d.col["id"], [])
                    for c in arr: c["done"] = False; s.log(c, f"Column \"{d.col['label']}\" deleted — moved to To Do")
                    kd["todo"] = arr + kd.get("todo", [])
            cols.remove(d.col)
        s.save(); self.refresh()

    # ---------- detail panel ----------
    DOCK_W = 440

    def open_detail(self, cid, col_id):
        card, col_id = self.store.find_card(cid, col_id)
        if not card: return
        self.detail_ref = (cid, col_id); self.render_detail()
        if self.dock.isVisible(): return
        self.dock.show()
        if self.motion():       # the board reflows as the pane slides in (setMaximumWidth also lowers the minimum while below it)
            self.dock.setMaximumWidth(1); self.animate(self.dock, b"maximumWidth", 1, self.DOCK_W, 260, on_done=lambda: (self.dock.setMaximumWidth(16777215), self.dock.setMinimumWidth(self.DOCK_W)))

    def close_detail(self):
        self.detail_ref = None
        if self.dock.isVisible() and self.motion():
            self.animate(self.dock, b"maximumWidth", self.dock.width(), 1, 200, QEasingCurve.InCubic, on_done=lambda: (self.dock.hide(), self.dock.setMaximumWidth(16777215), self.dock.setMinimumWidth(self.DOCK_W)))
        else: self.dock.hide()

    def _dcard(self):
        if not self.detail_ref: return None, None
        return self.store.find_card(*self.detail_ref)

    def render_detail(self):
        card, col_id = self._dcard()
        if not card: self.close_detail(); return
        s = self.store; col = s.col(col_id); done = card.get("done") or col_id == "done"
        self._clear(self.detail_layout); L = self.detail_layout; L.setContentsMargins(0, 0, 0, 0)
        inner = QWidget(); v = QVBoxLayout(inner); v.setContentsMargins(20, 16, 20, 16); v.setSpacing(12)
        top = QHBoxLayout(); top.addWidget(badge(f"{col.get('icon', '')} {col['label']}", "#fff", col["color"])); top.addWidget(badge(PRI_LABEL[card.get("priority", "med")], PRI_COLOR[card.get("priority", "med")]))
        if card.get("dueDate"): od = is_overdue(card["dueDate"], done); top.addWidget(badge(("⚠ Overdue " if od else "📅 ") + fmt_date(card["dueDate"]), PRI_COLOR["high"] if od else C("text2")))
        if card.get("repeat"): top.addWidget(badge("↻ " + REPEAT_SHORT.get(card["repeat"], card["repeat"]), C("accent")))
        top.addStretch(); cl = QPushButton("✕"); cl.setObjectName("ghost"); cl.clicked.connect(self.close_detail); top.addWidget(cl); v.addLayout(top)
        title = QLineEdit(card["title"]); title.setStyleSheet("font-size:17px;font-weight:700;background:transparent;border-color:transparent;"); title.editingFinished.connect(lambda: self.dset("title", title.text())); v.addWidget(title)
        g = QGridLayout(); colc = QComboBox()
        for c in s.columns: colc.addItem(f"{c.get('icon', '')} {c['label']}", c["id"])
        colc.setCurrentIndex(colc.findData(col_id)); colc.currentIndexChanged.connect(lambda: self.dmove(colc.currentData()))
        pri = QComboBox()
        for k, lab in PRI_LABEL.items(): pri.addItem(lab, k)
        pri.setCurrentIndex(pri.findData(card.get("priority", "med"))); pri.currentIndexChanged.connect(lambda: self.dset("priority", pri.currentData()))
        dcb = QCheckBox("Due"); de = QDateEdit(QDate.currentDate()); de.setCalendarPopup(True); de.setDisplayFormat("yyyy-MM-dd"); de.setMinimumWidth(150)
        if card.get("dueDate"): dcb.setChecked(True); de.setDate(QDate.fromString(card["dueDate"], "yyyy-MM-dd"))
        de.setEnabled(dcb.isChecked()); dcb.toggled.connect(lambda on: self.dset("dueDate", de.date().toString("yyyy-MM-dd") if on else "")); de.dateChanged.connect(lambda d: self.dset("dueDate", d.toString("yyyy-MM-dd")) if dcb.isChecked() else None)
        for i, (lab, w) in enumerate((("Column", colc), ("Priority", pri))): g.addWidget(QLabel(lab, objectName="muted"), 0, i); g.addWidget(w, 1, i)
        dl = QHBoxLayout(); dl.addWidget(dcb); dl.addWidget(de); dl.addStretch(); g.addWidget(QLabel("Due date", objectName="muted"), 2, 0); g.addLayout(dl, 3, 0, 1, 2)
        rp = QComboBox()
        for k, lab in REPEATS: rp.addItem(("↻ " if k else "") + lab, k)
        rp.setCurrentIndex(max(0, rp.findData(card.get("repeat", "")))); rp.currentIndexChanged.connect(lambda: self.dset_repeat(rp.currentData()))
        rl = QHBoxLayout(); rl.addWidget(rp)
        if card.get("repeat"):
            nd = next_due(card["dueDate"], card["repeat"]) if card.get("dueDate") else None
            rl.addWidget(QLabel(("then " + fmt_date(nd.isoformat()) if nd else "") + (f" · until {fmt_date(card['repeatUntil'])}" if card.get("repeatUntil") else ""), objectName="muted"))
            sk = QPushButton("Skip once"); sk.setObjectName("ghost"); sk.setToolTip("Move this task to its next occurrence without completing it"); sk.clicked.connect(lambda: self.skip_occurrence(card["id"], col_id)); rl.addWidget(sk)
        rl.addStretch(); g.addWidget(QLabel("Repeat", objectName="muted"), 4, 0); g.addLayout(rl, 5, 0, 1, 2); v.addLayout(g)
        lh = QHBoxLayout(); lh.addWidget(QLabel("LABELS", objectName="navSection")); lh.addStretch(); mg = QPushButton("Manage"); mg.setObjectName("ghost"); mg.clicked.connect(self.manage_labels); lh.addWidget(mg); v.addLayout(lh)
        lr = QGridLayout(); lr.setSpacing(6)        # ponytail: 3 chips per row instead of a flow layout; wraps within the 440 px dock
        for i, l in enumerate(s.labels):
            b = QPushButton(l["name"]); b.setCheckable(True); b.setChecked(l["id"] in card.get("labels", [])); b.setStyleSheet(f"QPushButton{{border-color:{l['color']};color:{l['color']};padding:3px 10px;}}QPushButton:checked{{background:{l['color']};color:#fff;}}")
            b.toggled.connect(lambda on, lid=l["id"]: self.dlabel(lid, on)); lr.addWidget(b, i // 3, i % 3)
        if not s.labels: lr.addWidget(QLabel("No labels yet", objectName="muted"), 0, 0)
        v.addLayout(lr)
        v.addWidget(QLabel("DESCRIPTION", objectName="navSection")); desc = QTextEdit(card.get("desc", "")); desc.setPlaceholderText("Add details, links, notes…"); desc.setFixedHeight(80)
        desc.focusOutEvent = lambda e, te=desc: (QTextEdit.focusOutEvent(te, e), self.dset("desc", te.toPlainText())); v.addWidget(desc)
        subs = card.get("subs", []); sd = sum(1 for x in subs if x.get("done")); v.addWidget(QLabel(f"CHECKLIST  {sd}/{len(subs)}" if subs else "CHECKLIST", objectName="navSection"))
        for x in subs:
            r = QHBoxLayout(); r.setSpacing(6); cb = QCheckBox(); cb.setChecked(bool(x.get("done"))); cb.toggled.connect(lambda on, sid=x["id"]: self.dsub(sid, on))
            tl = QLabel(x["text"]); tl.setWordWrap(True); tl.setToolTip("Double-click to edit"); tl.setStyleSheet(f"text-decoration:line-through;color:{C('text3')};" if x.get("done") else "")
            tl.mouseDoubleClickEvent = lambda e, sid=x["id"]: self.dsub_edit(sid)
            eb = QPushButton("✎"); eb.setObjectName("ghost"); eb.setToolTip("Edit item"); eb.clicked.connect(lambda _, sid=x["id"]: self.dsub_edit(sid))
            rm = QPushButton("✕"); rm.setObjectName("ghost"); rm.clicked.connect(lambda _, sid=x["id"]: self.dsub_remove(sid))
            r.addWidget(cb, 0, Qt.AlignTop); r.addWidget(tl, 1); r.addWidget(eb, 0, Qt.AlignTop); r.addWidget(rm, 0, Qt.AlignTop); v.addLayout(r)
        ar = QHBoxLayout(); si = QLineEdit(); si.setPlaceholderText("Add an item… (Enter)"); si.returnPressed.connect(lambda: self.dsub_add(si.text())); ab = QPushButton("Add"); ab.clicked.connect(lambda: self.dsub_add(si.text())); ar.addWidget(si); ar.addWidget(ab); v.addLayout(ar)
        comments = card.get("comments", []); v.addWidget(QLabel(f"COMMENTS  {len(comments) or ''}", objectName="navSection"))
        cr = QHBoxLayout(); ci = QTextEdit(); ci.setPlaceholderText("Write a comment… (Ctrl+Enter to post)"); ci.setFixedHeight(56); pb = QPushButton("Post"); pb.setObjectName("primary"); pb.clicked.connect(lambda: self.dcomment(ci.toPlainText()))
        QShortcut(QKeySequence("Ctrl+Return"), ci, activated=lambda: self.dcomment(ci.toPlainText())); cr.addWidget(ci, 1); cr.addWidget(pb, 0, Qt.AlignBottom); v.addLayout(cr)
        for m in reversed(comments):
            f = QFrame(); f.setObjectName("panel"); fl = QVBoxLayout(f); hr = QHBoxLayout(); hr.addWidget(QLabel(fmt_dt(m["at"]), objectName="muted")); hr.addStretch(); dbn = QPushButton("Delete"); dbn.setObjectName("ghost"); dbn.clicked.connect(lambda _, mid=m["id"]: self.dcomment_del(mid)); hr.addWidget(dbn); fl.addLayout(hr)
            t = QLabel(m["text"]); t.setWordWrap(True); fl.addWidget(t); v.addWidget(f)
        v.addWidget(QLabel("ACTIVITY", objectName="navSection"))
        for a in reversed(card.get("activity", [])[-20:]): v.addWidget(QLabel(f"{fmt_dt(a['at'])}   {a['text']}", objectName="muted2", wordWrap=True))
        v.addStretch(); sa = QScrollArea(); sa.setWidgetResizable(True); sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); sa.setWidget(inner); L.addWidget(sa, 1)
        foot = QHBoxLayout(); foot.setContentsMargins(16, 8, 16, 12); mk = QPushButton("↩ Reopen" if done else "✓ Mark complete"); mk.setObjectName("" if done else "primary"); mk.clicked.connect(lambda: self.toggle_done(card["id"], col_id))
        ed = QPushButton("✎ Edit in form"); ed.clicked.connect(lambda: self.edit_task(card["id"], col_id)); dl2 = QPushButton("Delete"); dl2.setObjectName("danger"); dl2.clicked.connect(lambda: self.delete_task(card["id"], col_id))
        foot.addWidget(mk); foot.addWidget(ed); foot.addStretch(); foot.addWidget(dl2); L.addLayout(foot)

    def dset_repeat(self, rep):
        card, _ = self._dcard()
        if not card: return
        if rep and not card.get("dueDate"): card["dueDate"] = dt.date.today().isoformat()
        self.dset("repeat", rep)

    def dset(self, field, val):
        card, col = self._dcard()
        if not card: return
        val = val.strip() if isinstance(val, str) else val
        if field == "title" and not val: self.render_detail(); return
        if (card.get(field) or "") == val: return
        card[field] = val; card["updatedAt"] = now_iso()
        if field == "priority": card["prioLock"] = True
        self.store.log(card, {"title": "Title updated", "desc": "Description updated", "priority": f"Priority set to {PRI_LABEL.get(val, val)}", "dueDate": f"Due date set to {fmt_date(val)}" if val else "Due date removed", "repeat": f"Repeats {dict(REPEATS).get(val, val).lower()}" if val else "Repeat removed"}[field])
        self.store.save(); self.refresh()

    def dmove(self, to):
        card, col = self._dcard()
        if not card or to == col: return
        self.store.move_card(card["id"], col, to); self.detail_ref = (card["id"], to); self.store.save(); self.refresh()

    def dlabel(self, lid, on):
        card, col = self._dcard()
        if not card: return
        ls = card.setdefault("labels", []); name = next((l["name"] for l in self.store.labels if l["id"] == lid), "")
        if on and lid not in ls: ls.append(lid); self.store.log(card, f"Label \"{name}\" added")
        elif not on and lid in ls: ls.remove(lid); self.store.log(card, f"Label \"{name}\" removed")
        card["updatedAt"] = now_iso(); self.store.save(); self.refresh()

    def dsub(self, sid, on):
        card, col = self._dcard()
        if not card: return
        for x in card.get("subs", []):
            if x["id"] == sid: x["done"] = on
        if card.get("subs") and all(x.get("done") for x in card["subs"]) and col != "done":
            self.store.move_card(card["id"], col, "done"); self.store.log(card, "All sub-tasks completed"); self.detail_ref = (card["id"], "done"); self.toast("🎉 All sub-tasks done — moved to Completed!")
        self.store.save(); self.refresh()

    def dsub_add(self, t):
        card, col = self._dcard(); t = t.strip()
        if not card or not t: return
        card.setdefault("subs", []).append({"id": uid(), "text": t, "done": False}); self.store.log(card, f"Checklist item added: {t}"); self.store.save(); self.refresh()

    def dsub_edit(self, sid):
        card, col = self._dcard()
        if not card: return
        x = next((x for x in card.get("subs", []) if x["id"] == sid), None)
        if not x: return
        t, ok = QInputDialog.getMultiLineText(self, "Edit checklist item", "Text:", x["text"])
        if ok and t.strip() and t.strip() != x["text"]: x["text"] = t.strip(); card["updatedAt"] = now_iso(); self.store.log(card, "Checklist item edited"); self.store.save(); self.refresh()

    def dsub_remove(self, sid):
        card, col = self._dcard()
        if not card: return
        card["subs"] = [x for x in card.get("subs", []) if x["id"] != sid]; self.store.save(); self.refresh()

    def dcomment(self, t):
        card, col = self._dcard(); t = t.strip()
        if not card or not t: return
        card.setdefault("comments", []).append({"id": uid(), "text": t, "at": now_iso()}); self.store.log(card, "Comment added"); self.store.save(); self.refresh()

    def dcomment_del(self, mid):
        card, col = self._dcard()
        if card: card["comments"] = [m for m in card.get("comments", []) if m["id"] != mid]; self.store.save(); self.refresh()

    # ---------- calendar ----------
    def iter_cards(self):
        """Every card in every month/year: (year, month_index, column, card).  The calendar is driven by DUE DATE, not by the month a card is filed under."""
        s = self.store
        for y in s.years():
            for mi in range(12):
                kd = s.kanban(mi, y)
                for c in s.columns:
                    for k in kd.get(c["id"], []): yield y, mi, c, k

    def locate_card(self, cid):
        for y, mi, c, k in self.iter_cards():
            if k["id"] == cid: return y, mi, c["id"], k
        return None

    def open_anywhere(self, cid):
        loc = self.locate_card(cid)
        if not loc: return
        y, mi, col, _ = loc
        if (y, mi) == (self.store.year, self.store.month): self.open_detail(cid, col)
        else: self.goto(y, mi, "kanban", lambda: self.open_detail(cid, col)); self.toast(f"Opened in {MONTHS_LONG[mi]} {y} — where this task is filed", 2400, "calendar")

    def cal_set_mode(self, mode):
        self.cal_mode = mode
        if mode == "week":
            t = dt.date.today(); self.cal_anchor = t if (t.year, t.month - 1) == (self.store.year, self.store.month) else dt.date(self.store.year, self.store.month + 1, 1)
        self.render_calendar()

    def cal_sync_month(self, d):
        s = self.store; s.year = d.year; s.ensure_year(d.year); s.month = d.month - 1

    def cal_step(self, n):
        if self.cal_mode == "month": self.step_month(n); return
        self.cal_anchor += dt.timedelta(days=7 * n); self.cal_sync_month(self.cal_anchor); self.refresh()

    def cal_today(self):
        self.cal_anchor = dt.date.today(); self.go_today()

    def day_overlay(self, iso):
        if self.overlay is None: DayOverlay(self, iso).exec()

    def render_calendar(self):
        s = self.store; y, m = s.year, s.month; self._clear(self.cal_grid); self._clear(self.cal_side); today = dt.date.today(); today_iso = today.isoformat(); hide_done = self.cal_hide_done.isChecked()
        week = self.cal_mode == "week"
        if week:
            if (self.cal_anchor.year, self.cal_anchor.month - 1) != (y, m): self.cal_anchor = today if (today.year, today.month - 1) == (y, m) else dt.date(y, m + 1, 1)
            start = self.cal_anchor - dt.timedelta(days=self.cal_anchor.weekday()); cells = 7; end = start + dt.timedelta(days=6); limit = 99
            self.cal_title.setText(f"{start.strftime('%b %d').replace(' 0', ' ')} – {end.strftime('%b %d, %Y').replace(' 0', ' ')}")
        else:
            first = dt.date(y, m + 1, 1); start = first - dt.timedelta(days=first.weekday()); days_in = calendar.monthrange(y, m + 1)[1]
            cells = -(-(first.weekday() + days_in) // 7) * 7; end = start + dt.timedelta(days=cells - 1); limit = 3
            self.cal_title.setText(f"{MONTHS_LONG[m]} {y}")
        for k, b in self.cal_mode_btns.items(): b.setChecked(k == self.cal_mode)
        by_date, backlog, unscheduled, nghost = {}, [], [], [0]
        def iso_date(v):
            try: return dt.date.fromisoformat(v) if v else None
            except ValueError: return None
        def chip(k, c, text, **kw): return CalChip(text, c["color"], pri=k.get("priority"), **kw)
        for yy, mi, c, k in self.iter_cards():
            done = bool(k.get("done") or c["id"] == "done"); d = iso_date(k.get("dueDate")); here = (yy, mi) == (y, m)
            if d is None:
                if here and not done: unscheduled.append(chip(k, c, ("↻ " if k.get("repeat") else "") + k["title"], drag_id=k["id"], on_click=lambda kid=k["id"]: self.open_anywhere(kid)))
                continue
            if hide_done and done: continue
            if d < start and not done:
                backlog.append((d, k, c, done)); continue
            if start <= d <= end: by_date.setdefault(k["dueDate"], []).append(chip(k, c, ("↻ " if k.get("repeat") else "") + k["title"], drag_id=k["id"], done=done, overdue=is_overdue(k["dueDate"], done), on_click=lambda kid=k["id"]: self.open_anywhere(kid)))
            if not done:
                for od in occurrences(k, start, end):
                    by_date.setdefault(od.isoformat(), []).append(CalChip("↻ " + k["title"], c["color"], None, dashed=True, ghost=True, on_click=lambda kid=k["id"]: self.open_anywhere(kid))); nghost[0] += 1
        n_sched = sum(len(v) for v in by_date.values()) - nghost[0]
        self.cal_stat.setText(f"{n_sched} scheduled · {len(unscheduled)} unscheduled" + (f" · {nghost[0]} repeats" if nghost[0] else "") + (f" · {len(backlog)} overdue earlier" if backlog else ""))
        for i, dn in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            self.cal_grid.addWidget(QLabel(dn, objectName="muted", alignment=Qt.AlignCenter), 0, i); self.cal_grid.setColumnStretch(i, 1)
        for r in range(cells // 7): self.cal_grid.setRowStretch(1 + r, 1)
        for i in range(cells):
            d = start + dt.timedelta(days=i); iso = d.isoformat(); out = (not week) and d.month != m + 1
            cell = CalDay(iso); cell.setProperty("out", out); cell.setProperty("today", iso == today_iso); cell.setProperty("weekend", d.weekday() >= 5); cell.setMinimumHeight(330 if week else 104)
            cell.dropped.connect(self.cal_drop); cell.added.connect(lambda iso: self.add_task("todo", dict(dueDate=iso)))
            cv = QVBoxLayout(cell); cv.setContentsMargins(6, 4, 6, 6); cv.setSpacing(3); cv.setAlignment(Qt.AlignTop); hr = QHBoxLayout()
            num = QLabel(str(d.day) + (" " + MONTHS[d.month - 1] if d.day == 1 or week else "")); num.setStyleSheet("font-weight:700;" + (f"color:{C('accent_text')};" if iso == today_iso else f"color:{C('text3')};" if out else "")); hr.addWidget(num); hr.addStretch()
            chips = by_date.get(iso, [])
            if len(chips) > limit: hr.addWidget(badge(str(len(chips)), C("text2")))
            ab = QPushButton(); ab.setObjectName("ghost"); ab.setIcon(make_icon("plus", 14)); ab.setIconSize(QSize(14, 14)); ab.setFixedSize(24, 24); ab.setToolTip(f"Add a task due {fmt_date(iso)}"); ab.clicked.connect(lambda _, iso=iso: self.add_task("todo", dict(dueDate=iso))); hr.addWidget(ab); cv.addLayout(hr)
            chips.sort(key=lambda ch: (ch.drag_id is None, 0))          # real tasks before ghost repeats
            for ch in chips[:limit]:
                if week: ch.setWordWrap(True); ch.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)      # roomy view: wrap titles instead of clipping
                cv.addWidget(ch)
            if len(chips) > limit:
                mb = QPushButton(f"+{len(chips) - limit} more"); mb.setObjectName("ghost"); mb.setStyleSheet(f"color:{C('accent_text')};font-weight:600;"); mb.clicked.connect(lambda _, iso=iso: self.day_overlay(iso)); cv.addWidget(mb)
                for ch in chips[limit:]: ch.deleteLater()
            self.cal_grid.addWidget(cell, 1 + i // 7, i % 7)
        tray = CalDay("", tray=True); tray.dropped.connect(self.cal_drop); tv = QVBoxLayout(tray); tv.setContentsMargins(12, 10, 12, 12); tv.setAlignment(Qt.AlignTop); tv.addWidget(QLabel(f"UNSCHEDULED   {len(unscheduled)}", objectName="navSection"))
        for ch in unscheduled[:12]: tv.addWidget(ch)
        for ch in unscheduled[12:]: ch.deleteLater()
        if len(unscheduled) > 12: tv.addWidget(QLabel(f"+{len(unscheduled) - 12} more — see the Task List", objectName="muted"))
        if not unscheduled: tv.addWidget(QLabel("Every open task has a date. Drop a task here to clear its due date.", objectName="muted", wordWrap=True))
        self.cal_side.addWidget(tray)
        if backlog:
            backlog.sort(key=lambda t: t[0]); f = GlassFrame(elev=1, radius=RADIUS["panel"]); fv = QVBoxLayout(f); fv.setContentsMargins(12, 10, 12, 12); fv.addWidget(QLabel(f"OVERDUE BEFORE THIS VIEW   {len(backlog)}", objectName="navSection"))
            for d, k, c, done in backlog[:10]: fv.addWidget(CalChip(f"{fmt_date(k['dueDate'])} · {k['title']}", c["color"], k["id"], False, True, on_click=lambda kid=k["id"]: self.open_anywhere(kid), pri=k.get("priority")))
            if len(backlog) > 10: fv.addWidget(QLabel(f"+{len(backlog) - 10} more", objectName="muted"))
            fv.addWidget(QLabel("Drag onto a day to reschedule.", objectName="muted")); self.cal_side.addWidget(f)

    def cal_drop(self, cid, iso):
        loc = self.locate_card(cid)
        if not loc: return
        card = loc[3]
        if (card.get("dueDate") or "") == iso: return
        card["dueDate"] = iso; card["updatedAt"] = now_iso(); self.store.log(card, f"Rescheduled to {fmt_date(iso)}" if iso else "Due date removed"); self.store.save(); self.run_auto_priority(all_months=True); self.refresh()
        self.toast(f"“{card['title']}” now due {fmt_date(iso)}" if iso else f"Due date cleared for “{card['title']}”")

    # ---------- list (same cards as the board, one line each) ----------
    LIST_PAGE = 25

    def _list_changed(self, *_):
        self.list_limit.clear(); self.render_list()

    def render_list(self, *_):
        s = self.store; self._clear(self.list_layout); kd = s.kanban(); q = self.list_search.text().strip().lower(); hide = self.list_hide_done.isChecked(); mode = self.list_group.currentData(); today = dt.date.today()
        rows = [(c, col) for col in s.columns for c in kd.get(col["id"], []) if not (hide and (c.get("done") or col["id"] == "done"))
                and (not q or q in " ".join([c.get("title", ""), c.get("desc", "")] + [x["text"] for x in c.get("subs", [])]).lower())]
        def key(c, col):
            if mode == "column": return (s.columns.index(col), f"{col.get('icon', '')} {col['label']}", col["color"])
            if mode == "priority": p = c.get("priority", "med"); return ({"high": 0, "med": 1, "low": 2}[p], PRI_LABEL[p], PRI_COLOR[p])
            if mode == "label":
                l = next((x for x in s.labels if x["id"] in c.get("labels", [])), None)
                return (s.labels.index(l), l["name"], l["color"]) if l else (999, "No label", C("text2"))
            try: n = (dt.date.fromisoformat(c["dueDate"]) - today).days
            except (KeyError, TypeError, ValueError): return (6, "No due date", C("text2"))
            if n < 0: return (0, "Overdue", PRI_COLOR["high"]) if not (c.get("done") or col["id"] == "done") else (5, "Past", C("text2"))
            return (1, "Today", "#ffb347") if n == 0 else (2, "Tomorrow", "#6c8aff") if n == 1 else (3, "This week", "#6c8aff") if n <= 6 else (4, "Next 30 days", C("text2")) if n <= 30 else (5, "Later", C("text2"))
        groups = {}
        for c, col in rows: groups.setdefault(key(c, col), []).append((c, col))
        for (order, name, color) in sorted(groups):
            items = groups[(order, name, color)]; hd = QHBoxLayout(); t = QLabel(name); t.setStyleSheet(f"font-weight:700;color:{T(color)};margin-top:8px;"); hd.addWidget(t); hd.addWidget(badge(str(len(items)), color)); hd.addStretch(); self.list_layout.addLayout(hd)
            if mode == "due": items.sort(key=lambda it: (it[0].get("dueDate") or "9999", -PRI_RANK.get(it[0].get("priority", "med"), 1)))
            lim = self.list_limit.get(name, self.LIST_PAGE)
            for c, col in items[:lim]:
                r = ListRow(s, c, col); r.clicked.connect(self.open_detail); r.toggle.connect(self.toggle_done); r.context.connect(self.card_menu); self.list_layout.addWidget(r)
            if len(items) > lim:
                mb = QPushButton(f"Show {min(self.LIST_PAGE, len(items) - lim)} more  ·  {len(items) - lim} hidden in “{name}”"); mb.setObjectName("addk")
                mb.clicked.connect(lambda _, n=name, l=lim: (self.list_limit.__setitem__(n, l + self.LIST_PAGE), self.render_list())); self.list_layout.addWidget(mb)
        if not rows: self.list_layout.addWidget(QLabel("No tasks match." if q or hide else "No tasks this month. Add one with + Add Task or Ctrl N.", objectName="muted"))
        ndone = sum(1 for c, col in rows if c.get("done") or col["id"] == "done"); self.list_stat.setText(f"{len(rows)} tasks · {ndone} done")

    # ---------- rollover ----------
    def open_rollover(self):
        s = self.store; d = GlassDialog(self); d.setWindowTitle(f"Month Rollover · {s.year}"); d.setMinimumWidth(560); v = QVBoxLayout(d)
        v.addWidget(QLabel("Auto-rollover is ON: incomplete tasks from past months move forward each time the app opens. Completed tasks stay where they were finished. December → January of the next year.", wordWrap=True, objectName="muted2"))
        for mi in range(12):
            inc = s.incomplete_cards(mi, s.year); tot = len(inc); past = s.month_past(mi, s.year)
            ty, tm = (s.year + 1, 0) if mi == 11 else (s.year, mi + 1)
            r = QHBoxLayout(); r.addWidget(QLabel(f"{MONTHS[mi]} {s.year} → {MONTHS[tm]} {ty}", objectName="sectitle"))
            st = "🔒 Not ended yet" if not past else ("✅ All done" if tot == 0 else f"⏳ {tot} pending"); r.addWidget(QLabel(st, objectName="muted")); r.addStretch()
            if past and tot:
                b = QPushButton(f"Move → {MONTHS[tm]} {ty}"); b.setObjectName("primary")
                b.clicked.connect(lambda _, m=mi, dd=d: (s.migrate_month(m, s.year), self.toast("✅ Moved"), dd.accept(), self.refresh(), self.open_rollover())); r.addWidget(b)
            v.addLayout(r)
        hist = s.db["migrations"][-8:][::-1]
        if hist:
            v.addWidget(QLabel("HISTORY", objectName="navSection"))
            for m in hist: v.addWidget(QLabel(f"{'🤖' if m.get('auto') else '👆'} {MONTHS[m['from']]} {m.get('fromYear')} → {MONTHS[m['to']]} {m.get('toYear')}   +{m['kanban'] + m.get('checklist', 0)} tasks   {fmt_dt(m['at'])}", objectName="muted2"))
        cb = QPushButton("Close"); cb.clicked.connect(d.accept); v.addWidget(cb); d.exec()

    # ---------- backup ----------
    def backup_now_ui(self, then=None):
        self.store.save()
        self.start_job("Backing up", lambda prog: self.store.backup_now(), icon="backup",
                       done_msg=lambda dest: ("💾 Backup saved: " + os.path.basename(dest)) if dest else "No data file to back up yet",
                       on_done=(lambda _: then()) if then else None)

    def open_backup(self):
        d = GlassDialog(self); d.setWindowTitle("Backup & Restore"); d.setMinimumWidth(600); v = QVBoxLayout(d)
        v.addWidget(QLabel("Automatic every 30 min and on quit · last 30 kept in the backup folder", objectName="muted"))
        v.addWidget(QLabel("BACKUP FOLDER", objectName="navSection")); cur = get_backup_dir(); pl = QLabel(cur); pl.setWordWrap(True); pl.setObjectName("muted2"); v.addWidget(pl)
        r = QHBoxLayout()
        def choose():
            p = QFileDialog.getExistingDirectory(d, "Choose backup folder", cur)
            if p: st = read_settings(); st["backupDir"] = p; write_settings(st); d.accept(); self.toast("Backup folder: " + p); self.open_backup()
        def set_dir(p):
            st = read_settings()
            if p: st["backupDir"] = p
            else: st.pop("backupDir", None)
            write_settings(st); d.accept(); self.toast("Backups now go to " + get_backup_dir()); self.open_backup()
        cb = QPushButton("📁 Choose folder…"); cb.setObjectName("primary"); cb.clicked.connect(choose); r.addWidget(cb)
        od = detect_onedrive()
        if od: ob = QPushButton("☁ Use OneDrive"); ob.setToolTip(os.path.join(od, f"{APP_NAME} Backups")); ob.clicked.connect(lambda: set_dir(os.path.join(od, f"{APP_NAME} Backups"))); r.addWidget(ob)
        else: r.addWidget(QLabel("OneDrive not detected — use Choose folder…", objectName="muted"))
        if cur != DEFAULT_BACKUP_DIR: rb = QPushButton("Reset to default"); rb.clicked.connect(lambda: set_dir(None)); r.addWidget(rb)
        ofb = QPushButton("Open folder"); ofb.clicked.connect(lambda: self.open_path(cur)); r.addWidget(ofb); r.addStretch(); v.addLayout(r)
        lst = self.store.backup_list(); v.addWidget(QLabel(f"BACKUPS IN THIS FOLDER ({len(lst)})", objectName="navSection"))
        r2 = QHBoxLayout(); bn = QPushButton("💾 Backup now"); bn.setObjectName("primary"); bn.clicked.connect(lambda: (d.accept(), self.backup_now_ui(then=self.open_backup))); r2.addWidget(bn)
        def restore_file():
            p, _ = QFileDialog.getOpenFileName(d, "Restore from backup file", cur, "Backup JSON (*.json)")
            if p: self._restore(p, d)
        rf = QPushButton("↩ Restore from file…"); rf.clicked.connect(restore_file); r2.addWidget(rf); r2.addStretch(); v.addLayout(r2)
        lw = QListWidget(); lw.setFixedHeight(200)
        for name, size, mt in lst: lw.addItem(f"{name}    {dt.datetime.fromtimestamp(mt).strftime('%Y-%m-%d %H:%M')}    {size / 1024:.1f} KB")
        v.addWidget(lw); rs = QPushButton("Restore selected"); rs.clicked.connect(lambda: self._restore(os.path.join(cur, lst[lw.currentRow()][0]), d) if lw.currentRow() >= 0 else None); v.addWidget(rs)
        v.addWidget(QLabel("LIVE DATA FILE", objectName="navSection")); v.addWidget(QLabel(DB_FILE, objectName="muted2", wordWrap=True))
        cl = QPushButton("Close"); cl.clicked.connect(d.accept); v.addWidget(cl); d.exec()

    def _restore(self, path, dlg=None):
        if QMessageBox.warning(self, "Restore backup", f"Restore from:\n{path}\n\nThis will overwrite current data (a safety backup is taken first). Continue?", QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes: return
        try:
            self.store.restore_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Restore failed", str(e)); return
        if dlg: dlg.accept()
        self.close_detail(); self.refresh(); self.toast("✅ Restored from " + os.path.basename(path))

    # ---------- export ----------
    def export_excel(self):
        d = ExportDialog(self, self.store)
        if d.exec() != QDialog.Accepted or not d.months(): return
        months = d.months(); tag = MONTHS[months[0]] if len(months) == 1 else f"{len(months)}months"
        p, _ = QFileDialog.getSaveFileName(self, "Export Excel", os.path.join(os.path.expanduser("~"), "Desktop", f"{APP_NAME}_{tag}_{self.store.year}.xlsx"), "Excel (*.xlsx)")
        if not p: return
        flags = (d.inc_board.isChecked(), d.inc_sum.isChecked(), d.inc_done.isChecked())
        snap = copy.copy(self.store); snap.db = copy.deepcopy(self.store.db)      # the worker reads a private snapshot, never the live store
        self.start_job("Exporting to Excel", lambda prog: export_excel(snap, p, months, *flags, progress=prog), done_msg="📊 Exported: " + os.path.basename(p),
                       on_done=lambda _: self.open_path(os.path.dirname(p)))

    # ---------- appearance ----------
    def palette_dict(self):
        return GLASS.p

    def effective_theme(self):
        m = self.appearance.get("theme", "system")
        return ("dark" if system_is_dark() else "light") if m not in ("dark", "light") else m

    def _on_system_scheme(self, *_):
        if self.appearance.get("theme", "system") not in ("dark", "light"): self.apply_appearance(animate=True)

    def apply_appearance(self, animate=False):
        a = self.appearance; theme = self.effective_theme()
        def go():
            GLASS.motion = bool(a.get("motion", True)); GLASS.kind = a.get("glass", "mica")
            for k, v in (a.get("tint") or {}).items():
                if k in GLASS.tint: GLASS.tint[k] = max(0.3, min(1.0, float(v)))
            GLASS.set_theme(theme, {k: a.get(k) for k in ("bg", "surface", "text", "accent")})
            fam = a.get("font") or pick_font_family()
            QApplication.instance().setStyleSheet(build_qss(GLASS.p, fam, int(a.get("size", 13))))
            ICONS.refresh(); refresh_glows()
            mode = a.get("theme", "system"); ic = {"system": "system", "light": "sun", "dark": "moon"}.get(mode, "moon")
            ICONS.rebind(self.theme_btn, ic); self.theme_btn.setToolTip(f"Theme: {mode.title()}  (click to change)")
            GLASS.native = self.glass_apply()
            if hasattr(self, "page"):
                self.refresh()
                if self.detail_ref: self.render_detail()
            self.update()
        crossfade(self, go) if animate else go()

    def save_appearance(self, animate=False):
        st = read_settings(); st["appearance"] = self.appearance; write_settings(st)
        self.store.db["meta"]["appearance_py"] = self.appearance; self.store.save(); self.apply_appearance(animate)

    def cycle_theme(self):
        m = self.appearance.get("theme", "system"); m = m if m in THEME_MODES else "dark"
        self.appearance["theme"] = THEME_MODES[(THEME_MODES.index(m) + 1) % 3]; self.save_appearance(animate=True)
        self.toast(f"Theme: {self.appearance['theme'].title()}" + (" (follows your OS)" if self.appearance["theme"] == "system" else ""), 1800, "palette")

    toggle_theme = cycle_theme

    def glass_status(self):
        n = {"mica": "Mica", "acrylic": "Acrylic", "tabbed": "Mica Alt"}.get(GLASS.native, "")
        if n: return f"Active: {n} — the OS blurs your wallpaper behind the window."
        if GLASS.kind == "off": return "Off — solid window."
        if sys.platform.startswith("win"): return "Native blur is not active on this system (needs Windows 10 1803+ / 11); using simulated glass."
        return "Simulated glass — Mica / Acrylic are Windows-only, so this platform paints a soft gradient backdrop instead."

    def open_appearance(self):
        d = GlassDialog(self); d.setWindowTitle("Appearance"); d.setMinimumWidth(580); v = QVBoxLayout(d); v.setSpacing(8); a = self.appearance
        def cap(t): v.addSpacing(6); v.addWidget(QLabel(t, objectName="navSection"))
        def change(**kw): a.update(kw); self.save_appearance(animate=True); sync()
        cap("THEME"); tr = QHBoxLayout(); grp = QButtonGroup(d); mode_btns = {}
        for key, icon, lab in (("system", "system", "System"), ("light", "sun", "Light"), ("dark", "moon", "Dark")):
            b = QPushButton(" " + lab); b.setCheckable(True); b.setIcon(make_icon(icon, 16)); b.setIconSize(QSize(16, 16)); grp.addButton(b); mode_btns[key] = b; b.clicked.connect(lambda _, k=key: change(theme=k)); tr.addWidget(b)
        v.addLayout(tr); v.addWidget(QLabel("System follows the OS dark / light setting live — no restart needed.", objectName="muted"))
        cap("WINDOW EFFECT"); gr = QHBoxLayout(); gc = QComboBox()
        for k, lab in (("mica", "Mica"), ("acrylic", "Acrylic"), ("tabbed", "Mica Alt"), ("off", "Off (solid)")): gc.addItem(lab, k)
        gc.setCurrentIndex(max(0, gc.findData(a.get("glass", "mica")))); gr.addWidget(QLabel("Material"), 1); gr.addWidget(gc); v.addLayout(gr)
        status = QLabel(objectName="muted2", wordWrap=True); v.addWidget(status)
        tr2 = QHBoxLayout(); sl = QSlider(Qt.Horizontal); sl.setRange(40, 100); tl = QLabel(); tr2.addWidget(QLabel("Glass tint"), 1); tr2.addWidget(sl, 2); tr2.addWidget(tl); v.addLayout(tr2)
        def tint_key(): return "dark" if GLASS.dark else "light"
        def tint_move(n): GLASS.tint[tint_key()] = n / 100; tl.setText(f"{n}%"); self.update()
        def tint_done(): a.setdefault("tint", {})[tint_key()] = sl.value() / 100; self.save_appearance()
        sl.valueChanged.connect(tint_move); sl.sliderReleased.connect(tint_done)
        gc.currentIndexChanged.connect(lambda: (a.__setitem__("glass", gc.currentData()), self.save_appearance(), sync()))
        cap("FONT"); fr = QHBoxLayout(); fc = QFontComboBox()
        fc.setCurrentFont(QFont(a.get("font") or pick_font_family()))
        fc.currentFontChanged.connect(lambda f: (a.__setitem__("font", f.family()), self.save_appearance())); fr.addWidget(QLabel("Family")); fr.addWidget(fc, 1)
        sz = QSpinBox(); sz.setRange(10, 20); sz.setValue(int(a.get("size", 13))); sz.valueChanged.connect(lambda n: (a.__setitem__("size", n), self.save_appearance())); fr.addWidget(QLabel("Size")); fr.addWidget(sz); v.addLayout(fr)
        cap("COLOURS"); crows = []
        def crow(label, key, varname):
            r = QHBoxLayout(); r.addWidget(QLabel(label), 1); b = QPushButton(); rb = QPushButton("Reset"); rb.setObjectName("ghost")
            def pick():
                c = QColorDialog.getColor(QColor(a.get(key) or GLASS.p[varname]), d, label)
                if c.isValid(): change(**{key: c.name()})
            b.clicked.connect(pick); rb.clicked.connect(lambda: change(**{key: ""})); r.addWidget(b); r.addWidget(rb); v.addLayout(r); crows.append((key, varname, b, rb))
        crow("Text colour", "text", "text"); crow("Accent colour (buttons, glow)", "accent", "accent"); crow("Background tint", "bg", "bg"); crow("Cards & panels", "surface", "s2")
        mr = QHBoxLayout(); mr.addWidget(QLabel("Animations & transitions"), 1); mc = QCheckBox("On"); mc.setChecked(self.motion()); mc.toggled.connect(lambda on: (a.__setitem__("motion", on), self.save_appearance())); mr.addWidget(mc); v.addLayout(mr)
        cap("TASKS"); ar = QHBoxLayout(); ar.addWidget(QLabel("Auto-priority by due date"), 1); ac = QCheckBox("On"); ac.setChecked(self.auto_prio_on()); ac.setToolTip("Overdue / due today / tomorrow → High · due within 7 days → at least Medium.\nOnly raises priority; tasks whose priority you set by hand are left alone."); ac.toggled.connect(self.set_auto_prio); ar.addWidget(ac); v.addLayout(ar)
        v.addWidget(QLabel("Raises priority as deadlines approach (never lowers it). Setting a priority yourself locks that task; right-click → Priority → Auto to unlock.", objectName="muted", wordWrap=True))
        cap("PRESETS"); pg = QGridLayout()
        for i, (name, theme, vals) in enumerate(PRESETS):
            b = QPushButton(name); bgc = vals.get("bg", THEMES[theme]["bg"]); tc = vals.get("text", THEMES[theme]["text"]); ac = vals.get("accent", THEMES[theme]["accent"])
            b.setStyleSheet(f"background:{bgc};color:{tc};border:1px solid {ac};")
            b.clicked.connect(lambda _, t=theme, vv=vals: change(theme=t, bg=vv.get("bg", ""), surface=vv.get("surface", ""), text=vv.get("text", ""), accent=vv.get("accent", ""))); pg.addWidget(b, i // 4, i % 4)
        v.addLayout(pg)
        rr = QHBoxLayout(); ra = QPushButton("Reset everything to default"); ra.clicked.connect(lambda: change(theme="system", font="", size=13, text="", accent="", bg="", surface="", motion=True, glass="mica", tint={})); rr.addWidget(ra); rr.addStretch()
        cl = QPushButton("Done"); cl.setObjectName("primary"); cl.clicked.connect(d.accept); rr.addWidget(cl); v.addLayout(rr)
        def sync():
            for k, bt in mode_btns.items(): bt.setChecked(a.get("theme", "system") == k)
            for key, var, b, rb in crows:
                cur = a.get(key) or GLASS.p[var]; b.setText(cur); b.setStyleSheet(f"background:{cur};color:{readable_on(cur)};"); rb.setVisible(bool(a.get(key)))
            sl.blockSignals(True); sl.setValue(round(GLASS.tint[tint_key()] * 100)); sl.blockSignals(False); tl.setText(f"{sl.value()}%"); status.setText(self.glass_status())
        sync(); d.exec()


SINGLE_INSTANCE_KEY = f"{APP_NAME}-single-instance-{__import__('getpass').getuser()}"


def main():
    app = QApplication(sys.argv); app.setApplicationName(APP_NAME); app.setQuitOnLastWindowClosed(False)
    from glass import ButtonFocusFilter; app._bff = ButtonFocusFilter(app); app.installEventFilter(app._bff)
    # If TaskTrail is already running (e.g. hidden in the tray), tell it to show itself and exit this copy.
    probe = QLocalSocket(); probe.connectToServer(SINGLE_INSTANCE_KEY)
    if probe.waitForConnected(300):
        probe.write(b"show"); probe.waitForBytesWritten(300); probe.disconnectFromServer(); sys.exit(0)
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)  # clear a stale socket left by a crash
    server = QLocalServer(); server.listen(SINGLE_INSTANCE_KEY)
    store = Store(); w = MainWindow(store); w.show()
    def _on_conn():
        c = server.nextPendingConnection()
        if c: c.readyRead.connect(lambda: (c.readAll(), w.show_window())); c.disconnected.connect(c.deleteLater)
    server.newConnection.connect(_on_conn)
    rc = app.exec(); server.close(); sys.exit(rc)


if __name__ == "__main__":
    main()
