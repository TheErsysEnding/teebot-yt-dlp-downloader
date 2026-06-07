"""Channel / bulk-account downloader (Author).

Downloads an entire YouTube / TikTok / Instagram / Twitter channel into
properly-organized subfolders, with date-range and media-type filtering.

Why a separate module:
    The main yt_dlp_gui.py handles single-URL or multi-URL downloads
    via yt-dlp only. Channels need different backends per platform:

        TikTok  (videos)   → ttdownloader.com (HD via tiktok_hd module)
        TikTok  (photos)   → tikwm.com API   (carousel image URLs)
        TikTok  (channels) → yt-dlp for listing + per-item routing
        YouTube (channels) → yt-dlp directly (well-supported)
        Instagram          → gallery-dl (needs login cookies)
        Twitter            → gallery-dl (works without login for public)
        Facebook           → gallery-dl (needs login)

    Plus channel-specific concerns: pagination, date filtering,
    media-type splits (Video/Picture subfolders), soft caps with
    warnings. All of that lives here so the main GUI stays simple.

Folder structure produced:
    <output_dir>/
        <Platform>/                       (e.g. TikTok, YouTube, Instagram)
            <Username>/                   (e.g. TheErsysEnding)
                Video/
                    TheErsysEnding_video_<id>.mp4
                Picture/
                    TheErsysEnding_picture_<id>.jpg

Public API:
    enumerate_channel(url, max_items=0, date_from=None, date_to=None)
        → iterator yielding (media_type, item_url, metadata_dict)
    download_channel(url, out_dir, options, progress_cb, log_cb)
        → blocking call, returns DownloadStats
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

# Tikwm + tiktok_hd live alongside this module
try:
    from . import tiktok_hd as _tk
except ImportError:
    import importlib.util as _ilu
    _here = Path(__file__).resolve().parent
    _spec = _ilu.spec_from_file_location("tiktok_hd", _here / "tiktok_hd.py")
    _tk = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_tk)


# ───────────────── gallery-dl invocation base ─────────────────
def _gallery_dl_base() -> list[str]:
    """Base command to invoke gallery-dl.

    Under a PyInstaller .exe there is no python interpreter to run
    ``-m gallery_dl``; instead we re-invoke our own frozen exe with the
    ``--gallery-dl`` sub-command (handled in teebot_launcher.py). In the
    normal dev / venv case we shell out to ``python -m gallery_dl``.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--gallery-dl"]
    return [sys.executable, "-X", "utf8", "-m", "gallery_dl"]


# ───────────────── SSL context (zertifikats-verifiziert) ─────────

# Früher CERT_NONE wegen "corporate proxies" — das öffnete MITM Tür und Tor
# und ist unnötig (tikwm- und Bild-Hosts haben gültige Zertifikate).
_SSL = ssl.create_default_context()

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/131.0.0.0 Safari/537.36")


# ───────────────── Data classes ──────────────────────────────────────────

@dataclass
class ChannelOptions:
    """User-controlled options from the ChannelDownloaderDialog."""
    max_items: int = 0                  # 0 = unlimited
    date_from: Optional[_dt.date] = None
    date_to: Optional[_dt.date] = None
    media_type: str = "both"            # both | video | picture
    quality: str = "best"               # best | 1080p | 720p | … (legacy)
    cookies_file: Optional[Path] = None  # for Instagram/Twitter/FB login
    overwrite: bool = False             # if True, re-download existing
    use_id_filename: bool = True        # True → uploader_kind_id.ext
    # NEU 2026-05-24: File modification + creation date = upload date.
    # Wenn True, wird os.utime + creation-time auf den Upload-Zeitpunkt
    # gesetzt — hilfreich um im Explorer chronologisch zu sortieren.
    set_upload_date_as_file_date: bool = True
    # NEU 2026-05-24: full main-GUI parity
    quality_height: Optional[int] = None  # 4320|2160|1440|1080|720|480|360|240|None=best|0=worst
    format_container: str = "mp4"         # mp4 | webm | mkv | original
    audio_only: bool = False              # bestaudio → mp3
    tiktok_quality: str = "Auto"          # Auto | "No Watermark (HD)" | "Only Sound (MP3)" | "Watermark (SD)"


