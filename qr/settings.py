"""Reading and writing the remembered preferences.

A portable copy keeps its settings beside the EXE, so they travel with it. An
installed copy (Program Files is not writable) and a run from source use
%APPDATA%/QuickResize instead. If a portable copy's folder is read-only, settings
last for the session only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import theme
from .core import FORMAT_INFO, MAX_DIMENSION
from .updates import app_folder, is_installed


def portable_folder() -> Path | None:
    """Return the folder holding a portable EXE, or None when installed or running from source."""
    return None if is_installed() else app_folder()


def settings_path() -> Path:
    folder = portable_folder()
    if folder is not None:
        return folder / "settings.json"
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return appdata / "QuickResize" / "settings.json"


def default_destination() -> str:
    return str(Path.home() / "Pictures" / "QuickResize")


@dataclass(frozen=True)
class SizePreset:
    """A saved Fit inside box. An empty name shows the dimensions instead."""

    name: str
    width: int
    height: int

    def label(self) -> str:
        return self.name or f"{self.width} \u00d7 {self.height}"


DEFAULT_PRESETS = (
    SizePreset("Large", 3000, 3000),
    SizePreset("Screen", 1920, 1920),
    SizePreset("Medium", 1080, 1080),
    SizePreset("Small", 900, 900),
)
MAX_PRESETS = 50
PRESET_NAME_LENGTH = 40


@dataclass
class Settings:
    width: str = "1600"
    height: str = "1600"
    fmt: str = "JPG"
    quality: int = 92
    destination: str = ""
    save_beside: bool = False
    replace: bool = False
    geometry: str = ""
    theme_mode: str = theme.DEFAULT_MODE
    accent: str = theme.DEFAULT_ACCENT
    presets: list[SizePreset] = field(default_factory=lambda: list(DEFAULT_PRESETS))


def _store_destination(destination: str) -> str | None:
    """Return the form of a destination to write, or None to leave it unset.

    The default folder is left unset so it follows the user on another PC. A folder
    on the app's own drive is stored without its letter, because a USB drive's
    letter can change between PCs.
    """
    folder = portable_folder()
    if folder is None:
        return destination
    if os.path.normcase(os.path.normpath(destination)) == os.path.normcase(os.path.normpath(default_destination())):
        return None
    drive, rest = os.path.splitdrive(destination)
    if drive and rest.startswith(("\\", "/")) and os.path.normcase(drive) == os.path.normcase(os.path.splitdrive(str(folder))[0]):
        return rest
    return destination


def _restore_destination(stored: str) -> str:
    """Undo _store_destination, and let go of a folder that does not exist on this PC."""
    folder = portable_folder()
    if folder is None:
        return stored
    drive, rest = os.path.splitdrive(stored)
    path = os.path.normpath(f"{os.path.splitdrive(str(folder))[0]}{rest}" if not drive and rest.startswith(("\\", "/")) else stored)
    # A new folder can be one level down, since the batch creates it.
    if os.path.isdir(path) or os.path.isdir(os.path.dirname(path)):
        return path
    return default_destination()


def _dimension(value: object, default: str) -> str:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        value = str(int(value))
    if isinstance(value, str):
        text = value.strip()
        if text.isdecimal() and 1 <= int(text) <= MAX_DIMENSION:
            return str(int(text))
    return default


def _quality(value: object) -> int:
    if isinstance(value, bool):
        return 92
    try:
        return max(1, min(100, int(value)))  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 92


def _presets(value: object) -> list[SizePreset]:
    """Read saved presets, skipping damaged entries. A missing list means the defaults."""
    if not isinstance(value, list):
        return list(DEFAULT_PRESETS)
    result = []
    for item in value[:MAX_PRESETS]:
        if not isinstance(item, dict):
            continue
        width, height = _dimension(item.get("width"), ""), _dimension(item.get("height"), "")
        name = item.get("name")
        if width and height:
            result.append(SizePreset(name.strip()[:PRESET_NAME_LENGTH] if isinstance(name, str) else "", int(width), int(height)))
    return result


def _read_raw(path: Path) -> dict[str, object]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse(raw: dict[str, object], base: Settings) -> Settings:
    """Build settings from saved values. A missing or damaged value keeps the base value."""
    fmt = raw.get("format")
    destination = raw.get("destination")
    geometry = raw.get("geometry")
    # Earlier versions stored "next to each source" as a value of the collision rule.
    collision = raw.get("collision")
    mode = raw.get("theme")
    accent = raw.get("accent")
    has_place = "save_beside" in raw or collision in ("beside", "overwrite", "unique")
    return Settings(
        width=_dimension(raw.get("width"), base.width),
        height=_dimension(raw.get("height"), base.height),
        fmt=fmt if isinstance(fmt, str) and fmt in FORMAT_INFO else base.fmt,
        quality=_quality(raw["quality"]) if "quality" in raw else base.quality,
        destination=_restore_destination(destination.strip()) if isinstance(destination, str) and destination.strip() else base.destination,
        save_beside=(raw.get("save_beside") is True or collision == "beside") if has_place else base.save_beside,
        replace=collision == "overwrite" if collision in ("beside", "overwrite", "unique") else base.replace,
        geometry=geometry if isinstance(geometry, str) else base.geometry,
        theme_mode=theme.mode_name(mode) if isinstance(mode, str) and theme.mode_name(mode).casefold() == mode.casefold() else base.theme_mode,
        accent=theme.accent_name(accent) if isinstance(accent, str) and theme.accent_name(accent).casefold() == accent.casefold() else base.accent,
        presets=_presets(raw["presets"]) if "presets" in raw else list(base.presets),
    )


def load_settings(path: Path | None = None) -> Settings:
    raw = _read_raw(path or settings_path())
    if "theme" not in raw and raw.get("dark_mode") is False:
        raw["theme"] = "Light"
    return _parse(raw, Settings(destination=default_destination()))


def _preset_list(presets: list[SizePreset]) -> list[dict[str, object]]:
    return [{"name": preset.name, "width": preset.width, "height": preset.height} for preset in presets]


def _write_json(target: Path, payload: dict[str, object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # Not tempfile.mkstemp: on Windows it retries a denied folder almost endlessly,
    # which froze the app when it ran from a read-only location.
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Merge into the existing file, replacing it atomically. Failure is not fatal."""
    target = path or settings_path()
    payload = _read_raw(target)
    payload.update(
        format=settings.fmt,
        quality=settings.quality,
        collision="overwrite" if settings.replace else "unique",
        save_beside=settings.save_beside,
        geometry=settings.geometry,
        theme=settings.theme_mode,
        accent=settings.accent,
        presets=_preset_list(settings.presets),
    )
    # An unfinished entry in a field should not erase the last good value.
    for key, value in (("width", settings.width), ("height", settings.height)):
        if _dimension(value, "") != "":
            payload[key] = value
    if settings.destination.strip():
        stored = _store_destination(settings.destination.strip())
        if stored is None:
            payload.pop("destination", None)
        else:
            payload["destination"] = stored
    try:
        _write_json(target, payload)
    except OSError:
        pass


