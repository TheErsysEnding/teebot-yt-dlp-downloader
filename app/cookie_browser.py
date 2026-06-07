"""In-app browser login → cookies.txt export (Playwright + Chromium).

Standalone subprocess module — designed to be spawned by yt_dlp_gui.py
or any other module that needs site cookies without forcing the user to
juggle browser extensions.

Usage from CLI:
    python -m autonomous.cookie_browser <url> --out <cookies.txt> [--site youtube]

Flow:
    1. Launches Playwright Chromium with a persistent user-data-dir under
       data/playwright_profiles/<site>/ so login state survives across runs.
    2. Navigates to <url> (e.g. https://www.youtube.com).
    3. Waits until the user closes the browser window.
    4. Reads ALL cookies (including HttpOnly Secure ones — yt-dlp needs
       these for YouTube auth) from the persistent context, converts to
       Netscape format, writes to <out>.
    5. Exit 0 on success, 1 on cancellation/error.

The persistent dir means: log in once, every future spawn reuses the
session. To "log out", the GUI can offer a "Profil zuruecksetzen" button
that deletes data/playwright_profiles/<site>/.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = ROOT / "data" / "playwright_profiles"


def _focus_window_by_pid_title(url_hint: str) -> None:
    """Bring the Chromium login window to the foreground on Windows.

    Playwright + page.bring_to_front() only changes the Chromium-internal
    tab focus, not the OS-level window Z-order. So if the user has other
    windows on top, our browser opens behind them and the user sees
    nothing happen. We fix this with SetForegroundWindow.

    Identifies the right window by chrome.exe process whose MainWindowTitle
    looks like a login page (best-effort substring match).
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import ctypes.wintypes as wt
        import time as _t

        user32 = ctypes.windll.user32

        # Give Chromium a moment to actually create its window
        _t.sleep(0.6)

        # Find chrome.exe windows; pick the topmost one with a non-empty title
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, wt.HWND, wt.LPARAM)
        candidates = []

        def _cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            # Chromium-for-Testing windows have this exact substring
            if "Chrome" in title or "Chromium" in title:
                candidates.append((hwnd, title))
            return True

        user32.EnumWindows(EnumWindowsProc(_cb), 0)
        if not candidates:
            return

        # Heuristic: prefer titles that look like a login page
        url_keywords = ["login", "signin", "sign in", "anmelden", "log in"]
        best = None
        for hwnd, title in candidates:
            tlow = title.lower()
            if any(k in tlow for k in url_keywords):
                best = hwnd
                break
        if best is None:
            best = candidates[0][0]

        # Windows restricts SetForegroundWindow from background apps to
        # prevent annoying focus theft. So we use a layered approach:
        #   1. Restore from minimized (if any)
        #   2. SetWindowPos(HWND_TOPMOST) — this *does* work from any
        #      process and yanks the window to the top of Z-order
        #   3. SetWindowPos(HWND_NOTOPMOST) — release topmost so the
        #      window behaves normally (user can put other things on top)
        #   4. FlashWindowEx — taskbar flashes so the user definitely sees
        user32.ShowWindow(best, 9)   # SW_RESTORE

        # SetWindowPos flags
        SWP_NOMOVE   = 0x0002
        SWP_NOSIZE   = 0x0001
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        HWND_TOPMOST    = -1
        HWND_NOTOPMOST  = -2

        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
        user32.SetWindowPos(best, HWND_TOPMOST,    0, 0, 0, 0, flags)
        user32.SetWindowPos(best, HWND_NOTOPMOST,  0, 0, 0, 0, flags)
        user32.BringWindowToTop(best)

        # Best-effort foreground (works if no other app is "actively"
        # holding focus — most of the time it does, even from background)
        user32.SetForegroundWindow(best)

        # Flash the taskbar entry as a guaranteed visible signal
        class FLASHWINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("hwnd", wt.HWND),
                ("dwFlags", ctypes.c_uint),
                ("uCount", ctypes.c_uint),
                ("dwTimeout", ctypes.c_uint),
            ]
        FLASHW_ALL = 0x03
        FLASHW_TIMERNOFG = 0x0C
        fi = FLASHWINFO(
            cbSize=ctypes.sizeof(FLASHWINFO),
            hwnd=best,
            dwFlags=FLASHW_ALL | FLASHW_TIMERNOFG,
            uCount=6,
            dwTimeout=0,
        )
        user32.FlashWindowEx(ctypes.byref(fi))
    except Exception:
        pass


