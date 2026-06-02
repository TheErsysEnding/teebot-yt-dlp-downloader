"""TikTok HD downloader — TTDownloader.com (HD master) + tikwm fallback.

Why this exists:
    yt-dlp can only reach TikTok's WEB API, which caps quality at 540p @
    ~540 kbps (about 600 KB for a 10s clip). The real 1080p @ ~2.5 Mbps
    master file is only served through TikTok's mobile-app API, which
    requires app-signed requests we can't easily forge.

    TTDownloader.com solves this server-side: they proxy the request and
    return the genuine HD master (verified 1080x1920 @ ~8 Mbps). We scrape
    their public flow:

        1. GET https://ttdownloader.com/        → session + CSRF token
        2. POST /search/  {url, token}          → HTML with HD link
        3. GET  /dl.php?v=<base64>              → streams the MP4 bytes

    tikwm.com is a secondary JSON API. Its video is only SD (≈576p), so we
    use it ONLY as a last-resort download fallback AND — importantly — as a
    metadata source (id / title / uploader / upload-date).

Why metadata matters (the multi-download fix, 2026-05-30):
    The GUI used to call yt-dlp's `extract_info()` to get the filename
    metadata BEFORE downloading. That call hits TikTok's own API *with the
    user's login cookies*, and TikTok bot-blocks an authenticated session
    after a few rapid automated requests → "works once, fails on the 2nd/
    3rd video". This module now exposes `get_metadata()` which derives the
    uploader + id straight from the URL (zero network, never fails) and
    enriches title/date from tikwm (best-effort). The HD download path no
    longer touches TikTok's API or the user's cookies at all, so it can't
    be rate-limited no matter how many videos you pull in a row.

Failure modes (caller should handle ALL gracefully):
    - TTDownloader down / changed      → tikwm fallback, then returns False
    - private / region-locked          → returns False; caller → yt-dlp
    - network timeout                  → retried once, then False

Public API:
    download(url, out_path, prefer, progress_cb, log_cb) -> bool
    get_metadata(url) -> dict          — id/title/uploader/upload_date/timestamp
    is_tiktok_url(url) -> bool

Uses ONLY stdlib (urllib, re, json, ssl, time) so the offline bundle needs
no extra wheels.
"""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# Real Chrome UA — both backends sometimes refuse Python-default UAs
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/131.0.0.0 Safari/537.36")

_HOME = "https://ttdownloader.com/"
_SEARCH = "https://ttdownloader.com/search/"
_TIKWM = "https://www.tikwm.com/api/"

# TLS-Zertifikate werden geprüft (Standard). Früher stand hier CERT_NONE
# ("corporate proxies"), das hebelt aber den MITM-Schutz aus — und
# ttdownloader.com / tikwm.com haben gültige Zertifikate.
_SSL = ssl.create_default_context()

_TIKTOK_HOSTS = ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com")


def is_tiktok_url(url: str) -> bool:
    """Cheap host check — does this look like a TikTok URL?"""
    if not url:
        return False
    u = url.lower()
    return any(h in u for h in _TIKTOK_HOSTS)


# ─────────────────────────── metadata ───────────────────────────

def _parse_url_meta(url: str) -> dict:
    """Pull what we can from the URL itself — never makes a network call.

    Works for the canonical form
        https://www.tiktok.com/@<uploader>/video/<id>
    Short links (vm./vt.) carry no handle/id, so those fields stay generic
    and tikwm (if reachable) fills them in.
    """
    uploader = "TikTok"
    vid = ""
    m = re.search(r"@([A-Za-z0-9._]+)", url)
    if m:
        uploader = m.group(1)
    m = re.search(r"/(?:video|photo|v)/(\d+)", url)
    if not m:
        m = re.search(r"(\d{15,25})", url)  # bare numeric id anywhere
    if m:
        vid = m.group(1)
    return {"uploader": uploader, "id": vid or "video", "title": "",
            "upload_date": "", "timestamp": 0}


def _tikwm_api(url: str, timeout: int = 25) -> Optional[dict]:
    """Query tikwm; return its `data` dict or None. Best-effort, no raise."""
    api = _TIKWM + "?url=" + urllib.parse.quote(url, safe="") + "&hd=1"
    try:
        req = urllib.request.Request(api, headers={
            "User-Agent": _UA, "Referer": "https://www.tikwm.com/"})
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            j = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:
        return None
    if not isinstance(j, dict) or j.get("code") != 0:
        return None
    d = j.get("data")
    return d if isinstance(d, dict) else None


