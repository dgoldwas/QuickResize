# QuickResize v2026.11.03.2

QuickResize is a lightweight Windows desktop batch converter for photos, camera RAW files, PDFs, and Photoshop documents. It resizes each input to fit inside a maximum width and height while preserving the original aspect ratio, then saves the result in a chosen output format.

## Download

Get either one from [Releases](https://github.com/dgoldwas/QuickResize/releases). They are the same app, with nothing to install, and both run from any folder or USB drive on 64-bit Windows 10 or later.

| | `QuickResize.exe` | `QuickResize-<version>-portable.zip` |
| --- | --- | --- |
| **Best for** | One file that is easy to carry | Faster starts |
| **To run** | Open it | Unzip it, then open `QuickResize.exe` inside the folder |
| **Starts in** | About 2.7 seconds | About 1.5 seconds |
| **Size on disk** | 63 MB | 163 MB |
| **While running** | Unpacks to a temporary folder, removed when it closes | Unpacks nothing |

Your settings are saved in `settings.json` beside the EXE, so they travel with it. To remove the app, delete the EXE and `settings.json`, or the whole folder.

Because the app is not code-signed, Windows may warn about an unrecognized app the first time. Choose More info, then Run anyway.

## Highlights

- Drop files or folders anywhere on the window, including subfolders. The window stays responsive while large folders are scanned.
- Every queued file shows a thumbnail and its size change before you start, such as `6000 × 4000 → 1600 × 1067`.
- Batches run in parallel across CPU cores, with progress, cancel, and the total space saved.
- Reorder by dragging, including several selected rows at once. Removing and clearing can be undone.
- Each failure is explained on its own row, and Retry failed reruns only what failed.
- Problems such as an invalid size appear next to the control before you start, rather than in a pop-up.
- Choose where files go and what happens to existing files as two separate, always-visible choices.
- Originals are never overwritten, and an interrupted save never damages an existing file.
- Color profiles are kept, so wide-gamut photos such as iPhone HEIC keep their color.
- Size, format, quality, destination, and window size are remembered between sessions.
- PDF page picker with thumbnails. Pages start unselected. Click to toggle, Shift+click for a run, or enter a range. Pages can be changed later from the list.
- HEIC/HEIF through `pillow-heif`, Canon CRW/CR3 through `rawpy` and LibRaw, and PSD/PSB as a flattened composite.
- PDF pages become separate images, with names like `document_page_001.png`.
- EXIF orientation is corrected. Other metadata is not copied to the output.
- Sharp at any display scale, and usable down to an 860 × 600 window.

## Keyboard

| Keys | Action |
| --- | --- |
| Ctrl+O / Ctrl+Shift+O | Add files / add folder |
| Delete | Remove selected |
| Ctrl+Z | Undo a removal |
| Alt+Up / Alt+Down | Move selected |
| Enter | Choose pages for the selected PDF |
| Ctrl+Enter | Start, or cancel a running batch |
| Esc | Cancel a running batch |

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

HEIC, RAW, and PDF input require `pillow-heif`, `rawpy`, and `pymupdf` respectively, and the app explains which is missing when one is needed. `requirements.txt` installs everything.

## Run the tests

```powershell
py -m pip install -r requirements-dev.txt
py -m pytest tests
```

## Build a standalone EXE

```powershell
./build.ps1
```

This runs the tests in a private `.venv`, then creates `dist\QuickResize.exe`, the `dist\QuickResize` folder, and its archive `dist\QuickResize-<version>-portable.zip`. The build recipe, including what is left out to keep them small, is in `QuickResize.spec`.

## Release versioning

The project uses `YYYY.MM.DD.counter` versioning. The first three components identify the date and the final component is the daily release counter. The current release, `2026.11.03.2`, is the second release on November 3, 2026. See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

Third-party components are listed in [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt). No license has been selected for QuickResize itself yet. Add a license before redistributing the project publicly.
