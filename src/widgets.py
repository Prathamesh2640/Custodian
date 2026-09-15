"""Custom painted widgets: gauges, sparklines, drive cards, confirm dialog."""
import math
import time
from collections import deque

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

import engine
import theme


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


def button(text, primary=False, danger=False, icon=None, tip=None):
    b = QPushButton(f"{icon}  {text}" if icon else text)
    if primary:
        b.setProperty("primary", True)
    if danger:
        b.setProperty("danger", True)
    b.setCursor(Qt.PointingHandCursor)
    if tip:
        b.setToolTip(tip)
    return b


def pill(text, color):
    lbl = QLabel(text)
    c = QColor(color)
    lbl.setStyleSheet(f"color:{color}; background: rgba({c.red()},{c.green()},{c.blue()},0.14);"
                      f"border:1px solid rgba({c.red()},{c.green()},{c.blue()},0.45); border-radius:10px;"
                      "padding:2px 9px; font-size:11px; font-weight:600;")
    lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lbl


def card(layout_cls=QVBoxLayout, margins=16, spacing=10):
    frame = QFrame()
    frame.setProperty("card", True)
    lay = layout_cls(frame)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(spacing)
    return frame, lay


class RingGauge(QWidget):
    """Donut gauge with an animated sweep."""

    def __init__(self, size=96, thickness=10):
        super().__init__()
        self.setFixedSize(size, size)
        self.thickness = thickness
        self._value = 0.0
        self.center_text, self.sub_text = "", ""
        self.anim = QVariantAnimation(self, duration=900, easingCurve=QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._set)

    def _set(self, v):
        self._value = float(v)
        self.update()

    def set_value(self, fraction, text="", sub=""):
        self.center_text, self.sub_text = text, sub
        self.anim.stop()
        self.anim.setStartValue(self._value)
        self.anim.setEndValue(max(0.0, min(1.0, fraction)))
        self.anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.thickness
        rect = QRectF(t / 2 + 1, t / 2 + 1, self.width() - t - 2, self.height() - t - 2)
        p.setPen(QPen(QColor("#1b2745"), t, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 0, 360 * 16)
        color = QColor(theme.usage_color(self._value))
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0, color.lighter(130))
        grad.setColorAt(1, color)
        p.setPen(QPen(QBrush(grad), t, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 90 * 16, -int(self._value * 360 * 16))
        p.setPen(QColor(theme.TEXT))
        f = QFont(self.font())
        f.setPixelSize(int(self.height() * 0.2))
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(0, 0, self.width(), self.height() * 0.58), Qt.AlignHCenter | Qt.AlignBottom, self.center_text)
        f.setPixelSize(int(self.height() * 0.11))
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        p.drawText(QRectF(0, self.height() * 0.58, self.width(), self.height() * 0.3), Qt.AlignHCenter | Qt.AlignTop,
                   self.sub_text)


class Sparkline(QWidget):
    def __init__(self, color, maximum=None, points=60, height=46):
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
        grad = QLinearGradient(0, 0, 0, h)
        c = QColor(self.color)
        c.setAlpha(110)
        grad.setColorAt(0, c)
        c.setAlpha(0)
        grad.setColorAt(1, c)
        p.fillPath(area, grad)
        p.setPen(QPen(self.color, 2))
        p.drawPath(line)
        p.setBrush(self.color)
        p.setPen(Qt.NoPen)
        p.drawEllipse(pts[-1], 3.5, 3.5)


