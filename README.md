# QuickResize v2026.11.09.3

QuickResize is a lightweight Windows desktop batch converter for photos, camera RAW files, PDFs, and Photoshop documents. It resizes each input to fit inside a maximum width and height while preserving the original aspect ratio, then saves the result in a chosen output format.

## Download

Get one from [Releases](https://github.com/dgoldwas/QuickResize/releases). All three are the same app, for 64-bit Windows 10 or later.

| | `QuickResize-<version>-Setup.exe` | `QuickResize.exe` | `QuickResize-<version>-portable.zip` |
| --- | --- | --- | --- |
| **Best for** | Everyday use on your own PC | One file that is easy to carry | Faster starts, no install |
| **To run** | Run setup, then open QuickResize from the Start menu | Open it | Unzip it, then open `QuickResize.exe` inside the folder |
| **Installs to** | `C:\Program Files\WarmButter\QuickResize` | Nowhere | Nowhere |
| **Updates** | Installs new versions itself | Download the new version | Download the new version |
| **Settings** | `%APPDATA%\QuickResize\settings.json` | `settings.json` beside the EXE | `settings.json` beside the EXE |
| **Starts in** | About 1.5 seconds | About 2.7 seconds | About 1.5 seconds |

To remove the installed copy, uninstall it from Settings > Apps. To remove a portable copy, delete the EXE and `settings.json`, or the whole folder.

### Updates

The **Check for updates** button beside the version number asks GitHub for the latest release. Packaged copies also check quietly at startup and every six hours, and the button changes to **Update to …** when one is out. An installed copy then downloads the new Setup.exe, checks it against GitHub's SHA-256, closes, installs after a Windows permission prompt, and opens again. A portable copy opens the release page.

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

## Build

```powershell
./build.ps1             # dist\QuickResize.exe and the portable folder and zip
./build-installer.ps1   # all of the above, plus dist\QuickResize-<version>-Setup.exe
```

`build.ps1` runs the tests in a private `.venv`, then creates `dist\QuickResize.exe`, the `dist\QuickResize` folder, and its archive `dist\QuickResize-<version>-portable.zip`. The build recipe, including what is left out to keep them small, is in `QuickResize.spec`.

`build-installer.ps1` also packs the folder into an installer with [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup --scope user`), from `installer\QuickResize.iss`. Add `-Install` to install it on this PC, or `-Release` to publish GitHub release `v<version>` with all three downloads. Installed copies only offer releases that include a `-Setup.exe`.

## Release versioning

The project uses `YYYY.MM.DD.counter` versioning. The first three components identify the date and the final component is the daily release counter. The current release, `2026.11.09.3`, is the third release on November 9, 2026. See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

Third-party components are listed in [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt). No license has been selected for QuickResize itself yet. Add a license before redistributing the project publicly.
