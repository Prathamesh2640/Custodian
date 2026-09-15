"""Draws src/icon.ico: a key whose bow is a disk platter, on a safety-yellow tile.
    .venv\\Scripts\\python src\\make_icon.py
Each size is rendered separately so 16/24/32 px stay crisp (small sizes drop the fine detail).
"""
import os
import struct
import sys

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
YELLOW, SLATE = QColor("#FFC83D"), QColor("#122327")


def key_path(detail):
    """Key pointing right; bow (platter) on the left. Coordinates in a 256 box."""
    p = QPainterPath()
    p.setFillRule(Qt.WindingFill)             # overlapping parts must merge, not cancel
    p.addEllipse(QPointF(92, 128), 60, 60)                     # platter / bow
    p.addRoundedRect(QRectF(138, 115, 88, 26), 6, 6)           # shaft
    if detail:
        p.addRect(QRectF(176, 128, 16, 38))                    # teeth
        p.addRect(QRectF(202, 128, 16, 26))
    else:
        p.addRect(QRectF(180, 128, 30, 34))
    return p.simplified()


def render(size):
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 256, size / 256)
    detail = size >= 40

    p.setPen(Qt.NoPen)
    p.setBrush(YELLOW)
    p.drawRoundedRect(QRectF(6, 6, 244, 244), 58, 58)

    p.translate(128, 128)                                      # slight tilt reads as "in use"
    p.rotate(-32)
    p.translate(-128, -128)
    p.setBrush(SLATE)
    p.drawPath(key_path(detail))

    # platter details in yellow: data track and hub
    p.setBrush(Qt.NoBrush)
    if detail:
        p.setPen(QPen(YELLOW, 7))
        p.drawEllipse(QPointF(92, 128), 38, 38)
    p.setPen(Qt.NoPen)
    p.setBrush(YELLOW)
    r = 13 if detail else 18
    p.drawEllipse(QPointF(92, 128), r, r)
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
