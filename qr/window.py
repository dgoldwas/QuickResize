"""The main window: adding files, choosing output settings, and running a batch."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent, QIcon, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import APP_NAME, APP_VERSION, theme
from .core import (
    IMAGE_EXTENSIONS,
    MAX_DIMENSION,
    BatchSummary,
    Job,
    JobResult,
    ResizeOptions,
    ScanResult,
    Thumbnail,
    close_pdf_cache,
    collect_inputs,
    format_bytes,
    path_key,
    pdf_page_count,
    plan_jobs,
    run_batch,
    summarize_add,
)
from .pdf_picker import PdfPagePicker
from .settings import Settings, load_settings, save_settings
from .thumbnails import ThumbnailService
from .update_ui import UpdateController
from .widgets import (
    DropOverlay,
    ElidedLabel,
    EmptyState,
    FileDelegate,
    FileList,
    IconLabel,
    QueueEntry,
    Segmented,
    Slider,
    button,
    label,
    new_item,
    repolish,
)

PRESETS = (1920, 1600, 1080, 800)
FORMAT_NOTES = {
    "JPG": "Best for photos. Transparent areas become white.",
    "PNG": "Lossless and keeps transparency. Larger files.",
    "WEBP": "Small files that keep transparency.",
    "TIFF": "Lossless, for print and archiving. Large files.",
    "BMP": "Uncompressed. Transparent areas become white.",
}


class _Bridge(QObject):
    """Carries results from worker threads onto the UI thread."""

    scanned = Signal(object)
    planned = Signal(int)
    job_started = Signal(object)
    job_finished = Signal(object)
    batch_finished = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or load_settings()
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.setMinimumSize(860, 600)

        self.entries: dict[int, QueueEntry] = {}
        self._next_id = 1
        self._undo: tuple[list[int], dict[int, QueueEntry]] | None = None
        self.is_running = False
        self.is_scanning = False
        self.is_picking = False
        self._close_after_run = False
        self._cancel = threading.Event()
        self._total_jobs = 0
        self._finished_jobs = 0
        self._last_summary: BatchSummary | None = None
        self._rows_by_key: dict[str, list[int]] = {}

        self.bridge = _Bridge(self)
        self.bridge.scanned.connect(self._on_scanned)
        self.bridge.planned.connect(self._on_planned)
        self.bridge.job_started.connect(self._on_job_started)
        self.bridge.job_finished.connect(self._on_job_finished)
        self.bridge.batch_finished.connect(self._on_batch_finished)

        self.thumbnails = ThumbnailService(parent=self)
        self.thumbnails.ready.connect(self._on_thumbnail)
        self._repaint = QTimer(self)
        self._repaint.setSingleShot(True)
        self._repaint.setInterval(30)
        self._repaint.timeout.connect(lambda: self.file_list.viewport().update())
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self.save_now)

        self._build()
        self._apply_settings()
        self._connect_settings()
        self._add_shortcuts()
        self._refresh()
        # Only packaged builds check on their own, so tests and source runs stay offline.
        self.updater = UpdateController(self, self.update_button, automatic=getattr(sys, "frozen", False))
        self.updater.report_last_result()

        restored = bool(self.settings.geometry) and self.restoreGeometry(QByteArray.fromHex(self.settings.geometry.encode()))
        if not restored:
            screen = self.screen().availableGeometry()
            self.resize(min(1120, screen.width()), min(760, screen.height()))

    # ---------------------------------------------------------------- construction

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Workspace")
        root.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # Clicking empty space leaves a text field.
        root.setFocus()  # Nothing should look focused until the user tabs.
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_files_area(), 1)
        outer.addWidget(self._build_side_panel())
        self.overlay = DropOverlay(root)

    def _build_files_area(self) -> QWidget:
        area = QWidget()
        layout = QVBoxLayout(area)
        layout.setContentsMargins(20, 14, 14, 10)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(IconLabel(QIcon(str(asset_path("QuickResize.ico"))), 24))
        top.addWidget(label(APP_NAME, "title"))
        version = label(f"v{APP_VERSION}", "version")
        top.addWidget(version)
        self.update_button = button("Check for updates", "ghost")
        top.addWidget(self.update_button)
        top.addStretch(1)
        self.top_add_files = button("Add files", icon_name="plus", tooltip="Add files (Ctrl+O)")
        self.top_add_files.clicked.connect(self.choose_files)
        top.addWidget(self.top_add_files)
        self.top_add_folder = button("Add folder", icon_name="folder", tooltip="Add folder, including subfolders (Ctrl+Shift+O)")
        self.top_add_folder.clicked.connect(self.choose_folder)
        top.addWidget(self.top_add_folder)
        layout.addLayout(top)

        self.stack = QStackedWidget()
        self.empty_add_files = button("Browse files", "primary", "plus", "#FFFFFF")
        self.empty_add_files.clicked.connect(self.choose_files)
        self.empty_add_folder = button("Add folder", icon_name="folder")
        self.empty_add_folder.setMinimumHeight(38)
        self.empty_add_folder.clicked.connect(self.choose_folder)
        self.empty_state = EmptyState(self.empty_add_files, self.empty_add_folder)
        self.empty_state.browse.connect(self.choose_files)
        self.stack.addWidget(self.empty_state)

        queue_page = QWidget()
        queue_layout = QVBoxLayout(queue_page)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(6)
        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 0, 0)
        header.setSpacing(2)
        self.count_label = label("", "count")
        header.addWidget(self.count_label)
        self.total_label = label("", "message")
        header.addSpacing(8)
        header.addWidget(self.total_label)
        header.addStretch(1)
        self.selection_label = label("", "message")
        header.addWidget(self.selection_label)
        header.addSpacing(4)
        self.up_button = button("", "ghost", "up", theme.MUTED, "Move up (Alt+Up)")
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        header.addWidget(self.up_button)
        self.down_button = button("", "ghost", "down", theme.MUTED, "Move down (Alt+Down)")
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        header.addWidget(self.down_button)
        self.remove_button = button("Remove", "ghost", "trash", theme.MUTED, "Remove selected (Delete)")
        self.remove_button.clicked.connect(self.remove_selected)
        header.addWidget(self.remove_button)
        self.clear_button = button("Clear all", "ghost")
        self.clear_button.clicked.connect(self.clear_all)
        header.addWidget(self.clear_button)
        queue_layout.addLayout(header)

        self.delegate = FileDelegate(self.thumbnails)
        self.delegate.entries = self.entries
        self.file_list = FileList(self.delegate)
        self.file_list.remove_requested.connect(self._remove_entry)
        self.file_list.pages_requested.connect(self._edit_pages)
        self.file_list.delete_pressed.connect(self.remove_selected)
        self.file_list.move_pressed.connect(self.move_selected)
        self.file_list.itemSelectionChanged.connect(self._sync_selection)
        queue_layout.addWidget(self.file_list, 1)
        self.stack.addWidget(queue_page)
        layout.addWidget(self.stack, 1)

        message_row = QHBoxLayout()
        message_row.setContentsMargins(4, 0, 0, 0)
        message_row.setSpacing(6)
        self.message_label = ElidedLabel()
        message_row.addWidget(self.message_label, 1)
        self.undo_button = button("Undo", "link", tooltip="Undo (Ctrl+Z)")
        self.undo_button.clicked.connect(self.undo)
        self.undo_button.hide()
        message_row.addWidget(self.undo_button)
        layout.addLayout(message_row)
        return area

    def _build_side_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("SidePanel")
        panel.setFixedWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(1, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("SideScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("SideContent")
        self.settings_area = content
        scroll.setWidget(content)
        body = QVBoxLayout(content)
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(0)

        # Size
        body.addWidget(label("Fit inside", "section"))
        body.addSpacing(7)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.preset_buttons: dict[int, object] = {}
        for size in PRESETS:
            chip = button(str(size), "chip", tooltip=f"Fit inside {size} \u00d7 {size} pixels")
            chip.setCheckable(True)
            chip.clicked.connect(lambda _checked=False, value=size: self._apply_preset(value))
            self.preset_buttons[size] = chip
            chips.addWidget(chip, 1)
        body.addLayout(chips)
        body.addSpacing(8)
        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        self.width_input = self._dimension_input("Maximum width in pixels")
        self.height_input = self._dimension_input("Maximum height in pixels")
        size_row.addWidget(self.width_input, 1)
        size_row.addWidget(label("\u00d7", "sep"))
        size_row.addWidget(self.height_input, 1)
        size_row.addWidget(label("px", "sep"))
        body.addLayout(size_row)
        body.addSpacing(5)
        self.size_note = label("Keeps proportions. Never crops or enlarges.", "caption", wrap=True)
        body.addWidget(self.size_note)
        body.addSpacing(18)

        # Format
        body.addWidget(label("Format", "section"))
        body.addSpacing(7)
        self.format_choice = Segmented([(name, name) for name in FORMAT_NOTES])
        body.addWidget(self.format_choice)
        body.addSpacing(5)
        self.format_note = label("", "caption", wrap=True)
        body.addWidget(self.format_note)
        self.quality_area = QWidget()
        quality_layout = QVBoxLayout(self.quality_area)
        quality_layout.setContentsMargins(0, 12, 0, 0)
        quality_layout.setSpacing(4)
        quality_header = QHBoxLayout()
        quality_header.addWidget(label("Quality", "section"))
        quality_header.addStretch(1)
        self.quality_value = label("", "value")
        quality_header.addWidget(self.quality_value)
        quality_layout.addLayout(quality_header)
        self.quality_slider = Slider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setAccessibleName("Quality")
        self.quality_slider.setMinimumHeight(22)
        quality_layout.addWidget(self.quality_slider)
        body.addWidget(self.quality_area)
        body.addSpacing(18)

        # Destination
        body.addWidget(label("Save to", "section"))
        body.addSpacing(7)
        self.destination_choice = Segmented([("folder", "One folder"), ("beside", "Next to originals")])
        body.addWidget(self.destination_choice)
        self.folder_area = QWidget()
        folder_layout = QHBoxLayout(self.folder_area)
        folder_layout.setContentsMargins(0, 8, 0, 0)
        folder_layout.setSpacing(6)
        self.destination_input = QLineEdit()
        self.destination_input.setAccessibleName("Destination folder")
        self.destination_input.setAcceptDrops(False)
        folder_layout.addWidget(self.destination_input, 1)
        self.destination_button = button("", icon_name="folder", tooltip="Choose folder")
        self.destination_button.clicked.connect(self.choose_destination)
        folder_layout.addWidget(self.destination_button)
        body.addWidget(self.folder_area)
        body.addSpacing(18)

        # Existing files
        body.addWidget(label("If a file already exists", "section"))
        body.addSpacing(7)
        self.exists_choice = Segmented([("keep", "Keep both"), ("replace", "Replace it")])
        body.addWidget(self.exists_choice)
        body.addSpacing(5)
        self.exists_note = label("", "caption", wrap=True)
        body.addWidget(self.exists_note)
        body.addStretch(1)

        layout.addWidget(scroll, 1)
        layout.addWidget(self._build_action_area())
        return panel

    def _dimension_input(self, name: str) -> QLineEdit:
        field = QLineEdit()
        field.setAccessibleName(name)
        field.setToolTip(name)
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        field.setMaxLength(6)
        field.setAcceptDrops(False)
        return field

    def _build_action_area(self) -> QWidget:
        area = QFrame()
        area.setObjectName("ActionArea")
        layout = QVBoxLayout(area)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(8)

        self.result_card = QFrame()
        self.result_card.setObjectName("ResultCard")
        card = QVBoxLayout(self.result_card)
        card.setContentsMargins(12, 10, 8, 10)
        card.setSpacing(3)
        title_row = QHBoxLayout()
        self.result_title = label("", "resultTitle")
        title_row.addWidget(self.result_title, 1)
        self.result_close = button("", "ghost", "close", theme.MUTED, "Dismiss")
        self.result_close.clicked.connect(self._dismiss_result)
        title_row.addWidget(self.result_close, 0, Qt.AlignmentFlag.AlignTop)
        card.addLayout(title_row)
        self.result_body = label("", "resultBody", wrap=True)
        card.addWidget(self.result_body)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 6, 4, 0)
        actions.setSpacing(6)
        self.open_button = button("Open folder", icon_name="folder")
        self.open_button.clicked.connect(self.open_result_folder)
        actions.addWidget(self.open_button, 1)
        self.retry_button = button("Retry failed")
        self.retry_button.clicked.connect(self.retry_failed)
        actions.addWidget(self.retry_button, 1)
        self.result_clear_button = button("Clear list")
        self.result_clear_button.clicked.connect(self.clear_all)
        actions.addWidget(self.result_clear_button, 1)
        card.addLayout(actions)
        self.result_card.hide()
        layout.addWidget(self.result_card)

        self.progress_label = ElidedLabel()
        self.progress_label.hide()
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.summary_label = label("", "caption", wrap=True)
        layout.addWidget(self.summary_label)
        self.resize_button = button("", "primary")
        self.resize_button.setMinimumHeight(42)
        self.resize_button.clicked.connect(self.start_or_cancel)
        layout.addWidget(self.resize_button)
        return area

    def _add_shortcuts(self) -> None:
        for sequence, action in (
            (QKeySequence.StandardKey.Open, self.choose_files),
            ("Ctrl+Shift+O", self.choose_folder),
            (QKeySequence.StandardKey.Undo, self.undo),
            ("Ctrl+Return", self.start_or_cancel),
        ):
            QShortcut(QKeySequence(sequence), self, activated=action)
        QShortcut(QKeySequence("Escape"), self, activated=self._on_escape)

    def _apply_settings(self) -> None:
        settings = self.settings
        self.width_input.setText(settings.width)
        self.height_input.setText(settings.height)
        self.format_choice.set_value(settings.fmt)
        self.quality_slider.setValue(settings.quality)
        self.destination_input.setText(settings.destination)
        self.destination_choice.set_value("beside" if settings.save_beside else "folder")
        self.exists_choice.set_value("replace" if settings.replace else "keep")

    def _connect_settings(self) -> None:
        self.width_input.textChanged.connect(self._on_setting_changed)
        self.height_input.textChanged.connect(self._on_setting_changed)
        self.destination_input.textChanged.connect(self._on_setting_changed)
        self.format_choice.changed.connect(self._on_setting_changed)
        self.destination_choice.changed.connect(self._on_setting_changed)
        self.exists_choice.changed.connect(self._on_setting_changed)
        self.quality_slider.valueChanged.connect(self._on_setting_changed)

    # ---------------------------------------------------------------- settings

    def _on_setting_changed(self, *_args: object) -> None:
        self._refresh()
        self._save_timer.start()

    def _apply_preset(self, size: int) -> None:
        self.width_input.setText(str(size))
        self.height_input.setText(str(size))
        self._refresh()  # Re-clicking the active chip changes no text, but unchecks the chip.

    def _dimension(self, field: QLineEdit) -> int | None:
        text = field.text().strip()
        if text.isdecimal() and 1 <= int(text) <= MAX_DIMENSION:
            return int(text)
        return None

    def _box(self) -> tuple[int, int] | None:
        width, height = self._dimension(self.width_input), self._dimension(self.height_input)
        return (width, height) if width and height else None

    def _collect_settings(self) -> Settings:
        return Settings(
            width=self.width_input.text().strip(),
            height=self.height_input.text().strip(),
            fmt=self.format_choice.value(),
            quality=self.quality_slider.value(),
            destination=self.destination_input.text().strip(),
            save_beside=self.destination_choice.value() == "beside",
            replace=self.exists_choice.value() == "replace",
            geometry=bytes(self.saveGeometry().toHex().data()).decode(),
        )

    def save_now(self) -> None:
        self._save_timer.stop()
        save_settings(self._collect_settings())

    def _output_blocker(self) -> str:
        """Explain why a batch cannot start, so problems appear before pressing the button."""
        if self._box() is None:
            return f"Enter a width and height from 1 to {MAX_DIMENSION}."
        if self.destination_choice.value() == "folder":
            destination = self.destination_input.text().strip()
            if not destination:
                return "Choose a folder to save to."
            if not Path(destination).expanduser().is_absolute():
                return "Enter a full folder path, like C:\\Photos."
        return ""

    # ---------------------------------------------------------------- view state

    def _set_invalid(self, field: QLineEdit, invalid: bool) -> None:
        if bool(field.property("invalid")) != invalid:
            field.setProperty("invalid", invalid)
            repolish(field)

    def _refresh(self) -> None:
        """Bring everything derived from the settings and queue up to date."""
        count = self.file_list.count()
        has_files = count > 0
        self.stack.setCurrentIndex(1 if has_files else 0)
        self.top_add_files.setVisible(has_files)
        self.top_add_folder.setVisible(has_files)

        width, height = self._dimension(self.width_input), self._dimension(self.height_input)
        self._set_invalid(self.width_input, width is None)
        self._set_invalid(self.height_input, height is None)
        for size, chip in self.preset_buttons.items():
            chip.setChecked(width == size and height == size)
        box = self._box()
        if box != self.delegate.box:
            self.delegate.box = box
            self.file_list.viewport().update()

        fmt = self.format_choice.value()
        self.format_note.setText(FORMAT_NOTES[fmt])
        self.quality_area.setVisible(fmt in ("JPG", "WEBP"))
        self.quality_value.setText(str(self.quality_slider.value()))
        beside = self.destination_choice.value() == "beside"
        self.folder_area.setVisible(not beside)
        replace = self.exists_choice.value() == "replace"
        self.exists_note.setText("Existing output files are overwritten. Your originals are always safe." if replace else "A number is added to the new file's name.")
        self.exists_note.setProperty("tone", "warn" if replace else None)
        repolish(self.exists_note)

        images = sum(len(entry.pages) if entry.pages is not None else 1 for entry in self.entries.values())
        total = sum(entry.size for entry in self.entries.values())
        self.count_label.setText(f"{count} file{'s' if count != 1 else ''}")
        self.total_label.setText(format_bytes(total) if total else "")
        self._sync_selection()

        blocker = self._output_blocker()
        if self.is_running:
            self.resize_button.setText("Stopping\u2026" if self._cancel.is_set() else "Cancel")
            self.resize_button.setProperty("kind", None)
            self.resize_button.setEnabled(not self._cancel.is_set())
            self.summary_label.hide()
        else:
            self.resize_button.setProperty("kind", "primary")
            noun = "image" if images == 1 else "images"
            self.resize_button.setText(f"Resize {images} {noun}" if images else "Add files to start")
            self.resize_button.setEnabled(bool(images) and not blocker and not self.is_scanning)
            # The result card already covers this space with something more useful.
            self.summary_label.setVisible(bool(blocker) or (bool(images) and self.result_card.isHidden()))
            self.summary_label.setProperty("tone", "error" if blocker else None)
            self.summary_label.setText(blocker or self._describe_output(box))
            repolish(self.summary_label)
        repolish(self.resize_button)

        locked = self.is_running or self.is_scanning
        for control in (self.top_add_files, self.top_add_folder, self.empty_add_files, self.empty_add_folder, self.clear_button):
            control.setEnabled(not locked)
        self.settings_area.setEnabled(not self.is_running)
        self.delegate.locked = self.is_running

    def _describe_output(self, box: tuple[int, int] | None) -> str:
        if not box:
            return ""
        return f"Saves as {self.format_choice.value()}, up to {box[0]} \u00d7 {box[1]} pixels"

    def _sync_selection(self) -> None:
        rows = self.file_list.selected_rows()
        has = bool(rows) and not self.is_running
        for control in (self.up_button, self.down_button, self.remove_button):
            control.setVisible(has)
        self.up_button.setEnabled(has and rows[0] > 0)
        self.down_button.setEnabled(has and rows[-1] < self.file_list.count() - 1)
        self.selection_label.setVisible(len(rows) > 1 and not self.is_running)
        self.selection_label.setText(f"{len(rows)} selected")
        self.clear_button.setVisible(not has and self.file_list.count() > 0)

    def _say(self, text: str, undoable: bool = False) -> None:
        self.message_label.setText(text)
        self.undo_button.setVisible(undoable)
        if not undoable:
            self._undo = None

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.centralWidget().rect())

    def _on_thumbnail(self, key: tuple[str, object], thumbnail: Thumbnail) -> None:
        for entry_id in self._rows_by_key.get(path_key(key[0]), ()):
            entry = self.entries.get(entry_id)
            if entry is not None:
                if thumbnail.size:
                    entry.dimensions = thumbnail.size
                if thumbnail.page_count:
                    entry.page_count = thumbnail.page_count
        if not self._repaint.isActive():
            self._repaint.start()

    # ---------------------------------------------------------------- adding files

    def _can_accept_files(self) -> bool:
        return not (self.is_running or self.is_scanning or self.is_picking)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and self._can_accept_files():
            event.acceptProposedAction()
            self.overlay.raise_()
            self.overlay.show()
        else:
            event.ignore()

    def dragLeaveEvent(self, _event: object) -> None:
        self.overlay.hide()

    def dropEvent(self, event: QDropEvent) -> None:
        self.overlay.hide()
        if not self._can_accept_files():
            event.ignore()
            return
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        event.acceptProposedAction()
        self.add_paths(paths)

    def choose_files(self) -> None:
        if not self._can_accept_files():
            return
        patterns = " ".join(f"*{extension}" for extension in sorted(IMAGE_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files", "", f"Supported files ({patterns});;All files (*.*)")
        if paths:
            self.add_paths([Path(path) for path in paths])

    def choose_folder(self) -> None:
        if not self._can_accept_files():
            return
        selected = QFileDialog.getExistingDirectory(self, "Choose a folder of photos")
        if selected:
            self.add_paths([Path(selected)])

    def choose_destination(self) -> None:
        current = self.destination_input.text().strip()
        start = current if current and Path(current).is_dir() else str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if selected:
            self.destination_input.setText(os.path.normpath(selected))

    def add_paths(self, paths: list[Path]) -> None:
        if not paths or not self._can_accept_files():
            return
        self.is_scanning = True
        self._say("Looking for files\u2026")
        self._refresh()
        # A large or network folder can take a while, and the window must stay live.
        threading.Thread(target=lambda: self.bridge.scanned.emit(collect_inputs(paths)), name="scan", daemon=True).start()

    def _on_scanned(self, result: ScanResult) -> None:
        self.is_scanning = False
        known = {path_key(entry.path): entry for entry in self.entries.values()}
        added = duplicates = 0
        pdfs = []
        for scanned in result.files:
            key = path_key(scanned.path)
            if scanned.path.suffix.lower() == ".pdf":
                pdfs.append(scanned)
            elif key in known:
                duplicates += 1
            else:
                known[key] = self._append_entry(scanned.path, scanned.size)
                added += 1

        # Show what was added right away, behind any PDF page picker.
        self._refresh()
        updated = cancelled = 0
        for position, scanned in enumerate(pdfs, start=1):
            existing = known.get(path_key(scanned.path))
            pages, page_count = self._pick_pages(scanned.path, existing.pages if existing else None, (position, len(pdfs)))
            if not pages:
                cancelled += 1
            elif existing is not None:
                existing.pages, existing.page_count = pages, page_count
                self._reset_status(existing)
                updated += 1
            else:
                entry = self._append_entry(scanned.path, scanned.size)
                entry.pages, entry.page_count = pages, page_count
                known[path_key(scanned.path)] = entry
                added += 1
        close_pdf_cache()
        self._say(summarize_add(added, updated, duplicates, result.unsupported, result.decoder_skips, cancelled))
        self._refresh()

    def _append_entry(self, path: Path, size: int) -> QueueEntry:
        entry = QueueEntry(self._next_id, path, size)
        self._next_id += 1
        self.entries[entry.id] = entry
        self.file_list.addItem(new_item(entry))
        self._rows_by_key.setdefault(path_key(path), []).append(entry.id)
        return entry

    def _pick_pages(self, path: Path, initial: list[int] | None, position: tuple[int, int] | None = None) -> tuple[list[int] | None, int | None]:
        try:
            page_count = pdf_page_count(path)
        except Exception as exc:
            self._say(f"Could not open {path.name}: {exc}")
            QMessageBox.warning(self, "Could not open PDF", f"{path.name}\n\n{exc}")
            return None, None
        if page_count < 1:
            QMessageBox.information(self, "No pages", f"{path.name} does not contain any pages.")
            return None, None
        self.is_picking = True
        try:
            picker = PdfPagePicker(path, page_count, self.thumbnails, initial, position, self)
            accepted = picker.exec() == PdfPagePicker.DialogCode.Accepted
            return (picker.selected_pages() if accepted else None), page_count
        finally:
            self.is_picking = False

    def _edit_pages(self, entry_id: int) -> None:
        entry = self.entries.get(entry_id)
        if entry is None or not self._can_accept_files():
            return
        pages, page_count = self._pick_pages(entry.path, entry.pages)
        close_pdf_cache()
        if pages:
            entry.pages, entry.page_count = pages, page_count
            self._reset_status(entry)
            self._say(f"Updated pages for {entry.path.name}")
            self._refresh()
            self.file_list.viewport().update()

    def _reset_status(self, entry: QueueEntry) -> None:
        entry.status, entry.message, entry.bytes_out = "", "", 0
        entry.failed_pages = []

    # ---------------------------------------------------------------- changing the list

    def _snapshot(self) -> None:
        order = [entry.id for entry in self.file_list.ordered_entries()]
        self._undo = (order, dict(self.entries))

    def _drop_entries(self, doomed: set[int]) -> None:
        # Qt reports a selection change per row here. The caller refreshes once afterward.
        self.file_list.blockSignals(True)
        if len(doomed) == self.file_list.count():
            self.file_list.clear()
        else:
            for row in range(self.file_list.count() - 1, -1, -1):
                if self.file_list.item(row).data(Qt.ItemDataRole.UserRole) in doomed:
                    self.file_list.takeItem(row)
        self.file_list.blockSignals(False)
        for entry_id in doomed:
            entry = self.entries.pop(entry_id)
            ids = self._rows_by_key.get(path_key(entry.path), [])
            if entry_id in ids:
                ids.remove(entry_id)

    def _remove_with_undo(self, doomed: set[int], text: str) -> None:
        if self.is_running or not doomed:
            return
        self._snapshot()
        self._drop_entries(doomed)
        self._say(text, undoable=True)
        self._refresh()

    def _remove_entry(self, entry_id: int) -> None:
        entry = self.entries.get(entry_id)
        if entry is not None:
            self._remove_with_undo({entry_id}, f"Removed {entry.path.name}")

    def remove_selected(self) -> None:
        rows = self.file_list.selected_rows()
        doomed = {self.file_list.item(row).data(Qt.ItemDataRole.UserRole) for row in rows}
        if len(doomed) == 1:
            self._remove_entry(next(iter(doomed)))
        else:
            self._remove_with_undo(doomed, f"Removed {len(doomed)} files")
        if rows and self.file_list.count():
            self.file_list.setCurrentRow(min(rows[0], self.file_list.count() - 1))

    def clear_all(self) -> None:
        if self.file_list.count():
            self._dismiss_result()
            count = self.file_list.count()
            self._remove_with_undo(set(self.entries), f"Cleared {count} file{'s' if count != 1 else ''}")

    def undo(self) -> None:
        if self._undo is None or self.is_running:
            return
        order, entries = self._undo
        self.file_list.blockSignals(True)
        self.file_list.clear()
        self.entries.clear()
        self.entries.update(entries)
        self._rows_by_key.clear()
        for entry_id in order:
            entry = self.entries[entry_id]
            self.file_list.addItem(new_item(entry))
            self._rows_by_key.setdefault(path_key(entry.path), []).append(entry_id)
        self.file_list.blockSignals(False)
        self._say("Restored")
        self._refresh()

    def move_selected(self, direction: int) -> None:
        rows = self.file_list.selected_rows()
        if not rows or self.is_running:
            return
        destination = rows[0] + direction
        if destination < 0 or rows[-1] + direction >= self.file_list.count():
            return
        self.file_list.move_block(rows, destination)
        self.file_list.scrollToItem(self.file_list.item(destination if direction < 0 else destination + len(rows) - 1))

    # ---------------------------------------------------------------- running a batch

    def start_or_cancel(self) -> None:
        if self.is_running:
            self.cancel()
        elif self.resize_button.isEnabled():
            self.start([(entry, entry.pages) for entry in self.file_list.ordered_entries()])

    def _on_escape(self) -> None:
        if self.is_running:
            self.cancel()

    def _options(self) -> ResizeOptions:
        box = self._box()
        assert box is not None
        beside = self.destination_choice.value() == "beside"
        return ResizeOptions(
            box[0],
            box[1],
            fmt=self.format_choice.value(),
            quality=self.quality_slider.value(),
            destination=None if beside else Path(self.destination_input.text().strip()).expanduser(),
            replace=self.exists_choice.value() == "replace",
        )

    def start(self, work: list[tuple[QueueEntry, list[int] | None]]) -> None:
        """Begin processing the given entries and, for a PDF, the given pages."""
        options = self._options()
        items = [(entry.id, entry.path, pages) for entry, pages in work]
        for entry, pages in work:
            self._reset_status(entry)
            entry.status = "waiting"
            entry.finished = 0
            entry.expected = len(pages) if pages is not None else 1
        self.save_now()
        self._dismiss_result()
        self._cancel.clear()
        self.is_running = True
        self._total_jobs = self._finished_jobs = 0
        self.file_list.clearSelection()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.progress_label.setText("Preparing\u2026")
        self.progress_label.show()
        self._say("")
        self._refresh()
        self.file_list.viewport().update()

        bridge = self.bridge

        def task() -> None:
            summary = BatchSummary()
            try:
                jobs = plan_jobs(items, options)
                bridge.planned.emit(len(jobs))
                summary = run_batch(jobs, options, self._cancel, bridge.job_started.emit, bridge.job_finished.emit)
            except Exception as exc:  # The window must always return to a usable state.
                summary.errors.append(str(exc))
            bridge.batch_finished.emit(summary)

        threading.Thread(target=task, name="batch", daemon=False).start()

    def _on_planned(self, total: int) -> None:
        self._total_jobs = total
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(0)

    def cancel(self) -> None:
        if self.is_running and not self._cancel.is_set():
            self._cancel.set()
            self.progress_label.setText("Finishing the files in progress\u2026")
            self._refresh()

    def _on_job_started(self, job: Job) -> None:
        entry = self.entries.get(job.tag)
        if entry is not None:
            entry.status = "working"
            self._update_row()
        if not self._cancel.is_set():
            self.progress_label.setText(f"{self._finished_jobs} of {self._total_jobs}  \u00b7  {job.label}")

    def _update_row(self) -> None:
        if not self._repaint.isActive():
            self._repaint.start()

    def _on_job_finished(self, result: JobResult) -> None:
        self._finished_jobs += 1
        self.progress_bar.setValue(self._finished_jobs)
        if not self._cancel.is_set():
            self.progress_label.setText(f"{self._finished_jobs} of {self._total_jobs}  \u00b7  {result.job.label}")
        entry = self.entries.get(result.job.tag)
        if entry is None:
            return
        entry.finished += 1
        if result.ok:
            entry.bytes_out += result.bytes_out
        else:
            if result.job.page is not None:
                entry.failed_pages.append(result.job.page)
            count = len(entry.failed_pages)
            prefix = f"{count} page{'s' if count != 1 else ''} failed: " if count else ""
            entry.message = prefix + result.error
        if entry.finished >= entry.expected:
            failures = len(entry.failed_pages) if entry.is_pdf else (1 if entry.message else 0)
            entry.status = "done" if not failures else "failed" if failures >= entry.expected else "partial"
        self._update_row()

    def _on_batch_finished(self, summary: BatchSummary) -> None:
        self.is_running = False
        self.progress_bar.hide()
        self.progress_label.hide()
        for entry in self.entries.values():
            if entry.status == "waiting" or (entry.status == "working" and entry.finished < entry.expected):
                entry.status = ""
        for row in range(self.file_list.count()):
            entry = self.file_list.entry_at(row)
            self.file_list.item(row).setToolTip(f"{entry.path}\n\n{entry.message}" if entry.message else str(entry.path))
        self._last_summary = summary
        self._show_result(summary)
        self._refresh()
        self.file_list.viewport().update()
        if self._close_after_run:
            self.close()

    def _show_result(self, summary: BatchSummary) -> None:
        saved, failed = summary.saved, len(summary.errors)
        noun = "image" if saved == 1 else "images"
        tone = "warn" if failed or summary.cancelled or not saved else "ok"
        if summary.cancelled:
            title = f"Stopped after {saved} {noun}"
        elif not saved:
            title = "Nothing was saved"
        elif failed:
            title = f"Saved {saved} {noun}, {failed} failed"
        else:
            title = f"Saved {saved} {noun}"
        details: list[str] = []
        if summary.bytes_in and summary.bytes_out:
            change = 1 - summary.bytes_out / summary.bytes_in
            trend = f"{change:.0%} smaller" if change >= 0.005 else f"{-change:.0%} larger" if change <= -0.005 else "about the same size"
            details.append(f"{format_bytes(summary.bytes_in)} \u2192 {format_bytes(summary.bytes_out)}, {trend}")
        if summary.elapsed >= 0.05 and saved:
            details.append(f"Took {summary.elapsed:.1f} s")
        if failed and not any(entry.status in ("failed", "partial") for entry in self.entries.values()):
            details.append(summary.errors[0])
        elif failed:
            details.append("Failed files are marked in the list.")
        self.result_title.setText(title)
        self.result_body.setText("  \u00b7  ".join(details[:2]) if not failed else "\n".join(details))
        self.result_body.setVisible(bool(details))
        self.result_card.setProperty("tone", tone)
        repolish(self.result_card)
        self.open_button.setVisible(bool(saved and summary.folder and summary.folder.is_dir()))
        can_retry = any(entry.status in ("failed", "partial") for entry in self.entries.values())
        self.retry_button.setVisible(can_retry)
        self.result_clear_button.setVisible(not can_retry)
        self.result_card.show()
        self._say("")
        for row in range(self.file_list.count()):
            entry = self.file_list.entry_at(row)
            if entry is not None and entry.status in ("failed", "partial"):
                self.file_list.scrollToItem(self.file_list.item(row))
                break

    def _dismiss_result(self) -> None:
        self.result_card.hide()
        self._refresh()

    def open_result_folder(self) -> None:
        folder = self._last_summary.folder if self._last_summary else None
        if folder is None:
            return
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except OSError as exc:
            self._say(f"Could not open folder: {exc}")

    def retry_failed(self) -> None:
        if self.is_running:
            return
        work = []
        for entry in self.file_list.ordered_entries():
            if entry.status in ("failed", "partial"):
                work.append((entry, list(entry.failed_pages) if entry.is_pdf else None))
        if work:
            self.start(work)

    # ---------------------------------------------------------------- closing

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.is_running:
            event.ignore()
            if self._close_after_run:
                return
            answer = QMessageBox.question(self, "Stop and quit?", "Images are still being resized. Stop after the files in progress and quit?")
            if answer == QMessageBox.StandardButton.Yes:
                self._close_after_run = True
                self.cancel()
                self.hide()  # The window goes now; the process exits when the workers finish.
            return
        self.save_now()
        self.updater.shutdown()
        self.thumbnails.shutdown()
        close_pdf_cache()
        event.accept()
        self.updater.launch_pending()
        if self._close_after_run:
            QApplication.quit()


def asset_path(name: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) if base else Path(__file__).resolve().parent.parent) / "assets" / name
