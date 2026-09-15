"""Custodian's look: a maintenance room. Slate walls, safety-yellow controls, mint for space won back.

Type: Bahnschrift (Windows' DIN signage face) for titles and numbers, Segoe UI Variable for reading.
"""
import os
import sys

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

BG = "#122327"        # boiler-room slate
PANEL = "#1A3035"
PANEL2 = "#223C42"
LINE = "#2D4A50"
TEXT = "#EEF3EA"      # chalk
MUTED = "#93ABA9"
FAINT = "#5E7A7A"
ACCENT = "#FFC83D"    # safety yellow: brand, primary actions, selection
INK = "#15201C"       # text on yellow
MINT = "#6FE0B0"      # healthy, freed, safe
SKY = "#8CC8F0"       # information, secondary series
AMBER = "#F59E42"     # warnings, review
RED = "#FF6F5C"       # destructive, critical

LEVEL = {"critical": RED, "warn": AMBER, "info": SKY, "good": MINT}
RISK = {"safe": MINT, "moderate": AMBER, "high": RED}
ICON_FONT = "Segoe Fluent Icons"   # Windows 11; falls back to MDL2 Assets on Windows 10
DISPLAY = "Bahnschrift"


def icon_font(size=14):
    f = QFont(ICON_FONT)
    f.setFamilies([ICON_FONT, "Segoe MDL2 Assets"])
    f.setPixelSize(size)
    return f


def display_font(px, style="SemiBold Condensed"):
    """Bahnschrift in a named width/weight; falls back to Segoe UI where it is missing."""
    f = QFontDatabase.font(DISPLAY, style, 10)
    if DISPLAY not in f.family():
        f = QFont("Segoe UI")
        f.setBold("Bold" in style)
    f.setPixelSize(px)
    return f


def usage_color(fraction):
    return RED if fraction >= 0.9 else AMBER if fraction >= 0.75 else MINT


def apply(app):
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
    font.setPointSizeF(9.5)
    app.setFont(font)

    pal = QPalette()
    for role, color in ((QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, PANEL),
                        (QPalette.AlternateBase, "#1D353A"), (QPalette.Text, TEXT), (QPalette.Button, PANEL2),
                        (QPalette.ButtonText, TEXT), (QPalette.Highlight, "#3A4A2A"),
                        (QPalette.HighlightedText, TEXT), (QPalette.ToolTipBase, PANEL2),
                        (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, FAINT), (QPalette.Link, ACCENT)):
        pal.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        pal.setColor(QPalette.Disabled, role, QColor(FAINT))
    app.setPalette(pal)
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))).replace("\\", "/")
    app.setStyleSheet(QSS.replace("{base}", base))


QSS = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {LINE}; padding: 6px 8px; }}
QLabel {{ color: {TEXT}; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[h1="true"] {{ font-family: "Bahnschrift SemiBold", "Bahnschrift"; font-size: 26px; font-weight: 600; }}
QLabel[h2="true"] {{ font-family: "Bahnschrift SemiBold", "Bahnschrift"; font-size: 15px; font-weight: 600;
                     color: {TEXT}; padding-top: 4px; }}

#sidebar {{ background: #0E1C1F; }}
#brand {{ font-family: "Bahnschrift SemiBold Condensed", "Bahnschrift"; font-size: 24px; font-weight: 600;
          color: {TEXT}; }}
QPushButton[nav="true"] {{
    text-align: left; padding: 10px 12px; border: none; border-radius: 4px;
    color: {MUTED}; background: transparent; font-size: 14px;
}}
QPushButton[nav="true"]:hover {{ color: {TEXT}; background: #15282C; }}
QPushButton[nav="true"]:checked {{ color: {INK}; background: {ACCENT}; font-weight: 600; }}

#header {{ background: {BG}; border-bottom: 1px solid {LINE}; }}
QFrame[card="true"] {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 6px; }}
#taskbar {{ background: #0E1C1F; border-top: 1px solid {LINE}; }}

QPushButton {{
    background: transparent; color: {TEXT}; border: 1px solid {LINE}; border-radius: 4px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {MUTED}; background: {PANEL2}; }}
QPushButton:pressed {{ background: #2A474E; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {FAINT}; border-color: #223A3F; background: transparent; }}
QPushButton[primary="true"] {{ color: {INK}; background: {ACCENT}; border: 1px solid {ACCENT}; font-weight: 700; }}
QPushButton[primary="true"]:hover {{ background: #FFD466; border-color: #FFD466; }}
QPushButton[danger="true"] {{ color: #1C0B08; background: {RED}; border: 1px solid {RED}; font-weight: 700; }}
QPushButton[danger="true"]:hover {{ background: #FF8B7B; border-color: #FF8B7B; }}
QPushButton[primary="true"]:disabled, QPushButton[danger="true"]:disabled {{
    background: #223A3F; border-color: #223A3F; color: {FAINT}; }}
QPushButton[seg="true"] {{ border-radius: 0; padding: 6px 14px; }}
QPushButton[seg="true"]:checked {{ background: {TEXT}; border-color: {TEXT}; color: {INK}; font-weight: 600; }}
QPushButton[chip="true"] {{ border-radius: 14px; padding: 5px 14px; color: {MUTED}; }}
QPushButton[chip="true"]:checked {{ background: {PANEL2}; border-color: {ACCENT}; color: {TEXT}; }}
QPushButton[link="true"] {{ border: none; background: transparent; color: {ACCENT}; text-align: left; padding: 0; }}
QPushButton[link="true"]:hover {{ text-decoration: underline; }}

QComboBox, QSpinBox, QLineEdit {{
    background: {PANEL}; color: {TEXT}; border: 1px solid {LINE}; border-radius: 4px; padding: 6px 10px;
    selection-background-color: {ACCENT}; selection-color: {INK};
}}
QComboBox:hover, QSpinBox:hover {{ border-color: {MUTED}; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {LINE}; outline: none;
    selection-background-color: {ACCENT}; selection-color: {INK}; }}
QCheckBox {{ color: {TEXT}; spacing: 8px; }}

QTreeWidget, QPlainTextEdit {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 6px; color: {TEXT}; }}
QTreeWidget {{ alternate-background-color: #1D353A; outline: none; }}
QTreeWidget::item {{ padding: 4px 2px; }}
QTreeWidget::item:selected {{ background: #2E4A3A; color: {TEXT}; }}
QHeaderView::section {{
    background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {LINE};
    padding: 8px; font-weight: 600;
}}
QPlainTextEdit {{ font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; padding: 8px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {MUTED}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {LINE}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {PANEL2}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; }}
QMenu::item:selected {{ background: {ACCENT}; color: {INK}; }}

QCheckBox::indicator, QTreeWidget::indicator {{
    width: 15px; height: 15px; border-radius: 3px; border: 1px solid {MUTED}; background: {BG};
}}
QCheckBox::indicator:hover, QTreeWidget::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked, QTreeWidget::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT}; image: url({{base}}/check.svg); }}
QTreeWidget::indicator:indeterminate {{ background: {MUTED}; border-color: {MUTED}; image: url({{base}}/partial.svg); }}
QCheckBox::indicator:disabled, QTreeWidget::indicator:disabled {{ border-color: {LINE}; background: {PANEL}; }}
"""
