"""Colors, fonts and the application style sheet."""
from PySide6.QtGui import QColor, QFont, QPalette

BG = "#0a0e1a"
SIDEBAR = "#0c1222"
SURFACE = "#111a2e"
SURFACE2 = "#172340"
BORDER = "#233154"
TEXT = "#e8edff"
MUTED = "#8a96b8"
CYAN = "#22d3ee"
VIOLET = "#a78bfa"
GREEN = "#34d399"
AMBER = "#fbbf24"
RED = "#fb7185"
BLUE = "#60a5fa"
PINK = "#f472b6"

LEVEL = {"critical": RED, "warn": AMBER, "info": BLUE, "good": GREEN}
RISK = {"safe": GREEN, "moderate": AMBER, "high": RED}
ICON_FONT = "Segoe Fluent Icons"   # Windows 11; falls back to MDL2 Assets on Windows 10


def icon_font(size=14):
    f = QFont(ICON_FONT)
    f.setFamilies([ICON_FONT, "Segoe MDL2 Assets"])
    f.setPixelSize(size)
    return f


def usage_color(fraction):
    return RED if fraction >= 0.9 else AMBER if fraction >= 0.75 else GREEN


def apply(app):
    app.setStyle("Fusion")
    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
    font.setPointSizeF(9.5)
    app.setFont(font)

    pal = QPalette()
    for role, color in ((QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, SURFACE),
                        (QPalette.AlternateBase, "#0f1729"), (QPalette.Text, TEXT), (QPalette.Button, SURFACE2),
                        (QPalette.ButtonText, TEXT), (QPalette.Highlight, "#1e3a8a"),
                        (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, SURFACE2),
                        (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, MUTED), (QPalette.Link, CYAN)):
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#4b5675"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#4b5675"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#4b5675"))
    app.setPalette(pal)
    app.setStyleSheet(QSS)


QSS = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; border-radius: 6px; }}
QLabel {{ color: {TEXT}; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[h1="true"] {{ font-size: 20px; font-weight: 600; }}
QLabel[h2="true"] {{ font-size: 13px; font-weight: 600; color: {TEXT}; }}

#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
#brand {{ font-size: 17px; font-weight: 700; color: {TEXT}; }}
QPushButton[nav="true"] {{
    text-align: left; padding: 10px 14px; border: none; border-radius: 10px;
    color: {MUTED}; background: transparent; font-size: 13px;
}}
QPushButton[nav="true"]:hover {{ background: {SURFACE}; color: {TEXT}; }}
QPushButton[nav="true"]:checked {{
    color: #ffffff; font-weight: 600;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(34,211,238,0.22), stop:1 rgba(167,139,250,0.10));
    border-left: 3px solid {CYAN};
}}

#header {{ background: {BG}; border-bottom: 1px solid {BORDER}; }}
#card, QFrame[card="true"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
#taskbar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}

QPushButton {{
    background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {CYAN}; }}
QPushButton:pressed {{ background: #1d2b4f; }}
QPushButton:disabled {{ color: #4b5675; border-color: #1a2542; background: #111a2e; }}
QPushButton[primary="true"] {{
    color: #06121f; font-weight: 700; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {CYAN}, stop:1 {VIOLET});
}}
QPushButton[primary="true"]:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #67e8f9, stop:1 #c4b5fd); }}
QPushButton[danger="true"] {{
    color: #ffffff; font-weight: 700; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f43f5e, stop:1 #f97316);
}}
QPushButton[danger="true"]:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #fb7185, stop:1 #fb923c); }}
QPushButton[primary="true"]:disabled, QPushButton[danger="true"]:disabled {{ background: #1a2542; color: #4b5675; }}
QPushButton[seg="true"] {{ border-radius: 0; padding: 6px 12px; }}
QPushButton[seg="true"]:checked {{ background: #1e3a8a; border-color: {BLUE}; color: #ffffff; font-weight: 600; }}
QPushButton[chip="true"] {{ border-radius: 14px; padding: 5px 12px; }}
QPushButton[chip="true"]:checked {{ background: rgba(34,211,238,0.18); border-color: {CYAN}; color: #ffffff; }}

QComboBox, QSpinBox, QLineEdit {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px;
    selection-background-color: #1e3a8a;
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:focus {{ border-color: {CYAN}; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: #1e3a8a; }}
QCheckBox {{ color: {TEXT}; spacing: 8px; }}

QTreeWidget, QPlainTextEdit {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; color: {TEXT};
}}
QTreeWidget::item {{ padding: 4px 2px; }}
QTreeWidget::item:selected {{ background: rgba(96,165,250,0.22); color: #ffffff; }}
QHeaderView::section {{
    background: {SURFACE2}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
    padding: 7px 8px; font-weight: 600;
}}
QPlainTextEdit {{ font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; padding: 8px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2a3a63; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {BLUE}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2a3a63; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QProgressBar {{ background: #0f1729; border: none; border-radius: 3px; }}
QProgressBar::chunk {{ border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {CYAN}, stop:0.5 {VIOLET}, stop:1 {PINK}); }}
QMenu {{ background: {SURFACE2}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: #1e3a8a; }}
"""