def get_metadata(url: str, log_cb: Optional[Callable[[str], None]] = None) -> dict:
    """Return filename metadata WITHOUT touching TikTok's API or cookies.

    Always returns a usable dict:
        {id, title, uploader, upload_date(YYYYMMDD), timestamp}
    URL-derived fields are guaranteed; tikwm enriches title/date if it can.
    """
    def _log(msg: str) -> None:
        if log_cb:
            try:
                log_cb(msg)
            except Exception:
                pass

    meta = _parse_url_meta(url)
    data = _tikwm_api(url)
    if data:
        author = data.get("author") or {}
        if isinstance(author, dict):
            uploader = (author.get("unique_id") or author.get("nickname")
                        or meta["uploader"])
        else:
            uploader = meta["uploader"]
        ts = data.get("create_time") or 0
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            ts = 0
        meta.update({
            "id": str(data.get("id") or meta["id"]),
            "title": (data.get("title") or "").strip() or meta["id"],
            "uploader": uploader,
            "timestamp": ts,
            "upload_date": time.strftime("%Y%m%d", time.gmtime(ts)) if ts else "",
        })
        _log(f"tiktok_hd: metadata via tikwm — @{uploader} / {meta['id']}")
    else:
        meta["title"] = meta["id"]
        _log("tiktok_hd: tikwm metadata unavailable — using URL-derived "
             f"id/uploader ({meta['uploader']} / {meta['id']})")
    return meta


# ─────────────────────── TTDownloader backend ───────────────────────

def _get_session() -> tuple[str, str]:
    """GET the homepage, return (PHPSESSID, csrf_token). Raises on failure."""
    req = urllib.request.Request(_HOME, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20, context=_SSL) as r:
        html = r.read().decode("utf-8", errors="ignore")
        cookies = r.headers.get_all("Set-Cookie") or []

    cookie_str = "\n".join(cookies)
    sid_m = re.search(r"PHPSESSID=([^;]+)", cookie_str)
    if not sid_m:
        raise RuntimeError("no PHPSESSID cookie in TTDownloader homepage")
    sid = sid_m.group(1)

    tok_m = re.search(
        r'name=["\']token["\']\s+value=["\']([^"\']+)["\']', html)
    if not tok_m:
        tok_m = re.search(r'token\s*[:=]\s*["\']([a-zA-Z0-9_-]+)["\']', html)
    if not tok_m:
        raise RuntimeError("no CSRF token in TTDownloader homepage")
    return sid, tok_m.group(1)


def _post_url(tiktok_url: str, sid: str, token: str) -> str:
    """POST /search/, return the response HTML containing download links."""
    body = urllib.parse.urlencode({"url": tiktok_url, "token": token}).encode()
    req = urllib.request.Request(_SEARCH, data=body, headers={
        "User-Agent": _UA,
        "Cookie": f"PHPSESSID={sid}",
        "Referer": _HOME,
        "Origin": "https://ttdownloader.com",
        "X-Requested-With": "XMLHttpRequest",
    })
    with urllib.request.urlopen(req, timeout=30, context=_SSL) as r:
        return r.read().decode("utf-8", errors="ignore")


def _parse_links(html: str) -> list[tuple[str, str]]:
    """Return [(label, url)] for each download option in the response."""
    results = re.findall(
        r'<div class="size">([^<]+)</div>.*?'
        r'<a[^>]+href="(https://ttdownloader\.com/dl[^"]+)"',
        html, flags=re.DOTALL)
    return [(lbl.strip(), url) for lbl, url in results]


def _pick_link(links: list[tuple[str, str]], prefer: str) -> Optional[str]:
    """Pick the link matching the user's preference."""
    pref = prefer.lower()
    if pref == "hd":
        for lbl, url in links:
            if "hd" in lbl.lower() and "no watermark" in lbl.lower():
                return url
        for lbl, url in links:
            if "no watermark" in lbl.lower():
                return url
    elif pref == "sd":
        for lbl, url in links:
            ll = lbl.lower()
            if "no watermark" in ll and "hd" not in ll:
                return url
    elif pref == "wm":
        for lbl, url in links:
            if "watermark" in lbl.lower() and "no" not in lbl.lower():
                return url
    elif pref == "audio":
        for lbl, url in links:
            if "sound" in lbl.lower() or "audio" in lbl.lower():
                return url
    return links[0][1] if links else None


