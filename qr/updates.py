"""Finding newer QuickResize releases on GitHub and installing them.

An installed copy (in Program Files, with Inno Setup's uninstaller beside it) downloads
the release's Setup.exe, checks it against GitHub's SHA-256, and hands it to a hidden
helper that waits for QuickResize to exit, runs setup through UAC, and opens the app
again. Portable copies are pointed at the release page instead, because installing
would leave the portable copy behind unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME, APP_VERSION

REPOSITORY = "dgoldwas/QuickResize"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases/latest"
LATEST_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
SETUP_SUFFIX = "-setup.exe"


@dataclass(frozen=True)
class AvailableUpdate:
    version: str
    title: str
    release_url: str
    asset_name: str
    download_url: str
    size: int
    sha256: str | None


class UpdateError(Exception):
    """A check or download that failed in a way worth telling the user about."""


def version_tuple(text: str) -> tuple[int, ...] | None:
    parts = text.strip().lstrip("vV").split(".")
    if not parts or not all(part.isdecimal() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def is_newer(candidate: str, current: str) -> bool:
    """Compare YYYY.MM.DD.N versions numerically, so 2026.11.09.10 beats 2026.11.09.9."""
    new = version_tuple(candidate)
    if new is None:
        return False
    old = version_tuple(current)
    return old is None or new > old


def parse_latest_release(text: str, current: str) -> AvailableUpdate | None:
    """Return the release when it is newer than `current`. A newer release with no Setup.exe is an error."""
    try:
        root = json.loads(text)
    except ValueError as error:
        raise UpdateError("GitHub sent a response that could not be read.") from error
    if not isinstance(root, dict) or root.get("draft") or root.get("prerelease"):
        return None
    tag = str(root.get("tag_name") or "")
    version = tag.lstrip("vV")
    if not is_newer(version, current):
        return None
    for asset in root.get("assets") or []:
        name = str(asset.get("name") or "")
        if not name.lower().endswith(SETUP_SUFFIX):
            continue
        digest = str(asset.get("digest") or "")
        sha = digest[len("sha256:"):].lower() if digest.lower().startswith("sha256:") else None
        return AvailableUpdate(
            version=version,
            title=str(root.get("name") or tag),
            release_url=str(root.get("html_url") or RELEASES_URL),
            asset_name=name,
            download_url=str(asset.get("browser_download_url") or ""),
            size=int(asset.get("size") or 0),
            sha256=sha,
        )
    raise UpdateError(f"Release {version} has no installer.")


# ---------------------------------------------------------------- where this copy lives


def app_folder() -> Path | None:
    """The folder holding the packaged EXE, or None when running from source."""
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None


def is_installed() -> bool:
    """True for a copy installed by Setup, which leaves its uninstaller beside the EXE."""
    folder = app_folder()
    return folder is not None and (folder / "unins000.exe").is_file()


def installed_exe() -> Path:
    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
    return Path(program_files) / "WarmButter" / APP_NAME / f"{APP_NAME}.exe"


def work_folder() -> Path:
    return Path(tempfile.gettempdir()) / f"{APP_NAME}-Update"


def result_path() -> Path:
    return work_folder() / "last-result.txt"


# ---------------------------------------------------------------- network


def _request(url: str, accept: str) -> urllib.request.Request:
    headers = {"User-Agent": f"{APP_NAME}-Updater/{APP_VERSION}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("QUICKRESIZE_GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token.strip()}"
    return urllib.request.Request(url, headers=headers)


def _context() -> ssl.SSLContext:
    # Loads the Windows certificate store, so no certificate bundle has to ship.
    return ssl.create_default_context()


def _describe(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 403:
            return "GitHub is limiting requests. Try again in an hour."
        return f"GitHub answered {error.code} {error.reason}."
    if isinstance(error, urllib.error.URLError):
        return "No connection to GitHub."
    if isinstance(error, TimeoutError):
        return "GitHub did not answer in time."
    return str(error) or type(error).__name__


def check(current: str = APP_VERSION, timeout: float = 15) -> AvailableUpdate | None:
    """Ask GitHub for the latest release. Returns None when there is nothing newer."""
    try:
        with urllib.request.urlopen(_request(LATEST_API, "application/vnd.github+json"), timeout=timeout, context=_context()) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code == 404:  # No releases yet.
            return None
        raise UpdateError(_describe(error)) from error
    except (OSError, ValueError) as error:
        raise UpdateError(_describe(error)) from error
    return parse_latest_release(text, current)


def download(update: AvailableUpdate, progress: Callable[[float], None] | None = None, cancel: threading.Event | None = None) -> Path:
    """Download the installer, verify it against GitHub's SHA-256, and return its path."""
    folder = work_folder()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / Path(update.asset_name).name
    partial = target.with_name(target.name + ".partial")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(_request(update.download_url, "application/octet-stream"), timeout=60, context=_context()) as response:
            length = int(response.headers.get("Content-Length") or update.size or 0)
            done = 0
            with partial.open("wb") as stream:
                while chunk := response.read(256 * 1024):
                    if cancel is not None and cancel.is_set():
                        raise UpdateError("The download was canceled.")
                    stream.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress and length:
                        progress(min(1.0, done / length))
        actual = digest.hexdigest()
        if update.sha256 and actual != update.sha256:
            raise UpdateError("The downloaded installer is damaged. Try again.")
        os.replace(partial, target)
    except UpdateError:
        partial.unlink(missing_ok=True)
        raise
    except (OSError, ValueError) as error:
        partial.unlink(missing_ok=True)
        raise UpdateError(_describe(error)) from error
    return target


