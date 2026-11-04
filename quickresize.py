"""QuickResize - lightweight Windows bulk image resizer.

Run with: python quickresize.py
Install dependencies with: pip install -r requirements.txt
"""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from qr import APP_NAME, APP_VERSION, theme
from qr.window import MainWindow, asset_path


def create_application(argv: list[str]) -> QApplication:
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)  # Also darkens the title bar.
    app.setFont(theme.ui_font(10))
    app.setStyleSheet(theme.STYLESHEET)
    app.setWindowIcon(QIcon(str(asset_path("QuickResize.ico"))))
    return app


def main() -> int:
    if sys.platform == "win32":
        # Group the window under the app's own taskbar icon when run from source.
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("QuickResize.App")
        except (AttributeError, OSError):
            pass
    app = create_application(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
