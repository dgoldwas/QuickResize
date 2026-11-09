from __future__ import annotations

import json

import pytest

from qr import updates


def release(tag: str = "v2026.12.01.1", assets: list[dict] | None = None, **extra) -> str:
    if assets is None:
        assets = [
            {"name": "QuickResize.exe", "browser_download_url": "https://x/exe", "size": 1},
            {
                "name": f"QuickResize-{tag[1:]}-Setup.exe",
                "browser_download_url": "https://x/setup",
                "size": 42,
                "digest": "sha256:ABCD",
            },
        ]
    return json.dumps({"tag_name": tag, "name": f"QuickResize {tag}", "html_url": "https://x/r", "assets": assets, **extra})


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("2026.11.09.10", "2026.11.09.9", True),
        ("2026.11.09.1", "2026.11.03.2", True),
        ("2026.11.03.2", "2026.11.03.2", False),
        ("2026.11.03.1", "2026.11.03.2", False),
        ("v2026.11.09.1", "2026.11.03.2", True),
        ("2026.11.09.1", "dev", True),
        ("latest", "2026.11.03.2", False),
    ],
)
def test_versions_compare_numerically(candidate, current, newer):
    assert updates.is_newer(candidate, current) is newer


def test_finds_the_setup_asset_of_a_newer_release():
    found = updates.parse_latest_release(release(), "2026.11.09.1")
    assert found == updates.AvailableUpdate(
        version="2026.12.01.1",
        title="QuickResize v2026.12.01.1",
        release_url="https://x/r",
        asset_name="QuickResize-2026.12.01.1-Setup.exe",
        download_url="https://x/setup",
        size=42,
        sha256="abcd",
    )


def test_nothing_to_do_when_current_or_prerelease():
    assert updates.parse_latest_release(release(), "2026.12.01.1") is None
    assert updates.parse_latest_release(release(prerelease=True), "2026.11.09.1") is None
    assert updates.parse_latest_release(release(draft=True), "2026.11.09.1") is None


def test_newer_release_without_installer_is_an_error():
    with pytest.raises(updates.UpdateError, match="no installer"):
        updates.parse_latest_release(release(assets=[]), "2026.11.09.1")


def test_older_release_without_installer_is_ignored():
    # Releases before the installer existed shipped only the EXE and the zip.
    assert updates.parse_latest_release(release("v2026.11.03.2", assets=[]), "2026.11.09.1") is None


def test_unreadable_response_is_an_error():
    with pytest.raises(updates.UpdateError):
        updates.parse_latest_release("<html>", "2026.11.09.1")


def test_only_a_copy_with_an_uninstaller_counts_as_installed(monkeypatch, tmp_path):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "QuickResize.exe"))
    assert not updates.is_installed()
    (tmp_path / "unins000.exe").write_bytes(b"")
    assert updates.is_installed()


def test_last_result_is_read_once(monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "work_folder", lambda: tmp_path)
    assert updates.take_last_result() is None
    (tmp_path / "last-result.txt").write_text("installed 2026.12.01.1\n", encoding="utf-8-sig")
    assert updates.take_last_result() == "installed 2026.12.01.1"
    assert updates.take_last_result() is None
