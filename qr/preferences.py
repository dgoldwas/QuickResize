"""QuickResize's live appearance settings."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QButtonGroup, QDialog, QGridLayout, QVBoxLayout, QWidget

from . import theme
from .widgets import Segmented, button, label


class PreferencesDialog(QDialog):
    changed = Signal(str, str)

    def __init__(self, mode: str, accent: str, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Preferences")
        self.setWindowTitle("Settings")
        self.setMinimumWidth(464)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(8)
        layout.addWidget(label("Appearance", "headline"))
        layout.addSpacing(8)
        layout.addWidget(label("Theme", "section"))
        self.mode = Segmented(
            [(name, name) for name in theme.MODES],
            icons={"System": "monitor", "Light": "sun", "Dark": "moon"},
        )
        self.mode.setAccessibleName("Theme")
        for name in theme.MODES:
            self.mode.segment(name).setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.mode.set_value(mode)
        layout.addWidget(self.mode)
        layout.addWidget(label("System follows Windows’ app mode.", "caption"))
        layout.addSpacing(10)
        layout.addWidget(label("Accent", "section"))

        accents = QGridLayout()
        accents.setSpacing(6)
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.accents = {}
        for index, (name, tint) in enumerate(theme.ACCENTS.items()):
            swatch = button(f" {name}", "swatch", tooltip=name)
            swatch.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            swatch.setIcon(_swatch_icon(tint))
            swatch.setCheckable(True)
            swatch.setChecked(name == accent)
            group.addButton(swatch)
            self.accents[name] = swatch
            accents.addWidget(swatch, index // 4, index % 4)
        layout.addLayout(accents)

        self.mode.changed.connect(lambda mode: self.changed.emit(mode, self.accent()))
        group.buttonClicked.connect(lambda _: self.changed.emit(self.mode.value(), self.accent()))
        layout.addSpacing(12)
        done = button("Done", "primary")
        done.setMinimumWidth(88)
        done.setDefault(True)
        done.clicked.connect(self.accept)
        layout.addWidget(done, 0, Qt.AlignmentFlag.AlignRight)
        self.mode.segment(mode).setFocus()

    def accent(self) -> str:
        return next(name for name, swatch in self.accents.items() if swatch.isChecked())


def _swatch_icon(tint: theme.Accent) -> QIcon:
    icon = QIcon()
    for ratio in (1.0, 1.5, 2.0, 3.0):
        size = round(16 * ratio)
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        gradient = QLinearGradient(0, 0, size, size)
        gradient.setColorAt(0.49, QColor(tint.swatch_deep))
        gradient.setColorAt(0.5, QColor(tint.dark))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(0, 0, size, size)
        painter.end()
        pixmap.setDevicePixelRatio(ratio)
        icon.addPixmap(pixmap)
    return icon
