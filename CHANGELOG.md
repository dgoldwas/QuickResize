# Changelog

## 2026.11.09.3 — 2026-11-09

### Fixed

- Check for updates now installs the update. The app quit after downloading, but the helper that runs Setup exited immediately and nothing was installed. Anyone on an earlier release needs to run this release's Setup.exe once by hand; updates work from then on.

## 2026.11.09.2 — 2026-11-09

### Installer

- Setup now installs into `C:\Program Files\WarmButter\QuickResize`, like the other WarmButter apps. Updating from an earlier release moves the install and removes the old `Program Files\QuickResize` folder. Settings in `%APPDATA%\QuickResize` are kept.

## 2026.11.09.1 — 2026-11-09

### Installer

- New `QuickResize-<version>-Setup.exe` installs QuickResize into `C:\Program Files\QuickResize`, with a Start menu entry, an optional desktop shortcut, and an uninstaller. It asks for administrator permission.
- An installed copy keeps its settings in `%APPDATA%\QuickResize`, because Program Files is not writable. Uninstalling keeps them.
- The single EXE and the portable zip are unchanged, and still keep settings beside the EXE.

### Check for updates

- A **Check for updates** button sits beside the version number. Packaged copies also check GitHub quietly at startup and every six hours, and the button changes to **Update to …** when a newer release is out.
- An installed copy downloads the new Setup.exe, verifies it against GitHub's SHA-256, closes, installs through a Windows permission prompt, and opens again. The next launch says whether the update installed.
- A portable copy opens the release page instead, since it cannot replace itself.
- Updating waits for a running batch to finish or be canceled.
- `build-installer.ps1` builds the Setup.exe along with the other two downloads. `-Install` installs it on this PC, and `-Release` publishes all three to GitHub.

## 2026.11.03.2 — 2026-11-03

- Added a portable folder download alongside the single EXE. It starts faster, and never unpacks to the temporary folder.
- Both downloads run the same app with nothing installed, and keep settings in `settings.json` beside the EXE.
- `build.ps1` now builds both.

## 2026.11.03.1 — 2026-11-03

### Portable

- QuickResize is one portable EXE. Run it from any folder or USB drive with nothing installed, and delete it to remove it.
- Settings live in `settings.json` beside the EXE and travel with it. The packaged app no longer uses `%APPDATA%`, so settings start fresh once.
- A saved folder on the app's own drive survives a change of drive letter, and one that does not exist on the current PC falls back to the default.

### Redesign

- Rebuilt the interface on Qt, with sharp rendering at every display scale and a dark title bar. The minimum window size drops from 960 x 860 to 860 x 600, so it now fits 768p screens.
- New first-run screen, and a full-window overlay confirming that a drop lands anywhere.
- Queue rows show a thumbnail, the size change before you start, and a status. Rows have their own remove and edit-pages buttons on hover.
- Output settings are always visible, with no dropdowns. Where files go and what happens to existing files are now two separate choices.
- Invalid settings are explained next to the controls, in place of error dialogs.
- Results appear in a card with the space saved, Open folder, and Retry failed. Each failure is explained on its row.
- Clearing and removing can be undone, in place of a confirmation dialog.
- Multi-select, dragging several rows at once, keyboard shortcuts, and PDF page editing from the list.
- The PDF picker adds Shift+click runs, and shows its thumbnails only as they scroll into view.

### Faster

- Batches run in parallel: a 32-photo test batch went from 14.1 s to 2.9 s on a 16-thread CPU.
- JPEGs decode at reduced scale, and RAW files use half-size demosaicing when that still reaches the target.
- Scanning and thumbnails no longer run on the UI thread, and the list handles thousands of files.
- HEIC, RAW, and PDF decoders load on first use. JPG output is optimized, about 3% smaller at the same quality. TIFF output is compressed.

### Fixed

