# TaskTrail (formerly FlowBoard Pro) — upgrade notes

## Python-only repository
The Electron/HTML edition has been removed; the PySide6 app that used to live in `python/` is now the repository root.
The data file, its format and the backup layout are unchanged, so existing installs keep all their data.
Installer registry keys are unchanged too, so `TaskTrail-Setup-*.exe` upgrades an existing install in place.

## v2.1
Data file format is unchanged. Everything below is additive.
- **Quick-add in every column** — `Renew SSL !high #ops @fri`. Enter saves; Shift+Enter opens the full form with the parsed values.
- **Calendar page (Alt+4)** — tasks by due date, drag to reschedule, *Unscheduled* tray, double-click a day to add. Checklist tasks with due dates appear too. Card activity gets "Rescheduled to …" / "Due date removed".
- **Search & commands (Ctrl+K)** — tasks from every month and year, plus commands; no match → Enter creates the task.
- **Needs attention** panel on the dashboard — overdue and due-within-7-days items from the board and the checklist, sorted by urgency, click to open.
- **Keyboard** — `[` `]` change month, `Alt 1–4` pages, `?` shortcut sheet.

## v2.0
### Renamed
- App is now **TaskTrail** (Plan · Do · Track). The "Kanban Board" page is now **Task Board**.
- On first launch, the old `%APPDATA%\FlowBoard Pro` data is picked up automatically if the new folder is empty — nothing is lost.

### Data model
- Storage is per **year**: `db.years[2026|2027|…].kanban / .checklist`. Existing data is upgraded automatically on load (it becomes year 2026). Old backups still restore.
- December → January rolls incomplete tasks into the next year. Switch years with ◀ ▶ in the sidebar.

### Task Board
- Drag to **reorder within a column** as well as between columns.
- **Custom columns**: ⋯ on any column header to rename / recolour / move; "+ Column" to add. Built-in columns can't be deleted (the dashboard and rollover depend on them).
- **Labels**: manage via "🏷 Labels"; assign in the task form or the detail panel; filter bar with search, priority and label chips.
- **Card detail panel**: click a card → title, column, priority, due date, labels, description, checklist, comments, and an automatic activity log.

### Appearance (sidebar → Tools)
- Body / heading font, text size, text colour, accent, background, card colour, six presets.

### Backup & Restore (sidebar → Tools)
- Choose any backup folder (e.g. OneDrive — detected automatically with a one-click button), reset to default.
- Backup now, list, restore from the folder, or **Restore from file…**.
- Automatic backups every 30 minutes and on quit, 30 kept.
