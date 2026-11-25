"""Colors, fonts, the application stylesheet, and the icon set."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

MODES = ("System", "Light", "Dark")
DEFAULT_MODE = "Dark"
DEFAULT_ACCENT = "Butter"


@dataclass(frozen=True)
class Accent:
    dark: str
    light: str
    ink: str
    swatch_deep: str


# Shared with FrameGrabber and VideoTrimmer. FrameGrabber also defines each swatch's deep half.
ACCENTS = {
    "Butter": Accent("#F5C451", "#F5C451", "#8F6400", "#9A6B00"),
    "Graphite": Accent("#E6E6E6", "#2B2B2B", "#2B2B2B", "#161616"),
    "Sky": Accent("#6CB6FF", "#3B82D9", "#2F6FC0", "#1F6FD0"),
    "Mint": Accent("#7FD1A6", "#3FA676", "#2B7F57", "#1E7F52"),
    "Rose": Accent("#F29BB0", "#D9577A", "#B8405F", "#C2476A"),
    "Violet": Accent("#B9A4F5", "#7C62D6", "#6A4FC8", "#6A4FD0"),
    "Coral": Accent("#FF9B7A", "#E5673F", "#C2502C", "#BF4A26"),
}


@dataclass(frozen=True)
class Colors:
    BG: str
    PANEL: str
    SURFACE: str
    SURFACE_HOVER: str
    SURFACE_PRESSED: str
    WELL: str
    BORDER: str
    BORDER_STRONG: str
    MENU: str
    MENU_BORDER: str
    TEXT: str
    MUTED: str
    FAINT: str
    SUCCESS: str
    DANGER: str
    WARNING: str
    ACCENT: str = ACCENTS[DEFAULT_ACCENT].dark
    ACCENT_TEXT: str = ACCENTS[DEFAULT_ACCENT].dark
    ON_ACCENT: str = "#14161A"


DARK = Colors(
    BG="#0D0F13", PANEL="#1B1D21", SURFACE="#1E2127", SURFACE_HOVER="#2C2F35",
    SURFACE_PRESSED="#343840", WELL="#121419", BORDER="#2C3038", BORDER_STRONG="#515761",
    MENU="#1B1F27", MENU_BORDER="#363B46", TEXT="#F2F4F8", MUTED="#A6AEBD", FAINT="#8C95A6",
    SUCCESS="#3DDC97", DANGER="#FF8A8A", WARNING="#E9B44C",
)
LIGHT = Colors(
    BG="#F0F0F3", PANEL="#FAFAFB", SURFACE="#FCFCFD", SURFACE_HOVER="#E9E9ED",
    SURFACE_PRESSED="#E2E2E7", WELL="#E8E8EC", BORDER="#D6D6DB", BORDER_STRONG="#A2A2AB",
    MENU="#FCFCFD", MENU_BORDER="#D6D6DB", TEXT="#1B1B1E", MUTED="#55555C", FAINT="#62626D",
    SUCCESS="#2E7D4F", DANGER="#B3261E", WARNING="#825806",
)
colors = DARK


def mode_name(value: object) -> str:
    return next((mode for mode in MODES if isinstance(value, str) and mode.casefold() == value.casefold()), DEFAULT_MODE)


def accent_name(value: object) -> str:
    return next((name for name in ACCENTS if isinstance(value, str) and name.casefold() == value.casefold()), DEFAULT_ACCENT)


def _luminance(color: str) -> float:
    rgb = QColor(color)
    channels = (rgb.redF(), rgb.greenF(), rgb.blueF())
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def _contrast(first: str, second: str) -> float:
    low, high = sorted((_luminance(first), _luminance(second)))
    return (high + 0.05) / (low + 0.05)


def apply(dark: bool, name: str) -> None:
    """Refresh styled controls, native Qt palettes, and custom-painted widgets together."""
    global colors
    base = DARK if dark else LIGHT
    tint = ACCENTS[accent_name(name)]
    fill = tint.dark if dark else tint.light
    ink = tint.dark if dark else tint.ink
    while not dark and min(_contrast(ink, surface) for surface in (base.BG, base.WELL, base.SURFACE_PRESSED)) < 4.5:
        ink = QColor(ink).darker(108).name().upper()
    on_fill = max(("#14161A", "#FFFFFF", "#000000"), key=lambda color: _contrast(color, fill))
    # Prefer the suite's near-black when it provides enough contrast.
    if _contrast("#14161A", fill) >= 4.5:
        on_fill = "#14161A"
    selected = replace(base, ACCENT=fill, ACCENT_TEXT=ink, ON_ACCENT=on_fill)
    app = QApplication.instance()
    if colors == selected and app.styleSheet():
        return
    colors = selected

    role = QPalette.ColorRole
    palette = QPalette()
    for key, value in {
        role.Window: colors.BG, role.WindowText: colors.TEXT, role.Base: colors.SURFACE,
        role.AlternateBase: colors.WELL, role.Text: colors.TEXT, role.Button: colors.SURFACE,
        role.ButtonText: colors.TEXT, role.ToolTipBase: colors.MENU, role.ToolTipText: colors.TEXT,
        role.Highlight: colors.ACCENT, role.Accent: colors.ACCENT, role.HighlightedText: colors.ON_ACCENT,
        role.Link: colors.ACCENT_TEXT, role.PlaceholderText: colors.FAINT,
    }.items():
        palette.setColor(key, QColor(value))
    for key in (role.WindowText, role.Text, role.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, key, QColor(colors.FAINT))
    QApplication.setPalette(palette)
    app.setStyleSheet(_STYLESHEET.format_map(vars(colors)))

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
    "download": '<path d="M12 4v11M7 10l5 5 5-5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    "upload": '<path d="M12 16V5M7 10l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M12 16v4M8 20h8"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
    "chevron": '<path d="M7 10l5 5 5-5"/>',
    "moon": '<path d="M20 15A8 8 0 1 1 9 4a7 7 0 0 0 11 11z"/>',
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


def icon(name: str, color: str | None = None, size: int = 18) -> QIcon:
    return _icon(name, color or colors.TEXT, colors.FAINT, size)


@lru_cache(maxsize=160)
def _icon(name: str, color: str, disabled: str, size: int) -> QIcon:
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


_STYLESHEET = """
* {{ outline: none; }}
QWidget {{ color: {TEXT}; }}
QMainWindow, QDialog, #Workspace {{ background: {BG}; }}
QDialog#Preferences {{ background: {PANEL}; }}
#SidePanel {{ background: {PANEL}; border-left: 1px solid {BORDER}; }}
#SideScroll, #SideContent {{ background: {PANEL}; border: none; }}
#ActionArea {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}

