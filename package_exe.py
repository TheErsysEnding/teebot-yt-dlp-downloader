"""Package the PyInstaller onedir build into a distributable ZIP.

Run AFTER the PyInstaller build succeeds. Copies README next to the .exe,
then zips dist/TEEbot_yt_dlp_Downloader -> Desktop ZIP.
"""
import os
import shutil
import zipfile
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
DIST_APP = BUILD_DIR / "dist" / "TEEbot_yt_dlp_Downloader"
README_SRC = BUILD_DIR / "README_EXE.txt"
ZIP_OUT = Path(os.path.expanduser(
    r"~\Desktop\TEEbot_yt_dlp_Downloader_EXE_v1.zip"))


def main() -> int:
    if not DIST_APP.exists():
        print(f"ERROR: build output not found: {DIST_APP}")
        return 1

    exe = DIST_APP / "TEEbot_yt_dlp_Downloader.exe"
    if not exe.exists():
        print(f"ERROR: exe not found: {exe}")
        return 1

    # Remove any stale German readme from earlier builds.
    stale = DIST_APP / "LIES_MICH.txt"
    if stale.exists():
        stale.unlink()
        print("  - LIES_MICH.txt (stale, removed)")

    # Drop the README right next to the .exe (English, international name).
    if README_SRC.exists():
        shutil.copy2(README_SRC, DIST_APP / "README.txt")
        print(f"  + README.txt")

    # Zip the whole onedir folder (preserve the top folder name so the
    # _internal stays next to the exe after extraction).
    if ZIP_OUT.exists():
        ZIP_OUT.unlink()

    print(f"Zipping -> {ZIP_OUT}")
    file_count = 0
    raw = 0
    with zipfile.ZipFile(ZIP_OUT, "w",
                         compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zf:
        for f in DIST_APP.rglob("*"):
            if not f.is_file():
                continue
            arc = Path("TEEbot_yt_dlp_Downloader") / f.relative_to(DIST_APP)
            zf.write(f, arcname=str(arc))
            file_count += 1
            raw += f.stat().st_size

    zsize = ZIP_OUT.stat().st_size
    print(f"  Files: {file_count}")
    print(f"  Raw:   {raw / 1024 / 1024:.1f} MB")
    print(f"  ZIP:   {zsize / 1024 / 1024:.1f} MB")
    print(f"  -> {ZIP_OUT}")
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
