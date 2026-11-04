"""Reusable controls and the virtualized file list."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QFontMetrics, QIcon, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .core import fit_size, format_bytes, format_pages, type_label
from .thumbnails import ThumbnailService

THUMB_SIDE = 112  # Pixels of preview, enough for a 44 point tile at 250% display scale.
ROW_HEIGHT = 64
ENTRY_ROLE = Qt.ItemDataRole.UserRole


def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def button(text: str = "", kind: str | None = None, icon_name: str | None = None, color: str = theme.TEXT, tooltip: str = "") -> QPushButton:
    # Qt leaves no gap between a button's icon and its text.
    widget = QPushButton(f" {text}" if text and icon_name else text)
    if kind:
        widget.setProperty("kind", kind)
    if icon_name:
        widget.setIcon(theme.icon(icon_name, color))
    if tooltip:
        widget.setToolTip(tooltip)
        widget.setAccessibleName(tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setAutoDefault(False)
    widget.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # The focus ring is for keyboard users.
    return widget


def repolish(widget: QWidget) -> None:
    """Re-evaluate stylesheet rules after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ElidedLabel(QLabel):
    """A one-line label that shortens long text instead of widening its parent."""

    def __init__(self, role: str = "message", parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setTextFormat(Qt.TextFormat.PlainText)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle, self.width())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


