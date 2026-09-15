"""Custodian - Windows drive cleaner. PySide6 front end; all safety logic lives in engine.py."""
import os
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

from PySide6.QtCore import QDir, QLockFile, QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import engine
import knowledge
import monitor
import rules
import theme
from widgets import (ConfirmDialog, DriveCard, HazardBar, MetricCard, PulseDot, button, card, label, number,
                     pill)

APP = "Custodian"
VERSION = "1.1.0"
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ICON = os.path.join(BASE, "icon.ico")
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP)
LOG_DIR = os.path.join(DATA_DIR, "logs")

GLYPH = dict(home="", clean="", files="", dupes="", guide="", log="",
             shield="", check="", warn="", info="")


class Log:
    """Append-only session log file, plus a hook for the UI."""

    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        self.path = os.path.join(LOG_DIR, datetime.now().strftime("session_%Y-%m-%d_%H%M%S.log"))
        self.lock = threading.Lock()
        self.sink = None

    def __call__(self, msg):
        line = f"{datetime.now():%H:%M:%S}  {msg}"
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        if self.sink:
            self.sink.emit(line)


class Bus(QObject):
    """Signals are the only way worker threads talk to the UI (queued across threads)."""
    line = Signal(str)
    done = Signal(object, object)       # callback, result
    failed = Signal(str)
    busy = Signal(bool)
    drive = Signal(object)
    recs = Signal(object)


def icon_label(glyph, color=theme.ACCENT, size=16):
    lbl = QLabel(glyph)
    lbl.setFont(theme.icon_font(size))
    lbl.setStyleSheet(f"color:{color}; background: transparent")
    return lbl


def make_tree(cols, first_width=420):
    t = QTreeWidget()
    t.setHeaderLabels(cols)
    t.setUniformRowHeights(True)
    t.setAlternatingRowColors(True)
    t.setSelectionMode(QAbstractItemView.ExtendedSelection)
    t.setColumnWidth(0, first_width)
    t.header().setStretchLastSection(True)
    for c in range(1, len(cols) - 1):
        t.header().setSectionResizeMode(c, QHeaderView.ResizeToContents)
    t.setContextMenuPolicy(Qt.CustomContextMenu)
    return t


# =============================================================================== pages

class Page(QWidget):
    title, subtitle, glyph = "", "", ""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(24, 18, 24, 18)
        self.lay.setSpacing(14)
        win.bus.busy.connect(self.on_busy)
        win.bus.drive.connect(self.on_drive)

    def on_busy(self, busy):
        pass

    def on_drive(self, drive):
        pass

    def scan(self):
        pass


class ActionBar(QFrame):
    """Selected total, delete mode (Permanent / Recycle Bin) and the destructive button."""
    RECYCLE_TIP = "Move to the Recycle Bin. Recoverable, but space is only freed when the bin is emptied."

    def __init__(self, verb, recycle_default):
        super().__init__()
        self.setProperty("card", True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 12, 10)
        self.selected = label("Nothing selected", size=13, bold=True)
        lay.addWidget(self.selected)
        lay.addStretch(1)
        lay.addWidget(label("Delete mode", muted=True))
        self.permanent = QPushButton("Permanent")
        self.recycle = QPushButton("Recycle Bin")
        self.group = QButtonGroup(self)
        for b in (self.permanent, self.recycle):
            b.setCheckable(True)
            b.setProperty("seg", True)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b)
            lay.addWidget(b)
        self.permanent.setToolTip("Delete immediately and free the space now. Cannot be undone.")
        self.recycle.setToolTip(self.RECYCLE_TIP)
        self.recycle_default = recycle_default
        (self.recycle if recycle_default else self.permanent).setChecked(True)
        lay.addSpacing(10)
        self.go = button(verb, danger=True)
        self.go.setEnabled(False)
        lay.addWidget(self.go)

    @property
    def use_recycle(self):
        return self.recycle.isChecked()

    def set_drive(self, drive):
        ok = bool(drive) and engine.has_recycle_bin(drive.root)
        self.recycle.setEnabled(ok)
        if ok:
            self.recycle.setToolTip(self.RECYCLE_TIP)
            (self.recycle if self.recycle_default else self.permanent).setChecked(True)
        else:
            self.permanent.setChecked(True)
            self.recycle.setToolTip("This drive has no Recycle Bin (removable drive). Deletion is permanent.")

    def set_selection(self, items, enabled):
        size = sum(i.size for i in items)
        self.selected.setText(f"{len(items):,} selected, {engine.fmt_size(size)}" if items else "Nothing selected")
        self.go.setEnabled(bool(items) and enabled)