def set_file_date_from_id(file_path: Path, item_id: str,
                            upload_date_str: str = "") -> bool:
    """Stamp file's modification + creation time with upload-date.

    Prefers `upload_date_str` (YYYYMMDD) if given, else falls back to
    deriving from TikTok-snowflake `item_id` (works for TikTok URLs).

    Returns True on success.
    """
    import os
    import time

    ts: Optional[float] = None
    # 1. Use given upload_date_str if available
    if upload_date_str and len(upload_date_str) == 8 and upload_date_str.isdigit():
        try:
            d = _dt.datetime(int(upload_date_str[:4]),
                              int(upload_date_str[4:6]),
                              int(upload_date_str[6:8]),
                              12, 0, 0)  # noon = avoids TZ drift
            ts = d.timestamp()
        except Exception:
            ts = None
    # 2. TikTok snowflake fallback (full timestamp incl. hour/min/sec)
    if ts is None and item_id and str(item_id).isdigit():
        try:
            tikts = int(item_id) >> 32
            if 1500000000 < tikts < 4000000000:
                ts = float(tikts)
        except Exception:
            pass
    if ts is None:
        return False

    try:
        os.utime(file_path, (ts, ts))
    except Exception:
        return False
    # Set creation-time on Windows via pywin32 if available; else skip.
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            # restype/argtypes setzen — sonst schneidet ctypes das 64-Bit-HANDLE
            # auf 32 Bit ab → SetFileTime bekommt ein kaputtes Handle + Leak.
            kernel32.CreateFileW.restype = wintypes.HANDLE
            kernel32.CreateFileW.argtypes = [
                wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
            ]
            # FILETIME = 100-ns intervals since 1601-01-01 UTC
            # unix epoch is 1970-01-01; offset = 116444736000000000 (100-ns units)
            ft_int = int((ts * 1e7) + 116444736000000000)
            ft = wintypes.FILETIME(ft_int & 0xFFFFFFFF, ft_int >> 32)
            h = kernel32.CreateFileW(
                str(file_path), 0x100,  # FILE_WRITE_ATTRIBUTES
                0x07,                   # share read/write/delete
                None,
                3,                      # OPEN_EXISTING
                0x02000000,             # FILE_FLAG_BACKUP_SEMANTICS (works on dirs too)
                None,
            )
            _invalid = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1  # INVALID_HANDLE_VALUE
            if h and h != _invalid:
                try:
                    kernel32.SetFileTime(h, ctypes.byref(ft),
                                          ctypes.byref(ft),
                                          ctypes.byref(ft))
                finally:
                    kernel32.CloseHandle(h)
    except Exception:
        pass
    return True


@dataclass
class DownloadStats:
    """Per-run statistics returned from download_channel."""
    enumerated: int = 0
    downloaded_video: int = 0
    downloaded_picture: int = 0
    skipped_existing: int = 0
    skipped_date: int = 0
    skipped_type: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


# ───────────────── Platform detection ────────────────────────────────────

def detect_platform(url: str) -> str:
    """Lowercase key from URL: 'youtube' | 'tiktok' | 'instagram' | … |
    'other'. Used to pick the backend."""
    u = (url or "").lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    if "twitter.com" in u or "x.com" in u:
        return "twitter"
    if "facebook.com" in u or "fb.watch" in u:
        return "facebook"
    return "other"


def pretty_platform(url: str) -> str:
    """Returns the folder-cased platform name (e.g. 'TikTok')."""
    m = {
        "youtube":   "YouTube",
        "tiktok":    "TikTok",
        "instagram": "Instagram",
        "twitter":   "Twitter",
        "facebook":  "Facebook",
    }
    return m.get(detect_platform(url), "Other")


def extract_username(url: str) -> str:
    """Best-effort username extraction from a channel URL.

    YouTube:    @TheErsysEnding         /@TheErsysEnding  /c/Foo  /channel/UC…
    TikTok:     @theersysending
    Instagram:  theersysending
    """
    if not url:
        return "unknown"
    plat = detect_platform(url)
    if plat == "youtube":
        m = re.search(r"/(@[^/?]+)", url)
        if m:
            return m.group(1).lstrip("@")
        m = re.search(r"/(?:c|user|channel)/([^/?]+)", url)
        if m:
            return m.group(1)
    elif plat == "tiktok":
        m = re.search(r"/@([^/?]+)", url)
        if m:
            return m.group(1)
    elif plat in ("instagram", "twitter", "facebook"):
        m = re.search(r"\.com/([^/?]+)", url)
        if m:
            return m.group(1)
    return "unknown"


# ───────────────── TikTok photo carousels via tikwm.com ─────────────────