class IconLabel(QWidget):
    """Draws an icon at paint time, so it stays sharp at any display scale."""

    def __init__(self, icon: QIcon, side: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._icon = icon
        self.setFixedSize(side, side)

    def paintEvent(self, _event: QPaintEvent) -> None:
        self._icon.paint(QPainter(self), self.rect())


class Segmented(QWidget):
    """An always-visible single choice, used where a dropdown would hide the options."""

    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for value, text in options:
            segment = button(text, "segment")
            segment.setCheckable(True)
            self._group.addButton(segment)
            self._buttons[value] = segment
            layout.addWidget(segment, 1)
            segment.clicked.connect(lambda _checked=False, chosen=value: self.changed.emit(chosen))

    def value(self) -> str:
        return next((value for value, segment in self._buttons.items() if segment.isChecked()), "")

    def set_value(self, value: str) -> None:
        self._buttons[value].setChecked(True)

    def segment(self, value: str) -> QPushButton:
        return self._buttons[value]


class Slider(QSlider):
    """A slider that lets the wheel scroll the panel unless it has keyboard focus."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class EmptyState(QWidget):
    """The first thing a new user sees: one large target that says what to do."""

    browse = Signal()

    def __init__(self, add_files: QPushButton, add_folder: QPushButton, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.addStretch(5)
        layout.addWidget(IconLabel(theme.icon("upload", theme.ACCENT_TEXT, size=44), 44), 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(14)
        headline = label("Drop photos, folders, or PDFs", "headline")
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(headline)
        layout.addSpacing(4)
        body = label("Subfolders are included. Your originals are never changed.", "body")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(body)
        layout.addSpacing(18)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        row.addWidget(add_files)
        row.addWidget(add_folder)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addSpacing(18)
        formats = label("JPG  ·  PNG  ·  WEBP  ·  TIFF  ·  BMP  ·  GIF  ·  HEIC  ·  CRW  ·  CR3  ·  PDF  ·  PSD", "caption")
        formats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(formats)
        layout.addStretch(6)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = self.underMouse()
        painter.setBrush(theme.with_alpha(theme.SURFACE, 150 if hovered else 90))
        pen = QPen(QColor(theme.ACCENT_TEXT if hovered else theme.BORDER_STRONG), 1.4, Qt.PenStyle.DashLine)
        pen.setDashPattern([5, 4])
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 16, 16)

    def enterEvent(self, _event: object) -> None:
        self.update()

    def leaveEvent(self, _event: object) -> None:
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.browse.emit()


class DropOverlay(QWidget):
    """Shown over the whole window during a drag, confirming a drop lands anywhere."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), theme.with_alpha(theme.BG, 215))
        area = QRectF(self.rect()).adjusted(14, 14, -14, -14)
        pen = QPen(QColor(theme.ACCENT_TEXT), 2, Qt.PenStyle.DashLine)
        pen.setDashPattern([6, 4])
        painter.setPen(pen)
        painter.setBrush(theme.with_alpha(theme.ACCENT, 34))
        painter.drawRoundedRect(area, 18, 18)
        centre = self.rect().center()
        theme.icon("upload", theme.ACCENT_TEXT, size=52).paint(painter, QRect(centre - QPoint(26, 62), QSize(52, 52)))
        painter.setPen(QColor(theme.TEXT))
        painter.setFont(theme.ui_font(16, theme.QFont.Weight.DemiBold, display=True))
        painter.drawText(QRect(0, centre.y() + 2, self.width(), 40), Qt.AlignmentFlag.AlignCenter, "Drop to add")


@dataclass
class QueueEntry:
    id: int
    path: Path
    size: int = 0
    pages: list[int] | None = None
    page_count: int | None = None
    dimensions: tuple[int, int] | None = None
    status: str = ""  # "", waiting, working, done, failed, partial
    message: str = ""
    finished: int = 0
    expected: int = 0
    bytes_out: int = 0
    failed_pages: list[int] = field(default_factory=list)

    @property
    def is_pdf(self) -> bool:
        return self.path.suffix.lower() == ".pdf"

    def thumb_key(self) -> tuple[str, int | None]:
        return str(self.path), (self.pages[0] if self.pages else None)


_PILLS = {
    "waiting": ("Waiting", theme.FAINT),
    "working": ("Working", theme.ACCENT_TEXT),
    "done": ("Done", theme.SUCCESS),
    "failed": ("Failed", theme.DANGER),
    "partial": ("Partial", theme.WARNING),
}


class FileDelegate(QStyledItemDelegate):
    """Paints a queue row: preview, name, the size change, and its status."""

    def __init__(self, thumbnails: ThumbnailService, parent: QWidget | None = None):
        super().__init__(parent)
        self.thumbnails = thumbnails
        self.entries: dict[int, QueueEntry] = {}
        self.box: tuple[int, int] | None = (1600, 1600)
        self.locked = False
        self._name_font = theme.ui_font(10, theme.QFont.Weight.Medium)
        self._meta_font = theme.ui_font(8.75)
        self._pill_font = theme.ui_font(8.5, theme.QFont.Weight.DemiBold)

    def sizeHint(self, _option: QStyleOptionViewItem, _index: object) -> QSize:
        return QSize(100, ROW_HEIGHT)

    @staticmethod
    def zones(rect: QRect, entry: QueueEntry) -> dict[str, QRect]:
        """Clickable areas, right-aligned within a row."""
        side = 28
        top = rect.center().y() - side // 2 + 1
        result = {"remove": QRect(rect.right() - side - 10, top, side, side)}
        if entry.is_pdf:
            result["pages"] = QRect(rect.right() - side * 2 - 12, top, side, side)
        return result

    def describe(self, entry: QueueEntry) -> str:
        parts = [type_label(entry.path)]
        if entry.is_pdf:
            parts.append(format_pages(entry.pages or [], entry.page_count))
        elif entry.dimensions:
            width, height = entry.dimensions
            if self.box:
                target = fit_size(width, height, self.box)
                parts.append(f"{width} × {height}" + (" (kept)" if target == entry.dimensions else f" → {target[0]} × {target[1]}"))
            else:
                parts.append(f"{width} × {height}")
        if entry.size:
            parts.append(format_bytes(entry.size) + (f" → {format_bytes(entry.bytes_out)}" if entry.bytes_out and not entry.is_pdf else ""))
        return "  ·  ".join(parts)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: object) -> None:
        entry = self.entries.get(index.data(ENTRY_ROLE))
        if entry is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = option.rect.adjusted(0, 2, -2, -2)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus) and bool(option.state & QStyle.StateFlag.State_KeyboardFocusChange)

        if selected or hovered or focused:
            painter.setPen(QPen(theme.with_alpha(theme.ACCENT_TEXT, 120 if selected or focused else 0), 1))
            painter.setBrush(theme.with_alpha(theme.ACCENT, 46) if selected else QColor(theme.SURFACE))
            painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)

        tile = QRect(rect.left() + 8, rect.center().y() - 21, 44, 44)
        self._paint_thumbnail(painter, tile, entry)

        show_buttons = hovered and not self.locked
        zones = self.zones(rect, entry)
        right = rect.right() - 12
        if show_buttons:
            right = min(zone.left() for zone in zones.values()) - 6
            for name, zone in zones.items():
                self._paint_zone_icon(painter, zone, "close" if name == "remove" else "edit")
        pill = _PILLS.get(entry.status)
        if pill:
            right = self._paint_pill(painter, right, rect.center().y(), *pill) - 10

        text_left = tile.right() + 12
        text_width = max(right - text_left, 20)
        painter.setFont(self._name_font)
        painter.setPen(QColor(theme.TEXT))
        name_metrics = QFontMetrics(self._name_font)
        painter.drawText(QRect(text_left, rect.top() + 11, text_width, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name_metrics.elidedText(entry.path.name, Qt.TextElideMode.ElideMiddle, text_width))

        painter.setFont(self._meta_font)
        metrics = QFontMetrics(self._meta_font)
        meta_rect = QRect(text_left, rect.top() + 31, text_width, 18)
        alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if entry.message and entry.status in ("failed", "partial"):
            painter.setPen(QColor(theme.DANGER if entry.status == "failed" else theme.WARNING))
            painter.drawText(meta_rect, alignment, metrics.elidedText(entry.message, Qt.TextElideMode.ElideRight, text_width))
        else:
            detail = self.describe(entry)
            painter.setPen(QColor(theme.MUTED))
            detail = metrics.elidedText(detail, Qt.TextElideMode.ElideRight, text_width)
            painter.drawText(meta_rect, alignment, detail)
            used = metrics.horizontalAdvance(detail) + 18
            room = text_width - used
            if room > 70:
                # Same-named files from different folders are told apart here.
                painter.setPen(QColor(theme.FAINT))
                folder = metrics.elidedText(str(entry.path.parent), Qt.TextElideMode.ElideMiddle, room)
                painter.drawText(QRect(text_left + used, meta_rect.top(), room, meta_rect.height()), alignment, folder)
        painter.restore()

    def _paint_thumbnail(self, painter: QPainter, tile: QRect, entry: QueueEntry) -> None:
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(tile), 8, 8)
        painter.fillPath(clip, QColor(theme.SURFACE_HOVER))
        key = entry.thumb_key()
        pixmap = self.thumbnails.pixmap(key)
        if pixmap is None:
            page = entry.pages[0] if entry.pages else (0 if entry.is_pdf else None)
            self.thumbnails.request(key, entry.path, page, THUMB_SIDE)
            theme.icon("file" if entry.is_pdf else "image", theme.FAINT, size=20).paint(painter, QRect(tile.center() - QPoint(10, 10), QSize(20, 20)))
            return
        painter.save()
        painter.setClipPath(clip)
        scaled = pixmap.size().scaled(tile.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRect(QPoint(0, 0), scaled)
        target.moveCenter(tile.center())
        painter.drawPixmap(target, pixmap)
        painter.restore()

    def _paint_zone_icon(self, painter: QPainter, zone: QRect, name: str) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SURFACE_HOVER))
        painter.drawRoundedRect(QRectF(zone), 7, 7)
        theme.icon(name, theme.MUTED, size=15).paint(painter, QRect(zone.center() - QPoint(7, 7), QSize(15, 15)))

    def _paint_pill(self, painter: QPainter, right: int, center_y: int, text: str, color: str) -> int:
        painter.setFont(self._pill_font)
        width = QFontMetrics(self._pill_font).horizontalAdvance(text) + 20
        pill = QRect(right - width, center_y - 11, width, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.with_alpha(color, 36))
        painter.drawRoundedRect(QRectF(pill), 11, 11)
        painter.setPen(QColor(color))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        return pill.left()


