"""yt-dlp GUI — Windows-native, modern, beginner-friendly (Author).

Features:
  - URL input (multi-URL: one per line, or comma/space separated)
  - Auto-detect plattform (TikTok / Instagram / YouTube / generic)
  - Quality dropdown (8K, 4K, 1440p, 1080p, 720p, 480p, 360p, Best, Worst)
    Falls back automatically when requested quality unavailable
  - Output folder picker (Browse button + drag-drop)
  - Cookies.txt picker (Browse button + drag-drop)
  - Format selector (mp4 default — auto-converts WebM/MKV)
  - Dark / Light mode toggle (persisted in %APPDATA%/teebot_yt_gui/settings.json)
  - Progress bar + log pane during download
  - "Open folder" button to jump to output after completion
  - Stoppable downloads (cancel button)

Discord-launchable: `python -m autonomous.yt_dlp_gui` from anywhere.

Standalone — does not require the Discord bot to run. Reuses the bundled
ffmpeg from `imageio_ffmpeg` for merging high-quality streams.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import filedialog, messagebox

# i18n + Toast helpers ((Author) v6)
try:
    from . import yt_dlp_i18n as _i18n
    from . import yt_dlp_toast as _toast
except ImportError:
    # Standalone-Mode: Module liegen im gleichen Ordner
    import importlib.util as _ilu
    _here = Path(__file__).resolve().parent
    for _mod_name in ("yt_dlp_i18n", "yt_dlp_toast"):
        _spec = _ilu.spec_from_file_location(_mod_name, _here / f"{_mod_name}.py")
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        sys.modules[_mod_name] = _mod
    import yt_dlp_i18n as _i18n  # type: ignore
    import yt_dlp_toast as _toast  # type: ignore

# Right-click context menu (cut/copy/paste/select-all) for all text inputs
try:
    from . import context_menu as _ctxmenu
except ImportError:
    import importlib.util as _ilu_cm
    _spec_cm = _ilu_cm.spec_from_file_location(
        "context_menu", Path(__file__).resolve().parent / "context_menu.py")
    _ctxmenu = _ilu_cm.module_from_spec(_spec_cm)
    _spec_cm.loader.exec_module(_ctxmenu)
    sys.modules["context_menu"] = _ctxmenu

# ───────────────── JS-Runtime (Deno) fuer YouTube ─────────────────
# (Author) yt-dlp braucht ein JavaScript-Runtime um YouTube's
# n-Challenge zu loesen (siehe github.com/yt-dlp/yt-dlp/wiki/EJS).
# Ohne das gibt YouTube nur Image-Formate zurueck = kein Video.
# Wir buendeln Deno (~35 MB Single-Binary) und legen es in 'runtime/'
# neben das Script. PATH wird so gesetzt dass yt-dlp es findet.

def _detect_and_register_deno() -> tuple[bool, str]:
    """Sucht deno.exe in 'runtime/' neben dem Script + global PATH.

    Returns (gefunden, pfad). Wenn gefunden: PATH wird vorne erweitert.
    """
    # 1. Lokales runtime-Verzeichnis (vom .bat-Setup)
    here = Path(__file__).resolve().parent
    candidates = [
        here / "runtime" / "deno.exe",
        here.parent / "runtime" / "deno.exe",
    ]
    for c in candidates:
        if c.exists():
            os.environ["PATH"] = str(c.parent) + os.pathsep + \
                                  os.environ.get("PATH", "")
            return True, str(c)
    # 2. PATH-deno (User hat selber installiert)
    import shutil as _sh
    p = _sh.which("deno")
    if p:
        return True, p
    return False, ""

DENO_AVAILABLE, DENO_PATH = _detect_and_register_deno()


try:
    import yt_dlp
    _YTDLP_AVAILABLE = True
except ImportError:
    _YTDLP_AVAILABLE = False

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = None


def _ensure_ffmpeg_exe_alias() -> "str | None":
    """yt-dlp's Trim-Code (download_ranges) sucht 'ffmpeg.exe' im PATH.
    imageio's binary heisst aber 'ffmpeg-win-x86_64-v7.1.exe'. Loesung:
    Hardlink/Kopie 'ffmpeg.exe' anlegen + PATH-prepend.

    Reihenfolge der Suche/Anlage:
      1. <here>/runtime/  (Standalone-Modus)
      2. <here>/../runtime/  (autonomous/-Modul-Ebene)
      3. %APPDATA%/teebot_yt_gui/runtime/  (universal Fallback)
    """
    if not FFMPEG_PATH or not Path(FFMPEG_PATH).exists():
        return None
    here = Path(__file__).resolve().parent
    candidates = [
        here / "runtime",
        here.parent / "runtime",
        Path(os.environ.get("APPDATA", str(Path.home()))) / "teebot_yt_gui" / "runtime",
    ]
    runtime = None
    for cand in candidates:
        if cand.exists():
            runtime = cand
            break
    if runtime is None:
        # Letzter Fallback: APPDATA-runtime ANLEGEN
        runtime = candidates[-1]
        try:
            runtime.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None
    target = runtime / "ffmpeg.exe"
    if target.exists():
        return str(runtime)
    try:
        os.link(FFMPEG_PATH, target)
    except (OSError, FileExistsError):
        try:
            import shutil
            shutil.copy2(FFMPEG_PATH, target)
        except Exception:
            return None
    return str(runtime)


_FFMPEG_RUNTIME_DIR = _ensure_ffmpeg_exe_alias()
if _FFMPEG_RUNTIME_DIR:
    os.environ["PATH"] = _FFMPEG_RUNTIME_DIR + os.pathsep + \
                          os.environ.get("PATH", "")

# ───────────────── Settings persistence ─────────────────

APP_NAME = "teebot_yt_gui"
GUI_VERSION = "v1.1 · 2026-05-31 (clear-history, channel-dl, tiktok-hd, 8 languages)"
SETTINGS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "theme": "dark",                # "dark" | "light"
    "language": "de",               # de|en|es|fr|it|tr|ru|pl
    "quality": "Best (auto)",
    "output_dir": str(Path.home() / "Desktop" / "yt_dlp_GUI_Downloads"),
    "cookies_file": "",             # empty = no cookies-file
    "cookies_browser": "(keine)",   # (keine) | chrome | firefox | edge | ...
    "format": "mp4",                # mp4 | webm | mkv | original
    "audio_only": False,            # Nur Audio (mp3) statt Video
    "embed_subs": False,
    "write_thumbnail": False,
    "rate_limit_kbps": 0,           # 0 = unlimited
    "window_size": "1100x800",
    # NEU 2026-05-09 v6:
    "url_history": [],              # letzte 20 URLs
    "trim_from": "",                # MM:SS oder leer
    "trim_to": "",                  # MM:SS oder leer
    "filename_template": "%(uploader)s/%(title).100B [%(id)s].%(ext)s",
    "toast_enabled": True,          # Windows-Toast bei Fertig
    "concurrent_downloads": 1,      # 1-3 (1=sequential)
    # NEU 2026-05-17: anfaenger-freundliches Dateinamen-Schema
    "filename_mode": "simple",      # "simple" | "profi"
    "fn_folder_struct": "platform_uploader", # better default: YouTube/TheErsysEnding/<Titel> [id].mp4
    "fn_date_prefix": False,
    "fn_date_format": "iso",        # iso|compact|dmy
    "fn_time_suffix": False,
    "fn_resolution_suffix": False,
    "fn_platform_tag": False,
    "fn_video_id": True,            # default an: eindeutig
    "fn_prefix": "",                # frei (z.B. "ARCHIV_")
    "fn_suffix": "",                # frei (z.B. "_backup")
    "fn_custom_title": "",          # nur wirksam bei 1 URL
    "fn_max_title_chars": 100,      # 50-200, Pfadlimit-Schutz
    "fn_sanitize": True,            # Sonderzeichen ersetzen
    "overwrite_policy": "skip",     # skip|overwrite|number
    "prefer_lang": "original",      # original|en|de — Multi-Language Titel
    "tiktok_quality": "Auto (Youtube-Qualität benutzen)",
    # NEU 2026-05-24: ID-statt-Beschreibung Filenames (User-Wunsch)
    # Wenn aktiviert (Default), wird Filename = {uploader}_{kind}_{id}.{ext}
    # statt {title} [{id}].{ext}. Kind = "video" oder "picture".
    "fn_use_id_not_title": True,
    # NEU 2026-05-24: File-Date = Upload-Date toggle. OFF by default für
    # normale Downloads (die meisten User wollen Download-Zeit als Datum),
    # ON by default im Channel-Downloader.
    "set_upload_date_as_file_date": False,
    # Channel-Downloader defaults
    "channel_max_items":      0,        # 0 = unbegrenzt
    "channel_date_from":      "",       # ISO YYYY-MM-DD oder leer
    "channel_date_to":        "",
    "channel_media_type":     "both",   # both|video|picture
    "channel_include_audio":  False,    # extra audio extraction?
}


# ─────────────── Filename template builder (Author) ───────────────
# Builds a yt-dlp output template from the user-friendly UI options.
# yt-dlp template syntax docs: %(field)s = field, %(field>%Y-%m-%d)s = strftime,
# %(field).100B = truncate to 100 BYTES (UTF-8 safe for Windows path limit).

# ─── Pretty platform names (overrides yt-dlp's lowercase extractor) ───
# Mapping from URL-substring → folder name. Order matters: first match wins,
# so put more-specific entries first (e.g. "youtu" before generic fallback).
PRETTY_PLATFORM = [
    ("youtube.com",       "YouTube"),
    ("youtu.be",          "YouTube"),
    ("tiktok.com",        "TikTok"),
    ("instagram.com",     "Instagram"),
    ("twitter.com",       "Twitter"),
    ("x.com",             "Twitter"),
    ("facebook.com",      "Facebook"),
    ("fb.watch",          "Facebook"),
    ("vimeo.com",         "Vimeo"),
    ("reddit.com",        "Reddit"),
    ("twitch.tv",         "Twitch"),
    ("dailymotion.com",   "Dailymotion"),
    ("soundcloud.com",    "SoundCloud"),
    ("bandcamp.com",      "Bandcamp"),
]


def detect_platform_pretty(url: str) -> str:
    """Pretty folder name from a URL — 'YouTube', 'TikTok' etc.

    Falls back to extracting the second-level domain ('example.com' →
    'Example') for unknown sites. Per the user spec: take what's between
    'www.' and the last '.' before the TLD.
    """
    if not url:
        return "Other"
    url_l = url.lower()
    # First try the curated map (correct capitalization)
    for needle, pretty in PRETTY_PLATFORM:
        if needle in url_l:
            return pretty
    # Fallback: regex-extract second-level domain, title-case it
    import re as _re
    m = _re.search(r"https?://(?:www\.)?([a-z0-9][a-z0-9-]*)\.[a-z]{2,8}",
                   url_l)
    if m:
        name = m.group(1)
        # Hyphens become underscores so Windows paths stay friendly
        name = name.replace("-", "_")
        # Title-case for nice folder
        return name.capitalize() if name else "Other"
    return "Other"


FOLDER_STRUCTURES = {
    "flat":               [],
    "uploader":           ["%(uploader)s"],
    "platform":           ["%(extractor)s"],
    "platform_uploader":  ["%(extractor)s", "%(uploader)s"],
    "year_month":         ["%(upload_date>%Y)s", "%(upload_date>%m)s"],
    "uploader_year":      ["%(uploader)s", "%(upload_date>%Y)s"],
}
DATE_FORMATS = {
    "iso":     "%(upload_date>%Y-%m-%d)s_",
    "compact": "%(upload_date)s_",
    "dmy":     "%(upload_date>%d.%m.%Y)s_",
}


def build_filename_template(opts: dict, num_urls: int = 1,
                              kind: str = "video") -> str:
    """Compose a yt-dlp outtmpl from the simple-mode UI options.

    Two filename-styles supported via `fn_use_id_not_title`:
      A) ID-mode (default, 2026-05-24): <uploader>_<kind>_<id>.<ext>
         Example: TheErsysEnding_video_7642778099603574048.mp4
         Reason: TikTok descriptions can be 100s of chars with emojis +
         line breaks that mess up file managers. ID is stable + unique.
      B) Title-mode (old default): <prefix><date>title[id]<suffix>.ext

    `kind` is "video" or "picture" — controls folder routing for the
    channel downloader. For single-URL downloads use "video".
    """
    folders = list(FOLDER_STRUCTURES.get(
        opts.get("fn_folder_struct", "uploader"),
        FOLDER_STRUCTURES["uploader"]))

    # ─── NEU 2026-05-24: ID-Mode (Default) ───
    if opts.get("fn_use_id_not_title", True):
        # Always: <uploader>_<kind>_<id>.<ext>
        # Pre-sanitize uploader at template time — yt-dlp doesn't sanitize
        # field values BEFORE substitution, so unsafe chars from the
        # uploader name leak straight into the filename.
        name = f"%(uploader)s_{kind}_%(id)s.%(ext)s"
        # Subfolder split for channel-downloader (Video/Picture)
        if opts.get("fn_split_by_kind", False):
            # Capitalize like Windows folder convention
            kind_folder = "Picture" if kind == "picture" else "Video"
            folders = folders + [kind_folder]
        return "/".join(folders + [name])

    # ─── OLD: Title-mode ───
    name = ""
    if opts.get("fn_prefix"):
        # Literal %-signs in user input must be doubled for yt-dlp
        name += str(opts["fn_prefix"]).replace("%", "%%")

    if opts.get("fn_date_prefix"):
        name += DATE_FORMATS.get(
            opts.get("fn_date_format", "iso"), DATE_FORMATS["iso"])

    # Title — custom override only sensible for single-URL downloads
    max_chars = max(20, min(250, int(opts.get("fn_max_title_chars", 100))))
    custom_title = opts.get("fn_custom_title", "").strip()
    if custom_title and num_urls <= 1:
        # Bake the literal title in; bypass yt-dlp's %(title)s machinery
        # so the user gets EXACTLY what they typed (truncated to the
        # length limit so the path-limit check still works).
        safe = custom_title.replace("%", "%%")
        name += safe[:max_chars]
    else:
        name += f"%(title).{max_chars}B"

    if opts.get("fn_resolution_suffix"):
        # %(height)sp gives "1080p" / "2160p"; cleaner than %(resolution)s
        name += "_%(height)sp"
    if opts.get("fn_time_suffix"):
        # Upload time HH-MM. epoch field has the original UTC timestamp.
        name += "_%(timestamp>%H-%M)s"

    tags = []
    if opts.get("fn_platform_tag"):
        tags.append("[%(extractor_key)s]")
    if opts.get("fn_video_id", True):
        tags.append("[%(id)s]")
    if tags:
        name += " " + " ".join(tags)

    if opts.get("fn_suffix"):
        name += str(opts["fn_suffix"]).replace("%", "%%")

    name += ".%(ext)s"
    return "/".join(folders + [name])


def render_template_preview(template: str, sample: dict) -> str:
    """Render a yt-dlp template with a sample dict for live preview.

    Handles %(key)s, %(key).100B (byte truncation), and %(key>FORMAT)s
    (strftime) — same syntax yt-dlp uses at download time.
    """
    import re as _re
    from datetime import datetime as _dt

    def _render_strftime(m):
        key, fmt = m.group(1), m.group(2)
        val = sample.get(key, "")
        # upload_date is always YYYYMMDD; timestamp is epoch seconds
        try:
            if key == "upload_date":
                d = _dt.strptime(str(val), "%Y%m%d")
            elif key == "timestamp":
                d = _dt.fromtimestamp(int(val))
            else:
                return str(val)
            return d.strftime(fmt)
        except Exception:
            return str(val)

    def _render_truncate(m):
        key, n = m.group(1), int(m.group(2))
        val = str(sample.get(key, ""))
        b = val.encode("utf-8")[:n]
        # decode safely even if truncated mid-codepoint
        return b.decode("utf-8", errors="ignore")

    out = template
    # strftime form first (greediest); %% must survive
    out = out.replace("%%", "\x00ESC\x00")
    out = _re.sub(r"%\((\w+)>([^)]+)\)s", _render_strftime, out)
    out = _re.sub(r"%\((\w+)\)\.(\d+)B", _render_truncate, out)
    out = _re.sub(r"%\((\w+)\)s",
                   lambda m: str(sample.get(m.group(1), "")), out)
    out = out.replace("\x00ESC\x00", "%")
    return out


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults so new keys appear with sane fallback
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        return merged
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(s: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ───────────────── Quality presets ─────────────────

QUALITY_OPTIONS = [
    "Best (auto)",
    "8K (4320p)",
    "4K (2160p)",
    "1440p (2K)",
    "1080p (Full HD)",
    "720p (HD)",
    "480p (SD)",
    "360p",
    "240p",
    "Worst (smallest)",
]

QUALITY_HEIGHT_MAP = {
    "Best (auto)": None,
    "8K (4320p)": 4320,
    "4K (2160p)": 2160,
    "1440p (2K)": 1440,
    "1080p (Full HD)": 1080,
    "720p (HD)": 720,
    "480p (SD)": 480,
    "360p": 360,
    "240p": 240,
    "Worst (smallest)": 0,
}

# ─── TikTok-spezifische Qualitäts-Optionen (Author) ───
# TikTok hat eine Eigenheit: das HD-Original ohne Wasserzeichen ist
# nur über bestimmte Format-IDs erreichbar. yt-dlp kennt diese als:
#   - "download_addr-0" / "play_addr-0" → Original ohne Wasserzeichen
#   - "download"                        → Mit Wasserzeichen (oft niedriger qual)
#   - "bestaudio"                       → Reine Tonspur (M4A → MP3)
# Reihenfolge: erstes Element = Auto (= "Youtube Qualität" wird benutzt).
TIKTOK_QUALITY_OPTIONS = [
    "Auto (Youtube-Qualität benutzen)",
    "No Watermark (HD)",
    "Only Sound (MP3)",
    "Watermark (SD)",
]


def tiktok_format_selector(choice: str) -> str:
    """Map TikTok-quality-dropdown choice → yt-dlp format string.

    HISTORICAL BUG (fixed 2026-05-24): TikTok serves the same video in
    multiple variants per resolution — the HEVC originals are at full
    bitrate (~2.5 Mbps for 1080p), while the H264 transcodes are heavily
    compressed (often 150 kbps even at 720p, which looks AWFUL). The old
    selector + format_sort=['res','fps','vcodec:h264'] picked the tiny
    H264 transcode every time, giving the user 279 KB / 158 kbps SD
    instead of TTDownloader's 3.2 MB / 2.5 Mbps 1080p.

    Fix: for HD we force height>=1080 first; the caller ALSO overrides
    format_sort to remove the H264 bias and add 'br' (bitrate DESC).
    """
    if choice == "No Watermark (HD)":
        # Strategy: NICHT nach Auflösung filtern! TikTok serviert oft
        # ein höher aufgelöstes UPSCALE (z.B. 720p @ 231 kbps) plus ein
        # niedriger aufgelöstes ORIGINAL (540p @ 542 kbps). Das größere
        # File ist immer das Original mit besserer Qualität.
        # `format_sort` (siehe TIKTOK_FORMAT_SORT) sorgt dafür dass das
        # größte File gewinnt, also einfach 'best' — yt-dlp benutzt den
        # custom sort und pickt automatisch das Richtige.
        return "b"
    if choice == "Only Sound (MP3)":
        return "bestaudio/best"
    if choice == "Watermark (SD)":
        # The watermarked render is the 'download' format-ID (TikTok-internal
        # rendered version with TikTok logo + username overlay).
        return ("download/"
                "best[format_id=download]/"
                "best[format_id*=watermark]/"
                "worst")
    # "Auto" or unknown → return empty, caller uses normal Youtube logic
    return ""


# TikTok-specific format_sort — überschreibt den YouTube-orientierten.
#
# HARTE LEKTION (2026-05-24, debugging TheErsysEnding-Video):
# TikTok publiziert pro Video MEHRERE Varianten mit komplett unterschied-
# lichen Bitrate-zu-Auflösungs-Verhältnissen. Beispiel von ECHTEM Video:
#   - h264_540p_542520  →  576×1024 @ 542 kbps  →  640 KB  ← REAL ORIGINAL
#   - bytevc1_720p_231465 →  720×1280 @ 231 kbps  →  273 KB  ← upscale
#
# Würden wir nach Auflösung sortieren (wie YouTube), kriegen wir das
# scheinbar-höhere 720p — aber das ist ein TikTok-internes Upscale mit
# weniger als der HÄLFTE der Bitrate. Visuell deutlich SCHLECHTER.
#
# Lösung: sort by SIZE first → größte Datei = meiste Information = beste
# Qualität, unabhängig vom Codec/Auflösungs-Trick. Funktioniert universell:
# wenn ein Video echtes 1080p hat, ist DAS die größte Datei und gewinnt.
# Hat es nur 540p-Original, gewinnt das hochbitrate 540p statt fakes-720p.
TIKTOK_FORMAT_SORT = ["size", "br", "res", "fps"]


def format_selector(height: Optional[int], container: str) -> str:
    """Build a yt-dlp format string for a height ceiling and container preference.

    Falls back to next-best when the requested quality isn't available.
    Always includes audio.
    """
    if height is None:
        # Best video + best audio, prefer container
        if container == "mp4":
            return ("bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                    "bestvideo*+bestaudio/best")
        return "bestvideo*+bestaudio/best"
    if height == 0:
        return "worstvideo*+worstaudio/worst"
    # With ceiling
    if container == "mp4":
        return (f"bestvideo[ext=mp4][height<={height}]+bestaudio[ext=m4a]/"
                f"bestvideo[height<={height}]+bestaudio/"
                f"best[height<={height}]/"
                f"bestvideo*+bestaudio/best")
    return (f"bestvideo[height<={height}]+bestaudio/"
            f"best[height<={height}]/"
            f"bestvideo*+bestaudio/best")


# ───────────────── Main GUI ─────────────────

class YtDlpGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        ctk.set_appearance_mode(self.settings["theme"])
        ctk.set_default_color_theme("blue")

        # i18n: Sprache aus settings laden + listener registrieren
        _i18n.set_language(self.settings.get("language", "de"))

        self.title(f"{_i18n.t('app.title')} · {GUI_VERSION}")
        self.geometry(self.settings.get("window_size", "1100x800"))
        self.minsize(900, 650)

        # ── Application icon (title bar + Windows taskbar) ───────────────
        # AppUserModelID must be set before window-show or Windows groups
        # this under pythonw.exe with the generic Python icon.
        try:
            import sys as _sys
            if _sys.platform == "win32":
                import ctypes as _ct
                _ct.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "TheErsysEnding.TEEbot.YtDlpDownloader.1")
            _icon_path = (Path(__file__).resolve().parent.parent
                          / "tools" / "branding" / "teebot.ico")
            if _icon_path.exists():
                self.iconbitmap(default=str(_icon_path))
                self.iconbitmap(str(_icon_path))
                _png_path = _icon_path.with_suffix(".png")
                if _png_path.exists():
                    try:
                        import tkinter as _tk
                        _photo = _tk.PhotoImage(file=str(_png_path))
                        self.iconphoto(True, _photo)
                        self._teebot_icon_ref = _photo
                    except Exception:
                        pass
        except Exception:
            pass

        # State
        self._download_thread: Optional[threading.Thread] = None
        self._current_ydl: Optional[yt_dlp.YoutubeDL] = None
        self._stop_requested = False
        self._log_queue: queue.Queue = queue.Queue()
        # NEU v6: Translatable widgets registry
        # {widget: (i18n_key, attr_name)} - attr_name: "text"/"placeholder_text"
        self._tr_widgets: dict = {}
        # NEU v6: Per-URL status rows {url: row_label}
        self._url_status_rows: dict = {}
        self._url_status_panel = None
        # Clipboard-Detect tracking (URL die wir schon angeboten haben)
        self._last_clipboard_offered: str = ""

        self._build_ui()
        # Rechtsklick-Menü (Ausschneiden/Kopieren/Einfügen) für ALLE
        # Text-/Eingabefelder — inkl. später erzeugter (Popouts, Dialoge).
        try:
            _ctxmenu.attach_context_menu(self)
        except Exception:
            pass
        self._poll_log_queue()
        # Periodisch Clipboard checken
        self.after(1500, self._poll_clipboard)
        # i18n live-switch listener
        _i18n.register_listener(self._retranslate_all)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ───── i18n Helper ─────

    def _tr(self, widget, key: str, attr: str = "text") -> None:
        """Setzt widget.configure(attr=t(key)) UND registriert es fuer
        Live-Sprach-Switch."""
        try:
            if attr == "text":
                widget.configure(text=_i18n.t(key))
            elif attr == "placeholder_text":
                widget.configure(placeholder_text=_i18n.t(key))
            elif attr == "label_text":  # Tab-Label fuer CTkTabview
                pass  # Tab-Labels muessen manuell uebersetzt werden
        except Exception:
            pass
        self._tr_widgets[widget] = (key, attr)

    def _retranslate_all(self) -> None:
        """Wird gerufen wenn sich die Sprache aendert. Updatet alle
        registrierten Widgets + UI-Elemente die nicht im _tr_widgets sind."""
        try:
            self.title(f"{_i18n.t('app.title')} · {GUI_VERSION}")
        except Exception:
            pass
        for widget, (key, attr) in list(self._tr_widgets.items()):
            try:
                if attr == "text":
                    widget.configure(text=_i18n.t(key))
                elif attr == "placeholder_text":
                    widget.configure(placeholder_text=_i18n.t(key))
            except Exception:
                pass
        # Cookies-Status neu uebersetzen
        try:
            self._update_cookies_status()
        except Exception:
            pass
        # Filename-Template-Preview updaten
        try:
            self._update_filename_preview()
        except Exception:
            pass

    def _build_header_branding(self, parent) -> None:
        """Center area in the header: Example social + yt-dlp GitHub.

        Two clickable label-style buttons. Hovering shows the URL via
        cursor change. CTkLabels don't expose a 'link' control, so we
        use CTkButton with transparent fg + text-color tinting to look
        like a hyperlink.
        """
        center = ctk.CTkFrame(parent, fg_color="transparent")
        center.pack(side="left", expand=True, fill="x", padx=20)

        # by TheErsysEnding (YouTube channel)
        ttls = ctk.CTkFrame(center, fg_color="transparent")
        ttls.pack(anchor="center")
        ctk.CTkLabel(
            ttls, text="by ",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"),
        ).pack(side="left")
        social_url = "https://www.youtube.com/@TheErsysEnding"
        ctk.CTkButton(
            ttls, text="TheErsysEnding",
            font=ctk.CTkFont(size=13, weight="bold", underline=True),
            fg_color="transparent", hover_color=("gray85", "gray25"),
            text_color=("#E0B040", "#E0B040"),    # gold accent
            height=22, width=0,
            cursor="hand2",
            command=lambda: self._open_url(social_url),
        ).pack(side="left", padx=(0, 2))

        # yt-dlp official GitHub link below the TEE branding
        gh_url = "https://github.com/yt-dlp/yt-dlp"
        ctk.CTkButton(
            center, text="⭐ yt-dlp auf GitHub (offiziell)",
            font=ctk.CTkFont(size=11, underline=True),
            fg_color="transparent", hover_color=("gray85", "gray25"),
            text_color=("#3b82f6", "#60a5fa"),
            height=20, width=0, cursor="hand2",
            command=lambda: self._open_url(gh_url),
        ).pack(anchor="center", pady=(2, 0))

    def _open_url(self, url: str) -> None:
        """Open the given URL in the user's default browser."""
        try:
            import webbrowser
            webbrowser.open(url, new=2)
        except Exception as e:
            messagebox.showerror("Fehler", f"URL konnte nicht geöffnet werden:\n{e}")

    def _change_language(self, code: str) -> None:
        """Wird vom Sprach-Dropdown gerufen."""
        # Code aus Display-Namen zurueckmappen
        for c, name in _i18n.LANGUAGES.items():
            if name == code or c == code:
                _i18n.set_language(c)
                self.settings["language"] = c
                save_settings(self.settings)
                return

    # ───── Layout ─────

    def _build_ui(self) -> None:
        # ─── Header: Title (left) + Branding (center) + Theme/Lang (right) ───
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))

        # Left: app title
        ctk.CTkLabel(
            header,
            text="🎬 TEE yt-dlp Downloader",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(side="left")

        # Center: social branding + GitHub link
        # Packs from the right so it lands in the middle as the right-side
        # buttons (lang/theme) take their space first.
        self._build_header_branding(header)
        # Sprach-Dropdown rechts (vor Theme)
        self.lang_var = ctk.StringVar(
            value=_i18n.LANGUAGES.get(self.settings.get("language", "de"),
                                       "Deutsch")
        )
        lang_menu = ctk.CTkOptionMenu(
            header, variable=self.lang_var,
            values=list(_i18n.LANGUAGES.values()),
            command=self._change_language,
            width=110, height=32,
        )
        lang_menu.pack(side="right", padx=(5, 0))
        # Theme-Toggle rechts daneben
        self.theme_btn = ctk.CTkButton(
            header,
            text="🌙" if self.settings["theme"] == "dark" else "☀️",
            width=40, height=32,
            command=self._toggle_theme,
        )
        self.theme_btn.pack(side="right", padx=(5, 5))

        self.subtitle_lbl = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"),
        )
        self.subtitle_lbl.pack(padx=20, pady=(0, 5))
        self._tr(self.subtitle_lbl, "app.subtitle")

        # ─── NEU 2026-05-24: Channel Downloader Button (direkt unter Titel) ───
        # Prominent unter dem Titel weil das ein Power-Feature ist und User
        # es schnell erreichen sollen ohne erst zu scrollen.
        channel_btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        channel_btn_frame.pack(fill="x", padx=20, pady=(0, 10))
        self.channel_btn = ctk.CTkButton(
            channel_btn_frame,
            text="",
            height=42,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#7c3aed", hover_color="#6d28d9",
            command=self._open_channel_downloader,
        )
        self.channel_btn.pack(fill="x", padx=0)
        self._tr(self.channel_btn, "channel.btn")

        # ─── NEU 2026-05-30: Immer sichtbares Log-Fenster GANZ UNTEN ───
        # Vorher lag das Log versteckt im 2. Tab ("Status / Log") — viele
        # User haben es dort nie gefunden ("es gibt überhaupt kein Log").
        # Jetzt: festes Panel am unteren Fensterrand, IMMER sichtbar (egal
        # wie weit man scrollt), mit Popout-Button zum Vergrößern. Wird VOR
        # dem Scroll-Frame mit side="bottom" gepackt, damit es unten klebt
        # und der Scroll-Bereich den Rest füllt.
        bottom_log = ctk.CTkFrame(self)
        bottom_log.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        log_hdr = ctk.CTkFrame(bottom_log, fg_color="transparent")
        log_hdr.pack(fill="x", padx=8, pady=(6, 0))
        self.log_title_lbl = ctk.CTkLabel(log_hdr, text="", anchor="w")
        self.log_title_lbl.pack(side="left", fill="x", expand=True)
        self._tr(self.log_title_lbl, "log.label")
        self.log_popout_btn = ctk.CTkButton(
            log_hdr, text="🔍 Vergrößern", width=130, height=26,
            font=ctk.CTkFont(size=11),
            fg_color="#0d9488", hover_color="#0f766e",
            command=self._open_log_popout,
        )
        self.log_popout_btn.pack(side="right", padx=(5, 0))
        self._tr(self.log_popout_btn, "log.popout")
        self.log_text = ctk.CTkTextbox(
            bottom_log, height=150,
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.log_text.pack(fill="x", expand=False, padx=8, pady=(2, 8))
        # Popout-Fenster-Referenzen (None solange geschlossen)
        self._log_popout_win: Optional[ctk.CTkToplevel] = None
        self._log_popout_text: Optional[ctk.CTkTextbox] = None

        # ─── Scrollable content (Author) ───
        # Everything below the header lives in a scrollable frame so the
        # full UI is reachable even on small windows or after adding new
        # sections (Variante 3, etc). Header + language/theme buttons
        # stay fixed at the top so they're always available.
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(side="top", fill="both", expand=True, padx=0, pady=0)

        # ─── URL input + Clipboard-Banner + History ───
        url_frame = ctk.CTkFrame(self.scroll)
        url_frame.pack(fill="x", padx=20, pady=5)
        self.url_lbl = ctk.CTkLabel(url_frame, text="", anchor="w")
        self.url_lbl.pack(fill="x", padx=10, pady=(8, 2))
        self._tr(self.url_lbl, "url.label")
        self.url_text = ctk.CTkTextbox(url_frame, height=70)
        self.url_text.pack(fill="x", padx=10, pady=(0, 4))
        self.url_text.insert("1.0", "")

        # Clipboard-Banner (initial unsichtbar)
        self.clip_frame = ctk.CTkFrame(url_frame, fg_color=("#fef9c3", "#3f3f00"))
        self.clip_lbl = ctk.CTkLabel(
            self.clip_frame, text="", font=ctk.CTkFont(size=11),
        )
        self.clip_lbl.pack(side="left", padx=8, pady=4)
        self.clip_btn_yes = ctk.CTkButton(
            self.clip_frame, text="", width=110, height=24,
            command=self._accept_clipboard,
        )
        self.clip_btn_yes.pack(side="right", padx=4, pady=4)
        self.clip_btn_no = ctk.CTkButton(
            self.clip_frame, text="", width=80, height=24,
            fg_color="gray40", hover_color="gray30",
            command=self._dismiss_clipboard,
        )
        self.clip_btn_no.pack(side="right", padx=4, pady=4)
        self._tr(self.clip_btn_yes, "url.clipboard.btn_yes")
        self._tr(self.clip_btn_no, "url.clipboard.btn_no")

        # History dropdown
        hist_row = ctk.CTkFrame(url_frame, fg_color="transparent")
        hist_row.pack(fill="x", padx=10, pady=(0, 8))
        self.history_lbl = ctk.CTkLabel(hist_row, text="", anchor="w",
                                          font=ctk.CTkFont(size=11),
                                          text_color=("gray40", "gray60"))
        self.history_lbl.pack(side="left")
        self._tr(self.history_lbl, "url.history.label")
        self.history_var = ctk.StringVar(value="")
        self._history_menu = ctk.CTkOptionMenu(
            hist_row,
            values=["—"] + (self.settings.get("url_history", []) or [])[:20],
            variable=self.history_var,
            command=self._on_history_pick,
            width=440,
        )
        self._history_menu.pack(side="left", padx=(8, 0))
        # Dedicated "clear history" button — wipes ONLY the URL history.
        self.history_clear_btn = ctk.CTkButton(
            hist_row, text="", width=140, height=28,
            fg_color="gray35", hover_color="gray25",
            command=self._clear_history,
        )
        self.history_clear_btn.pack(side="left", padx=(8, 0))
        self._tr(self.history_clear_btn, "url.history.clear")

        # ─── Quality + Format + Audio-Only ───
        opts1 = ctk.CTkFrame(self.scroll)
        opts1.pack(fill="x", padx=20, pady=5)
        # Hauptqualität (gilt für YouTube + alle Standard-Plattformen)
        self.quality_lbl = ctk.CTkLabel(opts1, text="Youtube Qualität:")
        self.quality_lbl.grid(row=0, column=0, padx=10, pady=8, sticky="w")
        # NOTE: kein _tr() mehr — Label ist platform-spezifisch
        self.quality_var = ctk.StringVar(value=self.settings["quality"])
        self.quality_menu = ctk.CTkOptionMenu(
            opts1, values=QUALITY_OPTIONS, variable=self.quality_var,
            width=200,
        )
        self.quality_menu.grid(row=0, column=1, padx=5, pady=8, sticky="w")
        self.format_lbl = ctk.CTkLabel(opts1, text="")
        self.format_lbl.grid(row=0, column=2, padx=(20, 10), pady=8, sticky="w")
        self._tr(self.format_lbl, "format.label")
        self.format_var = ctk.StringVar(value=self.settings["format"])
        self.format_menu = ctk.CTkOptionMenu(
            opts1, values=["mp4", "webm", "mkv", "original"],
            variable=self.format_var, width=120,
        )
        self.format_menu.grid(row=0, column=3, padx=5, pady=8, sticky="w")
        # Audio-Only Toggle
        self.audio_only_var = ctk.BooleanVar(
            value=self.settings.get("audio_only", False))
        self.audio_only_cb = ctk.CTkCheckBox(
            opts1, text="", variable=self.audio_only_var,
            command=self._on_audio_only_toggle,
        )
        self.audio_only_cb.grid(row=0, column=4, padx=(20, 10),
                                  pady=8, sticky="w")
        self._tr(self.audio_only_cb, "audio_only.label")

        # ─── TikTok-spezifische Qualität (IMMER sichtbar) ───
        # Designed Decision (2026-05-24, nach User-Feedback): Die Row ist
        # IMMER da, auch wenn keine TikTok-URL eingegeben ist. Sonst denkt
        # man die Spalte sei "raus genommen worden". Stattdessen passt sich
        # der Hint-Text an: bei TikTok-URL grün/aktiv, sonst grau/inaktiv.
        self.tiktok_quality_lbl = ctk.CTkLabel(
            opts1, text="TikTok Qualität:",
            text_color=("#ff0050", "#ff3370"),  # TikTok-Pink/Rot
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.tiktok_quality_var = ctk.StringVar(
            value=self.settings.get("tiktok_quality",
                                    TIKTOK_QUALITY_OPTIONS[0])
        )
        self.tiktok_quality_menu = ctk.CTkOptionMenu(
            opts1, values=TIKTOK_QUALITY_OPTIONS,
            variable=self.tiktok_quality_var,
            width=280,
            fg_color=("#ff0050", "#ff3370"),
            button_color=("#cc0040", "#cc0040"),
            button_hover_color=("#990030", "#990030"),
        )
        self.tiktok_quality_hint_lbl = ctk.CTkLabel(
            opts1, text="⚪ inaktiv (gib eine tiktok.com URL ein)",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray50"),
        )
        self.tiktok_quality_lbl.grid(row=1, column=0, padx=10, pady=(0, 8),
                                       sticky="w")
        self.tiktok_quality_menu.grid(row=1, column=1, columnspan=2,
                                         padx=5, pady=(0, 8), sticky="w")
        self.tiktok_quality_hint_lbl.grid(row=1, column=3, columnspan=2,
                                             padx=(10, 10), pady=(0, 8),
                                             sticky="w")
        # Initial-State: inaktiv (keine TikTok URL → grau)
        self._tiktok_row_visible = True
        self._tiktok_active = False
        try:
            self.tiktok_quality_menu.configure(state="disabled")
        except Exception:
            pass
        # URL-Textbox-Change → Hint + State updaten (aber Spalte bleibt!)
        try:
            self.url_text.bind("<KeyRelease>",
                               lambda e: self._refresh_tiktok_dropdown())
            self.url_text.bind("<<Paste>>",
                               lambda e: self.after(50,
                                   self._refresh_tiktok_dropdown))
        except Exception:
            pass
        # Initialer Check (falls History-URL bereits geladen wurde)
        self.after(300, self._refresh_tiktok_dropdown)

        # ─── Output dir ───
        out_frame = ctk.CTkFrame(self.scroll)
        out_frame.pack(fill="x", padx=20, pady=5)
        self.output_lbl = ctk.CTkLabel(out_frame, text="")
        self.output_lbl.grid(row=0, column=0, padx=10, pady=8, sticky="w")
        self._tr(self.output_lbl, "output.label")
        self.output_var = ctk.StringVar(value=self.settings["output_dir"])
        self.output_entry = ctk.CTkEntry(out_frame, textvariable=self.output_var)
        self.output_entry.grid(row=0, column=1, padx=5, pady=8, sticky="ew")
        self.output_browse_btn = ctk.CTkButton(
            out_frame, text="", width=110,
            command=self._pick_output_dir,
        )
        self.output_browse_btn.grid(row=0, column=2, padx=5, pady=8)
        self._tr(self.output_browse_btn, "output.browse")
        self.output_open_btn = ctk.CTkButton(
            out_frame, text="", width=80,
            command=self._open_output_dir,
        )
        self.output_open_btn.grid(row=0, column=3, padx=(5, 10), pady=8)
        self._tr(self.output_open_btn, "output.open")
        out_frame.grid_columnconfigure(1, weight=1)

        # ─── Cookies (kompakt, mit Test-Button) ───
        ck_frame = ctk.CTkFrame(self.scroll)
        ck_frame.pack(fill="x", padx=20, pady=5)
        self.cookies_title_lbl = ctk.CTkLabel(
            ck_frame, text="",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.cookies_title_lbl.grid(row=0, column=0, padx=10, pady=(8, 2),
                                       sticky="w", columnspan=5)
        self._tr(self.cookies_title_lbl, "cookies.title")
        # Variante 1 label — manuell exportierte cookies.txt-Datei
        self.cookies_v1_lbl = ctk.CTkLabel(
            ck_frame,
            text="📄 cookies.txt-Datei (Fallback, falls bereits exportiert):",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
        )
        self.cookies_v1_lbl.grid(row=1, column=0, padx=10, pady=(2, 2),
                                    sticky="w", columnspan=5)
        # Removed _tr() — text is now German-only and platform-specific
        self.cookies_var = ctk.StringVar(value=self.settings["cookies_file"])
        self.cookies_var.trace_add(
            "write", lambda *a: self._update_cookies_status())
        self.cookies_entry = ctk.CTkEntry(
            ck_frame, textvariable=self.cookies_var,
        )
        self.cookies_entry.grid(row=2, column=0, padx=(10, 5),
                                  pady=(0, 4), sticky="ew")
        self._tr(self.cookies_entry, "cookies.placeholder", "placeholder_text")
        self.cookies_browse_btn = ctk.CTkButton(
            ck_frame, text="", width=110,
            command=self._pick_cookies_file,
        )
        self.cookies_browse_btn.grid(row=2, column=1, padx=5, pady=(0, 4))
        self._tr(self.cookies_browse_btn, "cookies.browse")
        self.cookies_clear_btn = ctk.CTkButton(
            ck_frame, text="", width=80,
            command=lambda: self.cookies_var.set(""),
        )
        self.cookies_clear_btn.grid(row=2, column=2, padx=5, pady=(0, 4))
        self._tr(self.cookies_clear_btn, "cookies.clear")
        self.cookies_test_btn = ctk.CTkButton(
            ck_frame, text="", width=120,
            fg_color="#0d9488", hover_color="#0f766e",
            command=self._test_cookies,
        )
        self.cookies_test_btn.grid(row=2, column=3, padx=5, pady=(0, 4))
        self._tr(self.cookies_test_btn, "cookies.test")
        self.cookies_status_lbl = ctk.CTkLabel(
            ck_frame, text="", width=80, font=ctk.CTkFont(size=11),
        )
        self.cookies_status_lbl.grid(row=2, column=4, padx=(5, 10),
                                        pady=(0, 4), sticky="w")
        # NEU 2026-05-24: Variante 2 (browser-extraction) entfernt — funktionierte
        # nicht zuverlässig wegen Windows DPAPI-Verschlüsselung der Chrome-DB.
        # Zombie-Variable bleibt damit alter Code (_test_cookies usw.) nicht crasht.
        self.cookies_browser_var = ctk.StringVar(value="(keine)")

        # ─── Variante 2 (NEU): Integrierter Browser-Login — DRINGEND EMPFOHLEN ───
        # Spawnt Playwright Chromium in einem persistenten Profile-Dir,
        # User loggt sich ein, Cookies werden beim Schliessen automatisch
        # in cookies.txt exportiert UND aktualisiert sich automatisch bei
        # jedem Login. Das ist der zuverlässigste Weg — Cookies aus dem
        # eigenen Browser haben Session-Tokens die schnell ablaufen.
        self.cookies_v3_lbl = ctk.CTkLabel(
            ck_frame,
            text="⭐ EMPFOHLEN: Im integrierten Browser einloggen "
                 "— Cookies bleiben immer aktuell (persistente Session)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#16a34a", "#22c55e"),
        )
        self.cookies_v3_lbl.grid(row=3, column=0, padx=10, pady=(10, 2),
                                    sticky="w", columnspan=5)
        # Sub-hint below the green title
        self.cookies_v3_sub_lbl = ctk.CTkLabel(
            ck_frame,
            text="Klick → Browser öffnet sich → log dich ein → schließe das "
                 "Fenster. Cookies werden gespeichert + bei jedem Login "
                 "automatisch erneuert. (cookies.txt-Variante darüber ist "
                 "nur Fallback wenn man bereits einen Export hat.)",
            font=ctk.CTkFont(size=10),
            text_color=("gray40", "gray60"),
            wraplength=900, justify="left",
        )
        self.cookies_v3_sub_lbl.grid(row=4, column=0, padx=10, pady=(0, 4),
                                       sticky="w", columnspan=5)
        self.cookies_v3_site_var = ctk.StringVar(value="youtube")
        self.cookies_v3_site_menu = ctk.CTkOptionMenu(
            ck_frame, variable=self.cookies_v3_site_var,
            values=["youtube", "tiktok", "instagram", "twitter", "facebook"],
            width=120,
        )
        self.cookies_v3_site_menu.grid(row=5, column=0, padx=(10, 5),
                                          pady=(0, 8), sticky="w")
        self.cookies_v3_login_btn = ctk.CTkButton(
            ck_frame, text="🔓 Browser öffnen + einloggen",
            width=240, fg_color="#16a34a", hover_color="#15803d",
            command=self._open_login_browser,
        )
        self.cookies_v3_login_btn.grid(row=5, column=1, padx=5,
                                          pady=(0, 8), sticky="w",
                                          columnspan=2)
        self.cookies_v3_status_lbl = ctk.CTkLabel(
            ck_frame, text="", font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray50"),
        )
        self.cookies_v3_status_lbl.grid(row=5, column=3, padx=5,
                                           pady=(0, 8), sticky="w",
                                           columnspan=2)
        self._login_proc = None

        ck_frame.grid_columnconfigure(0, weight=1)

        # ─── Action buttons ───
        actions = ctk.CTkFrame(self.scroll, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(10, 5))
        self.dl_btn = ctk.CTkButton(
            actions, text="",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40, command=self._start_download,
        )
        self.dl_btn.pack(side="left", padx=(0, 5), fill="x", expand=True)
        self._tr(self.dl_btn, "btn.download")
        self.cancel_btn = ctk.CTkButton(
            actions, text="",
            height=40, fg_color="gray40", hover_color="gray30",
            command=self._cancel_download, state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=5)
        self._tr(self.cancel_btn, "btn.cancel")
        # NEU 2026-05-24: "Dateipfad anzeigen" → öffnet Output-Ordner im Explorer
        self.open_dir_btn = ctk.CTkButton(
            actions, text="",
            height=40, width=180,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#0d9488", hover_color="#0f766e",
            command=self._open_output_in_explorer,
        )
        self.open_dir_btn.pack(side="left", padx=5)
        self._tr(self.open_dir_btn, "output.open_explorer")

        # ─── Progress bar ───
        self.progress = ctk.CTkProgressBar(self.scroll)
        self.progress.pack(fill="x", padx=20, pady=(10, 5))
        self.progress.set(0)
        self.progress_label = ctk.CTkLabel(
            self.scroll, text="", font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
        )
        self.progress_label.pack(anchor="w", padx=20)
        self._tr(self.progress_label, "progress.ready")

        # ─── Tabview: Advanced + Status ───
        # Inside CTkScrollableFrame: drop `expand=True` (no "remaining
        # space" in a scrollable container) and keep a fixed height so
        # the tabs render with a sensible size.
        # NEU 2026-05-24: Vergrößert von 280 auf 460 weil User mehr Log-Platz will.
        self.tabview = ctk.CTkTabview(self.scroll, height=460)
        self.tabview.pack(fill="x", padx=20, pady=(8, 15))

        # Tab labels in current language - werden bei language-switch
        # NICHT live geupdated (CTkTabview limitation), aber neu bei Restart.
        tab_advanced = self.tabview.add(
            self._safe_tab_label("section_filename_notify", default="⚙ Advanced")
        )
        tab_status = self.tabview.add(
            self._safe_tab_label("status_log", default="📊 Status / Log")
        )

        self._build_tab_advanced(tab_advanced)
        self._build_tab_status(tab_status)

        # Cookies-Status initial setzen
        self._update_cookies_status()
        # Filename-Preview initial
        self._update_filename_preview()

        # First-run friendly hint in log
        self._log(_i18n.t("log.gui_version") + GUI_VERSION)
        if not _YTDLP_AVAILABLE:
            self._log(_i18n.t("msg.ytdlp_missing"))
        else:
            self._log(_i18n.t("log.ytdlp_version") + yt_dlp.version.__version__)
        if FFMPEG_PATH:
            self._log(_i18n.t("log.ffmpeg_version") + FFMPEG_PATH)
        if DENO_AVAILABLE:
            self._log(_i18n.t("log.deno_ok") + DENO_PATH)
        else:
            self._log(_i18n.t("log.deno_missing"))
        # Toast-Mechanism Status
        toast_ok, toast_mech = _toast.is_available()
        self._log(f"🔔 Toast-Mechanismus: {toast_mech}")
        self._log(_i18n.t("log.ready"))

    def _safe_tab_label(self, kind: str, default: str) -> str:
        """Tab-Labels sind nicht via i18n live-update-fähig, also
        nehmen wir kompakte Symbole + (optional) übersetzten Suffix."""
        if kind == "section_filename_notify":
            return f"⚙ {_i18n.t('header.theme') if False else 'Advanced'}"
        if kind == "status_log":
            return f"📊 {_i18n.t('url_status.title')[:18]}"
        return default

    def _build_tab_advanced(self, parent) -> None:
        """Tab mit Section-Trim, Filename-Template, Notifications, Extras."""
        # Section / Trim
        sec_frame = ctk.CTkFrame(parent)
        sec_frame.pack(fill="x", padx=10, pady=(10, 5))
        self.section_lbl = ctk.CTkLabel(
            sec_frame, text="", font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.section_lbl.grid(row=0, column=0, columnspan=4,
                                 padx=10, pady=(8, 2), sticky="w")
        self._tr(self.section_lbl, "trim.label")
        self.trim_from_lbl = ctk.CTkLabel(sec_frame, text="", width=50)
        self.trim_from_lbl.grid(row=1, column=0, padx=10, pady=4, sticky="w")
        self._tr(self.trim_from_lbl, "trim.from")
        self.trim_from_var = ctk.StringVar(
            value=self.settings.get("trim_from", ""))
        self.trim_from_entry = ctk.CTkEntry(
            sec_frame, textvariable=self.trim_from_var, width=120,
        )
        self.trim_from_entry.grid(row=1, column=1, padx=5, pady=4, sticky="w")
        self._tr(self.trim_from_entry, "trim.placeholder_from",
                 "placeholder_text")
        self.trim_to_lbl = ctk.CTkLabel(sec_frame, text="", width=50)
        self.trim_to_lbl.grid(row=1, column=2, padx=(20, 5), pady=4, sticky="w")
        self._tr(self.trim_to_lbl, "trim.to")
        self.trim_to_var = ctk.StringVar(
            value=self.settings.get("trim_to", ""))
        self.trim_to_entry = ctk.CTkEntry(
            sec_frame, textvariable=self.trim_to_var, width=120,
        )
        self.trim_to_entry.grid(row=1, column=3, padx=5, pady=4, sticky="w")
        self._tr(self.trim_to_entry, "trim.placeholder_to",
                 "placeholder_text")

        # ─── Datei-Schema ((Author) Simple-Mode UI) ───
        # Replaces the raw filename_template entry with friendly toggles.
        # The old textbox lives on under fn_profi_frame, hidden until the
        # user clicks "Profi-Modus".
        self._build_filename_section(parent)

        # Notifications

        # Notifications
        notify_frame = ctk.CTkFrame(parent)
        notify_frame.pack(fill="x", padx=10, pady=5)
        self.notify_title_lbl = ctk.CTkLabel(
            notify_frame, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.notify_title_lbl.grid(row=0, column=0, padx=10, pady=(8, 2),
                                      sticky="w", columnspan=3)
        self._tr(self.notify_title_lbl, "notify.title")
        self.toast_var = ctk.BooleanVar(
            value=self.settings.get("toast_enabled", True))
        self.toast_cb = ctk.CTkCheckBox(
            notify_frame, text="", variable=self.toast_var,
            command=self._on_toast_toggle,
        )
        self.toast_cb.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="w")
        self._tr(self.toast_cb, "notify.toast_label")
        self.toast_test_btn = ctk.CTkButton(
            notify_frame, text="", width=140,
            command=self._test_toast,
        )
        self.toast_test_btn.grid(row=1, column=1, padx=(20, 10),
                                    pady=(0, 8), sticky="w")
        self._tr(self.toast_test_btn, "notify.test_btn")

        # Extras: subs, thumbnail, rate-limit
        extras = ctk.CTkFrame(parent)
        extras.pack(fill="x", padx=10, pady=5)
        self.embed_subs_var = ctk.BooleanVar(value=self.settings["embed_subs"])
        self.embed_subs_cb = ctk.CTkCheckBox(
            extras, text="", variable=self.embed_subs_var,
        )
        self.embed_subs_cb.grid(row=0, column=0, padx=10, pady=8, sticky="w")
        self._tr(self.embed_subs_cb, "extras.subs")
        self.thumbnail_var = ctk.BooleanVar(
            value=self.settings["write_thumbnail"])
        self.thumbnail_cb = ctk.CTkCheckBox(
            extras, text="", variable=self.thumbnail_var,
        )
        self.thumbnail_cb.grid(row=0, column=1, padx=10, pady=8, sticky="w")
        self._tr(self.thumbnail_cb, "extras.thumbnail")
        self.rate_lbl = ctk.CTkLabel(extras, text="")
        self.rate_lbl.grid(row=0, column=2, padx=(20, 5), pady=8, sticky="w")
        self._tr(self.rate_lbl, "extras.rate_limit")
        self.rate_var = ctk.StringVar(
            value=str(self.settings["rate_limit_kbps"]))
        ctk.CTkEntry(extras, textvariable=self.rate_var, width=80).grid(
            row=0, column=3, padx=5, pady=8)

        # ─── Zurücksetzen / Portable-Reset (Author) ───
        reset_frame = ctk.CTkFrame(parent, border_width=2,
                                     border_color=("#fca5a5", "#7f1d1d"))
        reset_frame.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkLabel(
            reset_frame, text="🧹  Zurücksetzen / Portable-Reset",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(8, 2))
        ctk.CTkLabel(
            reset_frame,
            text="Löscht ALLE Settings, URL-Historie, Browser-Logins und "
                 "Cookies. Verwende das vor dem Weitergeben der portablen "
                 "Version, damit keine deiner Daten mitgehen.",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            wraplength=900, justify="left", anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkButton(
            reset_frame,
            text="🧹 Alle Settings + Logins löschen…",
            fg_color="#dc2626", hover_color="#b91c1c",
            height=34,
            command=self._open_reset_dialog,
        ).pack(anchor="w", padx=10, pady=(0, 10))

    def _open_reset_dialog(self) -> None:
        """Open the Portable-Reset confirmation dialog (same as launcher)."""
        try:
            from . import portable_reset as _pr
        except Exception as e:
            messagebox.showerror("Fehler",
                                  f"portable_reset nicht ladbar: {e}")
            return
        plan = _pr.collect_targets()
        if not plan.targets and not plan.warnings:
            messagebox.showinfo("Bereits sauber",
                                 "Es gibt nichts zu löschen — keine "
                                 "persönlichen Daten vorhanden.")
            return
        # Explicit extra warning since this is launched from the GUI
        # the user is actively in (not the central launcher) — make sure
        # they know it'll close the GUI's effects too.
        if not messagebox.askyesno(
            "⚠️ Warnung: ALLES löschen?",
            "ACHTUNG — dieser Reset löscht:\n\n"
            "  • Alle yt-dlp Downloader Settings (Output-Pfad, History, "
            "Cookies-Pfad, Filename-Schema usw.)\n"
            "  • Alle Browser-Logins (YouTube, TikTok, Instagram, …) im "
            "integrierten Browser\n"
            "  • Alle exportierten cookies.txt aus dem integrierten "
            "Browser\n"
            "  • TEE Launcher Settings + Python-Cache\n\n"
            "Heruntergeladene Videos und Source-Code bleiben erhalten.\n\n"
            "Wirklich fortfahren?"):
            return
        # Open the 2-stage dialog (with the type-LOESCHEN check)
        # Note: PortableResetDialog lives in launcher_gui — import lazily
        try:
            from .launcher_gui import PortableResetDialog
        except Exception:
            # Fallback: simple confirm + execute directly
            if messagebox.askyesno(
                "Letzte Bestätigung",
                "Wirklich JETZT alles löschen?\n(Dialog mit Vorschau "
                "konnte nicht geladen werden — fallback direkter Reset.)"):
                log_lines: list = []
                result = _pr.execute_reset(plan, log=log_lines.append)
                # Drop the in-memory URL history too — execute_reset only
                # deletes settings.json on disk, so without this the GUI
                # would re-save the old 20 URLs on the next change.
                self.settings["url_history"] = []
                self._refresh_history_menu()
                messagebox.showinfo(
                    "Fertig",
                    f"{result['deleted_dirs']} Ordner, "
                    f"{result['deleted_files']} Dateien, "
                    f"{result['reset_settings']} Settings gelöscht.")
            return
        PortableResetDialog(self, plan, _pr)
        # If the reset actually deleted settings.json, drop the in-memory
        # history as well so it isn't re-persisted on the next save.
        try:
            if not SETTINGS_FILE.exists():
                self.settings["url_history"] = []
                self._refresh_history_menu()
        except Exception:
            pass

    def _build_tab_status(self, parent) -> None:
        """Tab mit Per-URL-Status (volle Breite).

        Das Live-Log liegt seit 2026-05-30 NICHT mehr hier, sondern als
        festes, immer sichtbares Panel ganz unten im Hauptfenster (siehe
        _build_ui). Dieser Tab zeigt nur noch den Per-URL-Status.
        """
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        status_frame = ctk.CTkFrame(parent)
        status_frame.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.status_title_lbl = ctk.CTkLabel(
            status_frame, text="",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.status_title_lbl.pack(fill="x", padx=10, pady=(8, 2), anchor="w")
        self._tr(self.status_title_lbl, "url_status.title")
        self._url_status_panel = ctk.CTkScrollableFrame(status_frame)
        self._url_status_panel.pack(fill="both", expand=True,
                                     padx=10, pady=(0, 10))

    # ───── Action handlers ─────

    def _toggle_theme(self) -> None:
        new_theme = "light" if self.settings["theme"] == "dark" else "dark"
        self.settings["theme"] = new_theme
        ctk.set_appearance_mode(new_theme)
        self.theme_btn.configure(text="🌙" if new_theme == "dark" else "☀️")
        save_settings(self.settings)

    # ── NEU v6 Helpers ──────────────────────────────

    def _on_audio_only_toggle(self) -> None:
        """Audio-only Toggle: deaktiviert Quality+Format Dropdown wenn AN."""
        on = self.audio_only_var.get()
        try:
            state = "disabled" if on else "normal"
            self.quality_menu.configure(state=state)
            self.format_menu.configure(state=state)
        except Exception:
            pass
        self.settings["audio_only"] = on
        save_settings(self.settings)

    # ── NEU 2026-05-24: TikTok-Dropdown Aktiv/Inaktiv (immer sichtbar) ──

    def _set_tiktok_active(self, active: bool) -> None:
        """Aktiviert oder deaktiviert die TikTok-Qualität (Row bleibt sichtbar).

        Aktiv = bei TikTok-URL: pink-Dropdown bedienbar, grüner Hint.
        Inaktiv = sonst: Dropdown grau & disabled, grauer Hint.
        """
        try:
            if active:
                self.tiktok_quality_menu.configure(state="normal")
                self.tiktok_quality_hint_lbl.configure(
                    text="✅ aktiv (TikTok-URL erkannt)",
                    text_color=("#16a34a", "#22c55e"),
                )
            else:
                self.tiktok_quality_menu.configure(state="disabled")
                self.tiktok_quality_hint_lbl.configure(
                    text="⚪ inaktiv (gib eine tiktok.com URL ein)",
                    text_color=("gray50", "gray50"),
                )
            self._tiktok_active = active
        except Exception:
            pass

    def _refresh_tiktok_dropdown(self) -> None:
        """Liest die URL-Textbox und aktiviert/deaktiviert das TikTok-Dropdown.
        Die Row bleibt IMMER sichtbar — nur der Status ändert sich."""
        try:
            text = self.url_text.get("1.0", "end").strip()
        except Exception:
            return
        if not text:
            if self._tiktok_active:
                self._set_tiktok_active(False)
            return
        # Tokenize wie _start_download — Newlines/Spaces/Commas trennen URLs
        urls = re.split(r"[\s,]+", text)
        is_tiktok = any(
            detect_platform_pretty(u) == "TikTok"
            for u in urls if u.startswith(("http://", "https://"))
        )
        if is_tiktok and not self._tiktok_active:
            self._set_tiktok_active(True)
        elif not is_tiktok and self._tiktok_active:
            self._set_tiktok_active(False)

    def _on_toast_toggle(self) -> None:
        """Toast-Enabled persistieren + log."""
        on = self.toast_var.get()
        self.settings["toast_enabled"] = on
        save_settings(self.settings)
        if on:
            self._log("🔔 Windows-Toast aktiviert.")
        else:
            self._log(_i18n.t("log.toast_disabled"))

    def _test_toast(self) -> None:
        """Test-Toast feuern. Achtet auf toast_enabled-Setting:
        wenn AUS, gar nicht versuchen + im Log warnen."""
        if not self.toast_var.get():
            self._log(_i18n.t("log.toast_disabled"))
            return
        self._log(_i18n.t("log.toast_test"))
        ok = _toast.show_toast(
            _i18n.t("toast.test.title"),
            _i18n.t("toast.test.body"),
        )
        self._log(f"  -> Toast result: {ok}")

    def _send_toast(self, title_key: str, body_key: str, **kwargs) -> bool:
        """Wrapper: respektiert toast_enabled-Setting."""
        if not self.settings.get("toast_enabled", True):
            return False
        try:
            return _toast.show_toast(
                _i18n.t(title_key),
                _i18n.t(body_key, **kwargs),
            )
        except Exception:
            return False

    def _test_cookies(self) -> None:
        """Cookies testen indem yt-dlp.extract_info auf youtube.com lauft.
        Universal: testet auch ohne YouTube-spezifische URL."""
        cookies_path = self.cookies_var.get().strip()
        cookies_browser = self.cookies_browser_var.get().strip()
        if not cookies_path and (not cookies_browser
                                  or cookies_browser == "(keine)"):
            self._log(_i18n.t("cookies.test.no_cookies"))
            return
        self._log("🧪 Cookies werden getestet...")

        def worker():
            try:
                opts = {
                    "quiet": True, "no_warnings": True,
                    "skip_download": True,
                    "extract_flat": False,
                }
                if cookies_path and Path(cookies_path).exists():
                    opts["cookiefile"] = cookies_path
                elif cookies_browser and cookies_browser != "(keine)":
                    opts["cookiesfrombrowser"] = (cookies_browser.lower(),)
                # YouTube als Test-URL - bekanntes nicht-FSK-Video
                test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(test_url, download=False)
                if info and info.get("title"):
                    self._log_queue.put(("INFO",
                        _i18n.t("cookies.test.success") +
                        f" (extracted: {info['title'][:50]})"))
                else:
                    self._log_queue.put(("ERROR",
                        _i18n.t("cookies.test.fail")))
            except Exception as e:
                self._log_queue.put(("ERROR",
                    _i18n.t("cookies.test.fail") + f" ({e})"))

        threading.Thread(target=worker, daemon=True).start()

    def _update_filename_preview(self) -> None:
        """Live-Preview: zeigt wie ein Beispiel-File benannt wuerde."""
        try:
            tpl = self.filename_var.get().strip() or \
                  "%(uploader)s/%(title).100B [%(id)s].%(ext)s"
            example = {
                "uploader": "Example",
                "title": "Mein Beispiel-Video",
                "id": "AbCdEfGhIjK",
                "ext": "mp4",
                "upload_date": "20260509",
            }
            preview = tpl
            for k, v in example.items():
                preview = preview.replace(f"%({k})s", str(v))
                # Kürzungs-Syntax %(title).100B vereinfacht weg
                import re as _re
                preview = _re.sub(
                    r"%\(" + _re.escape(k) + r"\)\.\d+B",
                    str(v), preview)
            self.filename_preview_lbl.configure(
                text=f"{_i18n.t('filename.preview_label')}: {preview}"
            )
        except Exception:
            pass

    # ────────── Datei-Schema ((Author), Simple Mode) ──────────

    def _build_filename_section(self, parent) -> None:
        """Build the friendly filename-options section.

        Layout in two main groups: (1) Simple-mode controls (always built),
        (2) Profi-mode raw template entry (hidden until user toggles it).
        """
        # ─── NEU 2026-05-24: ID-Mode Toggle (großer Switch, GANZ OBEN) ───
        # Standard: ID-Mode AN → Files heißen z.B.
        #   TheErsysEnding_video_7642778099603574048.mp4
        # AUS → klassischer Titel-Modus mit Beschreibung als Name.
        id_mode_frame = ctk.CTkFrame(parent, fg_color=("#fef3c7", "#1f1f00"),
                                       corner_radius=6, border_width=2,
                                       border_color=("#f59e0b", "#fbbf24"))
        id_mode_frame.pack(fill="x", padx=10, pady=(5, 5))
        self.fn_use_id_var = ctk.BooleanVar(
            value=self.settings.get("fn_use_id_not_title", True))
        ctk.CTkCheckBox(
            id_mode_frame,
            text="🆔 ID-Mode: Dateiname = <Uploader>_<Typ>_<ID>.ext "
                 "(empfohlen — keine kaputten Filenames mit Emojis)",
            variable=self.fn_use_id_var,
            command=self._refresh_filename_preview,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#92400e", "#fbbf24"),
        ).pack(side="left", padx=10, pady=6)

        # ─── NEU 2026-05-24: Upload-Date als File-Date Toggle ───
        # Default OFF für normale Downloads (User will meist Download-Zeit).
        date_mode_frame = ctk.CTkFrame(parent,
                                         fg_color=("#dbeafe", "#0f1729"),
                                         corner_radius=6,
                                         border_width=1,
                                         border_color=("#3b82f6", "#60a5fa"))
        date_mode_frame.pack(fill="x", padx=10, pady=(0, 5))
        self.set_file_date_var = ctk.BooleanVar(
            value=self.settings.get("set_upload_date_as_file_date", False))
        ctk.CTkCheckBox(
            date_mode_frame,
            text="📅 Upload-Datum als File-Datum setzen "
                 "(optional — meist nicht nötig bei einzelnen Downloads)",
            variable=self.set_file_date_var,
            font=ctk.CTkFont(size=11),
            text_color=("#1e40af", "#60a5fa"),
        ).pack(side="left", padx=10, pady=6)

        fn_frame = ctk.CTkFrame(parent)
        fn_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkLabel(
            fn_frame, text="📂 Datei-Schema (Detail-Einstellungen für Titel-Modus)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=10, pady=(8, 4), sticky="w",
                columnspan=4)

        # Row 1: Folder structure
        ctk.CTkLabel(fn_frame, text="Ordner-Struktur:",
                     font=ctk.CTkFont(size=11)
                     ).grid(row=1, column=0, padx=(10, 5), pady=4, sticky="w")
        self.fn_folder_var = ctk.StringVar(
            value=self.settings.get("fn_folder_struct", "uploader"))
        folder_options = [
            "uploader",            # default
            "platform",
            "platform_uploader",
            "year_month",
            "uploader_year",
            "flat",
        ]
        self.fn_folder_menu = ctk.CTkOptionMenu(
            fn_frame, variable=self.fn_folder_var,
            values=folder_options, width=200,
            command=lambda _v: self._refresh_filename_preview())
        self.fn_folder_menu.grid(row=1, column=1, padx=5, pady=4,
                                    sticky="w", columnspan=3)

        # Row 2-3: Checkboxes (5 toggles)
        cb_frame = ctk.CTkFrame(fn_frame, fg_color="transparent")
        cb_frame.grid(row=2, column=0, columnspan=4, sticky="ew",
                        padx=10, pady=4)
        self.fn_date_var = ctk.BooleanVar(
            value=self.settings.get("fn_date_prefix", False))
        ctk.CTkCheckBox(
            cb_frame, text="Datum voranstellen",
            variable=self.fn_date_var,
            command=self._refresh_filename_preview,
        ).grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.fn_date_fmt_var = ctk.StringVar(
            value=self.settings.get("fn_date_format", "iso"))
        ctk.CTkOptionMenu(
            cb_frame, variable=self.fn_date_fmt_var,
            values=["iso", "compact", "dmy"], width=100,
            command=lambda _v: self._refresh_filename_preview(),
        ).grid(row=0, column=1, padx=5, pady=2, sticky="w")
        self.fn_time_var = ctk.BooleanVar(
            value=self.settings.get("fn_time_suffix", False))
        ctk.CTkCheckBox(
            cb_frame, text="Uhrzeit anhängen",
            variable=self.fn_time_var,
            command=self._refresh_filename_preview,
        ).grid(row=0, column=2, padx=5, pady=2, sticky="w")
        self.fn_res_var = ctk.BooleanVar(
            value=self.settings.get("fn_resolution_suffix", False))
        ctk.CTkCheckBox(
            cb_frame, text="Auflösung anhängen",
            variable=self.fn_res_var,
            command=self._refresh_filename_preview,
        ).grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.fn_platform_var = ctk.BooleanVar(
            value=self.settings.get("fn_platform_tag", False))
        ctk.CTkCheckBox(
            cb_frame, text="Plattform-Tag",
            variable=self.fn_platform_var,
            command=self._refresh_filename_preview,
        ).grid(row=1, column=1, padx=5, pady=2, sticky="w")
        self.fn_id_var = ctk.BooleanVar(
            value=self.settings.get("fn_video_id", True))
        ctk.CTkCheckBox(
            cb_frame, text="Video-ID (eindeutig)",
            variable=self.fn_id_var,
            command=self._refresh_filename_preview,
        ).grid(row=1, column=2, padx=5, pady=2, sticky="w")

        # Row 3: Text fields
        tx_frame = ctk.CTkFrame(fn_frame, fg_color="transparent")
        tx_frame.grid(row=3, column=0, columnspan=4, sticky="ew",
                        padx=10, pady=4)
        ctk.CTkLabel(tx_frame, text="Präfix:",
                     font=ctk.CTkFont(size=11),
                     ).grid(row=0, column=0, padx=(0, 5), pady=2, sticky="w")
        self.fn_prefix_var = ctk.StringVar(
            value=self.settings.get("fn_prefix", ""))
        self.fn_prefix_var.trace_add(
            "write", lambda *_a: self._refresh_filename_preview())
        ctk.CTkEntry(tx_frame, textvariable=self.fn_prefix_var,
                     placeholder_text="z.B. ARCHIV_", width=140,
                     ).grid(row=0, column=1, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(tx_frame, text="Suffix:",
                     font=ctk.CTkFont(size=11),
                     ).grid(row=0, column=2, padx=(15, 5), pady=2, sticky="w")
        self.fn_suffix_var = ctk.StringVar(
            value=self.settings.get("fn_suffix", ""))
        self.fn_suffix_var.trace_add(
            "write", lambda *_a: self._refresh_filename_preview())
        ctk.CTkEntry(tx_frame, textvariable=self.fn_suffix_var,
                     placeholder_text="z.B. _backup", width=140,
                     ).grid(row=0, column=3, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(tx_frame, text="Eigener Titel (nur bei 1 URL):",
                     font=ctk.CTkFont(size=11),
                     ).grid(row=1, column=0, padx=(0, 5), pady=2, sticky="w",
                                columnspan=2)
        self.fn_custom_title_var = ctk.StringVar(
            value=self.settings.get("fn_custom_title", ""))
        self.fn_custom_title_var.trace_add(
            "write", lambda *_a: self._refresh_filename_preview())
        ctk.CTkEntry(tx_frame, textvariable=self.fn_custom_title_var,
                     placeholder_text="leer = Original-Titel",
                     ).grid(row=1, column=2, padx=5, pady=2, sticky="ew",
                                columnspan=2)
        tx_frame.grid_columnconfigure(3, weight=1)

        # Row 4: Slider for max title length
        sl_frame = ctk.CTkFrame(fn_frame, fg_color="transparent")
        sl_frame.grid(row=4, column=0, columnspan=4, sticky="ew",
                        padx=10, pady=4)
        ctk.CTkLabel(sl_frame, text="Max. Titel-Länge:",
                     font=ctk.CTkFont(size=11),
                     ).grid(row=0, column=0, padx=(0, 5), pady=2, sticky="w")
        self.fn_max_chars_var = ctk.IntVar(
            value=int(self.settings.get("fn_max_title_chars", 100)))
        self.fn_max_chars_lbl = ctk.CTkLabel(
            sl_frame, text=f"{self.fn_max_chars_var.get()} B",
            font=ctk.CTkFont(size=11), width=50)
        self.fn_max_chars_lbl.grid(row=0, column=2, padx=(5, 0), pady=2,
                                      sticky="w")
        def _on_slider(val):
            self.fn_max_chars_var.set(int(val))
            self.fn_max_chars_lbl.configure(text=f"{int(val)} B")
            self._refresh_filename_preview()
        ctk.CTkSlider(
            sl_frame, from_=50, to=200, number_of_steps=30,
            command=_on_slider,
        ).grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        sl_frame.grid_columnconfigure(1, weight=1)

        # Row 5: Sanitize + Multi-Lang + Overwrite policy
        sx_frame = ctk.CTkFrame(fn_frame, fg_color="transparent")
        sx_frame.grid(row=5, column=0, columnspan=4, sticky="ew",
                        padx=10, pady=4)
        self.fn_sanitize_var = ctk.BooleanVar(
            value=self.settings.get("fn_sanitize", True))
        ctk.CTkCheckBox(
            sx_frame, text="Sonderzeichen ersetzen (Windows-safe)",
            variable=self.fn_sanitize_var,
            command=self._refresh_filename_preview,
        ).grid(row=0, column=0, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(sx_frame, text="Titel-Sprache:",
                     font=ctk.CTkFont(size=11),
                     ).grid(row=0, column=1, padx=(20, 5), pady=2, sticky="w")
        self.fn_prefer_lang_var = ctk.StringVar(
            value=self.settings.get("prefer_lang", "original"))
        ctk.CTkOptionMenu(
            sx_frame, variable=self.fn_prefer_lang_var,
            values=["original", "en", "de"], width=110,
            command=lambda _v: self._refresh_filename_preview(),
        ).grid(row=0, column=2, padx=5, pady=2, sticky="w")
        ctk.CTkLabel(sx_frame, text="Bei vorhandenen Dateien:",
                     font=ctk.CTkFont(size=11),
                     ).grid(row=1, column=0, padx=5, pady=(8, 2), sticky="w")
        self.fn_overwrite_var = ctk.StringVar(
            value=self.settings.get("overwrite_policy", "skip"))
        for i, (val, label) in enumerate([
            ("skip", "Überspringen"),
            ("overwrite", "Überschreiben"),
            ("number", "Nummer anhängen"),
        ]):
            ctk.CTkRadioButton(
                sx_frame, text=label, variable=self.fn_overwrite_var,
                value=val,
            ).grid(row=1, column=1 + i, padx=5, pady=(8, 2), sticky="w")

        # Row 6: Live preview (2 examples)
        self.fn_preview1_lbl = ctk.CTkLabel(
            fn_frame, text="", anchor="w",
            font=ctk.CTkFont(size=10, family="Consolas"),
            text_color=("gray40", "gray60"),
        )
        self.fn_preview1_lbl.grid(row=6, column=0, columnspan=4,
                                     padx=10, pady=(8, 1), sticky="ew")
        self.fn_preview2_lbl = ctk.CTkLabel(
            fn_frame, text="", anchor="w",
            font=ctk.CTkFont(size=10, family="Consolas"),
            text_color=("gray40", "gray60"),
        )
        self.fn_preview2_lbl.grid(row=7, column=0, columnspan=4,
                                     padx=10, pady=(1, 8), sticky="ew")

        # Row 8: Profi-mode switch + raw template (hidden initially)
        pr_frame = ctk.CTkFrame(fn_frame, fg_color="transparent")
        pr_frame.grid(row=8, column=0, columnspan=4, sticky="ew",
                        padx=10, pady=(4, 8))
        self.fn_mode_var = ctk.StringVar(
            value=self.settings.get("filename_mode", "simple"))
        ctk.CTkSwitch(
            pr_frame, text="🔧 Profi-Modus (eigenes Template)",
            variable=self.fn_mode_var, onvalue="profi", offvalue="simple",
            command=self._toggle_filename_mode,
        ).grid(row=0, column=0, padx=5, pady=2, sticky="w")

        self.fn_profi_frame = ctk.CTkFrame(pr_frame, fg_color="transparent")
        self.filename_var = ctk.StringVar(
            value=self.settings.get("filename_template",
                                     "%(uploader)s/%(title).100B [%(id)s].%(ext)s"))
        self.filename_var.trace_add(
            "write", lambda *_a: self._refresh_filename_preview())
        self.filename_entry = ctk.CTkEntry(
            self.fn_profi_frame, textvariable=self.filename_var,
            width=600)
        self.filename_entry.pack(fill="x", padx=5, pady=4)
        # Keep the old preview label for the legacy code path; not packed
        # in simple-mode so it just stays invisible.
        self.filename_preview_lbl = ctk.CTkLabel(
            self.fn_profi_frame, text="",
            font=ctk.CTkFont(size=10, family="Consolas"),
            text_color=("gray40", "gray60"),
        )
        pr_frame.grid_columnconfigure(0, weight=1)
        # Apply initial mode (shows/hides profi frame)
        self._toggle_filename_mode()
        # Initial preview
        self._refresh_filename_preview()

    def _toggle_filename_mode(self) -> None:
        mode = self.fn_mode_var.get()
        if mode == "profi":
            self.fn_profi_frame.grid(row=1, column=0, sticky="ew",
                                         padx=5, pady=(4, 0))
        else:
            self.fn_profi_frame.grid_forget()
        self._refresh_filename_preview()

    def _collect_fn_opts(self) -> dict:
        """Snapshot current Simple-mode UI state as the options dict."""
        return {
            "fn_folder_struct":    self.fn_folder_var.get(),
            "fn_date_prefix":      self.fn_date_var.get(),
            "fn_date_format":      self.fn_date_fmt_var.get(),
            "fn_time_suffix":      self.fn_time_var.get(),
            "fn_resolution_suffix": self.fn_res_var.get(),
            "fn_platform_tag":     self.fn_platform_var.get(),
            "fn_video_id":         self.fn_id_var.get(),
            "fn_prefix":           self.fn_prefix_var.get(),
            "fn_suffix":           self.fn_suffix_var.get(),
            "fn_custom_title":     self.fn_custom_title_var.get(),
            "fn_max_title_chars":  self.fn_max_chars_var.get(),
            "fn_sanitize":         self.fn_sanitize_var.get(),
            # NEU 2026-05-24: ID-Mode Toggle
            "fn_use_id_not_title": self.fn_use_id_var.get(),
        }

    def _refresh_filename_preview(self) -> None:
        """Render two preview examples (short title + long title)."""
        try:
            if self.fn_mode_var.get() == "profi":
                tpl = self.filename_var.get().strip() or \
                      "%(uploader)s/%(title).100B [%(id)s].%(ext)s"
            else:
                tpl = build_filename_template(self._collect_fn_opts(),
                                              num_urls=1)
            short = {
                "uploader": "TheErsysEnding", "extractor": "youtube",
                "extractor_key": "Youtube",
                "title": "Mein bestes Gaming-Video", "id": "aBcd1234XyZ",
                "ext": "mp4", "upload_date": "20091025",
                "timestamp": 1256472384, "height": 2160,
            }
            long_s = dict(short,
                title="Ein extrem langer Video-Titel mit vielen Worten "
                      "der typischerweise das Windows-Pfadlimit sprengt",
                uploader="TheErsysEnding", height=1080)
            p1 = render_template_preview(tpl, short)
            p2 = render_template_preview(tpl, long_s)
            self.fn_preview1_lbl.configure(text=f"  → {p1}")
            self.fn_preview2_lbl.configure(text=f"  → {p2}")
        except Exception as e:
            try:
                self.fn_preview1_lbl.configure(text=f"(preview error: {e})")
            except Exception:
                pass

    def _on_history_pick(self, choice: str) -> None:
        """User hat URL aus History gewaehlt -> in URL-Textbox einfuegen."""
        if not choice or choice == "—":
            return
        # Ans Ende der URL-Textbox haengen
        existing = self.url_text.get("1.0", "end").strip()
        new_text = f"{existing}\n{choice}".strip() if existing else choice
        self.url_text.delete("1.0", "end")
        self.url_text.insert("1.0", new_text)
        # Reset dropdown
        self.history_var.set("—")

    def _add_to_history(self, urls: list) -> None:
        """Adds URLs to history (max 20, dedup, latest first)."""
        hist = list(self.settings.get("url_history", []) or [])
        for u in urls:
            if u in hist:
                hist.remove(u)
            hist.insert(0, u)
        hist = hist[:20]
        self.settings["url_history"] = hist
        save_settings(self.settings)
        try:
            self._history_menu.configure(values=["—"] + hist)
        except Exception:
            pass

    def _refresh_history_menu(self) -> None:
        """Rebuild the history dropdown from the current settings."""
        hist = list(self.settings.get("url_history", []) or [])[:20]
        try:
            self._history_menu.configure(values=["—"] + hist)
        except Exception:
            pass
        try:
            self.history_var.set("—")
        except Exception:
            pass

    def _clear_history(self) -> None:
        """Dedicated button: clear ONLY the URL history (Verlauf).

        Wipes the in-memory list, persists the empty list to settings.json
        and refreshes the dropdown so nothing gets re-saved on next change.
        """
        hist = list(self.settings.get("url_history", []) or [])
        if not hist:
            try:
                messagebox.showinfo(_i18n.t("url.history.clear"),
                                    _i18n.t("history.clear.empty"))
            except Exception:
                pass
            return
        if not messagebox.askyesno(
                _i18n.t("url.history.clear"),
                _i18n.t("history.clear.confirm", n=len(hist))):
            return
        n = len(hist)
        self.settings["url_history"] = []
        save_settings(self.settings)
        self._refresh_history_menu()
        try:
            self._log(_i18n.t("history.clear.done", n=n))
        except Exception:
            pass

    def _poll_clipboard(self) -> None:
        """Pruefe ob Clipboard URL enthaelt + Banner zeigen."""
        try:
            content = self.clipboard_get().strip() if self else ""
        except Exception:
            content = ""
        # URL-Detection: einfach + lazy
        is_url = (content.startswith("http://") or
                  content.startswith("https://")) and len(content) < 500
        # Nur YT/IG/TT URLs anbieten
        is_relevant = is_url and any(d in content.lower() for d in (
            "youtube.com/", "youtu.be/", "tiktok.com/",
            "instagram.com/", "twitter.com/", "x.com/",
            "vimeo.com/", "facebook.com/",
        ))
        if (is_relevant
                and content != self._last_clipboard_offered
                and content not in self.url_text.get("1.0", "end")):
            self._show_clipboard_banner(content)
        self.after(2000, self._poll_clipboard)

    def _show_clipboard_banner(self, url: str) -> None:
        """Banner anzeigen: 'URL erkannt - übernehmen?'"""
        self._pending_clip_url = url
        text = f"📋 {_i18n.t('url.clipboard.detected')}\n   {url[:60]}"
        self.clip_lbl.configure(text=text)
        self.clip_frame.pack(fill="x", padx=10, pady=(0, 6))

    def _accept_clipboard(self) -> None:
        url = getattr(self, "_pending_clip_url", "")
        if url:
            existing = self.url_text.get("1.0", "end").strip()
            new_text = f"{existing}\n{url}".strip() if existing else url
            self.url_text.delete("1.0", "end")
            self.url_text.insert("1.0", new_text)
        self._dismiss_clipboard()

    def _dismiss_clipboard(self) -> None:
        self._last_clipboard_offered = getattr(self, "_pending_clip_url", "")
        self.clip_frame.pack_forget()

    def _add_url_status_row(self, url: str) -> None:
        """Fuegt eine Status-Zeile hinzu fuer eine URL/Item."""
        if url in self._url_status_rows:
            return
        if not self._url_status_panel:
            return
        try:
            row = ctk.CTkLabel(
                self._url_status_panel,
                text=f"⚪ {_i18n.t('url_status.queued')}: {url[:80]}",
                anchor="w", font=ctk.CTkFont(size=11),
            )
            row.pack(fill="x", padx=2, pady=2, anchor="w")
            self._url_status_rows[url] = row
        except Exception:
            pass

    def _set_url_status(self, url: str, status: str) -> None:
        """Status-Update fuer eine URL.
        status: 'queued' | 'downloading' | 'done' | 'failed' | 'skipped'."""
        icon_map = {
            "queued": "⚪", "downloading": "⬇", "done": "✅",
            "failed": "❌", "skipped": "⏭",
        }
        row = self._url_status_rows.get(url)
        if row is None:
            return
        try:
            row.configure(
                text=f"{icon_map.get(status, '?')} "
                     f"{_i18n.t(f'url_status.{status}')}: {url[:80]}"
            )
        except Exception:
            pass

    def _clear_url_status(self) -> None:
        """Leert das Per-URL Status-Panel (vor neuem Download-Run)."""
        for row in list(self._url_status_rows.values()):
            try:
                row.destroy()
            except Exception:
                pass
        self._url_status_rows.clear()

    def _pick_output_dir(self) -> None:
        d = filedialog.askdirectory(
            title="Speicher-Ordner wählen",
            initialdir=self.output_var.get() or str(Path.home()),
        )
        if d:
            self.output_var.set(d)

    def _open_output_dir(self) -> None:
        p = self.output_var.get()
        if p and Path(p).exists():
            os.startfile(p)
        else:
            messagebox.showinfo("Info", f"Ordner existiert noch nicht:\n{p}")

    def _pick_cookies_file(self) -> None:
        f = filedialog.askopenfilename(
            title="cookies.txt wählen",
            filetypes=[("Cookie files", "*.txt"), ("All files", "*.*")],
        )
        if f:
            self.cookies_var.set(f)

    # ─── Variante 3: integrierter Browser-Login (Author) ───
    SITE_URLS = {
        "youtube":   "https://www.youtube.com",
        "tiktok":    "https://www.tiktok.com/login",
        "instagram": "https://www.instagram.com/accounts/login/",
        "twitter":   "https://x.com/login",
        "facebook":  "https://www.facebook.com/login",
    }

    def _open_login_browser(self) -> None:
        """Spawn the cookie_browser subprocess + poll for the new cookies.txt."""
        if self._login_proc is not None and self._login_proc.poll() is None:
            # Could be a real running browser OR a zombie subprocess that
            # didn't detect Chromium dying. Detect zombies by checking if
            # any chrome.exe child belongs to it; if not, kill + restart.
            if self._is_login_zombie(self._login_proc):
                try:
                    self._login_proc.kill()
                except Exception:
                    pass
                self._login_proc = None
                self.cookies_v3_status_lbl.configure(
                    text="(toten Subprozess beendet, starte neu …)",
                    text_color=("gray50", "gray50"))
            else:
                if not messagebox.askyesno(
                    "Browser laeuft bereits",
                    "Es ist schon ein Browser-Fenster offen. "
                    "Soll der laufende Browser beendet und ein neuer "
                    "gestartet werden?"):
                    return
                try:
                    self._login_proc.kill()
                except Exception:
                    pass
                self._login_proc = None

        site = self.cookies_v3_site_var.get().strip().lower() or "youtube"
        url = self.SITE_URLS.get(site, f"https://{site}.com")

        # Output path: <ROOT>/data/cookies/<site>.txt
        root = Path(__file__).resolve().parent.parent
        out_dir = root / "data" / "cookies"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{site}.txt"

        venv_python = root / "venv" / "Scripts" / "python.exe"
        py = str(venv_python) if venv_python.exists() else sys.executable

        # NEU 2026-05-17: Chromium-Auto-Install. The recipient of the
        # portable zip won't have Playwright's Chromium binary in
        # %LOCALAPPDATA%/ms-playwright/ — on first click we must download
        # it (~150 MB). We do this synchronously with a progress window
        # so the user knows what's happening.
        if not self._chromium_installed():
            if not self._install_chromium_blocking(py):
                self.cookies_v3_status_lbl.configure(
                    text="Chromium-Download abgebrochen.",
                    text_color=("#b91c1c", "#ef4444"))
                return

        if getattr(sys, "frozen", False):
            # PyInstaller .exe: there is no python interpreter to run "-m".
            # Re-invoke our own frozen exe with the --cookie-browser
            # sub-command (handled in teebot_launcher.py).
            cmd = [sys.executable, "--cookie-browser",
                   url, "--out", str(out_path), "--site", site]
        else:
            # Package-relative so it works whether the package is called
            # "autonomous" (dev tree) or "app" (published zip).
            _pkg = __package__ or "autonomous"
            cmd = [py, "-X", "utf8", "-m", f"{_pkg}.cookie_browser",
                   url, "--out", str(out_path), "--site", site]
        try:
            self._login_proc = subprocess.Popen(
                cmd, cwd=str(root),
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                                if sys.platform == "win32" else 0),
            )
        except Exception as e:
            messagebox.showerror("Fehler",
                                  f"Konnte Browser nicht starten:\n{e}")
            return

        self._login_target_path = out_path
        self._login_site = site
        self._login_start_mtime = (out_path.stat().st_mtime
                                    if out_path.exists() else 0)
        self.cookies_v3_login_btn.configure(state="disabled",
                                              text="… Browser läuft …")
        self.cookies_v3_status_lbl.configure(
            text="Browser geöffnet — log dich ein und schließe das Fenster.",
            text_color=("#7c3aed", "#a78bfa"))
        self._poll_login_proc()

    def _chromium_installed(self) -> bool:
        """True if Playwright's Chromium binary is already downloaded.

        Playwright caches Chromium at:
          Windows:  %LOCALAPPDATA%/ms-playwright/chromium-<rev>/chrome-win/chrome.exe
          Linux:    ~/.cache/ms-playwright/chromium-<rev>/chrome-linux/chrome
        We do a fast filesystem check instead of asking Playwright (which
        would init the whole sync_api and is slow / not portable).
        """
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
        else:
            base = Path.home() / ".cache" / "ms-playwright"
        if not base.exists():
            return False
        for sub in base.glob("chromium-*"):
            for exe in ("chrome.exe", "chrome", "headless_shell.exe"):
                for cand in sub.rglob(exe):
                    if cand.is_file():
                        return True
        return False

    def _install_chromium_blocking(self, py_exe: str) -> bool:
        """Show a progress window + run `playwright install chromium`.

        Returns True if install succeeded, False if user cancelled / failed.
        Blocks the GUI (modal) — the user explicitly opted in via the
        Yes/No prompt, so freezing the launcher for ~30s is OK.
        """
        if not messagebox.askyesno(
            "Chromium fehlt",
            "Für den integrierten Browser-Login wird Chromium benötigt "
            "(~150 MB einmaliger Download).\n\n"
            "Jetzt herunterladen?"):
            return False

        # Modal progress window
        win = ctk.CTkToplevel(self)
        win.title("Chromium wird heruntergeladen …")
        win.geometry("520x180")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(
            win,
            text="⬇  Chromium wird heruntergeladen …",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(padx=20, pady=(20, 4))
        info_lbl = ctk.CTkLabel(
            win,
            text="Das dauert je nach Verbindung ~30 Sekunden — 2 Minuten.\n"
                 "Bitte das Fenster nicht schließen.",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"))
        info_lbl.pack(padx=20, pady=(0, 8))
        prog = ctk.CTkProgressBar(win, mode="indeterminate")
        prog.pack(fill="x", padx=20, pady=8)
        prog.start()
        status_lbl = ctk.CTkLabel(win, text="läuft …",
                                    font=ctk.CTkFont(size=11))
        status_lbl.pack(padx=20, pady=(4, 12))

        # Run the install in a worker thread so the progress bar animates
        result: dict = {"rc": None, "err": ""}

        def worker():
            try:
                if getattr(sys, "frozen", False):
                    # Frozen exe: run "playwright install chromium" via our
                    # own --pw-install sub-command (teebot_launcher.py).
                    _pw_cmd = [sys.executable, "--pw-install"]
                else:
                    _pw_cmd = [py_exe, "-X", "utf8", "-m", "playwright",
                               "install", "chromium"]
                proc = subprocess.run(
                    _pw_cmd,
                    capture_output=True, text=True, timeout=600,
                    creationflags=(subprocess.CREATE_NO_WINDOW
                                    if sys.platform == "win32" else 0),
                )
                result["rc"] = proc.returncode
                if proc.returncode != 0:
                    result["err"] = (proc.stderr or proc.stdout)[-400:]
            except Exception as e:
                result["rc"] = -1
                result["err"] = str(e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        # Pump the GUI while the worker runs
        while t.is_alive():
            try:
                win.update()
            except Exception:
                break
            t.join(timeout=0.1)
        try:
            prog.stop()
            win.destroy()
        except Exception:
            pass

        if result["rc"] != 0:
            messagebox.showerror(
                "Chromium-Download fehlgeschlagen",
                f"Exit-Code {result['rc']}\n\n{result['err'] or '(no output)'}\n\n"
                "Du kannst es manuell installieren mit:\n"
                "  venv\\Scripts\\python.exe -m playwright install chromium")
            return False
        return self._chromium_installed()

    def _is_login_zombie(self, proc) -> bool:
        """True if subprocess is alive but has no Chromium descendants.

        Symptom: cookie_browser hung in the post-close cleanup waiting on
        a Playwright event that never fires. The Chrome window is already
        gone but the Python parent is stuck. We detect this by walking
        the process tree.
        """
        if sys.platform != "win32":
            return False
        try:
            import psutil
            p = psutil.Process(proc.pid)
            # Collect entire descendant tree, look for any chrome.exe
            for child in p.children(recursive=True):
                try:
                    if "chrome" in child.name().lower():
                        return False
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            # No chrome descendants → Playwright is dead, parent zombie
            return True
        except Exception:
            return False

    def _poll_login_proc(self) -> None:
        """Tick every 1s: when subprocess exits, load the new cookies.txt."""
        proc = self._login_proc
        if proc is None:
            return
        rc = proc.poll()
        if rc is None:
            self.after(1000, self._poll_login_proc)
            return

        # Process exited
        self._login_proc = None
        self.cookies_v3_login_btn.configure(
            state="normal", text="🔓 Browser öffnen + einloggen")

        out = getattr(self, "_login_target_path", None)
        start_mtime = getattr(self, "_login_start_mtime", 0)
        if rc == 0 and out and out.exists() and out.stat().st_mtime > start_mtime:
            # New cookies written — wire them into Variante 1
            self.cookies_var.set(str(out))
            self.cookies_browser_var.set("(keine)")  # disable Variante 2
            self.cookies_v3_status_lbl.configure(
                text=f"✓ Cookies aus eingebettetem Browser ({self._login_site}) geladen",
                text_color=("#15803d", "#4ade80"))
            self._log(f"🌐 Cookies aus integriertem Browser geladen "
                       f"({self._login_site}) → {out}")
        elif rc == 0:
            self.cookies_v3_status_lbl.configure(
                text="Abgebrochen — keine neuen Cookies geschrieben.",
                text_color=("#b45309", "#fbbf24"))
        else:
            self.cookies_v3_status_lbl.configure(
                text=f"Fehler (exit {rc}) — siehe Console.",
                text_color=("#b91c1c", "#ef4444"))

    def _update_cookies_status(self) -> None:
        """Aktualisiert das Status-Label rechts neben dem cookies.txt-Pfad."""
        if not hasattr(self, "cookies_status_lbl"):
            return
        path = self.cookies_var.get().strip()
        if path:
            p = Path(path)
            if not p.exists():
                self.cookies_status_lbl.configure(
                    text=_i18n.t("cookies.status.missing"),
                    text_color=("#b91c1c", "#ef4444"))
                return
            try:
                head = p.read_text(encoding="utf-8", errors="ignore")[:200]
                if "netscape" in head.lower() or "# http" in head.lower():
                    self.cookies_status_lbl.configure(
                        text=_i18n.t("cookies.status.loaded"),
                        text_color=("#15803d", "#4ade80"))
                else:
                    self.cookies_status_lbl.configure(
                        text=_i18n.t("cookies.status.format_warn"),
                        text_color=("#b45309", "#fbbf24"))
            except Exception:
                self.cookies_status_lbl.configure(
                    text=_i18n.t("cookies.status.read_err"),
                    text_color=("#b45309", "#fbbf24"))
            return
        browser = self.cookies_browser_var.get().strip()
        if browser and browser != "(keine)":
            self.cookies_status_lbl.configure(
                text=f"🔍 {browser}",
                text_color=("#1d4ed8", "#60a5fa"))
        else:
            self.cookies_status_lbl.configure(
                text=_i18n.t("cookies.status.none"),
                text_color=("gray40", "gray60"))

    def _start_download(self) -> None:
        if self._download_thread and self._download_thread.is_alive():
            messagebox.showwarning("",
                                     _i18n.t("msg.already_running"))
            return

        urls_raw = self.url_text.get("1.0", "end").strip()
        if not urls_raw:
            messagebox.showwarning("", _i18n.t("msg.no_urls"))
            return
        urls = [u.strip() for u in re.split(r"[\s,]+", urls_raw) if u.strip()]
        if not urls:
            messagebox.showwarning("", _i18n.t("msg.no_urls_invalid"))
            return

        if not _YTDLP_AVAILABLE:
            messagebox.showerror("", _i18n.t("msg.ytdlp_missing"))
            return

        out_dir = self.output_var.get().strip()
        if not out_dir:
            messagebox.showwarning("", _i18n.t("msg.no_dir"))
            return
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        # Persist current settings (NEU v6: audio_only, trim, filename_template)
        self.settings.update({
            "quality": self.quality_var.get(),
            "format": self.format_var.get(),
            "output_dir": out_dir,
            "cookies_file": self.cookies_var.get(),
            "cookies_browser": self.cookies_browser_var.get(),
            "audio_only": self.audio_only_var.get(),
            "embed_subs": self.embed_subs_var.get(),
            "write_thumbnail": self.thumbnail_var.get(),
            "rate_limit_kbps": int(self.rate_var.get() or "0"),
            "trim_from": self.trim_from_var.get().strip(),
            "trim_to": self.trim_to_var.get().strip(),
            "filename_template": self.filename_var.get().strip() or
                                  "%(uploader)s/%(title).100B [%(id)s].%(ext)s",
            # NEU 2026-05-17: simple-mode UI state
            "filename_mode":       self.fn_mode_var.get(),
            "fn_folder_struct":    self.fn_folder_var.get(),
            "fn_date_prefix":      self.fn_date_var.get(),
            "fn_date_format":      self.fn_date_fmt_var.get(),
            "fn_time_suffix":      self.fn_time_var.get(),
            "fn_resolution_suffix": self.fn_res_var.get(),
            "fn_platform_tag":     self.fn_platform_var.get(),
            "fn_video_id":         self.fn_id_var.get(),
            "fn_prefix":           self.fn_prefix_var.get(),
            "fn_suffix":           self.fn_suffix_var.get(),
            "fn_custom_title":     self.fn_custom_title_var.get(),
            "fn_max_title_chars":  int(self.fn_max_chars_var.get()),
            "fn_sanitize":         self.fn_sanitize_var.get(),
            "overwrite_policy":    self.fn_overwrite_var.get(),
            "prefer_lang":         self.fn_prefer_lang_var.get(),
            # NEU 2026-05-24: TikTok-spezifische Qualität persistieren
            "tiktok_quality":      self.tiktok_quality_var.get(),
            # NEU 2026-05-24: ID-vs-Title Toggle
            "fn_use_id_not_title": self.fn_use_id_var.get(),
            "set_upload_date_as_file_date": self.set_file_date_var.get(),
        })
        save_settings(self.settings)

        # NEU v6: URLs zur History adden
        self._add_to_history(urls)
        # NEU v6: Per-URL Status-Rows aufbauen
        self._clear_url_status()
        for u in urls:
            self._add_url_status_row(u)

        # Lock UI
        self._stop_requested = False
        self.dl_btn.configure(state="disabled",
                                text=_i18n.t("btn.downloading"))
        self.cancel_btn.configure(state="normal")
        self.progress.set(0)
        self.progress_label.configure(text="Starte…")

        # Spawn worker
        self._download_thread = threading.Thread(
            target=self._download_worker,
            args=(urls, out_dir, dict(self.settings)),
            daemon=True,
        )
        self._download_thread.start()

    def _cancel_download(self) -> None:
        self._stop_requested = True
        self.progress_label.configure(text=_i18n.t("btn.cancel.requested"))
        self._log(_i18n.t("log.cancel_requested"))
        # Aktiv die laufenden Verbindungen abbrechen falls moeglich.
        # ydl.params['skip_download'] auf True setzen verhindert weitere
        # Downloads in Playlists.
        try:
            if self._current_ydl is not None:
                self._current_ydl.params["skip_download"] = True
        except Exception:
            pass

    # ── NEU 2026-05-24: Output-Ordner im Explorer öffnen ───────────────

    def _open_output_in_explorer(self) -> None:
        """Open the current output directory in Windows Explorer."""
        out = self.output_var.get().strip()
        if not out:
            messagebox.showinfo("", "Kein Output-Ordner gesetzt.")
            return
        p = Path(out)
        # Create on-the-fly so the button works even before first download
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Fehler",
                                  f"Output-Ordner konnte nicht angelegt werden:\n{e}")
            return
        try:
            if sys.platform == "win32":
                # explorer.exe takes a path arg directly
                subprocess.Popen(["explorer.exe", str(p)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            messagebox.showerror("Fehler",
                                  f"Explorer konnte nicht geöffnet werden:\n{e}")

    # ── NEU 2026-05-24: Channel-Downloader Modal ─────────────────────

    def _open_channel_downloader(self) -> None:
        """Open the bulk channel downloader dialog."""
        try:
            try:
                from . import channel_downloader_gui as _cdg
            except ImportError:
                import importlib.util as _ilu
                _here = Path(__file__).resolve().parent
                _spec = _ilu.spec_from_file_location(
                    "channel_downloader_gui",
                    _here / "channel_downloader_gui.py")
                _cdg = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_cdg)
            _cdg.ChannelDownloaderDialog(
                self,
                default_output_dir=self.output_var.get(),
                default_cookies_file=self.cookies_var.get(),
                use_id_filename=self.fn_use_id_var.get(),
            )
        except Exception as e:
            messagebox.showerror("Fehler",
                                  f"Channel-Downloader konnte nicht geöffnet "
                                  f"werden:\n{e}")

    # ── NEU 2026-05-24: TikTok HD via TTDownloader.com ────────────────

    def _try_tiktok_hd(self, url: str, tiktok_q: str, settings: dict,
                        out_dir: str, ydl) -> bool:
        """Versucht TikTok-HD über TTDownloader.com runterzuladen.

        Returns True wenn das File erfolgreich geschrieben wurde
        (yt-dlp wird dann übersprungen). False = caller fällt auf
        yt-dlp zurück (z.B. wenn TTDownloader down ist, oder die URL
        kein TikTok-Link ist, oder User "Auto"/"Only Sound" gewählt
        hat — letzteres kann yt-dlp direkt als bestaudio).

        Args:
            url:       die zu ladende URL
            tiktok_q:  Wert aus dem TikTok-Quality-Dropdown
            settings:  Settings-Dict (für filename template)
            out_dir:   Output-Verzeichnis
            ydl:       die yt-dlp-Instanz (nicht mehr benutzt — Metadaten
                       kommen jetzt cookie-frei via tiktok_hd.get_metadata;
                       Param bleibt für Signatur-Kompatibilität)
        """
        # Nur eingreifen wenn TikTok + User will HD oder SD-Watermark
        try:
            from . import tiktok_hd as _tk
        except ImportError:
            import importlib.util as _ilu
            try:
                _spec = _ilu.spec_from_file_location(
                    "tiktok_hd",
                    Path(__file__).resolve().parent / "tiktok_hd.py")
                _tk = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_tk)
            except Exception as e:
                self._log_queue.put(("INFO",
                    f"tiktok_hd Modul nicht ladbar: {e}"))
                return False

        if not _tk.is_tiktok_url(url):
            return False
        # Map dropdown choice → tiktok_hd 'prefer' arg
        prefer_map = {
            "No Watermark (HD)": "hd",
            "Watermark (SD)":    "wm",
        }
        prefer = prefer_map.get(tiktok_q)
        if prefer is None:
            # "Auto" oder "Only Sound" → yt-dlp normal weiterlaufen lassen
            return False

        # Filename-Metadaten holen — OHNE yt-dlp / TikTok-API.
        # FIX 2026-05-30 (Multi-Download-Bug): Früher riefen wir hier
        # ydl.extract_info(url) auf. Das trifft TikToks EIGENE API *mit den
        # Login-Cookies des Users*, und TikTok bot-blockt eine eingeloggte
        # Session nach 2-3 schnellen Requests → "1. Video geht, 2./3. Video
        # sofort Fehler". get_metadata() leitet uploader+id direkt aus der
        # URL ab (kein Netz, schlägt nie fehl) und reichert Titel/Datum via
        # tikwm an — komplett unabhängig von TikToks API und den Cookies.
        # Damit ist der HD-Pfad nicht mehr rate-limitierbar, egal wie viele
        # Videos hintereinander geladen werden.
        self._log_queue.put(("INFO",
            "🎵 TikTok HD via TTDownloader: hole Metadaten (ohne TikTok-API)…"))
        try:
            meta = _tk.get_metadata(
                url, log_cb=lambda m: self._log_queue.put(("INFO", m)))
        except Exception as e:
            self._log_queue.put(("INFO",
                f"tiktok_hd: get_metadata failed ({e}) — URL-Fallback"))
            meta = {}

        # Render the filename template via the same machinery as yt-dlp
        mode = settings.get("filename_mode", "simple")
        if mode == "profi":
            tpl = settings.get("filename_template", "") or \
                  "%(uploader)s/%(title).100B [%(id)s].%(ext)s"
        else:
            tpl = build_filename_template(settings, num_urls=1)
        # Pretty-platform substitution
        pretty = detect_platform_pretty(url)
        tpl = tpl.replace("%(extractor)s", pretty.replace("%", "%%"))
        tpl = tpl.replace("%(extractor_key)s", pretty.replace("%", "%%"))
        # Render template with the metadata dict (URL + tikwm, never yt-dlp)
        sample = {
            "uploader":   meta.get("uploader") or "TikTok",
            "title":      meta.get("title") or meta.get("id") or "video",
            "id":         meta.get("id") or "unknown",
            "ext":        "mp4",
            "upload_date": meta.get("upload_date") or "",
            "timestamp":  meta.get("timestamp") or 0,
            "height":     1920,
        }
        rendered_rel = render_template_preview(tpl, sample)
        out_path = Path(out_dir) / rendered_rel
        # Sanitize Windows-bad characters in path components
        clean_parts = []
        for part in out_path.parts:
            if ":" in part and len(part) <= 3:  # drive letter like "F:"
                clean_parts.append(part)
            else:
                clean_parts.append(re.sub(r'[<>:"|?*]', "_", part))
        out_path = Path(*clean_parts)

        # Overwrite-policy honor
        ow = settings.get("overwrite_policy", "skip")
        if out_path.exists() and ow == "skip":
            self._log_queue.put(("INFO",
                f"tiktok_hd: {out_path.name} existiert bereits — skip"))
            self._success_files.append(str(out_path))
            return True
        if ow == "number" and out_path.exists():
            base = out_path.with_suffix("")
            ext = out_path.suffix
            n = 1
            while out_path.exists():
                out_path = Path(f"{base} ({n}){ext}")
                n += 1

        # Progress callback wires into the existing progress bar
        def _progress(written: int, total: int) -> None:
            try:
                pct = (written / total) if total else 0
                mb_done = written / 1024 / 1024
                mb_total = total / 1024 / 1024
                self._log_queue.put(("PROGRESS",
                    (pct, f"TikTok-HD  {pct*100:.1f}%  "
                          f"{mb_done:.1f}/{mb_total:.1f} MB")))
            except Exception:
                pass

        def _log(msg: str) -> None:
            self._log_queue.put(("INFO", msg))

        ok = _tk.download(url, out_path, prefer=prefer,
                           progress_cb=_progress, log_cb=_log)
        if ok and out_path.exists() and out_path.stat().st_size > 0:
            self._success_files.append(str(out_path))
            self._log_queue.put(("INFO",
                f"✅ TikTok HD geschrieben: {out_path}"))
            return True
        # Fall-through: yt-dlp übernimmt
        self._log_queue.put(("INFO",
            "tiktok_hd: kein Erfolg — falle auf yt-dlp zurück"))
        return False

    def _download_worker(self, urls: list[str], out_dir: str,
                          settings: dict) -> None:
        """Run yt-dlp in a background thread, push log lines to queue.

        (Author) Erfolg wird ausschliesslich via _success_files
        getrackt (kommt vom progress_hook bei status='finished'). Damit
        zaehlt nur eine Datei die TATSAECHLICH geschrieben wurde, nicht
        ein durch ignoreerrors=True geschluckter Fehler.
        """
        height = QUALITY_HEIGHT_MAP.get(settings["quality"])
        container = settings["format"]
        audio_only = bool(settings.get("audio_only", False))
        # NEU v6: audio_only ueberschreibt format-selector mit bestaudio
        if audio_only:
            fmt = "bestaudio/best"
        else:
            fmt = format_selector(height, container)

        # NEU 2026-05-24: TikTok-spezifische Qualität — überschreibt fmt
        # WENN die erste URL TikTok ist UND der User nicht "Auto" gewählt
        # hat. Bei "Only Sound" wird audio_only erzwungen (für mp3-Konvert).
        tiktok_q = settings.get("tiktok_quality",
                                 TIKTOK_QUALITY_OPTIONS[0])
        is_tiktok_batch = (
            urls and detect_platform_pretty(urls[0]) == "TikTok"
        )
        tiktok_override_sort = False
        if is_tiktok_batch and tiktok_q != TIKTOK_QUALITY_OPTIONS[0]:
            tk_fmt = tiktok_format_selector(tiktok_q)
            if tk_fmt:
                fmt = tk_fmt
                # "Only Sound (MP3)" → MP3-Postprocessor aktivieren
                if tiktok_q == "Only Sound (MP3)":
                    audio_only = True
                # FIX 2026-05-24: TikTok's H264-Streams sind heruntertranskodiert
                # (~150 kbps bei 720p). Die HEVC-Originale haben Vollbitrate
                # (~2500 kbps bei 1080p). Wir müssen den globalen format_sort
                # überschreiben damit die Bitrate höher gewichtet wird als
                # die Codec-Präferenz.
                tiktok_override_sort = True
                self._log_queue.put(("INFO",
                    f"🎵 TikTok-Qualität: {tiktok_q} → format={tk_fmt}"))
        # NEU v6: Custom filename template
        # NEU 2026-05-17: simple-mode builds template from UI options; profi-
        # mode uses the raw template string.
        mode = settings.get("filename_mode", "simple")
        if mode == "profi":
            tpl = settings.get("filename_template", "").strip() or \
                  "%(uploader)s/%(title).100B [%(id)s].%(ext)s"
        else:
            tpl = build_filename_template(settings, num_urls=len(urls))

        # Pretty platform folder substitution.
        # yt-dlp's %(extractor)s is lowercase ("youtube") and
        # %(extractor_key)s is mixed-case ("Youtube"). Neither matches
        # what most people expect ("YouTube", "TikTok"). We pre-render
        # the platform placeholder with our own URL-based detection so
        # folders read naturally. Caveat: when downloading a batch with
        # mixed platforms, the FIRST URL's platform name is used for ALL.
        if urls:
            pretty = detect_platform_pretty(urls[0])
            # Escape '%' so yt-dlp doesn't try to interpret literal name
            pretty_escaped = pretty.replace("%", "%%")
            tpl = tpl.replace("%(extractor)s", pretty_escaped)
            tpl = tpl.replace("%(extractor_key)s", pretty_escaped)

        outtmpl = str(Path(out_dir) / tpl)

        # Reset success-tracking pro Download-Lauf
        self._success_files: list[str] = []
        self._age_restricted_seen = False
        self._bot_detect_seen = False
        self._js_missing_seen = False
        self._ffmpeg_missing_seen = False

        opts = {
            "outtmpl": outtmpl,
            "format": fmt,
            "restrictfilenames": False,
            "noplaylist": False,
            "ignoreerrors": True,  # don't abort batch on single failure
            "writesubtitles": settings["embed_subs"],
            "writeautomaticsub": settings["embed_subs"],
            "embedsubtitles": settings["embed_subs"],
            "writethumbnail": settings["write_thumbnail"],
            "quiet": True,
            "no_warnings": False,
            "logger": _GuiLogger(
                self._log_queue,
                on_age_restricted=self._mark_age_restricted,
                on_bot_detect=lambda: setattr(self, "_bot_detect_seen", True),
                on_js_missing=lambda: setattr(self, "_js_missing_seen", True),
                on_ffmpeg_missing=lambda: setattr(self, "_ffmpeg_missing_seen", True),
            ),
            "progress_hooks": [self._progress_hook],
            # (Author) post_hooks feuert NACH jedem fertigen Download.
            # Hier greift unser Cancel zwischen Playlist-Items.
            "post_hooks": [self._post_hook],
            # (Author) match_filter feuert VOR jeder Extraktion (auch
            # vor dem ersten Webpage-Fetch). Damit kann Cancel auch in der
            # Phase "Downloading webpage / player API JSON" greifen wo der
            # progress_hook noch nicht aktiv ist.
            "match_filter": self._match_filter,
            # Bei TikTok: NICHT h264 bevorzugen — TikTok-h264-Streams sind
            # heruntertranskodierte Versionen (158 kbps bei 720p!). HEVC-
            # Originale haben Vollbitrate (2500 kbps bei 1080p). Bitrate
            # gewinnt → 16× größere Datei = spürbar bessere Qualität.
            "format_sort": (TIKTOK_FORMAT_SORT
                            if tiktok_override_sort
                            else ["res", "fps", "vcodec:h264", "acodec:aac"]),
            # (Author) yt-dlp braucht zusaetzlich zur Deno-Runtime
            # die EJS-Challenge-Solver-Scripts (n-sig, signature). Diese werden
            # von github.com/yt-dlp/ejs gezogen + gecached. Ohne das gibt's
            # "Signature solving failed" auch wenn Deno installiert ist.
            "remote_components": {"ejs:github"},
            # (Author) Player-Client-Diversifikation - manche IPs
            # werden als Bot blockiert wenn yt-dlp nur default 'android_vr'
            # probiert. Mit dieser Liste probiert yt-dlp mehrere Clients
            # bis einer durchgeht. Reihenfolge = Erfolgs-Prio aus der Praxis.
            "extractor_args": {
                "youtube": {
                    "player_client": [
                        "mweb",          # Mobile Web - oft am wenigsten restriktiv
                        "web_safari",    # Safari-User-Agent
                        "web_creator",   # Creator-Studio (bypasst oft Bot-Check)
                        "android_vr",    # default fallback
                        "web",           # last resort
                    ],
                },
            },
        }
        # NEU 2026-05-17: Sonderzeichen-Filter (Windows-safe Dateinamen)
        if settings.get("fn_sanitize", True):
            opts["restrictfilenames"] = False
            # Sanitize via post-rename — restrictfilenames=True wandelt zu
            # viel um (Leerzeichen → _), wir wollen nur die Windows-Killer
            # Zeichen tauschen. yt-dlp macht das automatisch wenn der
            # Output-Pfad gegen WinAPI verstoesst.
            opts["windowsfilenames"] = True
        # NEU 2026-05-17: Overwrite-Policy (skip|overwrite|number)
        ow = settings.get("overwrite_policy", "skip")
        if ow == "skip":
            opts["overwrites"] = False
            opts["nooverwrites"] = True
        elif ow == "overwrite":
            opts["overwrites"] = True
            opts["nooverwrites"] = False
        elif ow == "number":
            # yt-dlp's default behaviour without explicit overwrite settings
            # adds a numbered suffix on conflict via outtmpl modification
            opts["overwrites"] = False
            opts["nooverwrites"] = False
        # NEU 2026-05-17: Multi-Language Titel — YouTube hat seit 2024
        # localized titles fuer manche Videos (manche grosse Kanaele).
        # extractor_args["youtube"]["lang"] zwingt yt-dlp einen bestimmten
        # locale-Code zu nutzen → info["title"] wird dann der lokalisierte.
        prefer_lang = settings.get("prefer_lang", "original")
        if prefer_lang in ("en", "de"):
            opts["extractor_args"]["youtube"]["lang"] = [prefer_lang]
        # JS-Runtime: Deno mit explizitem Pfad an yt-dlp uebergeben.
        if DENO_AVAILABLE and DENO_PATH:
            opts["js_runtimes"] = {"deno": {"path": DENO_PATH}}

        # NEU v6: Section/Trim — yt-dlp 'download_ranges'
        trim_from = settings.get("trim_from", "").strip()
        trim_to = settings.get("trim_to", "").strip()
        if trim_from or trim_to:
            try:
                from yt_dlp.utils import parse_duration
                tf = parse_duration(trim_from) if trim_from else 0
                tt = parse_duration(trim_to) if trim_to else None
                if tf is not None and (tt is None or tt > tf):
                    def _ranges_func(info_dict, ydl):
                        return [{"start_time": tf or 0,
                                 "end_time": tt if tt else info_dict.get("duration", 0)}]
                    opts["download_ranges"] = _ranges_func
                    opts["force_keyframes_at_cuts"] = True
                    self._log_queue.put(("INFO",
                        f"✂ Section-Trim: von {trim_from or '0:00'} bis "
                        f"{trim_to or 'Ende'}"))
            except Exception as e:
                self._log_queue.put(("INFO",
                    f"⚠ Trim-Parse-Fehler: {e} - ignoriert"))

        # Container / Format / Audio-Only postprocessing
        if audio_only:
            # Audio-only: bestaudio holen + zu mp3 konvertieren
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        elif container in ("mp4", "webm", "mkv"):
            opts["merge_output_format"] = container
            opts["postprocessors"] = [{
                "key": "FFmpegVideoConvertor",
                "preferedformat": container,
            }]
        if FFMPEG_PATH and Path(FFMPEG_PATH).exists():
            # Direkter EXE-Pfad - imageio-ffmpeg's binary heisst
            # 'ffmpeg-win-x86_64-v7.1.exe', nicht 'ffmpeg.exe'. yt-dlp
            # akzeptiert direkt den EXE-Pfad genauso wie das Verzeichnis.
            opts["ffmpeg_location"] = FFMPEG_PATH
        # Cookies-Source: cookies.txt-Datei ODER Browser (browser-extraction).
        # Priority: cookies_file (manuell exportiert) gewinnt vor browser.
        cookies = settings.get("cookies_file", "").strip()
        cookies_browser = settings.get("cookies_browser", "").strip()
        if cookies and Path(cookies).exists():
            opts["cookiefile"] = cookies
            self._log_queue.put(("INFO",
                f"🍪 Cookies geladen: {Path(cookies).name}"))
        elif cookies_browser and cookies_browser != "(keine)":
            # cookiesfrombrowser-Format: tuple (browser, profile, keyring, container)
            # 'profile=None' = default-profile
            opts["cookiesfrombrowser"] = (cookies_browser.lower(),)
            self._log_queue.put(("INFO",
                f"🍪 Cookies werden aus {cookies_browser}-Profil gezogen"))
        if settings["rate_limit_kbps"] > 0:
            opts["ratelimit"] = settings["rate_limit_kbps"] * 1024

        fail_count = 0
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                self._current_ydl = ydl
                for url in urls:
                    if self._stop_requested:
                        self._log_queue.put(("INFO", "Abbruch — Rest übersprungen."))
                        break
                    self._log_queue.put(("INFO", f"=== {url} ==="))
                    # NEU v6: URL-Status auf "downloading"
                    self._log_queue.put(("URL_STATUS", (url, "downloading")))
                    before_count = len(self._success_files)

                    # ── NEU 2026-05-24: TikTok HD via TTDownloader ──────
                    # yt-dlp kann TikTok's WEB-API nur bis ~540p/540kbps
                    # reichen. Echte 1080p @ 2.5 Mbps kommt nur über die
                    # Mobile-App-API — und TTDownloader.com proxy't das.
                    # Wir intercepten hier wenn:
                    #   - die URL TikTok ist
                    #   - User "No Watermark (HD)" oder "Watermark (SD)"
                    #     gewählt hat (NICHT bei "Only Sound" — da kann
                    #     yt-dlp's bestaudio direkt zum mp3)
                    tk_handled = self._try_tiktok_hd(
                        url, tiktok_q, settings, out_dir, ydl,
                    )
                    if tk_handled:
                        # Erfolgs-Tracking + nächste URL
                        new_files_check = len(self._success_files) - before_count
                        if new_files_check > 0:
                            self._log_queue.put(("URL_STATUS", (url, "done")))
                        continue

                    try:
                        # ydl.download() returns Anzahl Fehler (nicht erfolge)
                        ydl.download([url])
                    except yt_dlp.utils.MaxDownloadsReached:
                        self._log_queue.put(("INFO",
                            _i18n.t("log.cancelled_by_user")))
                        self._log_queue.put(("URL_STATUS", (url, "skipped")))
                        break
                    except Exception as e:
                        if self._stop_requested:
                            self._log_queue.put(("INFO",
                                _i18n.t("log.cancelled_by_user")))
                            self._log_queue.put(("URL_STATUS", (url, "skipped")))
                            break
                        self._log_queue.put(("ERROR", f"Fehler bei {url}: {e}"))
                        self._log_queue.put(("URL_STATUS", (url, "failed")))
                        fail_count += 1
                        continue
                    new_files = len(self._success_files) - before_count
                    # ── Auto-Retry bei Bot-Detection ohne Cookies ──
                    # (Author) Wenn yt-dlp Bot-Block bekommt UND
                    # User keine cookies konfiguriert hat, automatisch mit
                    # cookies-from-browser=chrome/firefox retry probieren.
                    has_cookies_setup = bool(
                        opts.get("cookiefile") or opts.get("cookiesfrombrowser")
                    )
                    cookies_loaded_but_blocked = False
                    if (new_files == 0 and self._bot_detect_seen
                            and not has_cookies_setup):
                        for browser in ("chrome", "firefox", "edge", "brave"):
                            self._log_queue.put(("INFO",
                                f"🔄 Auto-Retry mit Cookies aus {browser}..."))
                            self._bot_detect_seen = False
                            opts_retry = dict(opts)
                            opts_retry["cookiesfrombrowser"] = (browser,)
                            opts_retry["logger"] = opts["logger"]
                            opts_retry["progress_hooks"] = opts["progress_hooks"]
                            try:
                                with yt_dlp.YoutubeDL(opts_retry) as ydl_retry:
                                    ydl_retry.download([url])
                                if (len(self._success_files) - before_count) > 0:
                                    self._log_queue.put(("INFO",
                                        f"✅ Auto-Retry mit {browser}-Cookies "
                                        f"erfolgreich!"))
                                    break
                                # Cookies geladen, aber trotzdem bot-block?
                                if self._bot_detect_seen:
                                    cookies_loaded_but_blocked = True
                            except Exception as e:
                                msg = str(e).lower()
                                if "could not copy" in msg or "locked" in msg:
                                    self._log_queue.put(("INFO",
                                        f"({browser} DB gelockt - skip)"))
                                elif "dpapi" in msg or "decrypt" in msg:
                                    self._log_queue.put(("INFO",
                                        f"({browser} DPAPI-Fehler - "
                                        f"Windows-Verschluesselung blockt)"))
                                else:
                                    self._log_queue.put(("INFO",
                                        f"({browser} retry fail: {e})"))
                                continue
                        new_files = len(self._success_files) - before_count

                    if new_files > 0:
                        self._log_queue.put(("URL_STATUS", (url, "done")))
                    elif new_files == 0:
                        self._log_queue.put(("URL_STATUS", (url, "failed")))

                    if new_files == 0:
                        # Kein File geschrieben - = stiller Fehler durch ignoreerrors
                        fail_count += 1
                        if self._ffmpeg_missing_seen:
                            self._log_queue.put(("ERROR",
                                f"❌ {url} - ffmpeg fehlt fuer Section/Trim. "
                                f"Section-Trim braucht ffmpeg.exe im PATH "
                                f"oder runtime/-Folder. Loesung: .bat erneut "
                                f"starten ODER 'Section'-Felder leer lassen."))
                            self._ffmpeg_missing_seen = False
                        elif self._js_missing_seen:
                            self._log_queue.put(("ERROR",
                                f"❌ {url} - JavaScript-Runtime (Deno) fehlt. "
                                f"YouTube braucht Deno um die n-Challenge zu "
                                f"loesen. Loesung: .bat schliessen und neu "
                                f"starten - das laedt Deno einmalig (~35 MB) "
                                f"in den 'runtime/' Ordner. ALTERNATIV: Deno "
                                f"manuell installieren: 'irm "
                                f"https://deno.land/install.ps1 | iex' in "
                                f"PowerShell."))
                            self._js_missing_seen = False
                        elif cookies_loaded_but_blocked:
                            self._log_queue.put(("ERROR",
                                f"❌ {url} - Auto-Retry hat Cookies aus dem "
                                f"Browser geladen ABER YouTube blockt trotzdem. "
                                f"Heisst: dein Browser ist NICHT bei YouTube "
                                f"eingeloggt. Mach folgendes:\n"
                                f"  1. Browser auf -> youtube.com -> EINLOGGEN\n"
                                f"  2. Browser ZU machen\n"
                                f"  3. Download nochmal starten\n"
                                f"ODER: cookies.txt Variante:\n"
                                f"  1. Im eingeloggten Browser die Extension\n"
                                f"     'Get cookies.txt LOCALLY' installieren\n"
                                f"  2. Auf youtube.com -> Extension -> Export\n"
                                f"  3. Im GUI 'Cookies-Durchsuchen' -> diese .txt"))
                        elif self._bot_detect_seen:
                            self._log_queue.put(("ERROR",
                                f"❌ {url} - YouTube haelt dich fuer einen Bot. "
                                f"Auto-Retry hat keinen unverschluesselten "
                                f"Browser-Cookie-Store gefunden. Loesung: "
                                f"Browser zu, GUI neu starten -> Auto-Retry "
                                f"kann dann auf Cookie-DBs zugreifen. ODER: "
                                f"cookies.txt-Datei manuell exportieren ('Get "
                                f"cookies.txt LOCALLY' Extension) und im GUI "
                                f"unter Cookies-Durchsuchen laden."))
                            self._bot_detect_seen = False
                        elif self._age_restricted_seen:
                            self._log_queue.put(("ERROR",
                                f"❌ {url} ist altersbeschraenkt (FSK18). "
                                f"Loesung: cookies.txt eines eingeloggten "
                                f"Accounts unten waehlen ODER 'Cookies aus "
                                f"Browser' setzen."))
                            self._age_restricted_seen = False
                        else:
                            self._log_queue.put(("ERROR",
                                f"❌ {url} - keine Datei geschrieben "
                                f"(siehe Log oben)"))
                    else:
                        self._log_queue.put(("INFO",
                            f"✅ {new_files} Datei(en) gespeichert"))
        except Exception as e:
            self._log_queue.put(("ERROR", f"Unerwarteter Fehler: {e}"))
        finally:
            self._current_ydl = None
            ok_count = len(self._success_files)
            summary = (f"Fertig. OK: {ok_count} Datei(en) · "
                        f"Fehler: {fail_count} · "
                        f"URL-Total: {len(urls)}")
            self._log_queue.put(("DONE", summary))
            # NEU v6: Toast-Notification
            if ok_count > 0:
                self._log_queue.put(("TOAST_DONE",
                    {"n": ok_count, "folder": Path(out_dir).name}))
            elif fail_count > 0 and not self._stop_requested:
                self._log_queue.put(("TOAST_ERROR", {}))

    def _mark_age_restricted(self) -> None:
        """Wird vom Logger gerufen wenn er einen FSK/age-Fehler erkennt."""
        self._age_restricted_seen = True

    def _match_filter(self, info_dict, *, incomplete=False):
        """Wird VOR jeder Extraktion aufgerufen.

        (Author) Damit greift Cancel auch in der Phase
        'Downloading webpage / player API JSON' bevor der eigentliche
        Download startet. Bei Playlists: VOR jedem Item.

        Return None = Video wird heruntergeladen.
        Return non-empty string = Video wird ge-skippt (Reason).
        """
        if self._stop_requested:
            return "Abbruch durch Nutzer"
        return None

    def _post_hook(self, filepath: str) -> None:
        """Wird NACH jedem fertigen Datei-Download aufgerufen.

        (Author) Bei Playlists greift hier der Cancel zwischen den
        Items - sobald ein Video fertig ist, fliegen wir raus.
        """
        # NEU 2026-05-24: Wenn User es will, File-Datum auf Upload-Datum stempeln
        if self.settings.get("set_upload_date_as_file_date", False) and filepath:
            try:
                # Use channel_downloader's helper — it's already in autonomous/
                try:
                    from . import channel_downloader as _cd_mod
                except ImportError:
                    import importlib.util as _ilu
                    _spec = _ilu.spec_from_file_location(
                        "channel_downloader",
                        Path(__file__).resolve().parent / "channel_downloader.py")
                    _cd_mod = _ilu.module_from_spec(_spec)
                    _spec.loader.exec_module(_cd_mod)
                fp = Path(filepath)
                # Try to extract item_id from filename
                # New format: <Uploader>_<kind>_<id>.<ext>
                # Old format: <title> [<id>].<ext>
                stem = fp.stem
                m = re.search(r"\[([A-Za-z0-9_-]+)\]$", stem)
                if not m:
                    m = re.search(r"_([0-9]{15,})$", stem)
                item_id = m.group(1) if m else ""
                _cd_mod.set_file_date_from_id(fp, item_id, "")
            except Exception:
                pass  # never let date-stamp failure break the download

        if self._stop_requested:
            # DownloadCancelled gibt's in yt-dlp 2026 - nicht alle Versionen
            # haben es. Wir nehmen MaxDownloadsReached als breit-supported
            # Alternative die genauso aus der download-Loop rausspringt.
            try:
                raise yt_dlp.utils.MaxDownloadsReached()
            except AttributeError:
                raise yt_dlp.utils.DownloadError("Abbruch durch Nutzer")

    def _progress_hook(self, d: dict) -> None:
        """yt-dlp calls this with status updates."""
        if self._stop_requested:
            # Bei MaxDownloadsReached: yt-dlp bricht die ganze download-Loop ab
            # (statt nur das aktuelle Video). Bei DownloadError macht er weiter
            # mit dem naechsten Item (nicht was wir wollen).
            try:
                raise yt_dlp.utils.MaxDownloadsReached()
            except AttributeError:
                raise yt_dlp.utils.DownloadError("Abbruch durch Nutzer")
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total) if total else 0
            speed = d.get("speed") or 0
            speed_mb = speed / 1024 / 1024 if speed else 0
            fname = Path(d.get("filename", "")).name
            # NEU 2026-05-24: einmaliges Format-Info-Log pro Datei.
            # info_dict ist tief verschachtelt; format_id/width/height/vbr
            # liegen in d["info_dict"] beim ersten downloading-Event.
            if not hasattr(self, "_logged_format_files"):
                self._logged_format_files = set()
            if fname and fname not in self._logged_format_files:
                self._logged_format_files.add(fname)
                info = d.get("info_dict") or {}
                fmt_id = info.get("format_id", "?")
                w = info.get("width", "?")
                h = info.get("height", "?")
                vbr = info.get("vbr") or info.get("tbr") or 0
                vcodec = info.get("vcodec", "?")
                size_mb = (total / 1024 / 1024) if total else 0
                self._log_queue.put(("INFO",
                    f"📊 Format gewählt: id={fmt_id} · {w}×{h} · "
                    f"{vbr:.0f} kbps · codec={vcodec} · ~{size_mb:.1f} MB"))
            self._log_queue.put(("PROGRESS", (pct,
                                                f"{fname}  {pct*100:.1f}%  "
                                                f"{speed_mb:.2f} MB/s")))
        elif status == "finished":
            full_path = d.get("filename", "")
            fname = Path(full_path).name
            # Erfolg-tracking: tatsaechlich geschriebene Datei merken
            try:
                self._success_files.append(full_path)
            except AttributeError:
                self._success_files = [full_path]
            self._log_queue.put(("INFO", f"⬇  Heruntergeladen: {fname}"))

    def _poll_log_queue(self) -> None:
        """Drain log queue from worker thread → GUI (Tkinter is single-threaded)."""
        try:
            while True:
                kind, payload = self._log_queue.get_nowait()
                if kind == "PROGRESS":
                    pct, label = payload
                    self.progress.set(min(max(pct, 0), 1))
                    self.progress_label.configure(text=label)
                elif kind == "DONE":
                    self.progress.set(1.0)
                    self.progress_label.configure(text=payload)
                    self._log(payload)
                    self.dl_btn.configure(state="normal",
                                            text=_i18n.t("btn.download"))
                    self.cancel_btn.configure(state="disabled")
                elif kind == "URL_STATUS":
                    url, status = payload
                    self._set_url_status(url, status)
                elif kind == "TOAST_DONE":
                    self._send_toast(
                        "toast.title.done", "toast.body.done",
                        n=payload.get("n", 0),
                        folder=payload.get("folder", ""),
                    )
                elif kind == "TOAST_ERROR":
                    self._send_toast("toast.title.error", "toast.body.error")
                else:  # INFO / ERROR
                    self._log(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _log(self, msg: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {msg}\n"
        # Always write to inline log
        try:
            self.log_text.insert("end", line)
            self.log_text.see("end")
        except Exception:
            pass
        # NEU 2026-05-24: ALSO mirror to popout window if open
        if (self._log_popout_text is not None
                and self._log_popout_win is not None
                and self._log_popout_win.winfo_exists()):
            try:
                self._log_popout_text.insert("end", line)
                self._log_popout_text.see("end")
            except Exception:
                pass

    def _open_log_popout(self) -> None:
        """Open a separate independently-resizable window with a synced log.

        The popout is non-modal — user keeps the main window usable. Both
        the inline log AND the popout receive every new log line. Closing
        the popout simply detaches it; the inline log keeps running.
        """
        # If already open, just lift it
        if (self._log_popout_win is not None
                and self._log_popout_win.winfo_exists()):
            try:
                self._log_popout_win.lift()
                self._log_popout_win.focus_force()
            except Exception:
                pass
            return

        win = ctk.CTkToplevel(self)
        win.title("📋 TEE yt-dlp — Log (vergrößertes Fenster)")
        win.geometry("1100x650")
        win.minsize(700, 400)
        try:
            ico = (Path(__file__).resolve().parent.parent
                    / "tools" / "branding" / "teebot.ico")
            if ico.exists():
                win.after(200, lambda: win.iconbitmap(str(ico)))
        except Exception:
            pass

        # Header with close button hint
        hdr = ctk.CTkFrame(win, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(
            hdr, text="📋 Live-Log (synchronisiert mit Hauptfenster)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            hdr, text="🧹 Löschen", width=110, height=26,
            fg_color="gray40", hover_color="gray30",
            command=lambda: self._log_popout_text.delete("1.0", "end")
                                if self._log_popout_text else None,
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            hdr, text="📋 Kopieren", width=110, height=26,
            fg_color="#0d9488", hover_color="#0f766e",
            command=self._copy_log_to_clipboard,
        ).pack(side="right", padx=4)

        # The big log textbox
        popout_text = ctk.CTkTextbox(
            win, font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
        )
        popout_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        # Seed with whatever's in the inline log currently
        try:
            content = self.log_text.get("1.0", "end")
            popout_text.insert("end", content)
            popout_text.see("end")
        except Exception:
            pass

        # Store refs + cleanup on close
        self._log_popout_win = win
        self._log_popout_text = popout_text

        def _on_close():
            self._log_popout_win = None
            self._log_popout_text = None
            try:
                win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", _on_close)

    def _copy_log_to_clipboard(self) -> None:
        """Copy the log content to clipboard."""
        try:
            text = (self._log_popout_text or self.log_text).get("1.0", "end")
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    def _on_close(self) -> None:
        # Persist window size
        try:
            self.settings["window_size"] = self.geometry().split("+")[0]
            save_settings(self.settings)
        except Exception:
            pass
        if self._download_thread and self._download_thread.is_alive():
            if not messagebox.askyesno(
                "Download läuft",
                "Es läuft ein Download. Wirklich beenden?"
            ):
                return
            self._stop_requested = True
        self.destroy()


class _GuiLogger:
    """Adapter so yt-dlp's logger output ends up in our queue.

    Plus: erkennt verschiedene Failure-Patterns + ruft entsprechende
    Callbacks (age, bot-detect, js-runtime) damit der Worker klare
    Lösungs-Hints geben kann statt nur 'no file written'.
    """

    # yt-dlp / YouTube Fehlertexte die auf age-restriction hinweisen
    AGE_PATTERNS = (
        "sign in to confirm your age",
        "this video is age-restricted",
        "age-restricted",
        "age restricted",
        "confirm your age",
        "altersbeschr",
        "fsk",
        "this video may be inappropriate",
    )
    # Bot-Detection (YouTube fragt "are you not a bot?")
    BOT_PATTERNS = (
        "sign in to confirm you're not a bot",
        "sign in to confirm you re not a bot",
        "sign in to confirm you’re not a bot",
        "confirm you re not a bot",
        "confirm youre not a bot",
        "use --cookies-from-browser or --cookies",
    )
    # JS-Runtime fehlt -> nur HARTE Indikatoren (nicht n-challenge warnings,
    # die kommen auch wenn Deno laeuft + EJS-Solver gerade rate-limited).
    JS_PATTERNS = (
        "no supported javascript runtime could be found",
        "only images are available for download",
    )
    # ffmpeg fehlt fuer Trim/Section
    FFMPEG_PATTERNS = (
        "ffmpeg is not installed",
        "ffmpeg location is not specified",
    )

    def __init__(self, q: queue.Queue,
                 on_age_restricted=None,
                 on_bot_detect=None,
                 on_js_missing=None,
                 on_ffmpeg_missing=None):
        self.q = q
        self._on_age_restricted = on_age_restricted
        self._on_bot_detect = on_bot_detect
        self._on_js_missing = on_js_missing
        self._on_ffmpeg_missing = on_ffmpeg_missing

    def _check_patterns(self, msg: str) -> None:
        low = msg.lower()
        if self._on_age_restricted and any(p in low for p in self.AGE_PATTERNS):
            try: self._on_age_restricted()
            except Exception: pass
        if self._on_bot_detect and any(p in low for p in self.BOT_PATTERNS):
            try: self._on_bot_detect()
            except Exception: pass
        if self._on_js_missing and any(p in low for p in self.JS_PATTERNS):
            try: self._on_js_missing()
            except Exception: pass
        if self._on_ffmpeg_missing and any(p in low for p in self.FFMPEG_PATTERNS):
            try: self._on_ffmpeg_missing()
            except Exception: pass

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            return  # too noisy
        self.q.put(("INFO", msg))
    def info(self, msg: str) -> None:
        self.q.put(("INFO", msg))
    def warning(self, msg: str) -> None:
        self._check_patterns(msg)
        self.q.put(("INFO", f"⚠ {msg}"))
    def error(self, msg: str) -> None:
        self._check_patterns(msg)
        # User-Cancel ist kein Fehler - lokal als INFO loggen
        if "maximum number of downloads reached" in msg.lower():
            self.q.put(("INFO", "(cancel propagated)"))
            return
        self.q.put(("ERROR", msg))


def main() -> int:
    app = YtDlpGUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
