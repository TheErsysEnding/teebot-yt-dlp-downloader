# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the TEE yt-dlp Downloader (onedir, windowed).

Bundles: the sanitized `app` package, the full yt-dlp extractor set,
CustomTkinter themes, tkcalendar + babel locale data, the imageio-ffmpeg
binary, the Playwright python package + node driver, curl_cffi, gallery-dl,
plus a bundled Deno runtime (runtime/deno.exe) for YouTube n-sig solving.
"""
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

BUILD_DIR = os.path.abspath(os.getcwd())

datas = []
binaries = []
hiddenimports = []


def _add_all(pkg):
    global datas, binaries, hiddenimports
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
        print(f"[spec] collect_all({pkg}): {len(d)} datas, "
              f"{len(b)} bins, {len(h)} hidden")
    except Exception as exc:                      # noqa: BLE001
        print(f"[spec] WARN collect_all({pkg}) failed: {exc}")


for _pkg in ("customtkinter", "tkcalendar", "babel", "imageio_ffmpeg",
             "playwright", "curl_cffi", "gallery_dl", "winotify", "psutil"):
    _add_all(_pkg)

# yt-dlp lazily imports ~1800 extractor modules; force them all in.
hiddenimports += collect_submodules("yt_dlp")
hiddenimports += collect_submodules("gallery_dl")
hiddenimports += [
    "app",
    "app.yt_dlp_gui",
    "app.yt_dlp_i18n",
    "app.yt_dlp_toast",
    "app.cookie_browser",
    "app.tiktok_hd",
    "app.context_menu",
    "app.channel_downloader",
    "app.channel_downloader_gui",
    "app.portable_reset",
]

# Runtime assets that the app resolves via the filesystem.
datas += [
    (os.path.join(BUILD_DIR, "tools", "branding", "teebot.ico"),
     os.path.join("tools", "branding")),
    (os.path.join(BUILD_DIR, "tools", "branding", "teebot.png"),
     os.path.join("tools", "branding")),
    (os.path.join(BUILD_DIR, "runtime", "deno.exe"), "runtime"),
]

ICON = os.path.join(BUILD_DIR, "tools", "branding", "teebot.ico")

a = Analysis(
    ["teebot_launcher.py"],
    pathex=[BUILD_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "scipy", "pandas", "torch", "torchvision",
        "tensorflow", "IPython", "notebook", "pytest", "sphinx",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "numpy.testing",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TEEbot_yt_dlp_Downloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TEEbot_yt_dlp_Downloader",
)