class FileList(QListWidget):
    """The queue. Rows are painted on demand, so thousands of files stay smooth.

    Reordering moves the rows live under the cursor. Doing this with plain mouse
    events rather than QDrag means selection, scrolling, and external file drops
    never compete with an internal drag.
    """

    files_dropped = Signal(list)
    remove_requested = Signal(int)
    pages_requested = Signal(int)
    delete_pressed = Signal()
    move_pressed = Signal(int)

    def __init__(self, delegate: FileDelegate, parent: QWidget | None = None):
        super().__init__(parent)
        self.file_delegate = delegate
        self.setItemDelegate(delegate)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self._press_row = -1
        self._press_pos = QPoint()
        self._press_zone: tuple[str, int] | None = None
        self._dragging = False
        self._collapse_on_release = False

    def entry_at(self, row: int) -> QueueEntry | None:
        item = self.item(row)
        return self.file_delegate.entries.get(item.data(ENTRY_ROLE)) if item else None

    def ordered_entries(self) -> list[QueueEntry]:
        return [self.file_delegate.entries[self.item(row).data(ENTRY_ROLE)] for row in range(self.count())]

    def selected_rows(self) -> list[int]:
        return sorted(index.row() for index in self.selectedIndexes())

    def _zone_at(self, pos: QPoint) -> tuple[str, int] | None:
        if self.file_delegate.locked:
            return None
        index = self.indexAt(pos)
        entry = self.entry_at(index.row()) if index.isValid() else None
        if entry is None:
            return None
        rect = self.visualRect(index).adjusted(0, 2, -2, -2)
        for name, zone in self.file_delegate.zones(rect, entry).items():
            if zone.contains(pos):
                return name, entry.id
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        self._press_row, self._dragging, self._collapse_on_release = -1, False, False
        self._press_zone = None
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self._press_zone = self._zone_at(pos)
        if self._press_zone:
            return
        plain = not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        row = self.indexAt(pos).row()
        if plain and row >= 0:
            self._press_row, self._press_pos = row, pos
            if self.item(row).isSelected() and len(self.selectedItems()) > 1:
                # Keep the selection so it can be dragged. A plain click narrows it on release.
                self._collapse_on_release = True
                self.setFocus()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        if self._press_zone or self._press_row < 0 or self.file_delegate.locked:
            if self._press_row < 0 and not self._press_zone:
                super().mouseMoveEvent(event)
            return
        pos = event.position().toPoint()
        if not self._dragging and (pos - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._dragging = True
        self._collapse_on_release = False
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._drag_to(pos)

    def _drag_to(self, pos: QPoint) -> None:
        bar = self.verticalScrollBar()
        if pos.y() < 24:
            bar.setValue(bar.value() - 12)
        elif pos.y() > self.viewport().height() - 24:
            bar.setValue(bar.value() + 12)
        rows = self.selected_rows()
        if not rows:
            return
        target = self.indexAt(QPoint(10, min(max(pos.y(), 1), self.viewport().height() - 2))).row()
        if target < 0:
            target = self.count() - 1
        first = rows[0]
        # The block's first row follows the row under the cursor, offset by the grabbed row.
        destination = max(0, min(target - max(self._press_row - first, 0), self.count() - len(rows)))
        if destination != first or rows[-1] - first + 1 != len(rows):
            self.move_block(rows, destination)
            self._press_row = destination + rows.index(self._press_row) if self._press_row in rows else self._press_row

    def move_block(self, rows: list[int], destination: int) -> None:
        """Move rows together so their first row lands at destination, keeping them selected."""
        self.blockSignals(True)
        items = [self.takeItem(row) for row in reversed(rows)]
        self.clearSelection()
        for offset, item in enumerate(reversed(items)):
            self.insertItem(destination + offset, item)
            item.setSelected(True)
        self.blockSignals(False)
        self.itemSelectionChanged.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._press_zone:
            zone = self._zone_at(pos)
            pressed, self._press_zone = self._press_zone, None
            if zone == pressed:
                name, entry_id = zone
                (self.remove_requested if name == "remove" else self.pages_requested).emit(entry_id)
            return
        if self._dragging:
            self.unsetCursor()
            self._dragging = False
            self._press_row = -1
            self.setState(QAbstractItemView.State.NoState)
            return
        if self._collapse_on_release and self._press_row >= 0:
            self.setCurrentRow(self._press_row)
        self._collapse_on_release = False
        self._press_row = -1
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        entry = self.entry_at(self.indexAt(event.position().toPoint()).row())
        if entry is not None and entry.is_pdf and not self.file_delegate.locked:
            self.pages_requested.emit(entry.id)
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Delete or key == Qt.Key.Key_Backspace:
            self.delete_pressed.emit()
        elif event.modifiers() & Qt.KeyboardModifier.AltModifier and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.move_pressed.emit(-1 if key == Qt.Key.Key_Up else 1)
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            entry = self.entry_at(self.currentRow())
            if entry is not None and entry.is_pdf:
                self.pages_requested.emit(entry.id)
        else:
            super().keyPressEvent(event)

    # A list viewport receives file drags before its parent, so it relays them.
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        parent = self.window()
        parent.dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        event.setAccepted(event.mimeData().hasUrls() and not self.file_delegate.locked)

    def dragLeaveEvent(self, event: object) -> None:
        self.window().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.window().dropEvent(event)


def new_item(entry: QueueEntry) -> QListWidgetItem:
    item = QListWidgetItem()
    item.setData(ENTRY_ROLE, entry.id)
    item.setToolTip(str(entry.path))
    return item