QLabel {{ background: transparent; }}
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
    background: {ACCENT}; border: 1px solid {ACCENT}; color: {ON_ACCENT};
    font-size: 10.5pt; font-weight: 600; padding: 9px 16px; border-radius: 9px;
}}
QPushButton[kind="primary"]:hover {{ border-color: {ON_ACCENT}; }}
QPushButton[kind="primary"]:pressed {{ border-color: {BORDER_STRONG}; }}
QPushButton[kind="primary"]:disabled {{ background: {SURFACE}; border-color: {SURFACE}; color: {FAINT}; }}
QPushButton[kind="primary"]:focus {{ border-color: {ON_ACCENT}; }}

QPushButton[kind="ghost"] {{ background: transparent; border-color: transparent; color: {MUTED}; padding: 5px 9px; }}
QPushButton[kind="ghost"]:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QPushButton[kind="ghost"]:pressed {{ background: {SURFACE_PRESSED}; }}
QPushButton[kind="ghost"]:disabled {{ background: transparent; color: {FAINT}; }}
QPushButton[kind="ghost"]:focus {{ border-color: {ACCENT_TEXT}; }}

QPushButton[kind="link"] {{ background: transparent; border: none; color: {ACCENT_TEXT}; font-weight: 600; padding: 2px 6px; min-height: 16px; }}
QPushButton[kind="link"]:hover {{ color: {TEXT}; }}
QPushButton[kind="link"]:focus {{ border: 1px solid {ACCENT_TEXT}; border-radius: 4px; }}