class PulseDot(QWidget):
    """Breathing status dot: bright and animated while work is running."""

    def __init__(self, color=theme.CYAN, size=12):
        super().__init__()
        self.setFixedSize(size + 8, size + 8)
        self.color = QColor(color)
        self.active = False
        self.timer = QTimer(self, interval=40, timeout=self.update)

    def set_active(self, on, color=None):
        self.active = on
        if color:
            self.color = QColor(color)
        self.timer.start() if on else self.timer.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = (self.width() - 8) / 2
        if self.active:
            phase = (math.sin(time.monotonic() * 5) + 1) / 2
            halo = QColor(self.color)
            halo.setAlpha(int(40 + 80 * phase))
            p.setBrush(halo)
            p.setPen(Qt.NoPen)
            p.drawEllipse(c, r + 3 * phase + 1, r + 3 * phase + 1)
        p.setBrush(self.color if self.active else QColor("#3b4a70"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(c, r, r)


class MetricCard(QFrame):
    def __init__(self, title, color, maximum=None):
        super().__init__()
        self.setProperty("card", True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(4)
        top = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}; font-size:12px")
        top.addWidget(dot)
        top.addWidget(label(title, muted=True))
        top.addStretch(1)
        self.value = label("-", size=22, bold=True)
        top.addWidget(self.value)
        lay.addLayout(top)
        self.sub = label("", muted=True)
        lay.addWidget(self.sub)
        self.spark = Sparkline(color, maximum)
        lay.addWidget(self.spark)

    def update_value(self, v, text, sub=""):
        self.value.setText(text)
        self.sub.setText(sub)
        self.spark.push(v)


class DriveCard(QFrame):
    """Live drive tile: ring gauge plus a badge that lights up when free space changes."""

    def __init__(self, drive):
        super().__init__()
        self.setProperty("card", True)
        self.root = drive.root
        self.baseline = drive.free
        self.last_free = drive.free
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)
        self.ring = RingGauge(92, 10)
        lay.addWidget(self.ring)
        col = QVBoxLayout()
        col.setSpacing(3)
        head = QHBoxLayout()
        self.title = label("", size=15, bold=True)
        head.addWidget(self.title)
        head.addStretch(1)
        self.kind = pill(drive.kind, theme.BLUE if drive.kind == "Local disk" else theme.PINK)
        head.addWidget(self.kind)
        col.addLayout(head)
        self.free = label("", size=13)
        col.addWidget(self.free)
        self.meta = label("", muted=True)
        col.addWidget(self.meta)
        self.badge = label("", size=12, bold=True)
        col.addWidget(self.badge)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.fade = QTimer(self, singleShot=True, interval=8000, timeout=lambda: self._badge_idle())
        self.update_drive(drive)

    def _badge_idle(self):
        gained = self.last_free - self.baseline
        if gained > 1 << 20:
            self.badge.setText(f"▲ {engine.fmt_size(gained)} freed this session")
            self.badge.setStyleSheet(f"color:{theme.GREEN}; font-size:12px; font-weight:600")
        else:
            self.badge.setText("● live")
            self.badge.setStyleSheet(f"color:{theme.MUTED}; font-size:11px")

    def update_drive(self, d):
        used = (d.total - d.free) / d.total if d.total else 0
        self.title.setText(f"{d.root[:2]}  {d.name}")
        self.free.setText(f"{engine.fmt_size(d.free)} free")
        self.meta.setText(f"{engine.fmt_size(d.total - d.free)} used of {engine.fmt_size(d.total)} · {d.fs}")
        self.ring.set_value(used, f"{used * 100:.0f}%", "used")
        delta = d.free - self.last_free
        if abs(delta) >= 1 << 20 and self.last_free != d.free:
            up = delta > 0
            self.badge.setText(f"{'▲' if up else '▼'} {engine.fmt_size(abs(delta))} {'freed' if up else 'used'} just now")
            self.badge.setStyleSheet(f"color:{theme.GREEN if up else theme.AMBER}; font-size:12px; font-weight:700;"
                                     f"background: rgba({'52,211,153' if up else '251,191,36'},0.12);"
                                     "border-radius:6px; padding:2px 6px")
            self.fade.start()
        elif not self.fade.isActive():
            self._badge_idle()
        self.last_free = d.free


class ConfirmDialog(QDialog):
    def __init__(self, parent, title, lines, action_text, danger=True, ack=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        head = QHBoxLayout()
        icon = QLabel("")
        icon.setFont(theme.icon_font(26))
        icon.setStyleSheet(f"color:{theme.AMBER if danger else theme.CYAN}")
        head.addWidget(icon)
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
