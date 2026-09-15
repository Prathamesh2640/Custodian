"""Custom painted widgets: storage bars, hazard-tape progress, sparklines, drive cards, confirm dialog."""
from collections import deque

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

import engine
import theme

WARN_GLYPH = ""


def label(text="", muted=False, h1=False, h2=False, wrap=False, size=None, color=None, bold=False):
    lbl = QLabel(text)
    if muted:
        lbl.setProperty("muted", True)
    if h1:
        lbl.setProperty("h1", True)
    if h2:
        lbl.setProperty("h2", True)
    lbl.setWordWrap(wrap)
    css = []
    if size:
        css.append(f"font-size:{size}px")
    if color:
        css.append(f"color:{color}")
    if bold:
        css.append("font-weight:700")
    if css:
        lbl.setStyleSheet(";".join(css))
    return lbl


def number(text="", px=28, color=theme.TEXT):
    """Big condensed signage numerals for sizes and readings."""
    lbl = QLabel(text)
    lbl.setFont(theme.display_font(px))
    lbl.setStyleSheet(f"color:{color}")
    return lbl


def button(text, primary=False, danger=False, tip=None):
    b = QPushButton(text)
    if primary:
        b.setProperty("primary", True)
    if danger:
        b.setProperty("danger", True)
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def pill(text, color):
    """Small outlined tag, like a label on a storage bin."""
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{color}; border:1px solid {color}; border-radius:3px; padding:1px 7px;"
                      "font-size:11px; font-weight:600;")
    lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lbl


def card(layout_cls=QVBoxLayout, margins=16, spacing=10):
    frame = QFrame()
    frame.setProperty("card", True)
    lay = layout_cls(frame)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(spacing)
    return frame, lay


class StorageBar(QWidget):
    """Segmented fill gauge (one segment per 5%), like the level marks on a tank."""
    SEGMENTS = 20

    def __init__(self, height=14):
        super().__init__()
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._value = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(700)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._set)

    def _set(self, v):
        self._value = float(v)
        self.update()

    def set_value(self, fraction):
        fraction = max(0.0, min(1.0, fraction))
        if abs(fraction - self._value) < 1e-4:
            return
        self.anim.stop()
        self.anim.setStartValue(self._value)
        self.anim.setEndValue(fraction)
        self.anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        gap = 3
        seg = (self.width() - gap * (self.SEGMENTS - 1)) / self.SEGMENTS
        lit = self._value * self.SEGMENTS
        color = QColor(theme.usage_color(self._value))
        empty = QColor(theme.PANEL2)
        p.setPen(Qt.NoPen)
        for i in range(self.SEGMENTS):
            x = i * (seg + gap)
            fill = min(max(lit - i, 0.0), 1.0)
            p.setBrush(empty)
            p.drawRoundedRect(QRectF(x, 0, seg, self.height()), 2, 2)
            if fill > 0:
                p.setBrush(color)
                p.drawRoundedRect(QRectF(x, 0, seg * fill, self.height()), 2, 2)


class HazardBar(QWidget):
    """Progress strip that runs as moving safety tape while work is underway, and turns solid when done."""

    def __init__(self, height=6):
        super().__init__()
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.mode, self.fraction, self.color, self.offset = "idle", None, QColor(theme.MINT), 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        self.offset = (self.offset + 1.2) % 24
        self.update()

    def set_busy(self, fraction=None):
        self.mode, self.fraction = "busy", fraction
        if not self.timer.isActive():
            self.timer.start()
        self.update()

    def set_done(self, color):
        self.mode, self.color = "done", QColor(color)
        self.timer.stop()
        self.update()

    def set_idle(self):
        self.mode = "idle"
        self.timer.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.PANEL))
        if self.mode == "done":
            p.fillRect(self.rect(), self.color)
        elif self.mode == "busy":
            width = w if self.fraction is None else max(w * self.fraction, h * 4)
            p.setClipRect(QRectF(0, 0, width, h))
            p.fillRect(QRectF(0, 0, width, h), QColor(theme.INK))
            p.setBrush(QColor(theme.ACCENT))
            p.setPen(Qt.NoPen)
            x = -24 + self.offset
            while x < width + 24:
                p.drawPolygon(QPolygonF([QPointF(x, h), QPointF(x + h, 0), QPointF(x + h + 12, 0),
                                         QPointF(x + 12, h)]))
                x += 24


