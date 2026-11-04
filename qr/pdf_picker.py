"""The dialog for choosing which pages of a PDF to convert."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QMouseEvent, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .core import parse_page_range
from .thumbnails import ThumbnailService
from .widgets import button, label, repolish

TILE_WIDTH = 156
TILE_HEIGHT = 216
PREVIEW_SIDE = 340  # Pixels of preview, sharp up to about 250% display scale.


class _PageDelegate(QStyledItemDelegate):
    def __init__(self, path: Path, thumbnails: ThumbnailService, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = path
        self.thumbnails = thumbnails

    def sizeHint(self, _option: QStyleOptionViewItem, _index: QModelIndex) -> QSize:
        return QSize(TILE_WIDTH, TILE_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        page = index.row()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus) and bool(option.state & QStyle.StateFlag.State_KeyboardFocusChange)
        tile = QRectF(option.rect).adjusted(5, 5, -5, -5)
        painter.setPen(QPen(QColor(theme.ACCENT_TEXT if selected or focused else theme.BORDER_STRONG if hovered else theme.BORDER), 2 if selected else 1))
        painter.setBrush(theme.with_alpha(theme.ACCENT, 40) if selected else QColor(theme.SURFACE))
        painter.drawRoundedRect(tile, 10, 10)

        preview = tile.adjusted(9, 9, -9, -30).toRect()
        key = (str(self.path), "picker", page)
        pixmap = self.thumbnails.pixmap(key)
        if pixmap is None:
            self.thumbnails.request(key, self.path, page, PREVIEW_SIDE)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.SURFACE_HOVER))
            painter.drawRoundedRect(QRectF(preview), 4, 4)
        else:
            scaled = pixmap.size().scaled(preview.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRect(QPoint(0, 0), scaled)
            target.moveCenter(preview.center())
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(target), 3, 3)
            painter.setClipPath(clip)
            painter.drawPixmap(target, pixmap)
            painter.setClipping(False)

        painter.setFont(theme.ui_font(9, theme.QFont.Weight.DemiBold if selected else theme.QFont.Weight.Normal))
        painter.setPen(QColor(theme.TEXT if selected else theme.MUTED))
        painter.drawText(tile.adjusted(0, 0, 0, -8).toRect(), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, f"Page {page + 1}")

        badge = QRectF(tile.right() - 30, tile.top() + 8, 22, 22)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawEllipse(badge)
            theme.icon("check", "#FFFFFF", size=14).paint(painter, QRect(badge.center().toPoint() - QPoint(7, 7), QSize(14, 14)))
        elif hovered:
            painter.setPen(QPen(QColor(theme.TEXT), 1.5))
            painter.setBrush(theme.with_alpha(theme.BG, 170))
            painter.drawEllipse(badge)
        painter.restore()


class _PageGrid(QListWidget):
    """Each click toggles a page, and Shift+click selects through to the last page clicked."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._anchor = -1
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(36)
        self.setMouseTracking(True)
        self.setAcceptDrops(False)
        self.setDragEnabled(False)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        row = self.indexAt(event.position().toPoint()).row()
        if event.button() != Qt.MouseButton.LeftButton or row < 0:
            super().mousePressEvent(event)
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self._anchor >= 0:
            low, high = sorted((self._anchor, row))
            for index in range(low, high + 1):
                self.item(index).setSelected(True)
        else:
            self.item(row).setSelected(not self.item(row).isSelected())
        self._anchor = row
        self.setCurrentRow(row, self.selectionModel().SelectionFlag.NoUpdate)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        # Tracking is on for hover. Dragging must not paint a selection across tiles.
        if not event.buttons():
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        return


