# QuickResize v2026.08.02.5

QuickResize is a lightweight Windows desktop batch converter for photos, camera RAW files, PDFs, and Photoshop documents. It resizes each input to fit inside a maximum width and height while preserving the original aspect ratio, then saves the result in a chosen output format.

## Highlights

- Drag and drop files or folders into the queue.
- Queue management with remove, clear, move up/down, and drag-to-reorder controls.
- Light and dark themes, including themed fields, dropdowns, selections, and focus states.
- PDF page picker with thumbnails. Pages start unselected; click a thumbnail or checkbox to toggle, or use Select all/Clear selection.
- HEIC/HEIF decoding through `pillow-heif`.
- Canon CRW/CR3 RAW decoding through `rawpy` and LibRaw.
- PSD/PSB input as a flattened composite when supported by Pillow.
- PDF pages rendered as separate image files, with names like `document_page_001.png`.
- EXIF orientation correction.
- Per-file error handling so one bad file does not stop the batch.

## Supported inputs

JPG/JPEG, PNG, WEBP, TIFF, BMP, GIF, HEIC/HEIF, CRW, CR3, PDF, PSD, and PSB.

## Supported outputs

JPG, PNG, WEBP, TIFF, and BMP.

## Run from source

Install Python 3.10+ and run:

```powershell
py -m pip install -r requirements.txt
py quickresize.py
```

Native file drag-and-drop, HEIC input, RAW input, and PDF input require `tkinterdnd2`, `pillow-heif`, `rawpy`, and `pymupdf` respectively. Install all supported features with `requirements.txt`.

## Build a standalone EXE

```powershell
py -m pip install -r requirements.txt pyinstaller
pyinstaller --noconsole --onefile --clean --collect-all rawpy --collect-all pymupdf --name QuickResize quickresize.py
```

The finished executable will be in `dist\QuickResize.exe`.

## Release versioning

The project uses `YYYY.MM.DD.counter` versioning. The first three components identify the date and the final component is the daily release counter. The current release, `2026.08.02.5`, is the fifth release on August 2, 2026. See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

No license has been selected yet. Add a license before redistributing the project publicly.