def cookies_to_netscape(cookies: Iterable[dict]) -> str:
    """Convert Playwright cookie dicts to Netscape cookies.txt format.

    yt-dlp / curl / wget all read this format. Spec: each tab-separated
    line is `domain  flag  path  secure  expiration  name  value` where:
      - flag = TRUE if domain applies to subdomains (leading '.')
      - secure = TRUE / FALSE
      - expiration = unix timestamp; 0 for session cookies
    """
    out = [
        "# Netscape HTTP Cookie File",
        "# Generated by TEEbot cookie_browser — do not edit.",
        "",
    ]
    for c in cookies:
        domain = c.get("domain", "")
        if not domain:
            continue
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expires = c.get("expires", -1)
        # Playwright uses -1 for session cookies; Netscape uses 0
        exp_int = 0 if expires is None or expires < 0 else int(expires)
        name = c.get("name", "")
        value = c.get("value", "")
        # Skip blank cookies (malformed)
        if not name:
            continue
        # yt-dlp/curl markieren HttpOnly-Cookies mit dem Zeilen-Prefix
        # "#HttpOnly_" vor der Domain — sonst geht das Flag beim Re-Export
        # verloren bzw. manche Parser verwerfen die Zeile.
        dom_field = ("#HttpOnly_" + domain) if c.get("httpOnly") else domain
        out.append(
            f"{dom_field}\t{include_subdomains}\t{path}\t{secure}\t"
            f"{exp_int}\t{name}\t{value}"
        )
    return "\n".join(out) + "\n"


# ─── Stealth-Args (Author) ──────────────────────────────────
# TikTok/Instagram/Twitter/Facebook fingerprinten viel aggressiver als
# YouTube. Ohne diese Liste setzen sie nur SESSION-Cookies die beim
# Schliessen weg sind — wir kriegen also einen "Login gespeichert"-Hinweis,
# aber beim naechsten Mal ist man ausgeloggt.
#
# Quellen + Begruendung:
#   - --disable-blink-features=AutomationControlled  : entfernt navigator.webdriver
#   - --disable-features=IsolateOrigins,site-per-process : verhindert iframe-cross-origin
#     leaks die manche Detection-Skripte triggern
#   - --disable-features=AutomationControlled : noch ein Layer
#   - --no-sandbox erst NICHT setzen (manche Sites checken auf no-sandbox als
#     bot-signal); Playwright-default ist OK
#
# REALER Chrome-User-Agent (NICHT Chromium-for-Testing!):
#   - Chromium-for-Testing UA hat "HeadlessChrome" + Version-Suffix die TikTok
#     direkt als Bot flaggt
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process,AutomationControlled",
    "--disable-infobars",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-dev-shm-usage",
    "--disable-popup-blocking",
    # Realistische Window-Size (1920x1080 ist haeufigste real-user-Aufloesung)
    "--window-size=1280,900",
]

# Aktuelle Chrome 131 stable User-Agents (Mai 2026 — periodisch updaten!).
# Wir wollen NICHT die Chromium-for-Testing UA weil die TikTok bot-flag triggert.
STEALTH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _site_specific_url(site: str, url: str) -> str:
    """Manche Plattformen haben eine bessere Login-URL als die Homepage.
    Z.B. tiktok.com leitet beim ersten Besuch oft zu region-spez. Seiten
    weiter — direkt /login zu navigieren ist robuster."""
    site_map = {
        "tiktok":    "https://www.tiktok.com/login",
        "instagram": "https://www.instagram.com/accounts/login/",
        "twitter":   "https://x.com/login",
        "facebook":  "https://www.facebook.com/login",
        "youtube":   "https://accounts.google.com/ServiceLogin?service=youtube",
    }
    return site_map.get(site, url)


