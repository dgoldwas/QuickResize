"""File, Edit, and Help commands shared by the menu and keyboard."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDialog, QGridLayout, QMenu, QMenuBar, QMessageBox

from . import APP_NAME, APP_VERSION
from .widgets import button, label

if TYPE_CHECKING:
    from .window import MainWindow


class AppMenu(QMenuBar):
    def __init__(self, window: MainWindow):
        super().__init__(window)
        self.window = window
        self.setNativeMenuBar(False)
        file = self.addMenu("&File")
        self.add_files = self._command(file, "Add &files…", window.choose_files, "Ctrl+O")
        self.add_folder = self._command(file, "Add f&older…", window.choose_folder, "Ctrl+Shift+O")
        file.addSeparator()
        self.output_folder = self._command(file, "Choose o&utput folder…", window.choose_destination)
        self.resize_batch = self._command(file, "&Resize files", window.start_or_cancel, "Ctrl+Return")
        file.addSeparator()
        self._command(file, "E&xit\tAlt+F4", window.close)

        edit = self.addMenu("&Edit")
        self.undo = self._command(edit, "&Undo removal", window.undo, "Ctrl+Z")
        edit.addSeparator()
        self.remove = self._command(edit, "&Remove selected\tDel", window.remove_selected)
        self.up = self._command(edit, "Move &up\tAlt+Up", lambda: window.move_selected(-1))
        self.down = self._command(edit, "Move &down\tAlt+Down", lambda: window.move_selected(1))
        self.pages = self._command(edit, "Choose &PDF pages…\tEnter", window.edit_selected_pdf)
        self.clear = self._command(edit, "&Clear list", window.clear_all)
        edit.addSeparator()
        self.settings = self._command(edit, "&Settings…", window.show_preferences, "Ctrl+,")

        help_menu = self.addMenu("&Help")
        self._command(help_menu, "&Keyboard shortcuts", self.show_shortcuts, "F1")
        help_menu.addSeparator()
        self.update_action = help_menu.addAction("Check for updates")
        self._command(help_menu, "&About QuickResize", self.show_about)

    @staticmethod
    def _command(menu: QMenu, text: str, callback: Callable, shortcut: str = "") -> QAction:
        action = menu.addAction(text)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        return action

    def show_shortcuts(self) -> None:
        dialog = QDialog(self.window)
        dialog.setObjectName("Preferences")
        dialog.setWindowTitle("Keyboard shortcuts")
        dialog.setMinimumWidth(390)
        layout = QGridLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(24)
        layout.setColumnStretch(0, 1)
        layout.addWidget(label("Keyboard shortcuts", "headline"), 0, 0, 1, 2)
        shortcuts = (
            ("Add files", "Ctrl+O"),
            ("Add folder", "Ctrl+Shift+O"),
            ("Select all queued files", "Ctrl+A"),
            ("Remove selected", "Delete"),
            ("Undo a removal", "Ctrl+Z"),
            ("Move selected", "Alt+Up / Alt+Down"),
            ("Choose pages for the selected PDF", "Enter"),
            ("Start or cancel resizing", "Ctrl+Enter"),
            ("Cancel resizing", "Esc"),
            ("Settings", "Ctrl+,"),
        )
        for row, (name, keys) in enumerate(shortcuts, start=1):
            layout.addWidget(label(name, "body"), row, 0)
            layout.addWidget(label(keys, "value"), row, 1, Qt.AlignmentFlag.AlignRight)
        done = button("Done", "primary")
        done.setDefault(True)
        done.clicked.connect(dialog.accept)
        layout.addWidget(done, len(shortcuts) + 1, 1, Qt.AlignmentFlag.AlignRight)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def show_about(self) -> None:
        QMessageBox.about(self.window, f"About {APP_NAME}", f"<b>{APP_NAME} {APP_VERSION}</b><p>Batch image resizing and conversion for Windows.</p>")