- Same-named files from different folders overwrote each other when replacing existing files was on.
- A batch could overwrite one of its own source files, such as `x.png` saved as `x.jpg` over a queued `x.jpg`.
- A failed save could destroy the existing file it was replacing. Saves are now atomic.
- JPG and WEBP output dropped the color profile, so wide-gamut photos looked washed out.
- GIF and palette PNG images were resized with jagged nearest-neighbor sampling.
- CMYK images could not be saved as PNG.
- 16-bit grayscale images came out blank white when converted to JPG.
- Transparent images saved as BMP showed the hidden color under transparent pixels instead of white.
- A short, wide size box rendered PDF pages far larger than needed, which could exhaust memory. PDF renders now have a size limit.
- A drop during the PDF picker could open a second picker.
- Closing the window during a batch could leave a partial file. It now asks, and finishes the files in progress.
- A superscript digit in the settings file crashed the app at launch, and settings are now saved atomically.

## 2026.10.20.1 — 2026-10-20

- Show the current file and a progress bar while a batch runs, and let the user cancel after the current photo finishes.
- Lock the queue during a run, then mark each file pending, working, done, failed, or partial.
- Accept drops anywhere on the window, add an Add folder action, and include subfolders.
- Report added, skipped, and duplicate files, and warn when a HEIC, RAW, or PDF decoder is missing.
- Show each queued file's name, type, folder, and status, with a scrollbar.
- Open the PDF picker immediately, load thumbnails in the background, scroll them with the mouse wheel, highlight selected pages, and accept a page range such as `1-5, 8`.
- Remember width, height, format, JPG/WEBP quality, and the filename rule along with the destination folder.
- Add 1920, 1600, 1080, and 800 size presets, and state that smaller images stay at their original size.
- Let the user keep unique names, overwrite an existing file, or save next to each original.
- Show the finished batch in the window, with Open folder and a scrollable list of every error.
- Ask before clearing a queue of 8 or more files.
- Keep the window sharp on scaled displays.

## 2026.09.23.1 — 2026-09-23

- Made the dark interface permanent and removed the theme switch.
- Reorganized the main window into clear queue, resize settings, and destination sections.
- Remembered the destination folder between launches, including paths typed into the field.
- Added a custom application icon to the Windows build.

## 2026.08.02.7 — 2026-08-02

- Persisted the light/dark theme preference in the user’s Windows AppData settings.

## 2026.08.02.6 — 2026-08-02

- Fixed the queue card so Move up, Move down, Remove, and Clear queue remain visible while the file list expands.

## 2026.08.02.5 — 2026-08-02

- Fixed the main layout so the Resize photos action bar is reserved before the queue expands.

## 2026.08.02.4 — 2026-08-02

- Switched versioning to `YYYY.MM.DD.counter` format.
- The final number is the release counter for that calendar day.

## 0.26.8.5 — 2026-08-02

- Refreshed the UI with flatter modern controls, clearer hierarchy, a version badge, softer spacing, and updated light/dark color systems.

## 0.26.8.4 — 2026-08-02

- Fixed PDF picker layout so all three thumbnail columns remain visible.
- Moved PDF action buttons into a fixed bottom bar.
- Increased the main window default and minimum size so queue controls remain visible.

## 0.26.8.3 — 2026-08-02

- Fixed PDF rendering so selected pages can reach the requested maximum dimensions instead of being limited by a fixed 2x render scale.

## 0.26.8.2 — 2026-08-02

- PDF page selection opens with no pages selected.
- Added Select all and Clear selection controls.
- PDF thumbnails toggle selection when clicked.
- Added queue Clear, Remove, Move up, and Move down controls.
- Added drag-to-reorder support for queued files.
- Added consistent dark-theme styling for fields, dropdowns, and selections.
- Added HEIC, CRW, CR3, PDF, PSD, and PSB input support.

## Versioning

QuickResize uses `YYYY.MM.DD.counter` versioning. The first three components identify the release date and the final component is the daily release counter. `2026.11.03.2` is the second release on November 3, 2026.
