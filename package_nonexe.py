"""Rebuild the NON-EXE (bootstrap) distributable ZIP.

The bootstrap zip ships the `app/` *source* plus a handful of static
bootstrap files (install/start scripts, README, icon, requirements,
branding). Only `app/` changed in this round (right-click context menu,
bottom log + popout, TikTok multi-download fix), so we clone the previous
approved zip verbatim and swap in the freshly-patched `app/` source — this
guarantees the 7 non-app files stay byte-identical to the shipped baseline.

Run AFTER the patched app/ is verified (smoke_app_pkg.py).
"""
import os
import shutil
import sys
import zipfile
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
APP_SRC = BUILD_DIR / "app"
TOP = "TEEbot_yt_dlp_Downloader"
OLD_ZIP = Path(os.path.expanduser(rf"~\Desktop\{TOP}_v1.zip"))
NEW_TMP = BUILD_DIR / f"{TOP}_v1.NEW.zip"
BACKUP = BUILD_DIR / f"{TOP}_v1.PREV.zip"
README_SRC = BUILD_DIR / "README_BOOTSTRAP.txt"   # English, replaces old German README.txt
README_ARC = f"{TOP}/README.txt"

# The 10 source files that make up the published `app` package.
APP_FILES = [
    "__init__.py",
    "channel_downloader.py",
    "channel_downloader_gui.py",
    "context_menu.py",
    "cookie_browser.py",
    "portable_reset.py",
    "tiktok_hd.py",
    "yt_dlp_gui.py",
    "yt_dlp_i18n.py",
    "yt_dlp_toast.py",
]


def main() -> int:
    if not OLD_ZIP.exists():
        print(f"ERROR: previous zip not found: {OLD_ZIP}")
        return 1
    if not README_SRC.exists():
        print(f"ERROR: English readme not found: {README_SRC}")
        return 1
    for f in APP_FILES:
        if not (APP_SRC / f).exists():
            print(f"ERROR: missing app source file: {f}")
            return 1

    # 1. Copy every NON-app member of the old zip verbatim.
    carried = []
    with zipfile.ZipFile(OLD_ZIP) as zin, \
            zipfile.ZipFile(NEW_TMP, "w",
                            compression=zipfile.ZIP_DEFLATED,
                            compresslevel=6) as zout:
        for item in zin.infolist():
            if f"/{TOP}/app/" in f"/{item.filename}" or \
               item.filename.startswith(f"{TOP}/app/"):
                continue  # drop stale app/ members
            if item.filename == README_ARC:
                continue  # drop old German README.txt (replaced below)
            zout.writestr(item, zin.read(item.filename))
            carried.append(item.filename)

        # 2. Add the 10 freshly-patched app/ source files.
        added = []
        for f in APP_FILES:
            arc = f"{TOP}/app/{f}"
            zout.write(APP_SRC / f, arcname=arc)
            added.append(arc)

        # 3. Inject the English README.txt (replaces the dropped German one).
        zout.write(README_SRC, arcname=README_ARC)
        added.append(README_ARC)

    # 4. Sanity-check the new archive.
    with zipfile.ZipFile(NEW_TMP) as z:
        bad = z.testzip()
        if bad is not None:
            print(f"ERROR: corrupt entry in new zip: {bad}")
            return 1
        names = z.namelist()

    print(f"Carried {len(carried)} non-app files:")
    for n in sorted(carried):
        print(f"   = {n}")
    print(f"Added {len(added)} app/ files:")
    for n in sorted(added):
        print(f"   + {n}")
    if f"{TOP}/app/context_menu.py" not in names:
        print("ERROR: context_menu.py missing from new zip!")
        return 1
    print(f"context_menu.py present: OK")

    # 4. Back up the old zip (once) then move the new one onto the Desktop.
    if not BACKUP.exists():
        shutil.copy2(OLD_ZIP, BACKUP)
        print(f"Backed up old zip -> {BACKUP}")
    OLD_ZIP.unlink()
    shutil.move(str(NEW_TMP), str(OLD_ZIP))
    size = OLD_ZIP.stat().st_size
    print(f"\n  Entries: {len(names)}")
    print(f"  ZIP:     {size / 1024:.1f} KB")
    print(f"  -> {OLD_ZIP}")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