QPushButton[kind="picker"] {{ background: {WELL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 9px; min-height: 20px; }}
QPushButton[kind="picker"]:hover {{ background: {WELL}; border-color: {BORDER_STRONG}; }}
QPushButton[kind="picker"]:pressed, QPushButton[kind="picker"][open="true"] {{ background: {WELL}; border-color: {ACCENT_TEXT}; }}
QPushButton[kind="picker"]:focus {{ border-color: {ACCENT_TEXT}; }}
QPushButton[kind="picker"]:disabled {{ background: {PANEL}; border-color: {BORDER}; }}

#PresetPopup {{ background: {MENU}; border: 1px solid {MENU_BORDER}; border-radius: 10px; }}
#PresetScroll, #PresetList {{ background: transparent; border: none; }}
#PresetDivider {{ background: {BORDER}; border: none; }}
#PresetEditor {{ background: {WELL}; border: 1px solid {BORDER}; border-radius: 8px; }}
#PresetEditor QLineEdit {{ background: {SURFACE}; padding: 4px 7px; }}
#PresetEditor QLineEdit:focus {{ border-color: {ACCENT_TEXT}; }}
#PresetEditor QLineEdit[invalid="true"] {{ border-color: {DANGER}; }}
QPushButton[kind="presetItem"] {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 0; min-height: 30px; max-height: 30px; }}
QPushButton[kind="presetItem"]:hover {{ background: {SURFACE_HOVER}; }}
QPushButton[kind="presetItem"]:pressed {{ background: {SURFACE_PRESSED}; }}
QPushButton[kind="presetItem"]:focus {{ background: {SURFACE_HOVER}; border-color: {ACCENT_TEXT}; }}
QPushButton[kind="presetAction"] {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 0 8px; min-height: 30px; max-height: 30px; text-align: left; color: {ACCENT_TEXT}; font-weight: 600; }}
QPushButton[kind="presetAction"]:hover {{ background: {SURFACE_HOVER}; }}
QPushButton[kind="presetAction"]:pressed {{ background: {SURFACE_PRESSED}; }}
QPushButton[kind="presetAction"]:focus {{ border-color: {ACCENT_TEXT}; }}
QPushButton[kind="presetAction"]:disabled {{ background: transparent; color: {FAINT}; }}
QPushButton[kind="rowTool"] {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 0; min-height: 20px; }}
QPushButton[kind="rowTool"]:hover {{ background: {SURFACE_PRESSED}; }}
QPushButton[kind="rowTool"]:focus {{ border-color: {ACCENT_TEXT}; }}
QPushButton[kind="rowSave"] {{ background: {ACCENT}; border: 1px solid {ACCENT}; border-radius: 6px; padding: 0; min-height: 20px; }}
QPushButton[kind="rowSave"]:hover {{ border-color: {ON_ACCENT}; }}
QPushButton[kind="rowSave"]:focus {{ border-color: {ON_ACCENT}; }}
QPushButton[kind="rowSave"]:disabled {{ background: {SURFACE_PRESSED}; border-color: {SURFACE_PRESSED}; }}

#Segmented {{ background: {WELL}; border: 1px solid {BORDER}; border-radius: 9px; }}
QPushButton[kind="segment"] {{ background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 4px 2px; font-size: 9pt; color: {MUTED}; min-height: 18px; }}
QPushButton[kind="segment"]:hover {{ background: {SURFACE}; color: {TEXT}; }}
QPushButton[kind="segment"]:checked {{ background: {SURFACE}; border-color: {BORDER_STRONG}; color: {TEXT}; font-weight: 600; }}
QPushButton[kind="segment"]:focus {{ border-color: {ACCENT_TEXT}; }}
QPushButton[kind="segment"]:disabled {{ background: transparent; border-color: transparent; color: {FAINT}; }}
QPushButton[kind="segment"]:checked:disabled {{ background: {SURFACE}; border-color: {BORDER}; color: {MUTED}; }}
#Preferences QPushButton[kind="segment"]:checked {{ border-color: {ACCENT_TEXT}; }}

QPushButton[kind="swatch"] {{ border-radius: 16px; text-align: left; padding: 5px 9px; }}
QPushButton[kind="swatch"]:checked {{ border-color: {ACCENT_TEXT}; font-weight: 600; }}
QPushButton[kind="swatch"]:focus {{ border: 2px solid {ACCENT_TEXT}; padding: 4px 8px; }}

QLineEdit {{
    background: {WELL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 9px;
    font-size: 9.5pt; selection-background-color: {ACCENT}; selection-color: {ON_ACCENT};
}}
QLineEdit:hover {{ border-color: {BORDER_STRONG}; }}
QLineEdit:focus {{ border-color: {ACCENT_TEXT}; }}
QLineEdit:disabled {{ color: {FAINT}; }}
QLineEdit[invalid="true"] {{ border-color: {DANGER}; }}

QSlider::groove:horizontal {{ height: 4px; background: {BORDER_STRONG}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {ACCENT}; border: 1px solid {ACCENT_TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
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

QMenuBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; padding: 3px 10px; }}
QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 5px; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {ACCENT}; color: {ON_ACCENT}; }}
QMenu {{ background: {MENU}; color: {TEXT}; border: 1px solid {MENU_BORDER}; padding: 5px; }}
QMenu::item {{ padding: 6px 24px 6px 10px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT}; color: {ON_ACCENT}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; margin: 4px 6px; background: {BORDER}; }}

#ResultCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
#ResultCard[tone="ok"] {{ border-color: {SUCCESS}; }}
#ResultCard[tone="warn"] {{ border-color: {WARNING}; }}

QMessageBox {{ background: {PANEL}; }}
"""