def _stream_download(
    url: str, out_path: Path,
    headers: Optional[dict] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> int:
    """Download `url` to `out_path`. Returns bytes written. Raises on error."""
    req = urllib.request.Request(url, headers=headers or {"User-Agent": _UA})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=60, context=_SSL) as r:
        try:
            total = int(r.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            total = 0
        written = 0
        with open(out_path, "wb") as f:
            while True:
                chunk = r.read(256 * 1024)
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


def _ttdownloader_once(
    tiktok_url: str, out_path: Path, prefer: str,
    progress_cb: Optional[Callable[[int, int], None]],
    log: Callable[[str], None],
) -> bool:
    """One full TTDownloader attempt. Returns True iff a >0-byte file landed."""
    log("tiktok_hd: requesting TTDownloader session…")
    sid, token = _get_session()
    log("tiktok_hd: posting TikTok URL to TTDownloader…")
    html = _post_url(tiktok_url, sid, token)

    links = _parse_links(html)
    if not links:
        log("tiktok_hd: TTDownloader returned no links "
            "(private video? region-block? API change?)")
        return False
    log(f"tiktok_hd: TTDownloader options: {[lbl for lbl, _ in links]}")

    dl_url = _pick_link(links, prefer)
    if not dl_url:
        log(f"tiktok_hd: no link matching prefer='{prefer}'")
        return False

    log(f"tiktok_hd: downloading prefer='{prefer}' → {out_path.name}")
    nbytes = _stream_download(
        dl_url, out_path,
        headers={"User-Agent": _UA, "Cookie": f"PHPSESSID={sid}",
                 "Referer": _HOME},
        progress_cb=progress_cb)
    if nbytes <= 0:
        log("tiktok_hd: download wrote 0 bytes")
        _safe_unlink(out_path)
        return False
    log(f"tiktok_hd: TTDownloader success — {nbytes/1024/1024:.2f} MB "
        f"→ {out_path.name}")
    return True


# ─────────────────────────── tikwm backend ───────────────────────────

def _tikwm_download(
    tiktok_url: str, out_path: Path, prefer: str,
    progress_cb: Optional[Callable[[int, int], None]],
    log: Callable[[str], None],
) -> bool:
    """SD-quality fallback via tikwm JSON API. Returns True on success."""
    data = _tikwm_api(tiktok_url)
    if not data:
        log("tiktok_hd: tikwm API returned no data")
        return False
    pref = prefer.lower()
    if pref == "wm":
        link = data.get("wmplay") or data.get("play")
    else:  # hd / sd / fallback
        link = data.get("hdplay") or data.get("play") or data.get("wmplay")
    if not link:
        log("tiktok_hd: tikwm has no usable play link")
        return False
    if link.startswith("/"):
        link = "https://www.tikwm.com" + link
    log("tiktok_hd: downloading via tikwm fallback (SD ≈576p)…")
    nbytes = _stream_download(
        link, out_path,
        headers={"User-Agent": _UA, "Referer": "https://www.tikwm.com/"},
        progress_cb=progress_cb)
    if nbytes <= 0:
        log("tiktok_hd: tikwm download wrote 0 bytes")
        _safe_unlink(out_path)
        return False
    log(f"tiktok_hd: tikwm success — {nbytes/1024/1024:.2f} MB → {out_path.name}")
    return True


# ─────────────────────────── orchestrator ───────────────────────────

def _safe_unlink(p: Path) -> None:
    try:
        if p.exists():
            p.unlink()
    except Exception:
        pass


def download(
    tiktok_url: str,
    out_path: Path,
    prefer: str = "hd",
    progress_cb: Optional[Callable[[int, int], None]] = None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> bool:
    """Download `tiktok_url` to `out_path`. True iff a >0-byte file landed.

    Strategy (HD/SD/WM): TTDownloader (true HD master) with one retry, then
    tikwm (SD) as a last resort. Neither touches TikTok's API or the user's
    cookies, so repeated downloads never trip TikTok's per-account bot block.

    prefer: 'hd' | 'sd' | 'wm' | 'audio'  ('audio' is left to the caller).
    """
    def _log(msg: str) -> None:
        if log_cb:
            try:
                log_cb(msg)
            except Exception:
                pass

    if not is_tiktok_url(tiktok_url):
        _log("tiktok_hd: not a TikTok URL, skipping")
        return False

    if prefer.lower() not in ("hd", "sd", "wm"):
        # 'audio'/unknown → let the caller's yt-dlp path handle it
        return False

    # TTDownloader (HD master) — up to 2 attempts with a short backoff.
    for attempt in (1, 2):
        try:
            if _ttdownloader_once(tiktok_url, out_path, prefer,
                                  progress_cb, _log):
                return True
        except Exception as e:
            _log(f"tiktok_hd: TTDownloader attempt {attempt} failed ({e})")
        _safe_unlink(out_path)
        if attempt == 1:
            time.sleep(1.5)  # let a transient hiccup / soft-limit clear

    # Fallback: tikwm (SD but reliable, independent infra).
    _log("tiktok_hd: TTDownloader exhausted — trying tikwm fallback…")
    try:
        if _tikwm_download(tiktok_url, out_path, prefer, progress_cb, _log):
            return True
    except Exception as e:
        _log(f"tiktok_hd: tikwm fallback failed ({e})")
    _safe_unlink(out_path)

    _log("tiktok_hd: all backends failed — caller falls back to yt-dlp")
    return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <tiktok_url> <out.mp4> [hd|sd|wm]")
        print("       (or: meta <tiktok_url>  to dump metadata)")
        sys.exit(2)
    if sys.argv[1] == "meta":
        print(json.dumps(get_metadata(sys.argv[2], log_cb=print), indent=2))
        sys.exit(0)
    url, out = sys.argv[1], Path(sys.argv[2])
    pref = sys.argv[3] if len(sys.argv) > 3 else "hd"
    ok = download(url, out, prefer=pref, log_cb=print)
    sys.exit(0 if ok else 1)
