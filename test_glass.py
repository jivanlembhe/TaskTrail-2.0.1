"""Headless checks for the glass layer:  QT_QPA_PLATFORM=offscreen python test_glass.py
Uses a throw-away profile, never touches your real TaskTrail data."""
import os, sys, tempfile, copy
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="tt_test_"); os.environ["APPDATA"] = os.environ["XDG_CONFIG_HOME"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer, Qt
app = QApplication(sys.argv)
import glass as G, tasktrail as T

# 1. contrast: every preset, text/secondary/accent text on the *card* surface, white on the primary button
worst = []
for name, theme, vals in [("default", "dark", {}), ("default", "light", {})] + [(n, t, v) for n, t, v in T.PRESETS]:
    p = G.resolve_palette(theme, vals)
    for label, fg, need in (("text", p["text"], 7.0), ("text2", p["text2"], 4.5), ("text3", p["text3"], 4.5), ("accent_text", p["accent_text"], 4.5), ("danger", p["danger"], 4.5)):
        r = G.contrast(fg, p["card"]); worst.append((r, name, theme, label))
        assert r >= need, f"{name}/{theme} {label}: {r:.2f} < {need}"
    r = G.contrast("#ffffff", p["btn_top"]); assert r >= 4.5, f"{name}/{theme} primary button: {r:.2f}"
print(f"contrast OK across {len(T.PRESETS) + 2} palettes; lowest ratio {min(worst)[0]:.2f} ({min(worst)[1:]})")

# 2. window builds, every page renders, theme flips, sidebar collapses
win = T.MainWindow(T.Store()); T.GLASS.motion = False; win.appearance["motion"] = False
win.show(); app.processEvents()
for page in ("dashboard", "kanban", "list", "calendar"): win.show_page(page); app.processEvents()
for mode in ("light", "dark", "system"): win.appearance["theme"] = mode; win.apply_appearance(); app.processEvents()
win.sidebar.set_expanded(False, animate=False); assert win.sidebar.width() == G.Sidebar.W_CLOSED
win.sidebar.set_expanded(True, animate=False); assert win.sidebar.width() == G.Sidebar.W_OPEN
print("pages / themes / sidebar OK")

# 3. overlay blocks + restores the window; quick add creates a task
pal = T.Palette(win); QTimer.singleShot(40, lambda: (setattr(app, "_blocked", not win.centralWidget().isEnabled()), pal.reject())); pal.exec()
assert app._blocked and win.overlay is None and win.centralWidget().isEnabled()
n0 = sum(len(v) for v in win.store.kanban().values()); assert win.qa_submit("todo", "glass test !high #ops @tomorrow")
assert sum(len(v) for v in win.store.kanban().values()) == n0 + 1
print("overlay + quick add OK")

# 4. async job: UI thread keeps ticking, progress is monotonic, errors are reported
loop, out, ticks = QEventLoop(), {"p": []}, []
tm = QTimer(); tm.timeout.connect(lambda: ticks.append(1)); tm.start(2)
snap = copy.copy(win.store); snap.db = copy.deepcopy(win.store.db); path = os.path.join(os.environ["XDG_CONFIG_HOME"], "t.xlsx")
G.run_job(lambda pr: T.export_excel(snap, path, list(range(12)), True, True, True, progress=pr), lambda r: (out.update(ok=1), loop.quit()), lambda e: (out.update(err=e), loop.quit()), lambda f, m: out["p"].append(f))
loop.exec(); assert out.get("ok") and os.path.getsize(path) > 0 and out["p"] == sorted(out["p"]) and ticks
G.run_job(lambda pr: 1 / 0, None, lambda e: (out.update(err=e), loop.quit())); loop.exec(); assert "ZeroDivisionError" in out["err"] and G.GLASS.jobs == 0
print("async jobs OK")
print("ALL GLASS TESTS PASSED")