def _tikwm_get(url: str) -> dict:
    """GET tikwm.com API for a TikTok URL — returns the 'data' dict."""
    api = "https://www.tikwm.com/api/?url=" + urllib.parse.quote(url) + "&hd=1"
    req = urllib.request.Request(api, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
        body = json.loads(r.read())
    if body.get("code") != 0:
        raise RuntimeError(f"tikwm error: {body.get('msg')}")
    return body.get("data", {}) or {}


def _tiktok_classify(item_url: str, log_cb=None) -> tuple[str, str]:
    """Determines whether a TikTok URL is a 'video' or 'picture' post.

    Why this is needed:
        yt-dlp's flat-playlist enumeration of a TikTok channel rewrites
        EVERY item URL to /video/<id>, even when the original post is a
        photo carousel. So URL-based heuristics give wrong results.
        We hit tikwm.com — if the response has 'images', it's a photo.

    Returns: (kind, canonical_url) where kind = 'video' | 'picture'.
        canonical_url is the URL with the correct /video/ or /photo/
        segment swapped in.
    """
    try:
        data = _tikwm_get(item_url)
    except Exception as e:
        if log_cb:
            log_cb(f"tikwm classify failed for {item_url}: {e}")
        # Fall back to URL-based heuristic — better than nothing
        return ("picture" if "/photo/" in item_url else "video", item_url)
    images = data.get("images") or []
    if images and len(images) > 0:
        # It's a photo post — rewrite /video/ to /photo/ for downstream
        canonical = item_url.replace("/video/", "/photo/")
        return ("picture", canonical)
    return ("video", item_url)


def _download_image(img_url: str, out_path: Path,
                     progress_cb: Optional[Callable] = None) -> int:
    """Stream-download an image URL to out_path. Returns bytes written."""
    req = urllib.request.Request(img_url, headers={
        "User-Agent": _UA,
        "Referer": "https://www.tiktok.com/",
    })
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with urllib.request.urlopen(req, timeout=60, context=_SSL) as r:
        total = int(r.headers.get("Content-Length", 0) or 0)
        with open(out_path, "wb") as f:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
                if progress_cb and total:
                    try:
                        progress_cb(written, total)
                    except Exception:
                        pass
    return written


# ───────────────── Channel enumeration ───────────────────────────────────

def _tiktok_id_to_date(item_id: str) -> str:
    """TikTok video/photo IDs are 64-bit Snowflake IDs whose UPPER 32 bits
    encode the unix timestamp of upload. We extract it directly so we
    don't need per-item API calls just for date filtering.

    Returns YYYYMMDD string or "" if ID is malformed.
    """
    if not item_id or not str(item_id).isdigit():
        return ""
    try:
        ts = int(item_id) >> 32
        # Sanity check: TikTok launched 2016, IDs before ~2018 unlikely
        if ts < 1500000000 or ts > 4000000000:
            return ""
        d = _dt.datetime.fromtimestamp(ts)
        return d.strftime("%Y%m%d")
    except Exception:
        return ""


def _enumerate_via_ytdlp(
    url: str, max_items: int, log_cb: Callable[[str], None],
    cookies_file: Optional[Path] = None, need_dates: bool = False,
) -> list[dict]:
    """Use yt-dlp --flat-playlist to list channel items.

    Returns: list of dicts with keys id, url, title, upload_date (YYYYMMDD).

    NOTE: With process=False, yt-dlp's `playlistend` option is sometimes
    ignored because the entry-generator is exhausted lazily. We instead
    iterate the generator and stop at max_items ourselves — this is also
    much faster for big channels (1500+ items) since we don't wait for
    the full enumeration before applying the cap.
    """
    try:
        import yt_dlp
    except ImportError:
        log_cb("yt-dlp not available; cannot enumerate channel")
        return []
    opts = {
        "quiet": True, "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
    }
    # playlistend kicks in when process=True, but with flat-playlist we
    # need a different approach. Set it anyway as a hint.
    if max_items > 0:
        opts["playlistend"] = max_items
    if cookies_file and Path(cookies_file).exists():
        opts["cookiefile"] = str(cookies_file)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
    except Exception as e:
        log_cb(f"yt-dlp enumerate failed: {e}")
        return []
    if not info:
        return []
    entries = info.get("entries") or []
    # entries can be a generator — iterate manually so we can stop early
    is_tiktok = "tiktok.com" in (url or "").lower()
    out = []
    for e in entries:
        if not e:
            continue
        item_id = str(e.get("id") or "")
        item_url = e.get("url") or e.get("webpage_url") or ""
        # TikTok IDs encode timestamp in upper 32 bits — derive date for free
        upload_date = e.get("upload_date") or ""
        if not upload_date and is_tiktok:
            upload_date = _tiktok_id_to_date(item_id)
        out.append({
            "id":          item_id,
            "url":         item_url,
            "title":       e.get("title") or "",
            "upload_date": upload_date,
            "duration":    e.get("duration") or 0,
            # Heuristic: TikTok photo URLs have /photo/ in them
            "kind":        "picture" if "/photo/" in item_url else "video",
        })
        # Hard cap right here — TikTok-channel generators return 1500+ items
        # even with playlistend, so we have to enforce client-side.
        if max_items > 0 and len(out) >= max_items:
            break

    # NEU 2026-06-05: Flat-Playlist (v.a. YouTube) liefert KEIN upload_date →
    # bei aktivem Datumsfilter wuerden sonst ALLE Items ohne Datum verworfen
    # (= 0 Ergebnisse). Darum hier das Datum pro Item nachladen.
    if need_dates:
        missing = [it for it in out if not it.get("upload_date")]
        cap = 400
        if missing:
            if len(missing) > cap:
                log_cb(f"Datumsfilter: lade Datum nur fuer die ersten {cap} von "
                       f"{len(missing)} Items (Limit) — ggf. max_items setzen")
                missing = missing[:cap]
            else:
                log_cb(f"Datumsfilter: lade Upload-Datum fuer {len(missing)} "
                       f"Items nach …")
            try:
                d_opts = {"quiet": True, "no_warnings": True,
                          "skip_download": True, "extract_flat": False}
                if cookies_file and Path(cookies_file).exists():
                    d_opts["cookiefile"] = str(cookies_file)
                with yt_dlp.YoutubeDL(d_opts) as dydl:
                    for i, it in enumerate(missing, 1):
                        try:
                            vi = dydl.extract_info(
                                it.get("url") or it.get("id"),
                                download=False, process=False)
                            it["upload_date"] = (vi or {}).get("upload_date") or ""
                        except Exception:
                            pass
                        if i % 25 == 0:
                            log_cb(f"  … {i}/{len(missing)} Daten geladen")
            except Exception as e:
                log_cb(f"Datums-Nachladen fehlgeschlagen: {e}")
    return out


def _enumerate_via_gallerydl(
    url: str, max_items: int, log_cb: Callable[[str], None],
    cookies_file: Optional[Path] = None,
) -> list[dict]:
    """Use gallery-dl --simulate to enumerate channel items.

    Better than yt-dlp for Instagram/TikTok photo carousels. Returns dicts
    with 'url' (extracted) and 'id' (post id).
    """
    cmd = _gallery_dl_base() + [
        "--simulate", "--no-download",
        "--write-info-json",  # so we get the JSON metadata
        "--quiet",
    ]
    if max_items > 0:
        cmd += ["--range", f"1-{max_items}"]
    if cookies_file and Path(cookies_file).exists():
        cmd += ["--cookies", str(cookies_file)]
    cmd.append(url)
    log_cb(f"gallery-dl: {' '.join(cmd[3:])}")
    try:
        # --simulate prints URLs to stdout; --get-urls would print without
        # metadata. We use --get-urls instead since simulate prints titles
        # which we have to parse out. Actually --simulate prints in a
        # format with filenames, and stderr has the URLs. We use a JSON
        # approach: gallery-dl --dump-json
        cmd_json = _gallery_dl_base() + [
            "--dump-json", "--no-download", "--quiet",
        ]
        if max_items > 0:
            cmd_json += ["--range", f"1-{max_items}"]
        if cookies_file and Path(cookies_file).exists():
            cmd_json += ["--cookies", str(cookies_file)]
        cmd_json.append(url)
        proc = subprocess.run(cmd_json, capture_output=True, text=True,
                               timeout=300, encoding="utf-8",
                               errors="ignore")
        if proc.returncode != 0 and not proc.stdout:
            log_cb(f"gallery-dl error: {proc.stderr[:200]}")
            return []
        out = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("["):
                continue
            try:
                arr = json.loads(line)
            except Exception:
                continue
            # gallery-dl --dump-json prints [type, url, metadata]
            if isinstance(arr, list) and len(arr) >= 3:
                meta = arr[2] if isinstance(arr[2], dict) else {}
                out.append({
                    "id":          str(meta.get("id") or meta.get("post_id") or ""),
                    "url":         arr[1] if isinstance(arr[1], str) else "",
                    "title":       meta.get("description") or meta.get("title") or "",
                    "upload_date": _gallery_dl_date(meta),
                    "kind":        _gallery_dl_kind(meta, arr[1] if len(arr) > 1 else ""),
                    "_meta":       meta,  # keep for filename rendering
                })
        return out
    except Exception as e:
        log_cb(f"gallery-dl crashed: {e}")
        return []


def _gallery_dl_date(meta: dict) -> str:
    """Pull a YYYYMMDD date from gallery-dl metadata, best-effort."""
    for k in ("date", "upload_date", "created_at", "datetime", "publish_date"):
        v = meta.get(k)
        if not v:
            continue
        if isinstance(v, str):
            # ISO-like or with time
            m = re.match(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", v)
            if m:
                return "".join(m.groups())
        elif isinstance(v, (int, float)):
            # Unix timestamp
            try:
                d = _dt.datetime.fromtimestamp(int(v))
                return d.strftime("%Y%m%d")
            except Exception:
                pass
    return ""


def _gallery_dl_kind(meta: dict, url: str) -> str:
    """video | picture from gallery-dl metadata + URL hints."""
    # gallery-dl marks images in the URL extension or metadata
    if any(k in meta for k in ("video_url", "video", "duration")):
        return "video"
    ext = (meta.get("extension") or "").lower()
    if ext in ("mp4", "mov", "webm", "mkv", "m4v"):
        return "video"
    if ext in ("jpg", "jpeg", "png", "webp", "gif"):
        return "picture"
    # URL-based heuristic
    ul = (url or "").lower()
    if "/photo/" in ul:
        return "picture"
    if "/video/" in ul:
        return "video"
    return "video"  # default


def enumerate_channel(
    url: str,
    options: ChannelOptions,
    log_cb: Callable[[str], None] = lambda _m: None,
) -> list[dict]:
    """Enumerate items on a channel page, applying max_items + date filter.

    Returns: list of dicts with keys id, url, title, upload_date, kind.

    Backend choice:
        YouTube  → yt-dlp (well-supported, fast)
        Other    → gallery-dl (has upload_date in metadata)

    If date-filter is set, we need gallery-dl for ALL platforms except
    YouTube, because yt-dlp's flat-playlist mode skips dates.
    """
    plat = detect_platform(url)
    has_date_filter = bool(options.date_from or options.date_to)

    if plat in ("youtube", "tiktok"):
        # TikTok-IDs tragen den Timestamp in den oberen Bits → Datum gratis.
        # YouTube-Flat-Playlist hat KEIN upload_date → bei Datumsfilter laedt
        # _enumerate_via_ytdlp(need_dates=True) das Datum pro Item nach.
        # Bei Filter mehr Items aufzaehlen (manche fallen raus): x10.
        enum_cap = options.max_items
        if has_date_filter and enum_cap > 0:
            enum_cap = enum_cap * 10  # buffer
        items = _enumerate_via_ytdlp(url, enum_cap, log_cb,
                                      options.cookies_file,
                                      need_dates=(has_date_filter
                                                  and plat != "tiktok"))
    else:
        # Instagram, Twitter, Facebook → gallery-dl (has upload_date in meta)
        items = _enumerate_via_gallerydl(url, options.max_items, log_cb,
                                          options.cookies_file)

    # Date filter (gallery-dl items have upload_date set; yt-dlp ones don't)
    if has_date_filter:
        kept = []
        no_date_count = 0
        for it in items:
            ds = it.get("upload_date") or ""
            if len(ds) != 8 or not ds.isdigit():
                no_date_count += 1
                continue  # NO date → drop (strict mode when filter is set)
            try:
                d = _dt.date(int(ds[:4]), int(ds[4:6]), int(ds[6:8]))
            except Exception:
                no_date_count += 1
                continue
            if options.date_from and d < options.date_from:
                continue
            if options.date_to and d > options.date_to:
                continue
            kept.append(it)
        if no_date_count:
            log_cb(f"date-filter: dropped {no_date_count} items "
                   f"without parseable date")
        items = kept

    # Media-type filter
    if options.media_type != "both":
        want = options.media_type   # "video" or "picture"
        items = [it for it in items if it.get("kind") == want]

    # Cap to max_items AFTER filtering. yt-dlp's playlistend respects the
    # cap during enumeration, but if filters dropped items we re-enumerate
    # logically to honor the user's "max N items" intent.
    if options.max_items > 0 and len(items) > options.max_items:
        items = items[:options.max_items]

    return items


# ───────────────── Per-item download dispatch ────────────────────────────

def _build_filename(uploader: str, kind: str, item_id: str,
                     ext: str = "mp4", use_id: bool = True,
                     title: str = "") -> str:
    """Return the filename portion (no folder) for an item."""
    # Sanitize uploader (Windows-bad chars)
    uploader = re.sub(r'[<>:"/\\|?*]', "_", uploader or "unknown")
    item_id = re.sub(r'[<>:"/\\|?*]', "_", str(item_id) or "unknown")
    if use_id:
        return f"{uploader}_{kind}_{item_id}.{ext}"
    # Title-mode (legacy)
    title = re.sub(r'[<>:"/\\|?*]', "_", title or "untitled")[:100]
    return f"{title} [{item_id}].{ext}"


def _download_item_tiktok_video(
    item_url: str, out_path: Path, options: ChannelOptions,
    log_cb: Callable[[str], None],
    progress_cb: Optional[Callable] = None,
) -> bool:
    """TikTok video → tiktok_hd module (HD via TTDownloader).

    Honors options.tiktok_quality:
        "No Watermark (HD)" → prefer='hd' (default)
        "Watermark (SD)"    → prefer='wm'
        "Only Sound (MP3)"  → prefer='audio'  (extracts audio track)
        anything else       → prefer='hd'
    """
    prefer_map = {
        "No Watermark (HD)": "hd",
        "Watermark (SD)":    "wm",
        "Only Sound (MP3)":  "audio",
    }
    prefer = prefer_map.get(options.tiktok_quality, "hd")
    return _tk.download(item_url, out_path, prefer=prefer,
                        progress_cb=progress_cb, log_cb=log_cb)


def _download_item_tiktok_photo(
    item_url: str, out_dir: Path, uploader: str, item_id: str,
    options: ChannelOptions, log_cb: Callable[[str], None],
    progress_cb: Optional[Callable] = None,
) -> tuple[int, int]:
    """TikTok photo carousel → tikwm.com.

    Returns (written, skipped_existing) — z.B. (3, 0) neu, (0, 5) alles da.
    """
    try:
        data = _tikwm_get(item_url)
    except Exception as e:
        log_cb(f"tikwm fetch failed: {e}")
        return 0, 0
    images = data.get("images") or []
    if not images:
        # Maybe the URL is a video that tikwm returned as video data
        play = data.get("play") or data.get("hdplay")
        if play:
            log_cb(f"tikwm returned video for photo URL: {item_url}")
            return 0, 0
        return 0, 0
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    for i, img_url in enumerate(images, 1):
        # ext from URL or default jpg
        ext = "jpg"
        m = re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", img_url.lower())
        if m:
            ext = m.group(1)
            if ext == "jpeg":
                ext = "jpg"
        # Single-image post → no _01 suffix; multi → append _01, _02, …
        suffix = f"_{i:02d}" if len(images) > 1 else ""
        fname = _build_filename(
            uploader=uploader, kind="picture",
            item_id=f"{item_id}{suffix}", ext=ext,
            use_id=options.use_id_filename,
        )
        out_path = out_dir / fname
        if out_path.exists() and not options.overwrite:
            log_cb(f"skip existing: {fname}")
            skipped += 1
            continue
        try:
            _download_image(img_url, out_path, progress_cb)
            written += 1
            log_cb(f"wrote photo: {fname}")
        except Exception as e:
            log_cb(f"photo download failed ({fname}): {e}")
    return written, skipped


def _download_item_via_ytdlp(
    item_url: str, out_path: Path, options: ChannelOptions,
    log_cb: Callable[[str], None],
) -> bool:
    """YouTube + generic → yt-dlp.

    Honors quality_height (full range 4320 → 240, None=best, 0=worst),
    format_container (mp4/webm/mkv/original), and audio_only flag.
    """
    try:
        import yt_dlp
    except ImportError:
        log_cb("yt-dlp not available")
        return False

    # Build format string honoring all the new options
    h = options.quality_height
    container = options.format_container or "mp4"
    if options.audio_only:
        fmt = "bestaudio/best"
    elif h is None:
        # "Best" → highest available
        if container == "mp4":
            fmt = ("bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                   "bestvideo*+bestaudio/best")
        else:
            fmt = "bestvideo*+bestaudio/best"
    elif h == 0:
        fmt = "worstvideo*+worstaudio/worst"
    else:
        if container == "mp4":
            fmt = (f"bestvideo[ext=mp4][height<={h}]+bestaudio[ext=m4a]/"
                   f"bestvideo[height<={h}]+bestaudio/"
                   f"best[height<={h}]/"
                   f"bestvideo*+bestaudio/best")
        else:
            fmt = (f"bestvideo[height<={h}]+bestaudio/"
                   f"best[height<={h}]/"
                   f"bestvideo*+bestaudio/best")

    opts = {
        "outtmpl": str(out_path.with_suffix(".%(ext)s")),
        "format": fmt,
        "quiet": True, "no_warnings": True,
        "noplaylist": True,
    }
    if options.audio_only:
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    elif container in ("mp4", "webm", "mkv"):
        opts["merge_output_format"] = container
        # Remux statt Convert: Container per Stream-Copy aendern (kein
        # Re-Encode) → schneller + verlustfrei. Vorher wurde IMMER neu kodiert.
        opts["postprocessors"] = [{
            "key": "FFmpegVideoRemuxer",
            "preferedformat": container,
        }]
    if options.cookies_file and Path(options.cookies_file).exists():
        opts["cookiefile"] = str(options.cookies_file)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([item_url])
        # Echte Erfolgsprüfung: liegt wirklich eine Datei mit diesem Stamm
        # vor? Früher: out_path.parent.exists() — das war IMMER True (der
        # Ordner wird vorher angelegt), wodurch Fehlschläge als Erfolg
        # gezählt wurden und die Statistik verfälscht war.
        stem = out_path.stem
        return any(
            p.is_file() and p.name.startswith(stem + ".")
            for p in out_path.parent.iterdir()
        )
    except Exception as e:
        log_cb(f"yt-dlp download failed: {e}")
        return False


def _download_item_via_gallerydl(
    item_url: str, out_dir: Path, options: ChannelOptions,
    log_cb: Callable[[str], None],
) -> bool:
    """Instagram/Twitter/Facebook → gallery-dl directly downloads."""
    cmd = _gallery_dl_base() + [
        "--quiet",
        "-D", str(out_dir),   # destination directory
    ]
    if options.cookies_file and Path(options.cookies_file).exists():
        cmd += ["--cookies", str(options.cookies_file)]
    cmd.append(item_url)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=300, encoding="utf-8",
                              errors="ignore")
        if proc.returncode != 0:
            log_cb(f"gallery-dl error: {proc.stderr[:200]}")
            return False
        return True
    except Exception as e:
        log_cb(f"gallery-dl crashed: {e}")
        return False


# ───────────────── Top-level orchestrator ─────────────────────────────────

def download_channel(
    channel_url: str,
    out_dir: Path,
    options: ChannelOptions,
    progress_cb: Callable[[int, int, str], None] = lambda *a: None,
    log_cb: Callable[[str], None] = lambda m: print(m),
    cancel_flag: Optional[Callable[[], bool]] = None,
) -> DownloadStats:
    """Download an entire channel.

    Args:
        channel_url: the channel/user URL (e.g. https://www.tiktok.com/@user)
        out_dir: top-level output directory; channel goes into
                 <out_dir>/<Platform>/<Username>/{Video,Picture}/
        options: ChannelOptions instance with filters + cookies
        progress_cb: callable(items_done, items_total, current_label)
        log_cb: callable(line) for log messages
        cancel_flag: callable returning True to abort
    """
    stats = DownloadStats()
    plat = pretty_platform(channel_url)
    user = extract_username(channel_url)
    base = out_dir / plat / user

    log_cb(f"=== Channel: {channel_url}")
    log_cb(f"=== Platform: {plat} | User: {user} | Output: {base}")

    items = enumerate_channel(channel_url, options, log_cb)
    stats.enumerated = len(items)
    log_cb(f"Enumerated {len(items)} items "
           f"(after date/type filter)")

    if not items:
        log_cb("Nothing to download.")
        return stats

    for i, it in enumerate(items, 1):
        if cancel_flag and cancel_flag():
            log_cb("Cancel requested — stopping.")
            break
        item_url = it.get("url") or ""
        item_id = it.get("id") or "unknown"
        kind = it.get("kind") or "video"
        title = it.get("title") or ""
        progress_cb(i, len(items), f"{kind} {item_id}")
        log_cb(f"[{i}/{len(items)}] {kind} {item_id}")

        upload_date = it.get("upload_date") or ""
        # NEU 2026-05-24: TikTok-Items neu klassifizieren weil yt-dlp's
        # flat-playlist alle URLs zu /video/<id> umschreibt — auch echte
        # Foto-Posts. tikwm.com sagt uns ob es ein video- oder photo-Post ist.
        if detect_platform(item_url) == "tiktok":
            kind, item_url = _tiktok_classify(item_url, log_cb)
        sub = base / ("Picture" if kind == "picture" else "Video")
        # Per-item dispatch
        try:
            if detect_platform(item_url) == "tiktok":
                if kind == "picture":
                    written, skipped = _download_item_tiktok_photo(
                        item_url, sub, user, item_id, options, log_cb,
                    )
                    stats.downloaded_picture += written
                    stats.skipped_existing += skipped
                    if written == 0 and skipped == 0:
                        stats.failed += 1
                    elif written > 0 and options.set_upload_date_as_file_date:
                        # Stamp every photo file in this batch
                        for ph in sub.glob(f"*{item_id}*"):
                            set_file_date_from_id(ph, item_id, upload_date)
                else:
                    fname = _build_filename(
                        uploader=user, kind="video", item_id=item_id,
                        ext="mp4", use_id=options.use_id_filename,
                        title=title,
                    )
                    out_path = sub / fname
                    _stem = out_path.stem
                    if (not options.overwrite and sub.exists() and any(
                            p.is_file() and p.name.startswith(_stem + ".")
                            for p in sub.iterdir())):
                        # beliebige Endung (.mp4/.mp3) zaehlt als vorhanden
                        log_cb(f"skip existing: {fname}")
                        stats.skipped_existing += 1
                        continue
                    ok = _download_item_tiktok_video(
                        item_url, out_path, options, log_cb,
                    )
                    if ok:
                        stats.downloaded_video += 1
                        if options.set_upload_date_as_file_date:
                            set_file_date_from_id(out_path, item_id, upload_date)
                    else:
                        stats.failed += 1
            elif detect_platform(item_url) == "youtube":
                fname_base = _build_filename(
                    uploader=user, kind="video", item_id=item_id,
                    ext="mp4", use_id=options.use_id_filename,
                    title=title,
                )
                # yt-dlp picks its own ext; pass without extension
                out_path = sub / Path(fname_base).with_suffix("")
                _stem = out_path.name
                if (not options.overwrite and sub.exists() and any(
                        p.is_file() and p.name.startswith(_stem + ".")
                        for p in sub.iterdir())):
                    # bereits vorhanden -> als skipped zaehlen (vorher wurde es
                    # faelschlich als "downloaded" gezaehlt)
                    log_cb(f"skip existing: {_stem}")
                    stats.skipped_existing += 1
                    continue
                ok = _download_item_via_ytdlp(
                    item_url, out_path, options, log_cb,
                )
                if ok:
                    stats.downloaded_video += 1
                    if options.set_upload_date_as_file_date:
                        # YouTube videos may have varying extensions after merge
                        for v in sub.glob(f"*{item_id}.*"):
                            set_file_date_from_id(v, item_id, upload_date)
                else:
                    stats.failed += 1
            else:
                # Instagram, Twitter, Facebook → gallery-dl
                ok = _download_item_via_gallerydl(
                    item_url, sub, options, log_cb,
                )
                if ok:
                    if kind == "picture":
                        stats.downloaded_picture += 1
                    else:
                        stats.downloaded_video += 1
                else:
                    stats.failed += 1
        except Exception as e:
            stats.failed += 1
            stats.errors.append(f"{item_url}: {e}")
            log_cb(f"  ERROR {e}")

    log_cb(f"=== DONE — videos: {stats.downloaded_video}, "
           f"pictures: {stats.downloaded_picture}, "
           f"skipped: {stats.skipped_existing}, "
           f"failed: {stats.failed}")
    return stats


# ───────────────── CLI for ad-hoc testing ─────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="channel URL")
    ap.add_argument("--out", required=True, type=Path,
                    help="output directory")
    ap.add_argument("--max", type=int, default=10, help="max items")
    ap.add_argument("--from", dest="from_date", default=None,
                    help="from date YYYY-MM-DD")
    ap.add_argument("--to", dest="to_date", default=None,
                    help="to date YYYY-MM-DD")
    ap.add_argument("--type", default="both",
                    choices=["both", "video", "picture"])
    ap.add_argument("--cookies", type=Path, default=None,
                    help="cookies.txt for login-protected platforms")
    args = ap.parse_args()

    opts = ChannelOptions(
        max_items=args.max,
        date_from=_dt.date.fromisoformat(args.from_date) if args.from_date else None,
        date_to=_dt.date.fromisoformat(args.to_date) if args.to_date else None,
        media_type=args.type,
        cookies_file=args.cookies,
    )
    download_channel(args.url, args.out, opts, log_cb=print)