class PdfPagePicker(QDialog):
    """Pages start unselected unless the PDF is being edited from the list."""

    def __init__(self, path: Path, page_count: int, thumbnails: ThumbnailService, initial: list[int] | None = None, position: tuple[int, int] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.path = path
        self.page_count = page_count
        self.setWindowTitle(f"Choose pages — {path.name}")
        self.setModal(True)
        self.resize(840, 680)
        self.setMinimumSize(560, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(0)

        heading = "Choose pages"
        if position and position[1] > 1:
            heading += f"  ·  PDF {position[0]} of {position[1]}"
        layout.addWidget(label(heading, "headline"))
        layout.addSpacing(2)
        layout.addWidget(label(f"{path.name}  ·  {page_count} page{'s' if page_count != 1 else ''}. Click pages to select them, or Shift+click for a run.", "body"))
        layout.addSpacing(14)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("Pages, like 1-5, 8")
        self.range_input.setAccessibleName("Page range")
        self.range_input.setFixedWidth(190)
        self.range_input.setAcceptDrops(False)
        self.range_input.returnPressed.connect(self.apply_range)
        self.range_input.textChanged.connect(self._clear_range_error)
        tools.addWidget(self.range_input)
        self.range_button = button("Select range")
        self.range_button.clicked.connect(self.apply_range)
        tools.addWidget(self.range_button)
        self.range_error = label("", "caption")
        self.range_error.setProperty("tone", "error")
        tools.addWidget(self.range_error)
        tools.addStretch(1)
        self.all_button = button("Select all", "ghost")
        self.all_button.clicked.connect(self.select_all)
        tools.addWidget(self.all_button)
        self.none_button = button("Clear", "ghost")
        self.none_button.clicked.connect(self.clear_selection)
        tools.addWidget(self.none_button)
        layout.addLayout(tools)
        layout.addSpacing(10)

        self.grid = _PageGrid()
        self.grid.setItemDelegate(_PageDelegate(path, thumbnails, self.grid))
        self.grid.setGridSize(QSize(TILE_WIDTH, TILE_HEIGHT))
        for _page in range(page_count):
            self.grid.addItem(QListWidgetItem())
        self.grid.itemSelectionChanged.connect(self._sync)
        layout.addWidget(self.grid, 1)
        layout.addSpacing(12)

        footer = QHBoxLayout()
        self.count_label = label("", "message")
        footer.addWidget(self.count_label)
        footer.addStretch(1)
        self.cancel_button = button("Cancel")
        self.cancel_button.setMinimumHeight(38)
        self.cancel_button.clicked.connect(self.reject)
        footer.addWidget(self.cancel_button)
        self.accept_button = button("", "primary")
        self.accept_button.clicked.connect(self.accept)
        footer.addWidget(self.accept_button)
        layout.addLayout(footer)

        QShortcut(QKeySequence.StandardKey.SelectAll, self.grid, activated=self.select_all)

        self._repaint = QTimer(self)
        self._repaint.setSingleShot(True)
        self._repaint.setInterval(30)
        self._repaint.timeout.connect(self.grid.viewport().update)
        thumbnails.ready.connect(self._on_thumbnail)
        self._thumbnails = thumbnails

        for page in initial or []:
            if 0 <= page < page_count:
                self.grid.item(page).setSelected(True)
        self._sync()

    def _on_thumbnail(self, _key: object, _thumbnail: object) -> None:
        if self._repaint is not None and not self._repaint.isActive():
            self._repaint.start()

    def done(self, result: int) -> None:
        if self._repaint is not None:
            self._thumbnails.ready.disconnect(self._on_thumbnail)
            self._repaint.stop()
            self._repaint = None
        super().done(result)

    def keyPressEvent(self, event: object) -> None:
        # Enter belongs to the range field and the focused button, not to accepting.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            return
        super().keyPressEvent(event)

    def selected_pages(self) -> list[int]:
        return sorted(index.row() for index in self.grid.selectedIndexes())

    def select_all(self) -> None:
        self.grid.selectAll()

    def clear_selection(self) -> None:
        self.grid.clearSelection()

    def apply_range(self) -> None:
        try:
            pages = parse_page_range(self.range_input.text(), self.page_count)
        except ValueError:
            self.range_input.setProperty("invalid", True)
            repolish(self.range_input)
            self.range_error.setText(f"Use pages from 1 to {self.page_count}, like 1-5, 8")
            return
        self.grid.blockSignals(True)
        self.grid.clearSelection()
        for page in pages:
            self.grid.item(page).setSelected(True)
        self.grid.blockSignals(False)
        self._sync()
        self.grid.scrollToItem(self.grid.item(min(pages)))

    def _clear_range_error(self) -> None:
        if self.range_input.property("invalid"):
            self.range_input.setProperty("invalid", False)
            repolish(self.range_input)
        self.range_error.setText("")

    def _sync(self) -> None:
        count = len(self.grid.selectedIndexes())
        self.count_label.setText(f"{count} of {self.page_count} selected")
        self.accept_button.setText(f"Use {count} page{'s' if count != 1 else ''}" if count else "Select pages to continue")
        self.accept_button.setEnabled(count > 0)
