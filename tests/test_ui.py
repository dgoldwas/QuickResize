"""Drives the real widgets offscreen: clicks, drags, drops, and whole batches."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from qr import core, settings as settings_module
from qr.pdf_picker import PdfPagePicker
from qr.settings import Settings, load_settings
from qr.window import MainWindow

import quickresize


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or quickresize.create_application(["test"])


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "appdata" / "settings.json"
    monkeypatch.setattr(settings_module, "settings_path", lambda: path)
    return path


@pytest.fixture
def window(app, tmp_path, settings_file):
    win = MainWindow(Settings(destination=str(tmp_path / "out")))
    win.resize(1100, 720)
    win.show()
    yield win
    wait(lambda: not win.is_running)
    win.close()


def wait(condition, timeout=20.0):
    end = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < end, "timed out"
        QApplication.processEvents()
        time.sleep(0.002)


def pump(ms=30):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QApplication.processEvents()


def images(folder: Path, count=3, size=(300, 200)) -> list[Path]:
    folder.mkdir(exist_ok=True)
    paths = []
    for index in range(count):
        path = folder / f"p{index}.png"
        Image.new("RGB", size, (index * 40, 90, 120)).save(path)
        paths.append(path)
    return paths


def add(win, paths):
    win.add_paths(paths)
    wait(lambda: not win.is_scanning)
    pump()


def names(win):
    return [entry.path.name for entry in win.file_list.ordered_entries()]


def row_center(win, row) -> QPoint:
    return win.file_list.visualRect(win.file_list.model().index(row, 0)).center()


def run_to_end(win):
    win.resize_button.click()
    assert win.is_running
    wait(lambda: not win.is_running)
    pump()


# --- First run and validation ------------------------------------------------------


def test_starts_empty_with_action_disabled(window):
    assert window.stack.currentIndex() == 0
    assert not window.resize_button.isEnabled() and window.resize_button.text() == "Add files to start"


def test_invalid_size_blocks_start_and_explains_why(window, tmp_path):
    add(window, images(tmp_path / "s"))
    assert window.resize_button.isEnabled()
    window.width_input.setText("abc")
    assert not window.resize_button.isEnabled()
    assert window.width_input.property("invalid") is True
    assert "width and height" in window.summary_label.text()
    window.width_input.setText("800")
    assert window.resize_button.isEnabled() and window.width_input.property("invalid") is False


@pytest.mark.parametrize("value", ["0", "-5", "99999999", "\u00b2", "1.5", " "])
def test_bad_dimensions_are_rejected(window, value):
    window.height_input.setText(value)
    assert window._box() is None


def test_relative_destination_is_rejected(window, tmp_path):
    add(window, images(tmp_path / "s", 1))
    window.destination_input.setText("just/a/name")
    assert not window.resize_button.isEnabled() and "full folder path" in window.summary_label.text()


def test_destination_ignored_when_saving_beside_originals(window, tmp_path):
    add(window, images(tmp_path / "s", 1))
    window.destination_input.setText("")
    assert not window.resize_button.isEnabled()
    window.destination_choice.segment("beside").click()
    assert window.resize_button.isEnabled() and not window.folder_area.isVisibleTo(window.folder_area.parentWidget())


def test_presets_set_both_sizes_and_highlight(window):
    chip = window.preset_buttons[800]
    chip.click()
    assert window.width_input.text() == window.height_input.text() == "800"
    assert chip.isChecked() and not window.preset_buttons[1600].isChecked()
    chip.click()  # Clicking the active chip leaves it active.
    assert chip.isChecked()
    window.width_input.setText("801")
    assert not chip.isChecked()


def test_quality_only_shown_for_lossy_formats(window):
    parent = window.quality_area.parentWidget()
    assert window.quality_area.isVisibleTo(parent)
    window.format_choice.segment("PNG").click()
    assert not window.quality_area.isVisibleTo(parent)
    window.format_choice.segment("WEBP").click()
    assert window.quality_area.isVisibleTo(parent)


# --- Adding ---------------------------------------------------------------------------


def test_add_reports_counts_and_skips_duplicates(window, tmp_path):
    paths = images(tmp_path / "s")
    (tmp_path / "notes.txt").write_text("x")
    add(window, paths + [tmp_path / "notes.txt"])
    assert window.stack.currentIndex() == 1 and window.count_label.text() == "3 files"
    assert "Added 3 files" in window.message_label.text() and "1 unsupported" in window.message_label.text()
    add(window, paths[:2])
    assert window.file_list.count() == 3 and "2 already in the list" in window.message_label.text()


def test_add_folder_recurses(window, tmp_path):
    images(tmp_path / "s", 2)
    images(tmp_path / "s" / "deep", 2)
    add(window, [tmp_path / "s"])
    assert window.file_list.count() == 4


def test_thumbnail_fills_in_dimensions_and_shows_target_size(window, tmp_path):
    paths = images(tmp_path / "s", 1, size=(3000, 2000))
    add(window, paths)
    entry = window.file_list.ordered_entries()[0]
    wait(lambda: entry.dimensions == (3000, 2000))
    assert "3000 \u00d7 2000 \u2192 1600 \u00d7 1067" in window.delegate.describe(entry)
    window.preset_buttons[800].click()
    assert "\u2192 800 \u00d7 533" in window.delegate.describe(entry)
    window.preset_buttons[1920].click()
    window.width_input.setText("5000")
    window.height_input.setText("5000")
    assert "(kept)" in window.delegate.describe(entry)


_live_mime: list[QMimeData] = []  # Qt events do not own their mime data.


def drop_event(paths, event_class=QDropEvent):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    _live_mime.append(mime)
    if event_class is QDropEvent:
        return QDropEvent(QPointF(50, 50), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    return QDragEnterEvent(QPoint(50, 50), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


@pytest.mark.parametrize("target", ["window", "list"])
def test_file_drop_anywhere_shows_overlay_and_adds(window, tmp_path, target):
    add(window, images(tmp_path / "first", 1))
    paths = images(tmp_path / "s", 2)
    widget = window if target == "window" else window.file_list
    enter = drop_event(paths, QDragEnterEvent)
    widget.dragEnterEvent(enter)
    assert enter.isAccepted() and window.overlay.isVisible()
    widget.dropEvent(drop_event(paths))
    assert not window.overlay.isVisible()
    wait(lambda: not window.is_scanning)
    assert window.file_list.count() == 3


def test_drops_refused_during_a_run(window, tmp_path, monkeypatch):
    add(window, images(tmp_path / "s", 1))
    window.is_running = True
    enter = drop_event([tmp_path / "s"], QDragEnterEvent)
    window.dragEnterEvent(enter)
    assert not enter.isAccepted() and not window.overlay.isVisible()
    window.dropEvent(drop_event(images(tmp_path / "t", 1)))
    pump()
    window.is_running = False
    assert window.file_list.count() == 1


def test_scan_does_not_block_the_window(window, tmp_path, monkeypatch):
    gate = threading.Event()
    original = core.collect_inputs

    def slow(paths):
        gate.wait(5)
        return original(paths)

    monkeypatch.setattr("qr.window.collect_inputs", slow)
    window.add_paths(images(tmp_path / "s", 1))
    pump()  # We get here while the scan is still parked, so the event loop is alive.
    assert window.is_scanning and "Looking" in window.message_label.text()
    assert not window._can_accept_files()
    gate.set()
    wait(lambda: not window.is_scanning)
    assert window.file_list.count() == 1


# --- Editing the list -----------------------------------------------------------------


def test_remove_and_undo(window, tmp_path):
    add(window, images(tmp_path / "s"))
    window.file_list.setCurrentRow(1)
    window.remove_button.click()
    assert names(window) == ["p0.png", "p2.png"] and window.undo_button.isVisible()
    assert window.file_list.currentRow() == 1  # Delete, Delete, Delete keeps working.
    window.undo_button.click()
    assert names(window) == ["p0.png", "p1.png", "p2.png"] and not window.undo_button.isVisible()


def test_clear_all_needs_no_dialog_because_it_can_be_undone(window, tmp_path):
    add(window, images(tmp_path / "s", 10))
    window.clear_button.click()
    assert window.file_list.count() == 0 and window.stack.currentIndex() == 0
    assert window.entries == {} and window.resize_button.text() == "Add files to start"
    window.undo()
    assert window.file_list.count() == 10 and window.stack.currentIndex() == 1


def test_undo_expires_when_list_grows(window, tmp_path):
    add(window, images(tmp_path / "s", 2))
    window.clear_all()
    add(window, images(tmp_path / "t", 1))
    window.undo()
    assert window.file_list.count() == 1


def test_delete_key_removes_multiple(window, tmp_path):
    add(window, images(tmp_path / "s", 4))
    window.file_list.item(0).setSelected(True)
    window.file_list.item(2).setSelected(True)
    window.file_list.setFocus()
    QTest.keyClick(window.file_list, Qt.Key.Key_Delete)
    assert names(window) == ["p1.png", "p3.png"]
    assert "Removed 2 files" in window.message_label.text()


def test_move_buttons_and_alt_arrows(window, tmp_path):
    add(window, images(tmp_path / "s"))
    window.file_list.setCurrentRow(0)
    assert not window.up_button.isEnabled() and window.down_button.isEnabled()
    window.down_button.click()
    assert names(window) == ["p1.png", "p0.png", "p2.png"]
    assert [window.file_list.item(r).isSelected() for r in range(3)] == [False, True, False]
    QTest.keyClick(window.file_list, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert names(window) == ["p1.png", "p2.png", "p0.png"]
    assert not window.down_button.isEnabled()
    QTest.keyClick(window.file_list, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    assert names(window) == ["p1.png", "p0.png", "p2.png"]


def drag(win, start_row, end_row):
    viewport = win.file_list.viewport()
    start, end = row_center(win, start_row), row_center(win, end_row)
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in range(1, 7):
        point = start + (end - start) * (step / 6)
        QTest.mouseMove(viewport, point)
        # QTest.mouseMove does not carry the button state on every platform.
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtCore import QEvent

        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(viewport.mapToGlobal(point)), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        win.file_list.mouseMoveEvent(event)
        pump(5)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    pump()


def test_drag_reorders_down_and_up(window, tmp_path):
    add(window, images(tmp_path / "s", 5))
    drag(window, 0, 3)
    assert names(window) == ["p1.png", "p2.png", "p3.png", "p0.png", "p4.png"]
    drag(window, 4, 1)
    assert names(window) == ["p1.png", "p4.png", "p2.png", "p3.png", "p0.png"]
    # A plain click after dragging must still work normally.
    QTest.mouseClick(window.file_list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row_center(window, 2))
    assert window.file_list.selected_rows() == [2]


def test_drag_keeps_multi_selection_together(window, tmp_path):
    add(window, images(tmp_path / "s", 5))
    window.file_list.item(0).setSelected(True)
    window.file_list.item(1).setSelected(True)
    drag(window, 1, 3)
    assert names(window) == ["p2.png", "p3.png", "p0.png", "p1.png", "p4.png"]
    assert window.file_list.selected_rows() == [2, 3]


def test_plain_click_narrows_a_multi_selection(window, tmp_path):
    add(window, images(tmp_path / "s", 4))
    window.file_list.selectAll()
    QTest.mouseClick(window.file_list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row_center(window, 2))
    assert window.file_list.selected_rows() == [2]


def test_row_remove_button(window, tmp_path):
    add(window, images(tmp_path / "s"))
    index = window.file_list.model().index(1, 0)
    rect = window.file_list.visualRect(index).adjusted(0, 2, -2, -2)
    entry = window.file_list.entry_at(1)
    zone = window.delegate.zones(rect, entry)["remove"]
    QTest.mouseClick(window.file_list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, zone.center())
    assert names(window) == ["p0.png", "p2.png"]


def test_list_stays_fast_with_many_files(window, tmp_path):
    source = images(tmp_path / "s", 1)[0]
    started = time.perf_counter()
    window.file_list.setUpdatesEnabled(False)
    for index in range(5000):
        window._append_entry(source.with_name(f"f{index}.png"), 10)
    window.file_list.setUpdatesEnabled(True)
    window._refresh()
    pump()
    assert time.perf_counter() - started < 3
    started = time.perf_counter()
    window.file_list.selectAll()
    window.remove_selected()
    assert window.file_list.count() == 0 and time.perf_counter() - started < 1


# --- Running ------------------------------------------------------------------------------


def test_full_run_saves_and_reports(window, tmp_path):
    add(window, images(tmp_path / "s", 3, size=(1000, 500)))
    window.width_input.setText("200")
    window.height_input.setText("200")
    assert window.resize_button.text() == "Resize 3 images"
    run_to_end(window)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["p0.jpg", "p1.jpg", "p2.jpg"]
    assert Image.open(tmp_path / "out" / "p0.jpg").size == (200, 100)
    assert all(entry.status == "done" for entry in window.entries.values())
    assert window.result_title.text() == "Saved 3 images" and window.result_card.isVisible()
    assert window.open_button.isVisible() and window.result_clear_button.isVisible() and not window.retry_button.isVisible()
    assert not window.progress_bar.isVisible() and window.settings_area.isEnabled()
    assert window.resize_button.property("kind") == "primary"


def test_controls_lock_during_a_run_and_button_becomes_cancel(window, tmp_path, monkeypatch):
    gate = threading.Event()
    original = core.process_job
    monkeypatch.setattr(core, "process_job", lambda job, options: (gate.wait(10), original(job, options))[1])
    add(window, images(tmp_path / "s", 3))
    window.resize_button.click()
    assert window.resize_button.text() == "Cancel" and window.resize_button.isEnabled()
    assert not window.settings_area.isEnabled() and not window.top_add_files.isEnabled()
    assert window.progress_bar.isVisible()
    window.remove_selected()
    window.clear_all()
    assert window.file_list.count() == 3
    gate.set()
    wait(lambda: not window.is_running)


def test_cancel_stops_and_clears_waiting_rows(window, tmp_path, monkeypatch):
    gate = threading.Event()
    original = core.process_job
    monkeypatch.setattr(core, "process_job", lambda job, options: (gate.wait(10), original(job, options))[1])
    monkeypatch.setattr(core, "default_workers", lambda: 1)
    add(window, images(tmp_path / "s", 4))
    window.resize_button.click()
    wait(lambda: window._total_jobs == 4)
    window.resize_button.click()
    assert window.resize_button.text() == "Stopping\u2026" and not window.resize_button.isEnabled()
    gate.set()
    wait(lambda: not window.is_running)
    pump()
    assert window.result_title.text().startswith("Stopped after")
    assert window.result_card.property("tone") == "warn"
    assert all(entry.status in ("", "done") for entry in window.entries.values())
    assert window.resize_button.isEnabled() and window.resize_button.text() == "Resize 4 images"


def test_failure_is_explained_on_the_row_and_can_be_retried(window, tmp_path):
    paths = images(tmp_path / "s", 2)
    bad = tmp_path / "s" / "bad.jpg"
    bad.write_bytes(b"not an image")
    add(window, paths + [bad])
    run_to_end(window)
    entry = next(e for e in window.entries.values() if e.path == bad)
    assert entry.status == "failed" and entry.message == "Not a readable image. The file may be damaged."
    assert window.result_title.text() == "Saved 2 images, 1 failed"
    assert window.retry_button.isVisible() and not window.result_clear_button.isVisible()
    assert entry.message in window.file_list.item(2).toolTip()

    Image.new("RGB", (40, 40)).save(bad, format="JPEG")
    window.retry_button.click()
    assert window.is_running
    wait(lambda: not window.is_running)
    pump()
    assert entry.status == "done" and entry.message == ""
    assert window.result_title.text() == "Saved 1 image"
    # Only the failed file ran, so the others were not written a second time.
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["bad.jpg", "p0.jpg", "p1.jpg"]
    assert entry.message == "" and "\n" not in window.file_list.item(2).toolTip()


def test_unusable_destination_returns_to_ready(window, tmp_path):
    add(window, images(tmp_path / "s", 1))
    blocker = tmp_path / "file"
    blocker.write_text("x")
    window.destination_input.setText(str(blocker / "sub"))
    run_to_end(window)
    assert window.result_title.text() == "Nothing was saved"
    assert "Destination folder" in window.result_body.text()
    assert window.resize_button.isEnabled() and not window.open_button.isVisible()


def test_close_during_run_asks_then_waits_for_workers(window, tmp_path, monkeypatch):
    gate = threading.Event()
    original = core.process_job
    monkeypatch.setattr(core, "process_job", lambda job, options: (gate.wait(10), original(job, options))[1])
    add(window, images(tmp_path / "s", 2))
    window.resize_button.click()
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.No)
    window.close()
    assert window.isVisible() and window.is_running and not window._cancel.is_set()
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Yes)
    quit_calls = []
    monkeypatch.setattr(QApplication, "quit", lambda: quit_calls.append(True))
    window.close()
    assert not window.isVisible() and window._cancel.is_set() and window.is_running
    gate.set()
    wait(lambda: not window.is_running)
    pump()
    assert quit_calls == [True]
    assert not list((tmp_path / "out").glob("*.tmp")) if (tmp_path / "out").exists() else True


# --- PDF --------------------------------------------------------------------------------


@pytest.fixture
def pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "doc.pdf"
    document = pymupdf.open()
    for _ in range(6):
        document.new_page(width=300, height=400)
    document.save(path)
    document.close()
    yield path
    core.close_pdf_cache()


def click_page(picker, page, modifier=Qt.KeyboardModifier.NoModifier):
    point = picker.grid.visualItemRect(picker.grid.item(page)).center()
    QTest.mouseClick(picker.grid.viewport(), Qt.MouseButton.LeftButton, modifier, point)


@pytest.fixture
def picker(app, window, pdf):
    dialog = PdfPagePicker(pdf, 6, window.thumbnails, parent=window)
    dialog.show()
    pump()
    yield dialog
    dialog.reject()


def test_picker_starts_empty_and_cannot_be_accepted(picker):
    assert picker.selected_pages() == [] and not picker.accept_button.isEnabled()


def test_picker_click_toggles_and_shift_selects_a_run(picker):
    click_page(picker, 1)
    assert picker.selected_pages() == [1] and picker.accept_button.text() == "Use 1 page"
    click_page(picker, 1)
    assert picker.selected_pages() == []
    click_page(picker, 1)
    click_page(picker, 4, Qt.KeyboardModifier.ShiftModifier)
    assert picker.selected_pages() == [1, 2, 3, 4] and picker.accept_button.text() == "Use 4 pages"


def test_picker_range_all_and_clear(picker):
    picker.range_input.setText("1-2, 6")
    QTest.keyClick(picker.range_input, Qt.Key.Key_Return)
    assert picker.selected_pages() == [0, 1, 5] and picker.isVisible()  # Enter must not accept.
    picker.range_input.setText("99")
    picker.range_button.click()
    assert picker.range_input.property("invalid") is True and "1 to 6" in picker.range_error.text()
    assert picker.selected_pages() == [0, 1, 5]
    picker.range_input.setText("2")
    assert picker.range_error.text() == ""
    picker.all_button.click()
    assert len(picker.selected_pages()) == 6
    picker.none_button.click()
    assert picker.selected_pages() == []


def test_picker_repeated_close_is_safe(picker):
    picker.reject()
    picker.reject()


def test_pdf_flow_through_the_window(window, tmp_path, pdf, monkeypatch):
    seen = {}

    def choose(self):
        seen["initial"] = self.selected_pages()
        for page in self._choice:
            self.grid.item(page).setSelected(True)
        self.grid.clearSelection() if not self._choice else None
        return PdfPagePicker.DialogCode.Accepted

    monkeypatch.setattr(PdfPagePicker, "exec", choose)
    monkeypatch.setattr(PdfPagePicker, "_choice", [0, 2], raising=False)
    window.format_choice.segment("PNG").click()
    add(window, [pdf])
    entry = window.file_list.ordered_entries()[0]
    assert entry.pages == [0, 2] and entry.page_count == 6
    assert window.resize_button.text() == "Resize 2 images"

    # Editing starts from the current choice and survives a second run.
    monkeypatch.setattr(PdfPagePicker, "_choice", [3], raising=False)
    window.file_list.pages_requested.emit(entry.id)
    assert seen["initial"] == [0, 2] and entry.pages == [0, 2, 3]
    assert window.resize_button.text() == "Resize 3 images"
    run_to_end(window)
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["doc_page_001.png", "doc_page_003.png", "doc_page_004.png"]
    assert entry.status == "done"
    wait(lambda: not core._pdf_document)
    pdf.unlink()  # Nothing is left holding the file open.


def test_cancelled_pdf_is_skipped_with_a_note(window, pdf, monkeypatch):
    monkeypatch.setattr(PdfPagePicker, "exec", lambda self: PdfPagePicker.DialogCode.Rejected)
    add(window, [pdf])
    assert window.file_list.count() == 0 and "no pages selected" in window.message_label.text()


def test_unreadable_pdf_is_reported(window, tmp_path, monkeypatch):
    pytest.importorskip("pymupdf")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a pdf")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    add(window, [bad])
    assert warnings and window.file_list.count() == 0


# --- Persistence ------------------------------------------------------------------------


def test_settings_persist_across_sessions(app, tmp_path, settings_file):
    first = MainWindow(Settings(destination=str(tmp_path)))
    first.width_input.setText("777")
    first.format_choice.segment("WEBP").click()
    first.quality_slider.setValue(55)
    first.destination_choice.segment("beside").click()
    first.exists_choice.segment("replace").click()
    first.show()
    first.close()
    second = MainWindow(load_settings())
    assert second.width_input.text() == "777" and second.format_choice.value() == "WEBP"
    assert second.quality_slider.value() == 55
    assert second.destination_choice.value() == "beside" and second.exists_choice.value() == "replace"
    second.close()


def test_old_settings_file_opens_correctly(app, settings_file):
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text('{"destination": "C:/Users/x/Desktop", "width": "3000", "height": "900", "format": "PNG", "quality": 80, "collision": "beside", "theme": "dark"}')
    win = MainWindow(load_settings())
    assert (win.width_input.text(), win.height_input.text()) == ("3000", "900")
    assert win.format_choice.value() == "PNG" and win.destination_choice.value() == "beside"
    assert win.exists_choice.value() == "keep" and win.destination_input.text() == "C:/Users/x/Desktop"
    win.close()
    assert '"theme"' in settings_file.read_text()


def test_minimum_window_fits_all_primary_controls(window):
    window.resize(window.minimumSize())
    pump()
    assert window.height() <= 600 and window.resize_button.isVisible()
    assert window.resize_button.visibleRegion().boundingRect().height() >= 30
