"""Reading and writing the remembered preferences.

A portable copy keeps its settings beside the EXE, so they travel with it. An
installed copy (Program Files is not writable) and a run from source use
%APPDATA%/QuickResize instead. If a portable copy's folder is read-only, settings
last for the session only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

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


def _read_raw(path: Path) -> dict[str, object]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_settings(path: Path | None = None) -> Settings:
    raw = _read_raw(path or settings_path())
    fmt = raw.get("format")
    destination = raw.get("destination")
    geometry = raw.get("geometry")
    # Earlier versions stored "next to each source" as a value of the collision rule.
    collision = raw.get("collision")
    return Settings(
        width=_dimension(raw.get("width"), "1600"),
        height=_dimension(raw.get("height"), "1600"),
        fmt=fmt if isinstance(fmt, str) and fmt in FORMAT_INFO else "JPG",
        quality=_quality(raw.get("quality", 92)),
        destination=_restore_destination(destination.strip()) if isinstance(destination, str) and destination.strip() else default_destination(),
        save_beside=raw.get("save_beside") is True or collision == "beside",
        replace=collision == "overwrite",
        geometry=geometry if isinstance(geometry, str) else "",
    )


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
    except OSError:
        pass
