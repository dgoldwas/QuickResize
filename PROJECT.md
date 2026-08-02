# QuickResize Project Notes

## Purpose

QuickResize provides a focused Windows workflow for reducing or converting many visual files at once. The central rule is that an image is resized to fit within the requested maximum width and height; it is never stretched or cropped.

## Architecture

- `quickresize.py` contains the Tkinter application, queue model, file readers, PDF page picker, resize worker, theme styling, and output writer.
- Pillow handles standard raster images and Photoshop composites.
- `pillow-heif` registers HEIC/HEIF decoding with Pillow.
- `rawpy`/LibRaw demosaic Canon CRW and CR3 files into RGB images.
- PyMuPDF renders selected PDF pages into RGB images for normal resizing and conversion.
- `tkinterdnd2` supplies native Windows drag-and-drop support.
- A background worker performs conversions while the UI remains responsive.

## Processing flow

1. Files or folders enter the queue through the drop zone or file picker.
2. PDFs open a page-selection dialog. The dialog renders lightweight thumbnails, starts with every page unselected, and allows thumbnail/checkbox toggling, Select all, and Clear selection.
3. Queue order is controlled by the user with the action buttons or drag-to-reorder.
4. Each selected input is decoded into a Pillow image. RAW and PDF inputs are converted to RGB first; Photoshop inputs use the flattened composite exposed by Pillow.
5. EXIF orientation is applied, then `thumbnail()` scales the image inside the maximum dimensions using Lanczos resampling.
6. Output mode is normalized where necessary, such as compositing transparency onto white for JPG.
7. The result is written using the chosen output format. PDF pages receive a `_page_###` suffix.

## Version policy

QuickResize uses the requested `0.26.8.3` style: `26.8.3` records August 2, 2026, while the leading `0` keeps the project in pre-1.0 status. The final component is the patch sequence for that date. Keep the exact version in `VERSION`, `APP_VERSION`, the changelog, release tag, and executable documentation synchronized.

## Build and verify

```powershell
py -m pip install -r requirements.txt pyinstaller
py -m py_compile quickresize.py
./build.ps1
```

The build creates `dist\QuickResize.exe`. A practical smoke test should cover a raster image, a transparent PNG to JPG conversion, a multi-page PDF with partial selection, a HEIC file, and a RAW file when samples are available.

## Release checklist

- Update `VERSION`, `APP_VERSION`, `CHANGELOG.md`, and this documentation.
- Run syntax checks and conversion smoke tests.
- Build the standalone executable.
- Inspect `git status` and stage only intended project files.
- Commit with the release version in the message.
- Push the release branch and create the GitHub release tag `v0.26.8.3`.
- Attach `dist\QuickResize.exe` to the GitHub release.
