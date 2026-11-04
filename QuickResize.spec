# -*- mode: python ; coding: utf-8 -*-
"""Build recipe for the single-file dist\\QuickResize.exe. Run it with build.ps1."""
import os

from PyInstaller.utils.hooks import collect_all

datas = [
    (os.path.join(SPECPATH, "assets", "QuickResize.ico"), "assets"),
    (os.path.join(SPECPATH, "THIRD-PARTY-NOTICES.txt"), "."),
]
binaries = []
hiddenimports = []
rawpy_datas, rawpy_binaries, rawpy_hidden = collect_all("rawpy")
datas += rawpy_datas
binaries += rawpy_binaries
hiddenimports += rawpy_hidden

# Modules the app never imports, which optional paths of its dependencies pull in.
EXCLUDED_MODULES = [
    "tkinter",
    "unittest",
    "pydoc",
    "ssl",
    "PIL._avif",
    "PIL.AvifImagePlugin",
    "PIL.ImageQt",
    "onnxruntime",
    "pymupdf4llm",
    "pymupdf.layout",
    "pymupdf_layout",
    "PySide6.QtNetwork",
    "PySide6.QtOpenGL",
    "PySide6.QtDBus",
]

# Qt files the app has no use for: it draws with the raster engine, uses the
# built-in Fusion style, makes no network calls, and only loads a .ico through Qt.
EXCLUDED_BINARIES = (
    "opengl32sw.dll",
    "d3dcompiler_",
    "qt6network",
    "qt6opengl",
    "qt6pdf",
    "qt6qml",
    "qt6quick",
    "qt6virtualkeyboard",
    "qdirect2d",
    "qminimal",
    "qoffscreen",
    "qmodernwindowsstyle",
    "libcrypto",
    "libssl",
)
UNUSED_PLUGIN_FOLDERS = ("/plugins/tls/", "/plugins/networkinformation/", "/plugins/generic/", "/plugins/iconengines/")


def keep_binary(entry):
    name = entry[0].replace("\\", "/").lower()
    if any(part in name.rsplit("/", 1)[-1] for part in EXCLUDED_BINARIES):
        return False
    if any(folder in f"/{name}" for folder in UNUSED_PLUGIN_FOLDERS):
        return False
    if "/plugins/imageformats/" in f"/{name}" and not name.endswith("qico.dll"):
        return False
    return True


a = Analysis(
    ["quickresize.py"],
    pathex=[SPECPATH],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=EXCLUDED_MODULES,
    noarchive=False,
    optimize=0,
)
a.binaries = [entry for entry in a.binaries if keep_binary(entry)]
a.datas = [entry for entry in a.datas if "/translations/" not in entry[0].replace("\\", "/").lower()]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="QuickResize",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=[os.path.join(SPECPATH, "assets", "QuickResize.ico")],
)
