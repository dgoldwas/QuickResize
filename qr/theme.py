"""Colors, fonts, the application stylesheet, and the icon set."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

BG = "#0F1115"
PANEL = "#15181E"
SURFACE = "#1C2028"
SURFACE_HOVER = "#262B35"
SURFACE_PRESSED = "#2D333F"
BORDER = "#292E38"
BORDER_STRONG = "#3D4452"
TEXT = "#ECEFF4"
MUTED = "#A0A8B8"
FAINT = "#737C8D"
ACCENT = "#2F6FED"
ACCENT_HOVER = "#4480F5"
ACCENT_PRESSED = "#2860CF"
ACCENT_TEXT = "#8AB4FF"
SUCCESS = "#4CC38A"
DANGER = "#F2727F"
WARNING = "#E9B44C"

_ICONS = {
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="8.5" cy="9.5" r="1.6"/><path d="M4 17.5l5-5 4 4 3-3 4 4"/>',
    "file": '<path d="M6 3h8l5 5v13H6zM14 3v5h5"/>',
    "up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "trash": '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.4v.2"/>',
    "edit": '<path d="M4 20l1-4L16 5l3 3L8 19z"/>',
    "upload": '<path d="M12 16V5M7 10l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
}


def icon_pixmap(name: str, color: str, size: int, ratio: float = 2.0) -> QPixmap:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{_ICONS[name]}</svg>'
    )
    side = round(size * ratio)
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, side, side))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


@lru_cache(maxsize=None)
def icon(name: str, color: str = TEXT, disabled: str = FAINT, size: int = 18) -> QIcon:
    result = QIcon()
    for ratio in (1.0, 1.5, 2.0, 3.0):
        result.addPixmap(icon_pixmap(name, color, size, ratio), QIcon.Mode.Normal)
        result.addPixmap(icon_pixmap(name, disabled, size, ratio), QIcon.Mode.Disabled)
    return result


def with_alpha(color: str, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(alpha)
    return result


def _family(*names: str) -> str:
    available = set(QFontDatabase.families())
    return next((name for name in names if name in available), names[-1])


def ui_font(point_size: float = 10, weight: QFont.Weight = QFont.Weight.Normal, display: bool = False) -> QFont:
    names = ("Segoe UI Variable Display", "Segoe UI") if display else ("Segoe UI Variable Text", "Segoe UI")
    font = QFont(_family(*names))
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    return font


STYLESHEET = f"""
* {{ outline: none; }}
QWidget {{ color: {TEXT}; }}
QMainWindow, QDialog, #Workspace {{ background: {BG}; }}
#SidePanel {{ background: {PANEL}; border-left: 1px solid {BORDER}; }}
#SideScroll, #SideContent {{ background: {PANEL}; border: none; }}
#ActionArea {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}

QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 11pt; font-weight: 600; }}
QLabel[role="version"] {{ color: {FAINT}; font-size: 8.5pt; }}
QLabel[role="section"] {{ color: {MUTED}; font-size: 9pt; font-weight: 600; }}
QLabel[role="count"] {{ font-size: 10.5pt; font-weight: 600; }}
QLabel[role="caption"] {{ color: {FAINT}; font-size: 8.5pt; }}
QLabel[role="caption"][tone="warn"] {{ color: {WARNING}; }}
QLabel[role="caption"][tone="error"] {{ color: {DANGER}; }}
QLabel[role="value"] {{ color: {ACCENT_TEXT}; font-size: 9pt; font-weight: 600; }}
QLabel[role="sep"] {{ color: {FAINT}; }}
QLabel[role="message"] {{ color: {MUTED}; font-size: 9pt; }}
QLabel[role="headline"] {{ font-size: 15pt; font-weight: 600; }}
QLabel[role="body"] {{ color: {MUTED}; font-size: 10pt; }}
QLabel[role="resultTitle"] {{ font-size: 10.5pt; font-weight: 600; }}
QLabel[role="resultBody"] {{ color: {MUTED}; font-size: 9pt; }}

