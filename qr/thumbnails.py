"""Background thumbnail loading with a bounded in-memory cache."""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from pathlib import Path
from typing import Hashable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPixmap

from .core import Thumbnail, close_pdf_cache, make_thumbnail

MAX_CACHED = 600
MAX_QUEUED = 200


class ThumbnailService(QObject):
    """Loads previews off the UI thread, newest request first.

    Views request thumbnails as they paint rows, so serving the newest request
    first keeps what is on screen current while the user scrolls. Requests that
    were scrolled past fall off the queue and are simply requested again later.
    """

    ready = Signal(object, object)  # key, Thumbnail

    def __init__(self, workers: int = 2, parent: QObject | None = None):
        super().__init__(parent)
        self._workers = workers
        self._threads: list[threading.Thread] = []
        self._pending: deque[tuple[Hashable, Path, int | None, int]] = deque()
        self._known: set[Hashable] = set()
        self._wake = threading.Condition()
        self._stopping = False
        self._cache: OrderedDict[Hashable, QPixmap] = OrderedDict()
        self._delivered = _Relay()
        self._delivered.loaded.connect(self._on_loaded)

    def pixmap(self, key: Hashable) -> QPixmap | None:
        pixmap = self._cache.get(key)
        if pixmap is not None:
            self._cache.move_to_end(key)
        return pixmap

    def request(self, key: Hashable, path: Path, page: int | None, side: int) -> None:
        """Ask for a thumbnail. Repeat calls for a known key do nothing."""
        with self._wake:
            if key in self._known or self._stopping:
                return
            self._known.add(key)
            self._pending.append((key, path, page, side))
            while len(self._pending) > MAX_QUEUED:
                self._known.discard(self._pending.popleft()[0])
            if len(self._threads) < self._workers:
                thread = threading.Thread(target=self._run, name="thumbnails", daemon=True)
                self._threads.append(thread)
                thread.start()
            self._wake.notify()

    def shutdown(self) -> None:
        with self._wake:
            self._stopping = True
            self._pending.clear()
            self._wake.notify_all()

    def _run(self) -> None:
        while True:
            with self._wake:
                idle = not self._pending and not self._stopping
            if idle:
                close_pdf_cache()  # Windows must not see an idle app holding a PDF open.
            with self._wake:
                while not self._pending and not self._stopping:
                    self._wake.wait()
                if self._stopping:
                    return
                key, path, page, side = self._pending.pop()
            try:
                thumbnail = make_thumbnail(path, page, side)
                image = _to_qimage(thumbnail) if thumbnail.image is not None else None
            except Exception:  # An unreadable preview only means a placeholder icon.
                thumbnail, image = Thumbnail(None), None
            if self._stopping:
                return
            self._delivered.loaded.emit(key, thumbnail, image)

    def _on_loaded(self, key: Hashable, thumbnail: Thumbnail, image: QImage | None) -> None:
        if self._stopping:
            return
        if image is not None:
            self._cache[key] = QPixmap.fromImage(image)
            while len(self._cache) > MAX_CACHED:
                # An evicted preview may be requested again when it scrolls back in.
                evicted, _ = self._cache.popitem(last=False)
                with self._wake:
                    self._known.discard(evicted)
        self.ready.emit(key, thumbnail)


class _Relay(QObject):
    loaded = Signal(object, object, object)


def _to_qimage(thumbnail: Thumbnail) -> QImage:
    image = thumbnail.image
    assert image is not None
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    data = image.tobytes("raw", "RGBA")
    return QImage(data, image.width, image.height, image.width * 4, QImage.Format.Format_RGBA8888).copy()
