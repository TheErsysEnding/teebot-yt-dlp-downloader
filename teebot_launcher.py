"""PyInstaller entry point for the TEE yt-dlp Downloader (.exe build).

A single frozen .exe that also acts as its own helper-process launcher.
The GUI needs to spawn three kinds of child processes:

    * the Chromium cookie-login browser  (app.cookie_browser)
    * `playwright install chromium`      (first browser-login only)
    * gallery-dl                         (Instagram / Twitter / Facebook)

Inside a PyInstaller bundle there is NO python interpreter to run
``python -m <module>``.  So the GUI re-invokes THIS exe with a leading
sub-command flag, and we dispatch here.

    TEEbot_yt_dlp_Downloader.exe                       -> GUI
    TEEbot_yt_dlp_Downloader.exe --cookie-browser URL --out P --site S
    TEEbot_yt_dlp_Downloader.exe --pw-install
    TEEbot_yt_dlp_Downloader.exe --gallery-dl <gallery-dl args...>
"""
import os
import sys
import multiprocessing


def _guard_std_streams() -> None:
    """In a windowed (--noconsole) PyInstaller build, sys.stdout/stderr are
    ``None``. Helper sub-commands (cookie_browser, gallery-dl) call print(),
    which would crash on a None stream. Redirect to os.devnull as a guard."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except Exception:
                pass


def _bundle_dir() -> str:
    """Folder that holds the bundled data (``_MEIPASS`` when frozen)."""
    return getattr(sys, "_MEIPASS",
                   os.path.dirname(os.path.abspath(__file__)))


def _prepare_environment() -> None:
    """Put the bundled Deno runtime on PATH so yt-dlp's YouTube extractor
    (EJS / n-sig solving) can find ``deno`` without a system install."""
    runtime = os.path.join(_bundle_dir(), "runtime")
    if os.path.isdir(runtime):
        os.environ["PATH"] = runtime + os.pathsep + os.environ.get("PATH", "")
    # Quieter Playwright / make sure it writes browsers to the user cache.
    os.environ.setdefault("PYTHONUTF8", "1")


def _run_cookie_browser(rest: list) -> int:
    from app import cookie_browser
    return cookie_browser.main(rest)


def _run_gallery_dl(rest: list) -> int:
    import gallery_dl
    sys.argv = ["gallery-dl"] + rest
    rc = gallery_dl.main()
    return int(rc or 0)


def _run_pw_install(rest: list) -> int:
    """Equivalent of ``python -m playwright install chromium``."""
    from playwright.__main__ import main as pw_main
    sys.argv = ["playwright", "install", "chromium"]
    try:
        pw_main()
        return 0
    except SystemExit as exc:        # playwright calls sys.exit() internally
        try:
            return int(exc.code or 0)
        except (TypeError, ValueError):
            return 1


def _run_selftest(rest: list) -> int:
    """Diagnostic: verify the frozen download stack works. Writes a report
    to the file path in rest[0] (windowed exe has no console)."""
    out_path = rest[0] if rest else os.path.join(
        os.environ.get("TEMP", "."), "teebot_selftest.txt")
    lines = []

    def log(msg):
        lines.append(str(msg))

    import shutil
    import subprocess
    import tempfile

    log("=== TEEbot exe self-test ===")
    log(f"frozen={getattr(sys, 'frozen', False)}  exe={sys.executable}")
    log(f"bundle={_bundle_dir()}")

    deno = shutil.which("deno")
    log(f"deno on PATH: {deno}")

    ffmpeg_exe = None
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        log(f"ffmpeg: {ffmpeg_exe} exists={os.path.exists(ffmpeg_exe)}")
        r = subprocess.run([ffmpeg_exe, "-version"], capture_output=True,
                           text=True, timeout=30)
        log(f"ffmpeg -version rc={r.returncode}: "
            f"{(r.stdout or '').splitlines()[0] if r.stdout else ''}")
    except Exception as exc:                       # noqa: BLE001
        log(f"ffmpeg FAIL: {type(exc).__name__}: {exc}")

    try:
        from app import yt_dlp_gui
        log(f"app import OK  DENO_AVAILABLE={yt_dlp_gui.DENO_AVAILABLE} "
            f"FFMPEG_PATH set={bool(yt_dlp_gui.FFMPEG_PATH)}")
    except Exception as exc:                       # noqa: BLE001
        log(f"app import FAIL: {type(exc).__name__}: {exc}")

    # Real download of the smallest format -> proves extract+deno+download.
    # Try a couple of always-available videos (or an override in rest[1]).
    urls = []
    if len(rest) > 1 and rest[1]:
        urls.append(rest[1])
    urls += [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    ]
    import yt_dlp
    ok = False
    for u in urls:
        try:
            tmpdir = tempfile.mkdtemp(prefix="teebot_st_")
            opts = {
                "quiet": True, "no_warnings": True,
                "format": "worst[ext=mp4]/worst",
                "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(u, download=True)
            files = os.listdir(tmpdir)
            sz = sum(os.path.getsize(os.path.join(tmpdir, f)) for f in files)
            log(f"yt-dlp DOWNLOAD OK ({u}): title={info.get('title')!r} "
                f"files={files} bytes={sz}")
            shutil.rmtree(tmpdir, ignore_errors=True)
            ok = True
            break
        except Exception as exc:                    # noqa: BLE001
            log(f"yt-dlp try FAIL ({u}): {type(exc).__name__}: {exc}")
            shutil.rmtree(tmpdir, ignore_errors=True)
    if not ok:
        log("yt-dlp DOWNLOAD FAIL: all candidate URLs failed")

    log("=== end ===")
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass
    return 0


def main() -> int:
    multiprocessing.freeze_support()
    _guard_std_streams()
    _prepare_environment()

    argv = sys.argv[1:]
    cmd = argv[0] if argv else ""

    if cmd == "--cookie-browser":
        return _run_cookie_browser(argv[1:])
    if cmd == "--gallery-dl":
        return _run_gallery_dl(argv[1:])
    if cmd == "--pw-install":
        return _run_pw_install(argv[1:])
    if cmd == "--selftest":
        return _run_selftest(argv[1:])

    # Default: launch the GUI.
    from app import yt_dlp_gui
    return yt_dlp_gui.main()


if __name__ == "__main__":
    sys.exit(main() or 0)