# ---------------------------------------------------------------- export and import

EXPORT_KIND = "QuickResize settings"


def export_settings(settings: Settings, path: Path) -> None:
    """Write the preferences to share or keep. Window size stays behind. Raises OSError."""
    values: dict[str, object] = {
        "format": settings.fmt,
        "quality": settings.quality,
        "collision": "overwrite" if settings.replace else "unique",
        "save_beside": settings.save_beside,
        "theme": settings.theme_mode,
        "accent": settings.accent,
        "presets": _preset_list(settings.presets),
    }
    for key, value in (("width", settings.width), ("height", settings.height)):
        if _dimension(value, "") != "":
            values[key] = value
    if settings.destination.strip():
        values["destination"] = settings.destination.strip()
    _write_json(path, {"kind": EXPORT_KIND, "version": 1, "settings": values})


@dataclass
class ImportResult:
    settings: Settings
    added_sizes: int = 0
    existing_sizes: int = 0
    missing_destination: str = ""  # An imported save folder that does not exist on this PC.


_KNOWN_KEYS = {"format", "quality", "collision", "save_beside", "theme", "accent", "presets", "width", "height", "destination"}


def import_settings(path: Path, current: Settings) -> ImportResult:
    """Apply an exported file over the current preferences.

    Saved sizes are merged: a size whose width and height are already saved is
    skipped, so importing twice adds nothing. Raises ValueError for a file that is
    not QuickResize settings, and OSError when it cannot be read.
    """
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except ValueError as exc:
        raise ValueError("This file is not QuickResize settings.") from exc
    # A copied settings.json works as well as an exported file.
    raw = data.get("settings") if isinstance(data, dict) and data.get("kind") == EXPORT_KIND else data
    if not isinstance(raw, dict) or not _KNOWN_KEYS & raw.keys():
        raise ValueError("This file is not QuickResize settings.")
    raw = {key: value for key, value in raw.items() if key in _KNOWN_KEYS}
    imported = _presets(raw.pop("presets")) if isinstance(raw.get("presets"), list) else []
    destination = raw.pop("destination", None)
    merged = _parse(raw, current)
    presets = list(current.presets)
    saved = {(preset.width, preset.height) for preset in presets}
    result = ImportResult(merged)
    # A folder from another PC is used only when it exists here.
    if isinstance(destination, str) and destination.strip():
        folder = os.path.normpath(os.path.expanduser(destination.strip()))
        if os.path.isabs(folder) and os.path.isdir(folder):
            merged.destination = folder
        else:
            result.missing_destination = destination.strip()
    for preset in imported:
        if (preset.width, preset.height) in saved:
            result.existing_sizes += 1
        elif len(presets) < MAX_PRESETS:
            presets.append(preset)
            saved.add((preset.width, preset.height))
            result.added_sizes += 1
    merged.presets = presets
    merged.geometry = current.geometry
    return result
