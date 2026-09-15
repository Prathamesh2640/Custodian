"""Draws src/icon.ico (drive + sparkle). Run once after changing the design:
    .venv\\Scripts\\python src\\make_icon.py
Each size is rendered separately so 16/24/32 px stay crisp.
"""
import os
import struct
import sys

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")


def sparkle(cx, cy, r):
    k = r * 0.22   # waist of the four-point star
    pts = [(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k),
           (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)]
    path = QPainterPath(QPointF(*pts[0]))
    for p in pts[1:]:
        path.lineTo(*p)
    path.closeSubpath()
    return path


def render(size):
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 256, size / 256)
    small = size <= 24

    # background tile
    bg = QLinearGradient(0, 0, 256, 256)
    bg.setColorAt(0, QColor("#2563eb"))
    bg.setColorAt(1, QColor("#0f766e"))
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)

    # drive body
    p.setBrush(QColor("#f8fafc"))
    body = QRectF(40, 118, 176, 86) if not small else QRectF(30, 110, 196, 104)
    p.drawRoundedRect(body, 22, 22)
    p.setBrush(QColor("#cbd5e1"))
    p.drawRect(QRectF(body.left() + 16, body.top() + body.height() * 0.52, body.width() - 32, 10 if not small else 0))
    p.setBrush(QColor("#22c55e"))
    p.drawEllipse(QPointF(body.right() - 34, body.top() + body.height() / 2 - (8 if not small else 0)),
                  13 if not small else 20, 13 if not small else 20)

    # sparkles
    p.setBrush(QColor("#fde047"))
    p.drawPath(sparkle(150, 70, 52 if not small else 62))
    if not small:
        p.setBrush(QColor("#ffffff"))
        p.drawPath(sparkle(78, 62, 24))
        p.drawPath(sparkle(206, 44, 16))
    p.end()
    return img


def png_bytes(img):
    buf = QBuffer()
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def main():
    app = QGuiApplication(sys.argv)  # needed for QPainter
    assert app
    blobs = [(s, png_bytes(render(s))) for s in SIZES]
    offset = 6 + 16 * len(blobs)
    out = struct.pack("<HHH", 0, 1, len(blobs))
    for s, data in blobs:
        dim = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out += b"".join(d for _, d in blobs)
    with open(OUT, "wb") as f:
        f.write(out)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
