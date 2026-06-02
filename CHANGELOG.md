# Changelog

All notable changes to the **TEE yt-dlp Downloader** are documented here.
The project follows [Semantic Versioning](https://semver.org/).

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