class Sparkline(QWidget):
    def __init__(self, color, maximum=None, points=60, height=48):
        super().__init__()
        self.color = QColor(color)
        self.maximum = maximum
        self.values = deque([0.0] * points, maxlen=points)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def push(self, v):
        self.values.append(float(v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(theme.LINE), 1, Qt.DotLine))
        p.drawLine(0, h // 2, w, h // 2)
        top = self.maximum or max(max(self.values), 1.0) * 1.15
        n = len(self.values)
        pts = [QPointF(i * w / (n - 1), h - 2 - (v / top) * (h - 6)) for i, v in enumerate(self.values)]
        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        area = QPainterPath(line)
        area.lineTo(w, h)
        area.lineTo(0, h)
        area.closeSubpath()
        fill = QColor(self.color)
        fill.setAlpha(38)
        p.fillPath(area, fill)
        p.setPen(QPen(self.color, 2))
        p.drawPath(line)


class PulseDot(QWidget):
    """Status light: steady grey when idle, blinking in the task's colour while work runs."""

    def __init__(self, size=10):
        super().__init__()
        self.setFixedSize(size, size)
        self.color, self.active, self.lit = QColor(theme.FAINT), False, True
        self.timer = QTimer(self)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self._blink)

    def _blink(self):
        self.lit = not self.lit
        self.update()

    def set_active(self, on, color=None, blink=True):
        self.active, self.lit = on, True
        self.color = QColor(color) if on and color else QColor(theme.FAINT)
        self.timer.start() if on and blink else self.timer.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self.color)
        if not self.lit:
            c.setAlpha(70)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class MetricCard(QFrame):
    def __init__(self, title, color, maximum=None):
        super().__init__()
        self.setProperty("card", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.addWidget(label(title, muted=True))
        top.addStretch(1)
        self.value = number("-", 28, color)
        top.addWidget(self.value)
        lay.addLayout(top)
        self.sub = label("", muted=True)
        lay.addWidget(self.sub)
        lay.addSpacing(6)
        self.spark = Sparkline(color, maximum)
        lay.addWidget(self.spark)

    def update_value(self, v, text, sub=""):
        self.value.setText(text)
        self.sub.setText(sub)
        self.spark.push(v)


class DriveCard(QFrame):
    """Live drive tile: big free-space figure, segmented level bar, and a note when free space changes."""

    def __init__(self, drive):
        super().__init__()
        self.setProperty("card", True)
        self.root = drive.root
        self.baseline = drive.free
        self.last_free = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(6)
        head = QHBoxLayout()
        self.title = label("", size=14, bold=True)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(pill(drive.kind, theme.SKY if drive.kind == "Local disk" else theme.AMBER))
        lay.addLayout(head)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.free = number("", 40)
        row.addWidget(self.free, 0, Qt.AlignBottom)
        self.free_label = label("", muted=True)
        row.addWidget(self.free_label, 0, Qt.AlignBottom)
        row.addStretch(1)
        lay.addLayout(row)
        self.bar = StorageBar()
        lay.addWidget(self.bar)
        foot = QHBoxLayout()
        self.meta = label("", muted=True)
        foot.addWidget(self.meta)
        foot.addStretch(1)
        self.badge = label("")
        foot.addWidget(self.badge)
        lay.addLayout(foot)
        self.fade = QTimer(self)
        self.fade.setSingleShot(True)
        self.fade.setInterval(8000)
        self.fade.timeout.connect(self._badge_idle)
        self.update_drive(drive)

    def _badge_idle(self):
        gained = self.last_free - self.baseline
        if gained > 1 << 20:
            self.badge.setText(f"{engine.fmt_size(gained)} freed since opening")
            self.badge.setStyleSheet(f"color:{theme.MINT}; font-weight:600")
        else:
            self.badge.setText("")

    def update_drive(self, d):
        used = (d.total - d.free) / d.total if d.total else 0
        self.title.setText(f"{d.root[:2]}   {d.name}")
        size, unit = engine.fmt_size(d.free).split(" ")
        self.free.setText(size)
        self.free_label.setText(f"{unit} free of {engine.fmt_size(d.total)}")
        self.meta.setText(f"{used * 100:.0f}% used, {d.fs}")
        self.bar.set_value(used)
        if self.last_free is not None and abs(d.free - self.last_free) >= 1 << 20:
            up = d.free > self.last_free
            self.badge.setText(f"{engine.fmt_size(abs(d.free - self.last_free))} {'freed' if up else 'used'} just now")
            self.badge.setStyleSheet(f"color:{theme.INK}; background:{theme.MINT if up else theme.AMBER};"
                                     "border-radius:3px; padding:1px 7px; font-weight:700")
            self.fade.start()
        elif not self.fade.isActive() and self.last_free is not None:
            self._badge_idle()
        self.last_free = d.free


class ConfirmDialog(QDialog):
    def __init__(self, parent, title, lines, action_text, danger=True, ack=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(540)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        stripe = HazardBar(6)
        stripe.set_busy(None) if danger else stripe.set_done(theme.ACCENT)
        stripe.timer.stop()                     # static tape: a warning, not progress
        outer.addWidget(stripe)
        lay = QVBoxLayout()
        lay.setContentsMargins(24, 18, 24, 20)
        lay.setSpacing(12)
        outer.addLayout(lay)
        head = QHBoxLayout()
        icon = QLabel(WARN_GLYPH)
        icon.setFont(theme.icon_font(24))
        icon.setStyleSheet(f"color:{theme.AMBER if danger else theme.ACCENT}")
        head.addWidget(icon)
        head.addSpacing(6)
        head.addWidget(label(title, h1=True))
        head.addStretch(1)
        lay.addLayout(head)
        body = label("<br>".join(lines), wrap=True)
        body.setTextFormat(Qt.RichText)
        lay.addWidget(body)
        self.ack = None
        if ack:
            self.ack = QCheckBox(ack)
            self.ack.setStyleSheet(f"color:{theme.AMBER}; font-weight:600")
            lay.addWidget(self.ack)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        cancel.setDefault(True)
        row.addWidget(cancel)
        self.go = button(action_text, danger=danger, primary=not danger)
        self.go.clicked.connect(self.accept)
        row.addWidget(self.go)
        lay.addLayout(row)
        if self.ack:
            self.go.setEnabled(False)
            self.ack.toggled.connect(self.go.setEnabled)
