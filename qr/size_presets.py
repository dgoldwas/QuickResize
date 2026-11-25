"""The Fit inside dropdown: pick, save, edit, and remove sizes without leaving the panel."""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QCursor, QFont, QFontMetrics, QKeyEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .core import MAX_DIMENSION
from .settings import MAX_PRESETS, PRESET_NAME_LENGTH, SizePreset
from .widgets import button, label, repolish

ROW_HEIGHT = 32
VISIBLE_ROWS = 8


def _dims(width: int, height: int) -> str:
    return f"{width} \N{MULTIPLICATION SIGN} {height}"


def _paint_frame(widget: QPushButton) -> None:
    """Let the stylesheet draw the background and border, leaving the content to us."""
    option = QStyleOptionButton()
    widget.initStyleOption(option)
    option.text = ""
    painter = QPainter(widget)
    widget.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, widget)
    painter.end()


class PresetPicker(QPushButton):
    """A quiet dropdown showing which saved size matches the width and height fields."""

    chosen = Signal(int, int)
    presets_changed = Signal(list)

    def __init__(self, presets: list[SizePreset], parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("kind", "picker")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setToolTip("Saved sizes")
        self.presets = list(presets)
        self.current: tuple[int, int] | None = None
        self.popup: PresetPopup | None = None
        self._closed_at = 0.0
        self.clicked.connect(self.toggle_popup)
        self._sync_name()

    # ------------------------------------------------------------------ state

    def match(self) -> SizePreset | None:
        if self.current is None:
            return None
        return next((p for p in self.presets if (p.width, p.height) == self.current), None)

    def set_current(self, box: tuple[int, int] | None) -> None:
        if box != self.current:
            self.current = box
            self._sync_name()
            self.update()

    def set_presets(self, presets: list[SizePreset]) -> None:
        self.presets = list(presets)[:MAX_PRESETS]
        self._sync_name()
        self.update()
        self.presets_changed.emit(list(self.presets))

    def _sync_name(self) -> None:
        preset = self.match()
        self.setAccessibleName(f"Saved sizes: {preset.label() if preset else 'Custom size'}")

    # ------------------------------------------------------------------ popup

    def toggle_popup(self, _checked: bool = False, keyboard: bool = False) -> None:
        if self.popup is not None and self.popup.isVisible():
            self.popup.close()
            return
        if time.monotonic() - self._closed_at < 0.25:
            self._closed_at = 0.0
            return
        self.popup = PresetPopup(self)
        self.popup.closed.connect(self._popup_closed)
        self.setProperty("open", True)
        repolish(self)
        self.popup.open_below(self, keyboard)

    def _popup_closed(self) -> None:
        # A press on this button closes the popup first, and must not then reopen it.
        pressed = QApplication.mouseButtons() != Qt.MouseButton.NoButton
        self._closed_at = time.monotonic() if pressed and self.rect().contains(self.mapFromGlobal(QCursor.pos())) else 0.0
        self.popup = None
        self.setProperty("open", False)
        repolish(self)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_F4) or (
            event.key() == Qt.Key.Key_Space and not event.isAutoRepeat()
        ):
            self.toggle_popup(keyboard=True)
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ paint

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        _paint_frame(self)
        colors = theme.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.rect().adjusted(11, 0, -10, 0)
        chevron = QRect(area.right() - 15, area.center().y() - 7, 16, 16)
        theme.icon("chevron", colors.MUTED, 16).paint(painter, chevron)
        area.setRight(chevron.left() - 8)

        preset = self.match()
        if preset is None:
            name, detail, name_color = "Custom size", "", colors.MUTED
        elif preset.name:
            name, detail, name_color = preset.name, _dims(preset.width, preset.height), colors.TEXT
        else:
            name, detail, name_color = _dims(preset.width, preset.height), "", colors.TEXT
        if not self.isEnabled():
            name_color = colors.FAINT

        font = QFont(self.font())
        if detail:
            painter.setFont(font)
            painter.setPen(theme.with_alpha(colors.FAINT, 255))
            detail_width = QFontMetrics(font).horizontalAdvance(detail)
            painter.drawText(area, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, detail)
            area.setRight(area.right() - detail_width - 10)
        bold = QFont(font)
        bold.setWeight(QFont.Weight.DemiBold if preset else QFont.Weight.Normal)
        painter.setFont(bold)
        painter.setPen(theme.with_alpha(name_color, 255))
        text = QFontMetrics(bold).elidedText(name, Qt.TextElideMode.ElideRight, area.width())
        painter.drawText(area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()


class PresetItem(QPushButton):
    """One saved size. Edit and remove appear on hover or keyboard focus."""

    edit_requested = Signal()
    remove_requested = Signal()

    def __init__(self, preset: SizePreset, active: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.preset = preset
        self.active = active
        self.setProperty("kind", "presetItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(ROW_HEIGHT)
        self.setAccessibleName(f"{preset.label()}, {_dims(preset.width, preset.height)}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(0)
        layout.addStretch(1)
        self.edit_button = self._tool("edit", f"Edit {preset.label()}")
        self.edit_button.clicked.connect(self.edit_requested)
        self.remove_button = self._tool("trash", f"Remove {preset.label()}")
        self.remove_button.clicked.connect(self.remove_requested)
        layout.addWidget(self.edit_button)
        layout.addWidget(self.remove_button)
        self._show_tools(False)

    def _tool(self, icon_name: str, tooltip: str) -> QPushButton:
        tool = button("", "rowTool", icon_name=icon_name, color_role="MUTED", tooltip=tooltip)
        tool.setFixedSize(26, 24)
        policy = tool.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        tool.setSizePolicy(policy)
        tool.installEventFilter(self)
        return tool

    def _show_tools(self, visible: bool) -> None:
        self.edit_button.setVisible(visible)
        self.remove_button.setVisible(visible)

    def _refresh_tools(self) -> None:
        focused = self.hasFocus() or self.edit_button.hasFocus() or self.remove_button.hasFocus()
        self._show_tools(self.underMouse() or focused)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._refresh_tools()
        return False

    def enterEvent(self, event: object) -> None:
        super().enterEvent(event)
        self._show_tools(True)

    def leaveEvent(self, event: object) -> None:
        super().leaveEvent(event)
        self._refresh_tools()

    def focusInEvent(self, event: object) -> None:
        super().focusInEvent(event)
        self._refresh_tools()

    def focusOutEvent(self, event: object) -> None:
        super().focusOutEvent(event)
        self._refresh_tools()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.remove_requested.emit()
        elif event.key() == Qt.Key.Key_F2:
            self.edit_requested.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        _paint_frame(self)
        colors = theme.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        if self.active:
            theme.icon("check", colors.ACCENT_TEXT, 14).paint(painter, QRect(9, rect.center().y() - 7, 14, 14))
        area = rect.adjusted(30, 0, -10, 0)
        if self.edit_button.isVisible():
            area.setRight(self.edit_button.geometry().left() - 6)
        font = QFont(self.font())
        dims = _dims(self.preset.width, self.preset.height)
        if self.preset.name:
            painter.setFont(font)
            painter.setPen(theme.with_alpha(colors.FAINT, 255))
            painter.drawText(area, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, dims)
            area.setRight(area.right() - QFontMetrics(font).horizontalAdvance(dims) - 10)
        name_font = QFont(font)
        if self.active:
            name_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(name_font)
        painter.setPen(theme.with_alpha(colors.TEXT, 255))
        name = QFontMetrics(name_font).elidedText(self.preset.label(), Qt.TextElideMode.ElideRight, area.width())
        painter.drawText(area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        painter.end()


class PresetEditor(QFrame):
    """Inline fields for a new or changed size."""

    saved = Signal(object)
    cancelled = Signal()

    def __init__(self, preset: SizePreset | None, fallback: tuple[int, int] | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PresetEditor")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        width, height = (preset.width, preset.height) if preset else (fallback or ("", ""))
        self.name_input = QLineEdit(preset.name if preset else "")
        self.name_input.setPlaceholderText("Name (optional)")
        self.name_input.setAccessibleName("Preset name")
        self.name_input.setMaxLength(PRESET_NAME_LENGTH)
        layout.addWidget(self.name_input)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.width_input = self._field(str(width), "Width in pixels", "W")
        self.height_input = self._field(str(height), "Height in pixels", "H")
        row.addWidget(self.width_input, 1)
        row.addWidget(label("\N{MULTIPLICATION SIGN}", "sep"))
        row.addWidget(self.height_input, 1)
        cancel = button("", "rowTool", icon_name="close", color_role="MUTED", tooltip="Cancel (Esc)")
        cancel.setFixedSize(28, 28)
        cancel.clicked.connect(self.cancelled)
        self.save_button = button("", "rowSave", icon_name="check", color_role="ON_ACCENT", tooltip="Save (Enter)")
        self.save_button.setFixedSize(28, 28)
        self.save_button.clicked.connect(self.submit)
        row.addWidget(cancel)
        row.addWidget(self.save_button)
        layout.addLayout(row)
        for field in (self.name_input, self.width_input, self.height_input):
            field.returnPressed.connect(self.submit)
        for field in (self.width_input, self.height_input):
            field.textChanged.connect(self._validate)
        self._validate()

    def _field(self, text: str, name: str, placeholder: str) -> QLineEdit:
        field = QLineEdit(text)
        field.setAccessibleName(name)
        field.setPlaceholderText(placeholder)
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        field.setMaxLength(6)
        field.setMinimumWidth(52)
        return field

    @staticmethod
    def _value(field: QLineEdit) -> int | None:
        text = field.text().strip()
        return int(text) if text.isdecimal() and 1 <= int(text) <= MAX_DIMENSION else None

    def _validate(self) -> bool:
        ok = True
        for field in (self.width_input, self.height_input):
            invalid = self._value(field) is None and bool(field.text().strip())
            ok = ok and self._value(field) is not None
            if bool(field.property("invalid")) != invalid:
                field.setProperty("invalid", invalid)
                repolish(field)
        self.save_button.setEnabled(ok)
        return ok

    def submit(self) -> None:
        if not self._validate():
            for field in (self.width_input, self.height_input):
                if self._value(field) is None:
                    field.setProperty("invalid", True)
                    repolish(field)
                    field.setFocus()
                    field.selectAll()
                    return
            return
        width, height = self._value(self.width_input), self._value(self.height_input)
        self.saved.emit(SizePreset(self.name_input.text().strip(), width, height))

    def focus(self) -> None:
        target = self.name_input if self.name_input.text() or self._validate() else self.width_input
        target.setFocus()
        target.selectAll()


class PresetPopup(QWidget):
    """The open dropdown. It stays open while editing so several changes are quick."""

    closed = Signal()

    def __init__(self, picker: PresetPicker):
        super().__init__(picker, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.picker = picker
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.keyboard = False  # Focus rings appear only once the keyboard is in use.
        self.editing: int | None = None  # Index being edited, or -1 for a new preset.
        self.editor: PresetEditor | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame()
        self.frame.setObjectName("PresetPopup")
        outer.addWidget(self.frame)
        layout = QVBoxLayout(self.frame)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("PresetScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self.scroll)
        self.footer = QVBoxLayout()
        self.footer.setContentsMargins(0, 0, 0, 0)
        self.footer.setSpacing(0)
        layout.addLayout(self.footer)
        self.items: list[PresetItem] = []
        self.add_button: QPushButton | None = None
        self._build()

    # ------------------------------------------------------------------ content

    def _build(self) -> None:
        content = QWidget()
        content.setObjectName("PresetList")
        rows = QVBoxLayout(content)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(1)
        self.items = []
        self.editor = None
        current = self.picker.current
        match = self.picker.match()
        for index, preset in enumerate(self.picker.presets):
            if index == self.editing:
                self.editor = self._make_editor(preset)
                rows.addWidget(self.editor)
                continue
            item = PresetItem(preset, preset is match, content)
            item.clicked.connect(lambda _checked=False, p=preset: self._choose(p))
            item.edit_requested.connect(lambda i=index: self._start_edit(i))
            item.remove_requested.connect(lambda i=index: self._remove(i))
            rows.addWidget(item)
            self.items.append(item)
        if not self.picker.presets and self.editing != -1:
            empty = label("No saved sizes yet.", "caption")
            empty.setContentsMargins(10, 8, 10, 8)
            rows.addWidget(empty)
        rows.addStretch(1)
        self.scroll.setWidget(content)

        while self.footer.count():
            item = self.footer.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        divider = QFrame()
        divider.setObjectName("PresetDivider")
        divider.setFixedHeight(1)
        self.footer.addSpacing(4)
        self.footer.addWidget(divider)
        self.footer.addSpacing(4)
        if self.editing == -1:
            self.editor = self._make_editor(None)
            self.footer.addWidget(self.editor)
            self.add_button = None
        else:
            unsaved = current is not None and match is None
            text = f"Save {_dims(*current)}" if unsaved else "Add size"
            self.add_button = button(text, "presetAction", icon_name="plus", color_role="ACCENT_TEXT")
            self.add_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.add_button.setFixedHeight(ROW_HEIGHT)
            self.add_button.setEnabled(len(self.picker.presets) < MAX_PRESETS)
            self.add_button.clicked.connect(lambda: self._start_edit(-1))
            self.footer.addWidget(self.add_button)

        visible = min(max(len(self.picker.presets), 1), VISIBLE_ROWS)
        extra = 76 if self.editor is not None and self.editing != -1 else 0
        self.scroll.setFixedHeight(visible * (ROW_HEIGHT + 1) + extra)
        if self.editor is not None:
            self.editor.focus()
            if self.editing is not None and self.editing >= 0:
                self.scroll.ensureWidgetVisible(self.editor)

    def _make_editor(self, preset: SizePreset | None) -> PresetEditor:
        editor = PresetEditor(preset, self.picker.current)
        editor.saved.connect(self._save)
        editor.cancelled.connect(self._cancel_edit)
        return editor

    def _rebuild(self, focus: int | None = None) -> None:
        self._build()
        self.adjustSize()
        self._place()
        if self.editor is None:
            if not self.keyboard:
                self.setFocus()
            elif focus is not None and self.items:
                self.items[max(0, min(focus, len(self.items) - 1))].setFocus()
            elif self.add_button is not None:
                self.add_button.setFocus()

    # ------------------------------------------------------------------ actions

    def _choose(self, preset: SizePreset) -> None:
        self.picker.chosen.emit(preset.width, preset.height)
        self.close()

    def _start_edit(self, index: int) -> None:
        self.editing = index
        self._rebuild()

    def _cancel_edit(self) -> None:
        index = self.editing
        self.editing = None
        self._rebuild(focus=index if index is not None and index >= 0 else None)

    def _save(self, preset: SizePreset) -> None:
        presets = list(self.picker.presets)
        if self.editing is not None and 0 <= self.editing < len(presets):
            presets[self.editing] = preset
            focus = self.editing
        else:
            presets.append(preset)
            focus = len(presets) - 1
        self.editing = None
        self.picker.set_presets(presets)
        self._rebuild(focus=focus)

    def _remove(self, index: int) -> None:
        presets = list(self.picker.presets)
        del presets[index]
        self.picker.set_presets(presets)
        self._rebuild(focus=index)

    # ------------------------------------------------------------------ window

    def open_below(self, anchor: QWidget, keyboard: bool = False) -> None:
        self.keyboard = keyboard
        self.setFixedWidth(anchor.width())
        self.adjustSize()
        self._place()
        self.show()
        if not keyboard:
            self.setFocus()
        elif self.items:
            active = next((item for item in self.items if item.active), self.items[0])
            active.setFocus()
        elif self.add_button is not None:
            self.add_button.setFocus()

    def _place(self) -> None:
        anchor = self.picker
        below = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        screen = anchor.screen().availableGeometry()
        top = below.y()
        if top + self.height() > screen.bottom():
            top = anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 4
        self.move(below.x(), max(screen.top(), top))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            if self.editing is not None:
                self._cancel_edit()
            else:
                self.close()
            return
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and self.editing is None:
            self.keyboard = True
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab) and self.focusWidget() not in (None, self):
                super().keyPressEvent(event)
                return
            targets: list[QWidget] = [*self.items]
            if self.add_button is not None and self.add_button.isEnabled():
                targets.append(self.add_button)
            if targets:
                focused = next((i for i, w in enumerate(targets) if w.hasFocus() or w.isAncestorOf(self.focusWidget() or w)), -1)
                step = -1 if key in (Qt.Key.Key_Up, Qt.Key.Key_Backtab) else 1
                if focused < 0:
                    focused = next((i for i, w in enumerate(targets) if getattr(w, "active", False)), -1)
                    step = 0 if focused >= 0 else 1
                targets[(focused + step) % len(targets)].setFocus()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: object) -> None:
        super().closeEvent(event)
        self.closed.emit()