QPushButton {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 12px; font-size: 9.5pt; min-height: 20px;
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; border-color: {BORDER_STRONG}; }}
QPushButton:pressed {{ background: {SURFACE_PRESSED}; }}
QPushButton:disabled {{ color: {FAINT}; background: {PANEL}; border-color: {BORDER}; }}
QPushButton:focus {{ border-color: {ACCENT_TEXT}; }}

QPushButton[kind="primary"] {{
    background: {ACCENT}; border: 1px solid {ACCENT}; color: white;
    font-size: 10.5pt; font-weight: 600; padding: 9px 16px; border-radius: 9px;
}}
QPushButton[kind="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[kind="primary"]:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton[kind="primary"]:disabled {{ background: {SURFACE}; border-color: {SURFACE}; color: {FAINT}; }}
QPushButton[kind="primary"]:focus {{ border-color: white; }}

QPushButton[kind="ghost"] {{ background: transparent; border-color: transparent; color: {MUTED}; padding: 5px 9px; }}
QPushButton[kind="ghost"]:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QPushButton[kind="ghost"]:pressed {{ background: {SURFACE_PRESSED}; }}
QPushButton[kind="ghost"]:disabled {{ background: transparent; color: {FAINT}; }}
QPushButton[kind="ghost"]:focus {{ border-color: {ACCENT_TEXT}; }}

QPushButton[kind="link"] {{ background: transparent; border: none; color: {ACCENT_TEXT}; font-weight: 600; padding: 2px 6px; min-height: 16px; }}
QPushButton[kind="link"]:hover {{ color: white; }}
QPushButton[kind="link"]:focus {{ border: 1px solid {ACCENT_TEXT}; border-radius: 4px; }}

QPushButton[kind="chip"] {{ border-radius: 14px; padding: 4px 0; font-size: 9pt; color: {MUTED}; min-height: 18px; }}
QPushButton[kind="chip"]:hover {{ color: {TEXT}; }}
QPushButton[kind="chip"]:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton[kind="chip"]:focus {{ border-color: {ACCENT_TEXT}; }}
QPushButton[kind="chip"]:checked:disabled {{ background: {SURFACE_PRESSED}; border-color: {BORDER_STRONG}; color: {MUTED}; }}

#Segmented {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 9px; }}
QPushButton[kind="segment"] {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px 2px; font-size: 9pt; color: {MUTED}; min-height: 18px; }}
QPushButton[kind="segment"]:hover {{ background: {SURFACE}; color: {TEXT}; }}
QPushButton[kind="segment"]:checked {{ background: {SURFACE_PRESSED}; border-color: {BORDER_STRONG}; color: {TEXT}; font-weight: 600; }}
QPushButton[kind="segment"]:focus {{ border-color: {ACCENT_TEXT}; }}
QPushButton[kind="segment"]:disabled {{ background: transparent; border-color: transparent; color: {FAINT}; }}
QPushButton[kind="segment"]:checked:disabled {{ background: {SURFACE}; border-color: {BORDER}; color: {MUTED}; }}

QLineEdit {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 9px;
    font-size: 9.5pt; selection-background-color: {ACCENT}; selection-color: white;
}}
QLineEdit:hover {{ border-color: {BORDER_STRONG}; }}
QLineEdit:focus {{ border-color: {ACCENT_TEXT}; }}
QLineEdit:disabled {{ color: {FAINT}; }}
QLineEdit[invalid="true"] {{ border-color: {DANGER}; }}

QSlider::groove:horizontal {{ height: 4px; background: {BORDER_STRONG}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: {ACCENT_TEXT}; }}
QSlider::handle:horizontal:focus {{ background: {ACCENT_TEXT}; }}
QSlider::sub-page:horizontal:disabled {{ background: {BORDER_STRONG}; }}
QSlider::handle:horizontal:disabled {{ background: {FAINT}; }}

QProgressBar {{ background: {BORDER}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

QListWidget {{ background: transparent; border: none; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 3px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

QToolTip {{ background: {SURFACE_HOVER}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 4px 6px; }}

#ResultCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
#ResultCard[tone="ok"] {{ border-color: {SUCCESS}; }}
#ResultCard[tone="warn"] {{ border-color: {WARNING}; }}

QMessageBox {{ background: {PANEL}; }}
"""
