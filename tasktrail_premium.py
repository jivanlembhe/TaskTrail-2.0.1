#!/usr/bin/env python3
"""
TaskTrail premium UI launcher.
Run this instead of tasktrail.py to enable the glassmorphism / motion polish.
"""

import tasktrail
from premium_ui import premium_shadow


if not getattr(tasktrail, "_premium_patched", False):
    tasktrail._premium_patched = True

    original_build = tasktrail.MainWindow._build
    def _build(self):
        original_build(self)
        self.sidebar = self.findChild(tasktrail.QFrame, "sidebar")
        self.topbar = self.findChild(tasktrail.QFrame, "topbar")
        self.dock = self.findChild(tasktrail.QDockWidget, "")

    tasktrail.MainWindow._build = _build

    original_apply = tasktrail.MainWindow.apply_appearance
    def apply_appearance(self):
        original_apply(self)
        p = self.palette_dict()
        if hasattr(self, "sidebar") and self.sidebar is not None:
            premium_shadow(self.sidebar, p["accent"], blur=26, y=12)
        if hasattr(self, "topbar") and self.topbar is not None:
            premium_shadow(self.topbar, p["accent"], blur=18, y=8)
        if hasattr(self, "dock") and self.dock is not None:
            premium_shadow(self.dock, p["accent"], blur=24, y=0)

    tasktrail.MainWindow.apply_appearance = apply_appearance


if __name__ == "__main__":
    tasktrail.main()