# ---------------------------------------------------------------- installing

HELPER_SCRIPT = r"""
param([int]$ProcessId, [string]$Setup, [string]$Version, [string]$Installed, [string]$Current, [string]$Result)
try { Wait-Process -Id $ProcessId -Timeout 120 -ErrorAction Stop } catch { }
$outcome = "failed: setup did not run"
try {
    $process = Start-Process -FilePath $Setup -ArgumentList '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS' -Verb RunAs -Wait -PassThru -ErrorAction Stop
    if ($process.ExitCode -eq 0) { $outcome = "installed $Version" } else { $outcome = "failed: setup exited with code $($process.ExitCode)" }
} catch { $outcome = "failed: $($_.Exception.Message)" }
Set-Content -LiteralPath $Result -Value $outcome -Encoding utf8
$app = if ($outcome -like 'installed*' -and (Test-Path -LiteralPath $Installed)) { $Installed } else { $Current }
# Started from this unelevated helper, QuickResize runs as the user rather than as administrator.
if (Test-Path -LiteralPath $app) { Start-Process -FilePath $app }
if ($outcome -like 'installed*') { Remove-Item -LiteralPath $Setup -ErrorAction SilentlyContinue }
"""


def launch_installer_after_exit(setup: Path, version: str) -> None:
    """Start the hidden helper. The caller must then quit so setup can replace the files."""
    folder = work_folder()
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / "install-update.ps1"
    script.write_text(HELPER_SCRIPT, encoding="utf-8")
    result_path().unlink(missing_ok=True)
    current = sys.executable if getattr(sys, "frozen", False) else str(installed_exe())
    subprocess.Popen(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
            "-File", str(script),
            "-ProcessId", str(os.getpid()), "-Setup", str(setup), "-Version", version,
            "-Installed", str(installed_exe()), "-Current", current, "-Result", str(result_path()),
        ],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
    )


def take_last_result() -> str | None:
    """Read and clear the outcome the helper left from the last update, if any."""
    path = result_path()
    try:
        text = path.read_text(encoding="utf-8-sig").strip()
        path.unlink()
    except OSError:
        return None
    return text or None
