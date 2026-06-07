# Changelog

All notable changes to the **TEE yt-dlp Downloader** are documented here.
The project follows [Semantic Versioning](https://semver.org/).

## [1.2.0] — 2026-06-05

### Added
- **Settings window (⚙)** — a dedicated button (top-right, next to theme &
  language) opens a separate window holding Section/Trim, the filename scheme
  (incl. ID-mode), notifications and extras. The main view now stays clean —
  only the reset button remains at the bottom.
- **Custom filename template `{name}`** — put your own text at any position
  around the standard name, e.g. `TEE{name}` → `TEEMyVideo.mp4` or `{name}_yt`.
  The extension is added automatically; with a live preview.
- **Per-video Section/Trim** — the from/to trim no longer persists. It clears
  after each download and on restart (with a visible hint), so it never
  silently applies to the wrong video.
- **Trimmed downloads kept separately** — re-downloading a video with a trim
  now writes a distinct file (time range in the name, e.g.
  `… [1m00s-2m00s].mp4`) and keeps the original.
- **Windows filename-length protection** — overlong names are shortened to the
  Windows limit (255 chars / 260 path) while keeping your custom text and the
  extension; optionally switchable to "ask first".

### Fixed
- **Browser login no longer lost on re-open** — re-opening the integrated
  browser used to hard-kill it, discarding a fresh TikTok/Instagram login
  (lazily-written session). It now closes gracefully and flushes first.
- **Channel + date filter on YouTube returned nothing** — YouTube's flat
  enumeration has no upload date, so every item was dropped. Upload dates are
  now back-filled per item.
- **Rate-limit field** — non-numeric input (e.g. "5 MB") silently aborted the
  download; it is now parsed safely.
- **Cancel during the cookie auto-retry** — Stop now also affects the retry.
- **"Set creation date = upload date"** — fixed unreliable behavior + a handle
  leak on 64-bit Windows (CreateFileW handle truncation).
- **TikTok "skip existing"** — now matches any extension (the audio/MP3 mode
  re-downloaded every run before).
- **Channel statistics** — skipped/existing items are no longer counted as
  freshly downloaded.
- **Corrupt settings.json** — is backed up as `settings.json.corrupt` and
  logged instead of being silently overwritten with defaults.
- **Cookie export** — HttpOnly cookies are written with the `#HttpOnly_` prefix.
- **portable-reset** — the venv-cache skip now also recognizes
  `.venv` / `env` / `site-packages`.

### Changed
- **Container output uses remux instead of re-encoding** — mp4/webm/mkv are
  produced by stream-copy (fast, lossless) instead of always re-encoding.
- **"Overwrite: number"** now honestly behaves as "skip" (yt-dlp has no native
  conflict-numbering).
- Window title shows **v1.2**.

## [1.1.1] — 2026-06-02

### Fixed
- **Security:** enforce TLS certificate verification on the TikTok-HD and
  channel-download backends (removed an insecure permissive SSL context).
- **TikTok HD:** fixed a progress update that could freeze the live log and
  progress bar mid-download.
- **Channel downloader:** count a download as success only when a file is
  actually written; cleanly stop the dialog's polling loop on close.

### Changed
- Declared the `psutil` dependency (used by the cookie-browser watchdog).
- Documentation cleanup.

## [1.1] — 2026-05-31

### Added
- **Clear-history button** — a dedicated *"Clear history"* button next to the
  URL-history dropdown that wipes **only** the saved URL history, with a
  confirmation prompt. Available in all 8 UI languages.

### Fixed
- **Reset now clears the history for good** — the red *"delete all / portable
  reset"* button previously deleted `settings.json` on disk, but the running
  app still held the URLs in memory and re-saved them, so the history
  reappeared after a restart. The reset (and the new button) now also drop the
  in-memory history, so cleared links stay gone.

### Changed
- In-zip readme is now in **English** and named `README.txt` (previously
  `LIES_MICH.txt`, German).
- Added social links (Linktree / YouTube / TikTok / Instagram / Twitch) to the
  README and to both in-zip readmes.
- The window title now shows the version (**v1.1**).

## [1.0] — 2026-05-31

### Added
- Initial public release.
- Download from TikTok, YouTube, Instagram, Facebook, Twitter/X and 1000+ sites
  (powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp)).
- **TikTok HD** — true 1080p, no watermark, no login required (TTDownloader backend).
- **Channel Downloader** — batch entire YouTube / TikTok / Instagram channels
  with date- and media-type filters.
- **Cookie login** via the integrated browser (Instagram / Facebook).
- 8 UI languages, live log panel + popout, right-click context menus.
- Two distributions: standalone **EXE** (no Python needed) and a **Python
  bootstrap** that auto-installs its dependencies.
- Licensed under the **GNU GPL v2.0**.
