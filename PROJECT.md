# QuickResize Project Notes

## Purpose

QuickResize provides a focused Windows workflow for reducing or converting many visual files at once. The central rule is that an image is resized to fit within the requested maximum width and height; it is never stretched or cropped.

## Architecture

- `quickresize.py` is the entry point. It creates the application and shows the window.
- `qr/core.py` is the image pipeline: finding inputs, naming outputs, decoding, resizing, and saving. It has no UI dependency.
- `qr/settings.py` reads and writes the settings: `settings.json` beside the EXE when packaged, or `%APPDATA%\QuickResize\settings.json` from source.
- `qr/window.py` is the main window, and owns the queue and batch state.
- `qr/widgets.py` holds the reusable controls and the virtualized file list. `qr/pdf_picker.py` is the page picker.
- `qr/thumbnails.py` loads previews on background threads, newest request first, with a bounded cache.
- `qr/theme.py` holds the colors, stylesheet, and icons.
- PySide6 (Qt) provides the interface. Only `PySide6-Essentials` is needed.
- Pillow handles standard raster images and Photoshop composites.
- `pillow-heif`, `rawpy`/LibRaw, and PyMuPDF are imported on first use, because they cost more startup time than everything else combined.

## Processing flow

1. Files or folders enter the queue by dropping them anywhere, or with Add files or Add folder. A background thread scans folders recursively.
2. PDFs open the page picker immediately. Pages start unselected, and thumbnails load as they scroll into view.
3. Queue order is controlled by dragging rows, or with the move buttons or Alt+Up and Alt+Down.
4. All output names are assigned in queue order before any decoding starts, so results are deterministic while files finish out of order. An output never takes the name of another output or any source in the batch, even when replacing existing files is allowed.
5. Worker threads process the batch in parallel. Pillow releases the GIL while decoding, resizing, and encoding. All PyMuPDF calls share a lock because it is not thread-safe.
6. Each input is decoded and shrunk in one step. JPEGs decode at reduced scale, and RAW files use half-size demosaicing when that still reaches the target. PDF pages render directly at the target size.
7. Palette and 1-bit images are converted first, because Pillow can only resize those modes with nearest-neighbor sampling. EXIF orientation is applied. Images already small enough stay at their original size.
8. The image is converted for the output format: 16-bit grayscale is scaled to 8 bits where needed, CMYK is converted to RGB, and transparency is composited onto white for JPG and BMP. The ICC profile is kept when it still describes the output.
9. The result is written to a temporary file and moved into place, so a failed write cannot damage an existing file. PDF pages receive a `_page_###` suffix. JPG and WEBP use the selected quality.

## Version policy

QuickResize uses `YYYY.MM.DD.counter` versioning. For example, `2026.11.03.2` means the second release published on November 3, 2026. The final component resets to `1` at the start of each day and increments for each release that day. Keep the exact version in `VERSION`, `APP_VERSION` in `qr/__init__.py`, the changelog, release tag, and executable documentation synchronized.

## Build and verify

```powershell
py -m pip install -r requirements-dev.txt
py -m pytest tests
./build.ps1
```

The build creates `dist\QuickResize.exe`, the `dist\QuickResize` folder, and `dist\QuickResize-<version>-portable.zip`. Both forms must keep running with nothing installed, and write only `settings.json` beside the EXE and the chosen output folder. The single file also uses a temporary folder that it removes on exit. The tests run without showing a window. They do not cover a real RAW file or a native drag from File Explorer, so a practical smoke test should also cover a RAW file when a sample is available, a drag from Explorer, and a window on a scaled display.

## Release checklist

- Update `VERSION`, `APP_VERSION` in `qr/__init__.py`, `CHANGELOG.md`, and this documentation.
- Run the tests and the smoke test above.
- Build both release forms.
- Inspect `git status` and stage only intended project files.
- Commit with the release version in the message.
- Push the release branch and create the GitHub release tag `v2026.11.03.2`.
- Attach `dist\QuickResize.exe`, `dist\QuickResize-<version>-portable.zip`, and `THIRD-PARTY-NOTICES.txt` to the GitHub release.