def run_login(url: str, out_path: Path, site: str) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright",
              file=sys.stderr)
        return 2

    profile_dir = PROFILES_DIR / site
    profile_dir.mkdir(parents=True, exist_ok=True)
    # Externes "sauber schliessen"-Signal vom GUI (graceful restart). Liegt
    # diese Datei vor, brechen wir die Warteschleife ab und flushen sauber —
    # statt vom Eltern-Prozess hart gekillt zu werden. Ohne das geht ein
    # frischer Login in localStorage/IndexedDB verloren (TikTok/Instagram!).
    stop_file = profile_dir / ".close_request"
    try:
        if stop_file.exists():
            stop_file.unlink()
    except Exception:
        pass

    # Prefer site-specific login URL if user just passed the homepage
    eff_url = _site_specific_url(site, url) if url == "homepage" else url

    print(f"[cookie_browser] profile: {profile_dir}")
    print(f"[cookie_browser] url:     {eff_url}")
    print(f"[cookie_browser] output:  {out_path}")
    print(f"[cookie_browser] site:    {site}")
    print("[cookie_browser] launching Chromium — close the window when "
          "you're done logging in.")

    with sync_playwright() as p:
        # Persistent context = real user-data-dir, cookies survive restarts.
        # headless=False is mandatory (login needs UI). Args mirror a real
        # desktop Chrome so TikTok/Instagram don't fingerprint us as bot.
        launch_kwargs = dict(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 800},
            user_agent=STEALTH_USER_AGENT,
            locale="de-DE",                          # Realistisch fuer DE-User
            timezone_id="Europe/Berlin",             # Konsistent mit Locale
            args=STEALTH_ARGS,
            ignore_default_args=[
                "--enable-automation",
                "--enable-blink-features=IdleDetection",
            ],
            # Try real Chrome first; if not installed, falls back to bundled
            # Chromium. Real Chrome has way less bot-fingerprint surface.
            channel="chrome",
        )
        try:
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        except Exception as e:
            # Fallback: real Chrome nicht installiert → bundled Chromium
            print(f"[cookie_browser] real Chrome unavailable ({e}), "
                  f"falling back to bundled Chromium")
            launch_kwargs.pop("channel", None)
            ctx = p.chromium.launch_persistent_context(**launch_kwargs)

        # Inject a tiny stealth script BEFORE any page navigation. This
        # overwrites navigator.webdriver = false, fakes plugins, and patches
        # the WebGL renderer string. Together this passes 90% of standard
        # bot-detection checks (incl. TikTok's "human verification").
        try:
            ctx.add_init_script("""
                // 1. navigator.webdriver — always undefined for real Chrome
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                // 2. Plugins — empty array on Chromium, real Chrome has PDF viewer
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [
                        {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
                        {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
                        {name: 'Native Client', filename: 'internal-nacl-plugin'}
                    ]
                });
                // 3. Languages — must match Accept-Language header
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['de-DE', 'de', 'en-US', 'en']
                });
                // 4. WebGL renderer string — Chromium reports 'SwiftShader',
                // real GPUs report actual vendor. Fake an Nvidia GPU.
                const origGetParam = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(p) {
                    if (p === 37445) return 'Google Inc. (NVIDIA)';
                    if (p === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11)';
                    return origGetParam.call(this, p);
                };
                // 5. Chrome runtime — must exist
                window.chrome = window.chrome || { runtime: {} };
                // 6. Permissions API quirk — real Chrome handles 'notifications' specially
                const origQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (p) => (
                    p.name === 'notifications'
                        ? Promise.resolve({state: Notification.permission})
                        : origQuery(p)
                );
            """)
        except Exception as e:
            print(f"[cookie_browser] stealth-script inject failed: {e}")

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # Re-bind eff_url so the goto uses the site-specific login URL
        url = eff_url
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"[cookie_browser] WARN navigation: {e}")

        # Force the window to the foreground. Playwright launches Chromium
        # in the background by default on Windows; without this the user
        # only sees their taskbar flash and thinks "nothing happened".
        try:
            page.bring_to_front()
        except Exception:
            pass
        _focus_window_by_pid_title(url)

        # Detection strategy for "user is done": LAYERED so we don't get
        # stuck if any single signal misfires.
        #   1. ctx.on("close") — fires when the whole BrowserContext dies
        #   2. page.on("close") — fires on each tab close
        #   3. Periodic heartbeat — try ctx.cookies(); fails if browser
        #      died without firing a clean close event
        #   4. Hard timeout — never block longer than 30 min
        # Earlier version only checked ctx.pages and never noticed when
        # the user closed the last tab via the X button (Playwright keeps
        # the dead Page object in ctx.pages briefly).
        closed = [False]

        def _on_close(_evt=None):
            closed[0] = True

        ctx.on("close", _on_close)

        def _wire_page(pg):
            pg.on("close", _on_close)
        for pg in ctx.pages:
            _wire_page(pg)
        # New tabs the user opens should also trigger close detection
        ctx.on("page", _wire_page)

        # Cache the cookies right before close so we still have them if
        # the browser dies abruptly between our last heartbeat and the
        # close event.
        cookies = []
        deadline = time.time() + 30 * 60   # 30 min hard cap
        last_heartbeat = 0.0
        try:
            while not closed[0] and time.time() < deadline:
                time.sleep(0.4)
                # Externes Schliess-Signal vom GUI? -> graceful beenden (der
                # Flush-Code unten schreibt dann Cookies/localStorage auf Platte)
                try:
                    if stop_file.exists():
                        stop_file.unlink()
                        print("[cookie_browser] stop-request -> graceful close")
                        closed[0] = True
                        break
                except Exception:
                    pass
                # Heartbeat every 2s: snapshot cookies + verify browser alive
                if time.time() - last_heartbeat > 2.0:
                    last_heartbeat = time.time()
                    try:
                        cookies = ctx.cookies() or cookies
                    except Exception:
                        # Browser died without close event → treat as done
                        print("[cookie_browser] browser unreachable, "
                              "treating as closed")
                        closed[0] = True
                        break
                    # All tabs gone? user clicked X on the last tab
                    if not ctx.pages:
                        closed[0] = True
                        break
        except KeyboardInterrupt:
            print("[cookie_browser] interrupted")

        # Try one last cookie snapshot (may fail if browser is fully dead
        # — that's fine, we have the heartbeat snapshot as fallback)
        try:
            fresh = ctx.cookies()
            if fresh:
                cookies = fresh
        except Exception:
            pass

        # IMPORTANT for TikTok/Instagram/Twitter/Facebook:
        # Chromium writes localStorage + IndexedDB to disk LAZILY. If we
        # close ctx immediately after the user clicks X, the in-memory
        # auth tokens may never reach the user-data-dir on disk → next
        # browser-open looks ausgeloggt. Wait 1.5s for Chrome's storage
        # flush thread to fsync. Also explicitly call storage_state() to
        # force a checkpoint.
        try:
            time.sleep(1.5)
            _ = ctx.storage_state()  # forces a flush
        except Exception:
            pass

        try:
            ctx.close()
        except Exception:
            pass

        # Extra grace period for Chrome's profile lock to release. Without
        # this, the *next* spawn occasionally hits "ProfileDirectory in use"
        # because the OS hasn't released the lockfile yet.
        try:
            time.sleep(0.5)
        except Exception:
            pass

    if not cookies:
        print("[cookie_browser] no cookies captured", file=sys.stderr)
        return 1

    netscape = cookies_to_netscape(cookies)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(netscape, encoding="utf-8")
    print(f"[cookie_browser] wrote {len(cookies)} cookies -> {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="URL to navigate to (login page or homepage)")
    ap.add_argument("--out", required=True, type=Path,
                    help="Output path for cookies.txt")
    ap.add_argument("--site", default="default",
                    help="Profile bucket name (e.g. youtube, tiktok, instagram)")
    args = ap.parse_args(argv)
    return run_login(args.url, args.out, args.site)


if __name__ == "__main__":
    sys.exit(main())