class ResultsPage(Page):
    """Shared behaviour for pages that scan, show a checkable tree and delete the selection."""
    verb, recycle_default, personal = "Delete selected", False, False

    def __init__(self, win):
        super().__init__(win)
        self.result = None
        self.guard = None

    def build_bottom(self):
        self.bar = ActionBar(self.verb, self.recycle_default)
        self.bar.go.clicked.connect(self.delete_selected)
        self.lay.addWidget(self.bar)
        self.tree.itemChanged.connect(self.refresh_selection)
        self.tree.customContextMenuRequested.connect(self.context_menu)

    def on_drive(self, drive):
        self.bar.set_drive(drive)
        if self.result and (not drive or self.result.root != drive.root):
            self.clear("Drive changed. Scan again.")

    def on_busy(self, busy):
        self.scan_btn.setEnabled(not busy)
        self.tree.setEnabled(not busy)
        self.refresh_selection()

    def clear(self, msg):
        self.result = self.guard = None
        self.tree.clear()
        self.summary.setText(msg)
        self.refresh_selection()

    def nodes(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            node = stack.pop()
            stack.extend(node.child(i) for i in range(node.childCount()))
            yield node

    def checked(self):
        return [n.data(0, Qt.UserRole) for n in self.nodes()
                if n.data(0, Qt.UserRole) is not None and not n.data(0, Qt.UserRole).blocked
                and n.checkState(0) == Qt.Checked]

    def set_all(self, state, predicate=lambda item: True):
        self.tree.blockSignals(True)
        for node in self.nodes():
            item = node.data(0, Qt.UserRole)
            if item is not None and node.flags() & Qt.ItemIsUserCheckable:
                node.setCheckState(0, state if predicate(item) else Qt.Unchecked)
        self.tree.blockSignals(False)
        self.tree.viewport().update()
        self.refresh_selection()

    def refresh_selection(self, *_):
        if hasattr(self, "bar"):
            self.bar.set_selection(self.checked() if self.result else [], not self.win.busy())

    def context_menu(self, pos):
        node = self.tree.itemAt(pos)
        item = node and node.data(0, Qt.UserRole)
        if not item:
            return
        path = item.paths[0]
        menu = QMenu(self)
        target = path if os.path.isdir(path) else os.path.dirname(path)
        menu.addAction("Open location", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(target)))
        if self.personal and os.path.isfile(path):
            menu.addAction("Open file", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        menu.addAction("Copy path", lambda: QGuiApplication.clipboard().setText("\n".join(item.paths)))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def delete_selected(self):
        win = self.win
        if win.busy() or not self.result:
            return
        if not win.drive or win.drive.root != self.result.root:
            return self.clear("Drive changed. Scan again before deleting.")
        items = self.checked()
        if not items:
            return
        recycle = self.bar.use_recycle
        size = sum(i.size for i in items)
        personal = any(i.rule["action"] == "userfile" for i in items)
        review = [i for i in items if i.rule["risk"] != rules.SAFE and i.rule["action"] != "userfile"]
        c = theme
        lines = [f"<b>{len(items):,}</b> item(s) on <b>{self.result.root[:2]}</b> totalling "
                 f"<b style='color:{c.ACCENT}'>{engine.fmt_size(size)}</b>.", ""]
        if recycle:
            lines.append(f"<span style='color:{c.MINT}'><b>Recycle Bin mode</b></span>: everything stays recoverable. "
                         "Free space only goes up after you empty the bin.")
        else:
            lines.append(f"<span style='color:{c.RED}'><b>Permanent mode</b></span>: removed immediately and "
                         "cannot be recovered.")
        if review:
            lines += ["", f"<span style='color:{c.AMBER}'><b>Marked Review:</b></span>"]
            lines += [f"&nbsp;&nbsp;• {i.label} <span style='color:{c.MUTED}'>({engine.fmt_size(i.size)})</span>"
                      for i in review[:10]]
            if len(review) > 10:
                lines.append(f"&nbsp;&nbsp;… and {len(review) - 10} more")
        if any(i.group for i in items):
            lines += ["", "At least one copy of every duplicate set is always kept."]
        lines += ["", f"<span style='color:{c.MUTED}'>Files used by open apps are skipped. Every path is re-checked "
                      "against the guard rails first. Press Stop (Esc) at any time.</span>"]
        ack = "I understand these personal files cannot be recovered" if personal and not recycle else None
        dlg = ConfirmDialog(win, "Move to Recycle Bin?" if recycle else "Delete permanently?", lines,
                            "Move to Recycle Bin" if recycle else "Delete permanently", danger=not recycle, ack=ack)
        if not dlg.exec():
            return

        root, guard = self.result.root, self.guard
        win.log(f"{'Recycle' if recycle else 'Delete'} started on {root}: {len(items)} item(s), {engine.fmt_size(size)}")

        def job():
            before = engine.free_space(root)
            out = engine.clean(items, guard, win.cancel, win.progress, win.log, recycle, win.stats)
            out["gained"] = engine.free_space(root) - before
            return out
        win.run_task("Recycling" if recycle else "Cleaning", job, self.cleaned)

    def cleaned(self, out):
        gained = max(out["gained"], 0)
        msg = f"Freed {engine.fmt_size(gained)} from {out['files']:,} files"
        if out["moved"]:
            msg += f", {engine.fmt_size(out['moved'])} moved to the Recycle Bin"
        extra = [f"{out['errors']:,} locked" if out["errors"] else "",
                 f"{out['skipped']} skipped" if out["skipped"] else "",
                 f"{out['refused']} refused by guard rails" if out["refused"] else ""]
        extra = [x for x in extra if x]
        if extra:
            msg += " (" + ", ".join(extra) + ")"
        self.win.log("RESULT " + msg)
        self.win.session_freed += gained
        self.clear(msg + ". Scan again to see what is left.")
        self.win.refresh_drives()
        self.win.flash(msg, theme.MINT if not out["errors"] and not out["refused"] else theme.AMBER)


class CleanupPage(ResultsPage):
    title, subtitle, glyph = "Cleanup", "Junk, caches and leftovers on the selected drive", GLYPH["clean"]
    verb, recycle_default = "Clean selected", False

    def __init__(self, win):
        super().__init__(win)
        top = QHBoxLayout()
        self.scan_btn = button("Scan drive", primary=True, tip="Read-only. Nothing is deleted. (F5)")
        self.scan_btn.clicked.connect(self.scan)
        top.addWidget(self.scan_btn)
        self.deep = QCheckBox("Search the whole drive")
        self.deep.setToolTip("Also finds node_modules, __pycache__, test caches, dumps, Office lock files and "
                             "macOS metadata anywhere on the drive.")
        self.deep.setChecked(win.settings.value("cleanup/deep", True, type=bool))
        top.addWidget(self.deep)
        self.users = QCheckBox("All user accounts")
        self.users.setChecked(win.admin and win.settings.value("cleanup/users", True, type=bool))
        self.users.setEnabled(win.admin)
        self.users.setToolTip("Clean caches and temp files of every account on this PC." if win.admin
                              else "Restart as administrator to include other accounts.")
        top.addWidget(self.users)
        top.addStretch(1)
        for text, fn in (("Select safe", lambda: self.set_all(Qt.Checked, lambda i: i.rule["risk"] == rules.SAFE)),
                         ("Select all", lambda: self.set_all(Qt.Checked)),
                         ("Select none", lambda: self.set_all(Qt.Unchecked)),
                         ("Expand / collapse", self.toggle_expand)):
            b = button(text)
            b.clicked.connect(fn)
            top.addWidget(b)
        self.lay.addLayout(top)
        self.summary = label("Press Scan. Scanning is read-only and never deletes anything.", muted=True)
        self.lay.addWidget(self.summary)
        self.tree = make_tree(["Item", "Size", "Files", "Risk", "Details"], 400)
        self.lay.addWidget(self.tree, 1)
        self.build_bottom()

    def on_busy(self, busy):
        super().on_busy(busy)
        self.deep.setEnabled(not busy)
        self.users.setEnabled(not busy and self.win.admin)

    def refresh_selection(self, *_):
        # ticking a category also ticks its blocked rows; untick them so the view never lies
        blocked = [n for n in self.nodes() if n.data(0, Qt.UserRole) is not None
                   and n.data(0, Qt.UserRole).blocked and n.checkState(0) != Qt.Unchecked]
        if blocked:
            self.tree.blockSignals(True)
            for n in blocked:
                n.setCheckState(0, Qt.Unchecked)
            self.tree.blockSignals(False)
            self.tree.viewport().update()
        super().refresh_selection()

    def toggle_expand(self):
        expand = not any(self.tree.topLevelItem(i).isExpanded() for i in range(self.tree.topLevelItemCount()))
        (self.tree.expandAll if expand else self.tree.collapseAll)()

    def scan(self):
        win = self.win
        if win.busy() or not win.drive:
            return
        root, deep, users = win.drive.root, self.deep.isChecked(), self.users.isChecked()
        win.settings.setValue("cleanup/deep", deep)
        if win.admin:
            win.settings.setValue("cleanup/users", users)
        self.clear(f"Scanning {root[:2]} …")
        guard = engine.Guard(root)
        win.log(f"Junk scan on {root} (whole drive={deep}, all accounts={users})")
        win.run_task("Scanning for junk",
                     lambda: (engine.scan(root, guard, win.cancel, win.progress, deep=deep, admin=win.admin,
                                          all_users=users, stats=win.stats), guard), self.scanned)

    def scanned(self, payload):
        self.result, self.guard = payload
        res = self.result
        self.fill(res.items)
        total = sum(i.size for i in res.items)
        safe = sum(i.size for i in res.items if i.rule["risk"] == rules.SAFE and not i.blocked)
        blocked = sum(1 for i in res.items if i.blocked)
        text = (f"Found {engine.fmt_size(total)} in {len(res.items)} items ({engine.fmt_size(safe)} marked safe) "
                f"in {res.seconds:.0f}s.")
        if blocked:
            text += f"  {blocked} blocked: close the named apps or restart as administrator, then scan again."
        self.summary.setText(text)
        self.win.log(text)
        self.refresh_selection()
        self.win.flash(f"Scan complete: {engine.fmt_size(total)} found", theme.ACCENT)

    def fill(self, items):
        t = self.tree
        t.blockSignals(True)
        t.clear()
        cats = {}
        for item in sorted(items, key=lambda i: (i.rule["cat"], -i.size)):
            cat = cats.get(item.rule["cat"])
            if cat is None:
                cat = cats[item.rule["cat"]] = QTreeWidgetItem(t, [item.rule["cat"]])
                cat.setFlags(cat.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                f = cat.font(0)
                f.setBold(True)
                cat.setFont(0, f)
            name = item.where if item.rule["id"] == "node_modules" else item.label
            safe = item.rule["risk"] == rules.SAFE
            leaf = QTreeWidgetItem(cat, [name, engine.fmt_size(item.size), f"{item.files:,}", "Safe" if safe else "Review",
                                  item.rule["note"] or item.where])
            leaf.setData(0, Qt.UserRole, item)
            leaf.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            leaf.setForeground(3, QColor(theme.MINT if safe else theme.AMBER))
            tip = "\n".join(item.paths[:40]) + (f"\n… and {len(item.paths) - 40:,} more" if len(item.paths) > 40 else "")
            leaf.setToolTip(0, tip)
            leaf.setToolTip(4, f"{item.rule['note']}\n\n{tip}".strip())
            if item.blocked:
                # Qt derives a category's box from its children; a child without a state hides it
                leaf.setCheckState(0, Qt.Unchecked)
                leaf.setFlags(leaf.flags() & ~Qt.ItemIsUserCheckable & ~Qt.ItemIsEnabled)
                leaf.setText(4, f"Blocked: {item.blocked}")
                leaf.setForeground(4, QColor(theme.AMBER))
            else:
                leaf.setFlags(leaf.flags() | Qt.ItemIsUserCheckable)
                leaf.setCheckState(0, Qt.Checked if safe else Qt.Unchecked)
        for cat in cats.values():
            kids = [cat.child(i) for i in range(cat.childCount())]
            states = {k.checkState(0) for k in kids if k.flags() & Qt.ItemIsUserCheckable}
            if states:   # setting a parent only propagates to checkable (unblocked) children
                cat.setCheckState(0, states.pop() if len(states) == 1 else Qt.PartiallyChecked)
            size = sum(k.data(0, Qt.UserRole).size for k in kids)
            cat.setText(1, engine.fmt_size(size))
            cat.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            cat.setForeground(1, QColor(theme.ACCENT))
            cat.setExpanded(True)
        if not items:
            QTreeWidgetItem(t, ["Nothing to clean was found on this drive."])
        t.blockSignals(False)


class FilesPage(ResultsPage):
    title, subtitle, glyph = "Large & old files", "Your biggest and most forgotten files", GLYPH["files"]
    verb, recycle_default, personal = "Delete selected", True, True

    def __init__(self, win):
        super().__init__(win)
        top = QHBoxLayout()
        self.scan_btn = button("Find files", primary=True, tip="Read-only. (F5)")
        self.scan_btn.clicked.connect(self.scan)
        top.addWidget(self.scan_btn)
        top.addWidget(label("Bigger than", muted=True))
        self.min_mb = QSpinBox(minimum=1, maximum=1_000_000, singleStep=50, suffix=" MB")
        self.min_mb.setValue(win.settings.value("files/min_mb", 250, type=int))
        top.addWidget(self.min_mb)
        top.addWidget(label("Not modified for", muted=True))
        self.days = QSpinBox(minimum=0, maximum=3650, singleStep=30, suffix=" days")
        self.days.setSpecialValueText("any age")
        self.days.setValue(win.settings.value("files/days", 0, type=int))
        top.addWidget(self.days)
        top.addStretch(1)
        for text, fn in (("Select all", lambda: self.set_all(Qt.Checked)),
                         ("Select none", lambda: self.set_all(Qt.Unchecked))):
            b = button(text)
            b.clicked.connect(fn)
            top.addWidget(b)
        self.lay.addLayout(top)
        self.summary = label("Finds large files outside Windows and program folders. Nothing is selected for you.",
                             muted=True)
        self.lay.addWidget(self.summary)
        self.tree = make_tree(["File", "Size", "Modified", "Folder"], 360)
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionsClickable(True)
        self.tree.header().setSortIndicatorShown(True)
        self.tree.header().sectionClicked.connect(self.sort_by)
        self.sort_col, self.sort_desc = 1, True
        self.lay.addWidget(self.tree, 1)
        self.build_bottom()

    def sort_by(self, col):
        # manual sort: Qt's item sorting with Python keys is unreliable in PySide
        self.sort_desc = not self.sort_desc if col == self.sort_col else col in (1, 2)
        self.sort_col = col
        t = self.tree
        t.blockSignals(True)
        nodes = [t.takeTopLevelItem(0) for _ in range(t.topLevelItemCount())]
        nodes.sort(key=lambda n: (n.data(0, Qt.UserRole).size if col == 1 else
                                  n.data(0, Qt.UserRole).mtime if col == 2 else n.text(col).lower()),
                   reverse=self.sort_desc)
        t.addTopLevelItems(nodes)
        t.blockSignals(False)
        t.header().setSortIndicator(col, Qt.DescendingOrder if self.sort_desc else Qt.AscendingOrder)

    def scan(self):
        win = self.win
        if win.busy() or not win.drive:
            return
        root, mb, days = win.drive.root, self.min_mb.value(), self.days.value()
        win.settings.setValue("files/min_mb", mb)
        win.settings.setValue("files/days", days)
        self.clear(f"Searching {root[:2]} …")
        guard = engine.Guard(root)
        win.log(f"Large file search on {root} (>= {mb} MB, untouched for {days} days)")
        win.run_task("Finding large files",
                     lambda: (engine.scan_files(root, guard, win.cancel, mb, days, stats=win.stats), guard),
                     self.scanned)

    def scanned(self, payload):
        self.result, self.guard = payload
        res = self.result
        t = self.tree
        t.blockSignals(True)
        t.clear()
        for item in res.items:
            p = item.paths[0]
            leaf = QTreeWidgetItem(t, [os.path.basename(p), engine.fmt_size(item.size),
                                datetime.fromtimestamp(item.mtime).strftime("%Y-%m-%d"), os.path.dirname(p)])
            leaf.setData(0, Qt.UserRole, item)
            leaf.setData(1, Qt.UserRole + 1, item.size)
            leaf.setData(2, Qt.UserRole + 1, item.mtime)
            leaf.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            leaf.setForeground(1, QColor(theme.usage_color(min(item.size / (4 << 30), 1.0))))
            leaf.setToolTip(0, p)
            leaf.setFlags(leaf.flags() | Qt.ItemIsUserCheckable)
            leaf.setCheckState(0, Qt.Unchecked)
        t.blockSignals(False)
        self.sort_col, self.sort_desc = 1, True
        t.header().setSortIndicator(1, Qt.DescendingOrder)
        total = sum(i.size for i in res.items)
        self.summary.setText(f"{len(res.items):,} files totalling {engine.fmt_size(total)}, found in {res.seconds:.0f}s. "
                             "Right-click to open a file or its folder. Click a column to sort.")
        self.refresh_selection()
        self.win.flash(f"Found {len(res.items):,} large files totalling {engine.fmt_size(total)}", theme.ACCENT)


class DuplicatesPage(ResultsPage):
    title, subtitle, glyph = "Duplicates", "Identical files, compared by content", GLYPH["dupes"]
    verb, recycle_default, personal = "Remove selected copies", True, True

    def __init__(self, win):
        super().__init__(win)
        top = QHBoxLayout()
        self.scan_btn = button("Find duplicates", primary=True, tip="Read-only. (F5)")
        self.scan_btn.clicked.connect(self.scan)
        top.addWidget(self.scan_btn)
        top.addWidget(label("Files bigger than", muted=True))
        self.min_mb = QSpinBox(minimum=0, maximum=100_000, suffix=" MB")
        self.min_mb.setSpecialValueText("any size")
        self.min_mb.setValue(win.settings.value("dupes/min_mb", 1, type=int))
        top.addWidget(self.min_mb)
        top.addStretch(1)
        for text, fn in (("Keep oldest, select rest", lambda: self.auto_select(oldest=True)),
                         ("Keep newest, select rest", lambda: self.auto_select(oldest=False)),
                         ("Select none", lambda: self.set_all(Qt.Unchecked))):
            b = button(text)
            b.clicked.connect(fn)
            top.addWidget(b)
        self.lay.addLayout(top)
        self.summary = label("Skips Windows, program folders, AppData, node_modules and .git. "
                             "At least one copy of every set is always kept.", muted=True)
        self.lay.addWidget(self.summary)
        self.tree = make_tree(["File", "Size", "Modified", "Folder"], 360)
        self.lay.addWidget(self.tree, 1)
        self.build_bottom()

    def auto_select(self, oldest):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            kids = [group.child(k) for k in range(group.childCount())]
            if kids:
                keep = (min if oldest else max)(kids, key=lambda n: n.data(0, Qt.UserRole).mtime)
                for k in kids:
                    k.setCheckState(0, Qt.Unchecked if k is keep else Qt.Checked)
        self.tree.blockSignals(False)
        self.tree.viewport().update()
        self.refresh_selection()

    def scan(self):
        win = self.win
        if win.busy() or not win.drive:
            return
        root, mb = win.drive.root, self.min_mb.value()
        win.settings.setValue("dupes/min_mb", mb)
        self.clear(f"Comparing files on {root[:2]} …")
        guard = engine.Guard(root)
        win.log(f"Duplicate search on {root} (>= {mb} MB)")
        win.run_task("Finding duplicates",
                     lambda: (engine.find_duplicates(root, guard, win.cancel, mb or 0.001, win.progress, win.stats),
                              guard), self.scanned)

    def scanned(self, payload):
        self.result, self.guard = payload
        res = self.result
        t = self.tree
        t.blockSignals(True)
        t.clear()
        groups = {}
        for item in res.items:
            groups.setdefault(item.group, []).append(item)
        waste = 0
        for members in groups.values():
            size, copies = members[0].size, len(members[0].peers)
            waste += size * (copies - 1)
            head = QTreeWidgetItem(t, [f"{os.path.basename(members[0].paths[0])}   ({copies} copies)", engine.fmt_size(size),
                                "", f"{engine.fmt_size(size * (copies - 1))} reclaimable"])
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            head.setForeground(3, QColor(theme.SKY))
            for item in members:
                p = item.paths[0]
                leaf = QTreeWidgetItem(head, [os.path.basename(p), engine.fmt_size(size),
                                       datetime.fromtimestamp(item.mtime).strftime("%Y-%m-%d %H:%M"),
                                       os.path.dirname(p)])
                leaf.setData(0, Qt.UserRole, item)
                leaf.setToolTip(0, p)
                leaf.setFlags(leaf.flags() | Qt.ItemIsUserCheckable)
                leaf.setCheckState(0, Qt.Unchecked)
            head.setExpanded(len(groups) <= 200)
        t.blockSignals(False)
        self.summary.setText(f"{len(groups):,} duplicate sets, {engine.fmt_size(waste)} reclaimable, found in "
                             f"{res.seconds:.0f}s. Nothing is selected until you choose.")
        self.refresh_selection()
        self.win.flash(f"{len(groups):,} duplicate sets, {engine.fmt_size(waste)} reclaimable", theme.SKY)


class DashboardPage(Page):
    title, subtitle, glyph = "Dashboard", "Live view of your drives and machine", GLYPH["home"]

    def __init__(self, win):
        super().__init__(win)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(0, 0, 8, 0)
        self.body.setSpacing(14)
        scroll.setWidget(body)
        self.lay.addWidget(scroll)

        self.body.addWidget(label("Drives", h2=True))
        self.drive_grid = QGridLayout()
        self.drive_grid.setSpacing(14)
        self.body.addLayout(self.drive_grid)
        self.cards = {}

        self.body.addWidget(label("Live activity", h2=True))
        row = QHBoxLayout()
        row.setSpacing(14)
        self.cpu = MetricCard("Processor", theme.ACCENT, 100)
        self.ram = MetricCard("Memory", theme.SKY, 100)
        self.disk = MetricCard("Disk activity", theme.MINT)
        for m in (self.cpu, self.ram, self.disk):
            row.addWidget(m)
        self.body.addLayout(row)

        head = QHBoxLayout()
        head.addWidget(label("Recommendations", h2=True))
        self.rec_status = label("", muted=True)
        head.addWidget(self.rec_status)
        head.addStretch(1)
        self.rec_btn = button("Re-check")
        self.rec_btn.clicked.connect(win.check_recommendations)
        head.addWidget(self.rec_btn)
        self.body.addLayout(head)
        self.recs = QVBoxLayout()
        self.recs.setSpacing(10)
        self.body.addLayout(self.recs)
        self.body.addStretch(1)
        win.bus.recs.connect(self.show_recs)

    def update_drives(self, drives):
        roots = [d.root for d in drives]
        if list(self.cards) != roots:
            for c in self.cards.values():
                c.setParent(None)
            self.cards = {}
            for n, d in enumerate(drives):
                self.cards[d.root] = DriveCard(d)
                self.drive_grid.addWidget(self.cards[d.root], n // 3, n % 3)
        else:
            for d in drives:
                self.cards[d.root].update_drive(d)

    def update_metrics(self, s):
        self.cpu.update_value(s["cpu"], f"{s['cpu']:.0f}%", "all cores")
        self.ram.update_value(s["ram"], f"{s['ram']:.0f}%",
                              f"{engine.fmt_size(s['ram_used'])} of {engine.fmt_size(s['ram_total'])}")
        io = s["disk_read"] + s["disk_write"]
        self.disk.update_value(io, f"{engine.fmt_size(int(io))}/s",
                               f"read {engine.fmt_size(int(s['disk_read']))}/s, "
                               f"write {engine.fmt_size(int(s['disk_write']))}/s")

    def show_recs(self, recs):
        while self.recs.count():
            w = self.recs.takeAt(0).widget()
            if w:
                w.setParent(None)
        self.rec_status.setText(f"checked {datetime.now():%H:%M}")
        self.rec_btn.setEnabled(True)
        glyphs = {"critical": GLYPH["warn"], "warn": GLYPH["warn"], "info": GLYPH["info"], "good": GLYPH["check"]}
        for level, title, detail, action in recs:
            color = theme.LEVEL[level]
            frame, lay = card(QHBoxLayout, 14, 12)
            frame.setStyleSheet(f"QFrame[card='true']{{border-left: 4px solid {color};}}")
            lay.addWidget(icon_label(glyphs[level], color, 22))
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(label(title, size=13, bold=True))
            col.addWidget(label(detail, muted=True, wrap=True))
            lay.addLayout(col, 1)
            if action:
                b = button(action["label"], primary=level in ("critical", "warn"))
                b.clicked.connect(lambda _=False, a=action: self.win.do_action(a))
                lay.addWidget(b)
            self.recs.addWidget(frame)


class GuidePage(Page):
    title, subtitle, glyph = "Toolbox & Guide", "Every cleaning procedure, explained and one click away", GLYPH["guide"]

    def __init__(self, win):
        super().__init__(win)
        self.search = QLineEdit(placeholderText="Search procedures  (hibernation, docker, windows.old, restore …)")
        self.search.textChanged.connect(self.filter)
        self.lay.addWidget(self.search)
        chips = QHBoxLayout()
        self.cat_group = QButtonGroup(self)
        for n, cat in enumerate(["All"] + knowledge.CATEGORIES):
            b = QPushButton(cat.replace("&", "&&"))
            b.setProperty("category", cat)
            b.setCheckable(True)
            b.setProperty("chip", True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(n == 0)
            self.cat_group.addButton(b)
            chips.addWidget(b)
        chips.addStretch(1)
        self.cat_group.buttonClicked.connect(lambda _: self.filter())
        self.lay.addLayout(chips)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        self.grid = QGridLayout(body)
        self.grid.setSpacing(14)
        self.grid.setContentsMargins(0, 0, 8, 0)
        self.grid.setAlignment(Qt.AlignTop)
        scroll.setWidget(body)
        self.lay.addWidget(scroll, 1)
        self.run_buttons = []
        self.cards = [(g, self.make_card(g)) for g in knowledge.GUIDE]
        self.filter()

    def make_card(self, g):
        frame, lay = card(QVBoxLayout, 16, 8)
        head = QHBoxLayout()
        head.addWidget(label(g["title"], size=14, bold=True), 1)
        if g["impact"] != "-":
            head.addWidget(pill(g["impact"], theme.ACCENT))
        head.addWidget(pill(g["risk"].capitalize(), theme.RISK[g["risk"]]))
        lay.addLayout(head)
        lay.addWidget(label(g["cat"], muted=True))
        lay.addWidget(label(g["summary"], wrap=True))
        if g["steps"]:
            steps = label("".join(f"<p style='margin:3px 0'><span style='color:{theme.ACCENT}'><b>{n}.</b></span> "
                                  f"{s}</p>" for n, s in enumerate(g["steps"], 1)), wrap=True)
            steps.setTextFormat(Qt.RichText)
            steps.setVisible(False)
            toggle = QPushButton("▸ Show steps")
            toggle.setProperty("link", True)
            toggle.setCursor(Qt.PointingHandCursor)
            toggle.clicked.connect(lambda _=False, s=steps, t=toggle: (
                s.setVisible(not s.isVisible()), t.setText("▾ Hide steps" if s.isVisible() else "▸ Show steps")))
            lay.addWidget(toggle)
            lay.addWidget(steps)
        row = None
        for n, a in enumerate(g["actions"]):
            if n % 3 == 0:
                row = QHBoxLayout()
                row.setSpacing(8)
                lay.addLayout(row)
            b = button(a["label"], primary=a["kind"] == "page")
            b.clicked.connect(lambda _=False, act=a: self.win.do_action(act))
            if a["kind"] == "run":
                self.run_buttons.append((b, a))
                b.setToolTip("Runs: " + subprocess.list2cmdline(a["args"]) +
                             ("\nNeeds administrator." if a["admin"] else ""))
            row.addWidget(b)
            if n % 3 == 2 or n == len(g["actions"]) - 1:
                row.addStretch(1)
        return frame

    def on_busy(self, busy):
        for b, a in self.run_buttons:
            b.setEnabled(not busy and (self.win.admin or not a["admin"]))

    def focus(self, guide_id):
        g = knowledge.GUIDE_BY_ID.get(guide_id)
        if g:
            self.cat_group.buttons()[0].setChecked(True)
            self.search.setText(g["title"])

    def filter(self):
        text = self.search.text().strip().lower()
        cat = self.cat_group.checkedButton().property("category")
        for _, frame in self.cards:
            self.grid.removeWidget(frame)
            frame.hide()
        n = 0
        for g, frame in self.cards:
            hay = " ".join([g["title"], g["summary"], g["cat"], *g["steps"]]).lower()
            if (cat == "All" or g["cat"] == cat) and all(w in hay for w in text.split()):
                self.grid.addWidget(frame, n // 2, n % 2)
                frame.show()
                n += 1
        self.on_busy(self.win.busy())


class LogPage(Page):
    title, subtitle, glyph = "Activity", "Everything Custodian did, also saved to disk", GLYPH["log"]

    def __init__(self, win):
        super().__init__(win)
        top = QHBoxLayout()
        top.addWidget(label(f"Log file: {win.logger.path}", muted=True), 1)
        for text, fn in (("Open log folder", lambda: os.startfile(LOG_DIR)),
                         ("Copy all", lambda: QGuiApplication.clipboard().setText(self.view.toPlainText())),
                         ("Clear view", lambda: self.view.clear())):
            b = button(text)
            b.clicked.connect(fn)
            top.addWidget(b)
        self.lay.addLayout(top)
        self.view = QPlainTextEdit(readOnly=True)
        self.view.setMaximumBlockCount(50000)
        self.lay.addWidget(self.view, 1)
        win.bus.line.connect(self.append)

    def append(self, line):
        body = line[10:]
        color = (theme.RED if body.startswith(("ERROR", "REFUSED", "UNHANDLED")) or "could not" in body else
                 theme.AMBER if body.startswith(("SKIPPED", "KEPT", "Stopped")) else
                 theme.MINT if body.startswith(("CLEANED", "RECYCLED", "RESULT")) else
                 theme.ACCENT if body.startswith("> ") else None)
        if color:
            esc = line.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
            self.view.appendHtml(f"<span style='color:{color}'>{esc}</span>")
        else:
            self.view.appendPlainText(line)


# =============================================================================== window

PAGES = (("dashboard", DashboardPage), ("cleanup", CleanupPage), ("files", FilesPage),
         ("duplicates", DuplicatesPage), ("guide", GuidePage), ("log", LogPage))


class Main(QMainWindow):
    def __init__(self, logger, lock):
        super().__init__()
        self.logger, self.lock = logger, lock
        self.bus = Bus()
        logger.sink = self.bus.line
        self.settings = QSettings(APP, APP)
        self.admin = engine.is_admin()
        self.cancel = threading.Event()
        self.stats = engine.Stats()
        self.worker = None
        self.proc = None
        self.stoppable = True
        self.progress_text, self.progress_frac = "", None
        self.drive = None
        self.drives = []
        self.session_freed = 0
        self.monitor = monitor.Monitor()

        self.setWindowTitle(f"{APP} (Administrator)" if self.admin else APP)
        self.setWindowIcon(QIcon(ICON))
        self.resize(1360, 880)
        self.setMinimumSize(1080, 700)
        geo = self.settings.value("window/geometry")
        if geo:
            self.restoreGeometry(geo)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.build_sidebar())
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self.build_header())
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        right.addWidget(self.build_taskbar())
        root.addLayout(right, 1)
        self.setCentralWidget(central)

        self.bus.done.connect(lambda cb, res: cb(res))
        self.bus.failed.connect(self.task_failed)
        self.pages = {}
        for key, cls in PAGES:
            self.pages[key] = cls(self)
            self.stack.addWidget(self.pages[key])

        for n, (key, _) in enumerate(PAGES, 1):
            QShortcut(QKeySequence(f"Ctrl+{n}"), self, activated=lambda k=key: self.show_page(k))
        QShortcut(QKeySequence("F5"), self, activated=lambda: self.stack.currentWidget().scan())
        QShortcut(QKeySequence("Escape"), self, activated=self.stop)

        self.refresh_drives()
        self.show_page(self.settings.value("window/page", "dashboard"))
        self.log(f"{APP} {VERSION} started, administrator: {self.admin}, log: {logger.path}")

        QTimer(self, interval=100, timeout=self.tick_task).start()
        QTimer(self, interval=1000, timeout=self.tick_metrics).start()
        QTimer(self, interval=2500, timeout=self.refresh_drives).start()
        self.tick_metrics()
        self.check_recommendations()

    # ------------------------------------------------------------------ chrome
    def build_sidebar(self):
        side = QFrame(objectName="sidebar")
        side.setFixedWidth(236)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 18, 14, 16)
        lay.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(ICON).pixmap(36, 36))
        brand.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(QLabel(APP, objectName="brand"))
        col.addWidget(label("Drive care for Windows", muted=True))
        brand.addLayout(col)
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(18)
        self.nav_buttons = {}
        group = QButtonGroup(self)
        font = QFont()
        font.setFamilies(["Segoe UI Variable Text", "Segoe UI", theme.ICON_FONT, "Segoe MDL2 Assets"])
        font.setPixelSize(14)
        for n, (key, cls) in enumerate(PAGES, 1):
            b = QPushButton(f"{cls.glyph}     {cls.title.replace('&', '&&')}")
            b.setFont(font)
            b.setProperty("nav", True)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"Ctrl+{n}")
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            group.addButton(b)
            self.nav_buttons[key] = b
            lay.addWidget(b)
        lay.addStretch(1)

        box, blay = card(QVBoxLayout, 12, 6)
        head = QHBoxLayout()
        head.addWidget(icon_label(GLYPH["shield"], theme.MINT if self.admin else theme.AMBER, 18))
        head.addWidget(label("Administrator" if self.admin else "Standard mode", bold=True))
        head.addStretch(1)
        blay.addLayout(head)
        blay.addWidget(label("Full access to Windows folders, all accounts and system tools." if self.admin
                             else "Windows folders, other accounts and system tools need administrator.",
                             muted=True, wrap=True))
        if not self.admin:
            b = button("Restart as administrator", primary=True)
            b.clicked.connect(self.elevate)
            blay.addWidget(b)
        lay.addWidget(box)
        lay.addSpacing(6)
        self.freed_label = label("", color=theme.MINT, bold=True)
        lay.addWidget(self.freed_label)
        lay.addWidget(label(f"v{VERSION}", muted=True))
        return side

    def build_header(self):
        head = QFrame(objectName="header")
        lay = QHBoxLayout(head)
        lay.setContentsMargins(24, 14, 20, 14)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.page_title = label("", h1=True)
        self.page_sub = label("", muted=True)
        col.addWidget(self.page_title)
        col.addWidget(self.page_sub)
        lay.addLayout(col)
        lay.addStretch(1)
        self.readings = {}
        for key, name, color in (("cpu", "CPU", theme.ACCENT), ("ram", "Memory", theme.SKY),
                                 ("disk", "Disk", theme.MINT)):
            col = QVBoxLayout()
            col.setSpacing(0)
            value = number("-", 22, color)
            col.addWidget(value, 0, Qt.AlignRight)
            col.addWidget(label(name, muted=True), 0, Qt.AlignRight)
            self.readings[key] = value
            lay.addLayout(col)
            lay.addSpacing(18)
        lay.addSpacing(14)
        lay.addWidget(label("Drive", muted=True))
        self.drive_box = QComboBox()
        self.drive_box.setMinimumWidth(310)
        self.drive_box.setToolTip("Every scan and clean works on this drive only.")
        self.drive_box.currentIndexChanged.connect(self.drive_selected)
        lay.addWidget(self.drive_box)
        return head

    def build_taskbar(self):
        bar = QFrame(objectName="taskbar")
        v = QVBoxLayout(bar)
        v.setContentsMargins(20, 8, 16, 10)
        v.setSpacing(6)
        self.progress_bar = HazardBar(6)
        v.addWidget(self.progress_bar)
        row = QHBoxLayout()
        self.dot = PulseDot()
        row.addWidget(self.dot)
        self.phase = label("Ready", bold=True, size=13)
        row.addWidget(self.phase)
        row.addSpacing(10)
        self.counters = QLabel()
        self.counters.setTextFormat(Qt.RichText)
        row.addWidget(self.counters)
        row.addStretch(1)
        self.current = label("", muted=True)
        self.current.setMaximumWidth(480)
        row.addWidget(self.current)
        self.stop_btn = button("Stop", tip="Stop the running task (Esc)")
        self.stop_btn.setStyleSheet(f"QPushButton{{color:{theme.RED}; border-color:{theme.RED}; font-weight:700}}"
                                    "QPushButton:disabled{color:#4b5675; border-color:#1a2542}")
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setEnabled(False)
        row.addWidget(self.stop_btn)
        v.addLayout(row)
        self.flash_timer = QTimer(self, singleShot=True, interval=9000, timeout=self.idle_taskbar)
        self.idle_taskbar()
        return bar

    # ------------------------------------------------------------------ navigation + actions
    def show_page(self, key):
        if key.startswith("guide:"):
            self.pages["guide"].focus(key.split(":", 1)[1])
            key = "guide"
        if key not in self.pages:
            key = "dashboard"
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        self.nav_buttons[key].setChecked(True)
        self.page_title.setText(page.title)
        self.page_sub.setText(page.subtitle)
        self.settings.setValue("window/page", key)

    def do_action(self, a):
        kind = a["kind"]
        if kind == "page":
            self.show_page(a["page"])
        elif kind == "elevate":
            self.elevate()
        elif kind == "run":
            self.run_command(a)
        elif kind == "open":
            target = os.path.expandvars(a["target"])
            try:
                if target.lower().startswith("control.exe "):
                    subprocess.Popen(target.split(" ", 1), creationflags=engine.NO_WINDOW)
                else:
                    os.startfile(target)
            except OSError as e:
                self.flash(f"Could not open {target}: {e.strerror or e}", theme.RED)

    def run_command(self, a):
        if self.busy():
            return self.flash("Wait for the current task to finish, or press Stop.", theme.AMBER)
        if a["admin"] and not self.admin:
            return self.flash("This needs administrator: use 'Restart as administrator' in the sidebar.", theme.AMBER)
        drive = (self.drive.root if self.drive else engine.system_root())[:2]
        args = [x.replace("{drive}", drive).replace("{sysdrive}", engine.system_root()[:2]) for x in a["args"]]
        if a.get("confirm"):
            dlg = ConfirmDialog(self, a["label"], [a["confirm"], "", f"<span style='color:{theme.MUTED}'>Command: "
                                                   f"{subprocess.list2cmdline(args)}</span>"], "Run")
            if not dlg.exec():
                return
        self.show_page("log")
        unsafe_to_stop = args[0].lower() in ("dism", "compact", "defrag", "chkdsk", "powershell", "vssadmin")
        self.run_task(f"Running {a['label']}",
                      lambda: engine.run_command(args, self.log, on_start=lambda p: setattr(self, "proc", p)),
                      lambda code: self.command_done(a["label"], code), stoppable=not unsafe_to_stop)

    def command_done(self, title, code):
        self.proc = None
        self.log(f"RESULT {title} finished with exit code {code}")
        self.refresh_drives()
        self.flash(f"{title} finished" if code == 0 else f"{title} exited with code {code} (see Activity)",
                   theme.MINT if code == 0 else theme.AMBER)

    # ------------------------------------------------------------------ drives + live data
    def refresh_drives(self):
        try:
            drives = engine.list_drives()
        except OSError:
            return
        if [d.root for d in drives] != [d.root for d in self.drives]:
            current = self.drive.root if self.drive else self.settings.value("window/drive", engine.system_root())
            self.drives = drives
            self.drive_box.blockSignals(True)
            self.drive_box.clear()
            for d in drives:
                self.drive_box.addItem(str(d), d.root)
            self.drive_box.setCurrentIndex(max(self.drive_box.findData(current), 0))
            self.drive_box.blockSignals(False)
            self.drive_selected()
        else:
            self.drives = drives
            for n, d in enumerate(drives):
                self.drive_box.setItemText(n, str(d))
            if self.drive:
                self.drive = next((d for d in drives if d.root == self.drive.root), self.drive)
        self.pages["dashboard"].update_drives(drives) if hasattr(self, "pages") else None
        if self.session_freed > 0:
            self.freed_label.setText(f"▲ {engine.fmt_size(self.session_freed)} freed this session")

    def drive_selected(self, *_):
        root = self.drive_box.currentData()
        self.drive = next((d for d in self.drives if d.root == root), None)
        if self.drive:
            self.settings.setValue("window/drive", self.drive.root)
        self.bus.drive.emit(self.drive)

    def tick_metrics(self):
        s = self.monitor.sample()
        self.pages["dashboard"].update_metrics(s)
        io = s["disk_read"] + s["disk_write"]
        self.readings["cpu"].setText(f"{s['cpu']:.0f}%")
        self.readings["ram"].setText(f"{s['ram']:.0f}%")
        self.readings["disk"].setText(f"{engine.fmt_size(int(io))}/s")

    def check_recommendations(self):
        dash = self.pages["dashboard"]
        dash.rec_btn.setEnabled(False)
        dash.rec_status.setText("checking …")
        drives, admin = list(self.drives), self.admin

        def job():
            try:
                self.bus.recs.emit(knowledge.recommendations(drives, admin))
            except Exception:
                self.log("ERROR while checking recommendations\n" + traceback.format_exc())
        threading.Thread(target=job, daemon=True).start()

    # ------------------------------------------------------------------ tasks
    def busy(self):
        return self.worker is not None and self.worker.is_alive()

    def progress(self, text, frac=None):
        self.progress_text, self.progress_frac = text, frac

    def run_task(self, phase, fn, on_done, stoppable=True):
        if self.busy():
            self.flash("Another task is running. Press Stop or wait.", theme.AMBER)
            return False
        self.cancel.clear()
        self.stats.reset(phase)
        self.progress_text, self.progress_frac = phase, None
        self.stoppable = stoppable
        self.flash_timer.stop()
        self.dot.set_active(True, theme.ACCENT)
        self.phase.setStyleSheet("font-size:13px; font-weight:700")
        self.phase.setText(phase)
        self.stop_btn.setEnabled(stoppable)
        self.stop_btn.setToolTip("Stop the running task (Esc)" if stoppable
                                 else "This Windows tool cannot be interrupted safely. It stops on its own.")

        def work():
            try:
                result = fn()
            except engine.Cancelled:
                self.bus.failed.emit("Stopped. Nothing further was changed.")
                return
            except Exception:
                self.log("ERROR\n" + traceback.format_exc())
                self.bus.failed.emit("Something went wrong. Details are on the Activity page.")
                return
            self.bus.done.emit(lambda res: (self.task_finished(), on_done(res)), result)

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.bus.busy.emit(True)
        return True

    def task_finished(self):
        self.worker = None
        self.proc = None
        self.stop_btn.setEnabled(False)
        self.bus.busy.emit(False)
        QApplication.alert(self)

    def task_failed(self, msg):
        self.task_finished()
        self.flash(msg, theme.AMBER)

    def stop(self):
        if not self.busy():
            return
        if not self.stoppable:
            return self.log("Stop ignored: this Windows tool cannot be interrupted safely.")
        self.cancel.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.stop_btn.setEnabled(False)
        self.phase.setText("Stopping after the current file …")
        self.dot.set_active(True, theme.RED)

    def tick_task(self):
        if not self.busy():
            return
        s, c = self.stats, theme
        elapsed = max(time.monotonic() - s.started, 0.001)
        parts = []
        if s.files or s.dirs:
            parts += [f"<span style='color:{c.ACCENT}'><b>{s.files:,}</b></span> files",
                      f"<span style='color:{c.SKY}'><b>{s.dirs:,}</b></span> folders",
                      f"<span style='color:{c.MUTED}'>{s.files / elapsed:,.0f}/s</span>"]
        if s.found:
            parts.append(f"found <span style='color:{c.SKY}'><b>{engine.fmt_size(s.found)}</b></span>")
        if s.deleted:
            parts.append(f"removed <span style='color:{c.MINT}'><b>{s.deleted:,}</b></span>")
        if s.freed:
            parts.append(f"freed <span style='color:{c.MINT}'><b>{engine.fmt_size(s.freed)}</b></span>")
        if s.moved:
            parts.append(f"recycled <span style='color:{c.MINT}'><b>{engine.fmt_size(s.moved)}</b></span>")
        if s.errors:
            parts.append(f"<span style='color:{c.AMBER}'>{s.errors:,} skipped</span>")
        parts.append(f"<span style='color:{c.MUTED}'>{int(elapsed // 60):02d}:{int(elapsed % 60):02d}</span>")
        self.counters.setText("&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;".join(parts))
        if not self.cancel.is_set():
            self.phase.setText(self.progress_text or s.phase)
        cur = s.current
        self.current.setText(cur if len(cur) < 72 else cur[:24] + " … " + cur[-44:])
        self.progress_bar.set_busy(self.progress_frac)

    def flash(self, msg, color):
        if self.busy():
            return self.log(msg)
        self.dot.set_active(True, color, blink=False)
        self.phase.setText(msg)
        self.phase.setStyleSheet(f"color:{color}; font-size:13px; font-weight:700")
        self.counters.setText("")
        self.current.setText("")
        self.progress_bar.set_done(color) if color != theme.RED else self.progress_bar.set_idle()
        self.flash_timer.start()

    def idle_taskbar(self):
        self.dot.set_active(False)
        self.phase.setText("Ready")
        self.phase.setStyleSheet("font-size:13px; font-weight:700")
        self.counters.setText(f"<span style='color:{theme.MUTED}'>Scans only read. Esc stops a task, "
                              "Ctrl+1 to 6 switch pages, F5 scans.</span>")
        self.current.setText("")
        self.progress_bar.set_idle()

    # ------------------------------------------------------------------ misc
    def log(self, msg):
        self.logger(msg)

    def elevate(self):
        if self.busy():
            return self.flash("Wait for the current task to finish first.", theme.AMBER)
        self.lock.unlock()
        if engine.relaunch_as_admin():
            self.close()
        else:
            self.lock.tryLock()
            self.flash("Elevation was cancelled.", theme.AMBER)

    def closeEvent(self, e):
        if self.busy():
            dlg = ConfirmDialog(self, "Quit while working?", ["A task is still running. Stop it and quit?"],
                                "Stop and quit")
            if not dlg.exec():
                return e.ignore()
            self.cancel.set()
            if self.proc and self.proc.poll() is None and self.stoppable:
                self.proc.terminate()
            self.worker.join(timeout=10)
        self.settings.setValue("window/geometry", self.saveGeometry())
        e.accept()


def main():
    if sys.platform != "win32":
        sys.exit("Custodian runs on Windows only.")
    engine.shell32.SetCurrentProcessExplicitAppUserModelID("Custodian.DriveCare")   # taskbar uses our icon
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(QIcon(ICON))
    theme.apply(app)
    logger = Log()

    def hook(kind, value, tb):
        logger("UNHANDLED ERROR\n" + "".join(traceback.format_exception(kind, value, tb)))
        QMessageBox.critical(None, APP, f"Unexpected error (saved to {logger.path}):\n\n{value}")
    sys.excepthook = hook

    lock = QLockFile(QDir(DATA_DIR).filePath("app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP, "Custodian is already running.")
        return 0
    win = Main(logger, lock)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
