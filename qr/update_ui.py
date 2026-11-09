"""The window's Check for updates button: checks at startup and every six hours, and installs on request."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QPushButton

from . import APP_NAME, APP_VERSION, updates
from .widgets import repolish

if TYPE_CHECKING:
    from .window import MainWindow

CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000
FIRST_CHECK_DELAY_MS = 5000


class UpdateController(QObject):
    # Emitted from worker threads; Qt delivers them on the UI thread.
    _checked = Signal(object, bool)
    _check_failed = Signal(str, bool)
    _progress = Signal(float)
    _downloaded = Signal(object)
    _download_failed = Signal(str)

    def __init__(self, window: MainWindow, button: QPushButton, automatic: bool):
        super().__init__(window)
        self.window = window
        self.button = button
        self.available: updates.AvailableUpdate | None = None
        self.pending_setup: Path | None = None
        self.busy = False
        self._cancel = threading.Event()

        self._checked.connect(self._on_checked)
        self._check_failed.connect(self._on_check_failed)
        self._progress.connect(self._on_progress)
        self._downloaded.connect(self._on_downloaded)
        self._download_failed.connect(self._on_download_failed)
        button.clicked.connect(self.on_click)

        self._timer = QTimer(self)
        self._timer.setInterval(CHECK_INTERVAL_MS)
        self._timer.timeout.connect(lambda: self.check(manual=False))
        if automatic:
            # Let the window open first; the check is one small request.
            QTimer.singleShot(FIRST_CHECK_DELAY_MS, self, lambda: self.check(manual=False))
            self._timer.start()
        self.show_state()

    # ---------------------------------------------------------------- state

    def show_state(self) -> None:
        button = self.button
        button.setEnabled(True)
        if self.available is not None:
            button.setText(f"Update to {self.available.version}")
            button.setProperty("kind", "link")
            button.setToolTip(f"{APP_NAME} {self.available.version} is available (you have {APP_VERSION}). Click to install it.")
        else:
            button.setText("Check for updates")
            button.setProperty("kind", "ghost")
            button.setToolTip(f"{APP_NAME} {APP_VERSION}: check for updates")
        button.setAccessibleName(button.text())
        repolish(button)

    def _show_busy(self, text: str) -> None:
        self.button.setText(text)
        self.button.setEnabled(False)

    def report_last_result(self) -> None:
        """Say how the update that closed the previous session went."""
        result = updates.take_last_result()
        if not result:
            return
        if result.lower().startswith("failed"):
            detail = result.split(":", 1)[1].strip() if ":" in result else result
            self.window._say(f"The last update didn't install ({detail}). Click Check for updates to try again.")
        elif result.lower().startswith("installed"):
            self.window._say(f"Updated to {APP_NAME} {APP_VERSION}.")

    def shutdown(self) -> None:
        self._cancel.set()
        self._timer.stop()

    def _run(self, work) -> None:
        def guarded() -> None:
            try:
                work()
            except RuntimeError:
                pass  # The window closed while the thread ran.

        threading.Thread(target=guarded, name="QuickResize update", daemon=True).start()

    # ---------------------------------------------------------------- checking

    def on_click(self) -> None:
        if self.busy:
            return
        if self.pending_setup is not None:
            self._install_now()
        elif self.available is None:
            self.check(manual=True)
        else:
            self.install()

    def check(self, manual: bool) -> None:
        if self.busy or self.pending_setup is not None:
            return
        self.busy = True
        if manual:
            self._show_busy("Checking…")

        def work() -> None:
            try:
                found = updates.check()
            except updates.UpdateError as error:
                self._check_failed.emit(str(error), manual)
            else:
                self._checked.emit(found, manual)

        self._run(work)

    def _on_checked(self, found: updates.AvailableUpdate | None, manual: bool) -> None:
        self.busy = False
        self.available = found
        self.show_state()
        if manual:
            if found is None:
                self.window._say(f"{APP_NAME} is up to date (version {APP_VERSION}).")
            else:
                self.install()

    def _on_check_failed(self, message: str, manual: bool) -> None:
        # Automatic checks fail quietly when offline and try again later.
        self.busy = False
        self.show_state()
        if manual:
            self.window._say(f"Couldn't check for updates. {message}")

    # ---------------------------------------------------------------- installing

    def install(self) -> None:
        update = self.available
        if update is None or self.busy:
            return
        window = self.window
        if not updates.is_installed():
            answer = QMessageBox.question(
                window,
                f"Update {APP_NAME}",
                f"{APP_NAME} {update.version} is available. You have {APP_VERSION}.\n\n"
                "This copy is portable, so it can't update itself. Open the download page?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(update.release_url))
            return
        if window.is_running:
            window._say("Finish or cancel the batch before updating.")
            return
        size = f" ({update.size / 1048576:.0f} MB)" if update.size else ""
        kept = " The list of files is not kept." if window.entries else ""
        answer = QMessageBox.question(
            window,
            f"Update {APP_NAME}",
            f"{APP_NAME} {update.version} is available. You have {APP_VERSION}.\n\n"
            f"Download it{size} and install it now? {APP_NAME} will close, Windows will ask for permission "
            f"to install, and {APP_NAME} will open again when the update is done.{kept}",
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        self.busy = True
        self._show_busy("Downloading…")

        def work() -> None:
            try:
                path = updates.download(update, self._progress.emit, self._cancel)
            except updates.UpdateError as error:
                self._download_failed.emit(str(error))
            else:
                self._downloaded.emit(path)

        self._run(work)

    def _on_progress(self, fraction: float) -> None:
        if self.busy:
            self.button.setText(f"Downloading… {fraction:.0%}")

    def _on_download_failed(self, message: str) -> None:
        self.busy = False
        self.show_state()
        self.window._say(f"The update couldn't be downloaded. {message}")

    def _on_downloaded(self, path: Path) -> None:
        self.busy = False
        self.pending_setup = path
        if self.window.is_running:
            # A batch started during the download. Install when the user is ready.
            self.button.setText("Install update")
            self.button.setEnabled(True)
            self.window._say("The update is ready. Click Install update when the batch is done.")
            return
        self._install_now()

    def _install_now(self) -> None:
        if self.window.is_running:
            self.window._say("Finish or cancel the batch before updating.")
            return
        self._show_busy("Installing…")
        # The window's closeEvent hands the installer to the helper.
        self.window.close()

    def launch_pending(self) -> None:
        """Called as the window closes: start the helper that installs a downloaded update."""
        if self.pending_setup is None or self.available is None:
            return
        try:
            updates.launch_installer_after_exit(self.pending_setup, self.available.version)
        except OSError as error:
            QMessageBox.warning(
                None, APP_NAME, f"The update couldn't be started: {error}\n\nRun {self.pending_setup} to install it."
            )
