<p align="center">
  <img src="tools/branding/teebot.png" alt="TEEbot Logo" width="110">
</p>

<h1 align="center">TEE yt-dlp Downloader</h1>

<p align="center">
  A portable, feature-rich GUI downloader for TikTok, YouTube, Instagram and 1000+ platforms.<br>
  Built with <a href="https://github.com/yt-dlp/yt-dlp">yt-dlp</a> and CustomTkinter.
</p>

<p align="center">
  <a href="../../releases/latest"><img alt="Download" src="https://img.shields.io/github/v/release/TheErsysEnding/teebot-yt-dlp-downloader?label=Download&color=0d9488"></a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Windows-lightgrey">
  <img alt="License" src="https://img.shields.io/badge/License-GPLv2-blue">
</p>

<p align="center">
  <b>Made by TheErsysEnding</b> — gaming content, mods &amp; free tools like this one.
</p>

<p align="center">
  <a href="https://linktr.ee/theersysending"><img alt="Linktree" src="https://img.shields.io/badge/Linktree-all%20my%20links-39E09B?logo=linktree&logoColor=white"></a>
  <a href="https://www.youtube.com/@TheErsysEnding"><img alt="YouTube" src="https://img.shields.io/badge/YouTube-%40TheErsysEnding-FF0000?logo=youtube&logoColor=white"></a>
  <a href="https://www.tiktok.com/@theersysending"><img alt="TikTok" src="https://img.shields.io/badge/TikTok-%40theersysending-000000?logo=tiktok&logoColor=white"></a>
  <a href="https://www.instagram.com/theersysending"><img alt="Instagram" src="https://img.shields.io/badge/Instagram-%40theersysending-E4405F?logo=instagram&logoColor=white"></a>
  <a href="https://www.twitch.tv/theersysending"><img alt="Twitch" src="https://img.shields.io/badge/Twitch-theersysending-9146FF?logo=twitch&logoColor=white"></a>
</p>

---

## ✨ Features

- **1000+ sites** — TikTok, YouTube, Instagram, Facebook, Twitter/X and more (powered by yt-dlp)
- **TikTok HD** — true 1080p, no watermark, works without yt-dlp login
- **Channel Downloader** — batch-download entire YouTube / TikTok / Instagram channels
  - Date range filter, media-type filter (video / photo / audio only)
  - Automatic file-date = upload date
- **Multiple formats** — mp4, webm, mkv, mp3, m4a, flac, wav
- **Cookie support** — for login-required content (FSK18, private posts, etc.)
- **Right-click context menu** — copy / paste / cut in every text field
- **Live log panel** — always visible at the bottom, with popout window
- **8 languages** — German, English, Spanish, French, Italian, Turkish, Polish, Russian
- **Portable** — no installation required (EXE version)

---

## 📥 Download

| Version | Description | Download |
|---|---|---|
| **EXE Portable** | Standalone .exe — no Python needed, just unzip and run | [Latest Release →](../../releases/latest) |
| **Bootstrap** | Requires Python 3.10+ — auto-installs dependencies on first run | [Latest Release →](../../releases/latest) |

---

## 🚀 Usage

### EXE Version (recommended — no Python required)
1. Download `TEEbot_yt_dlp_Downloader_EXE_v1.zip` from [Releases](../../releases/latest)
2. Extract to any folder
3. Run `TEEbot_yt_dlp_Downloader.exe`

### Bootstrap Version (Python 3.10+ required)
1. Download `TEEbot_yt_dlp_Downloader_v1.zip` from [Releases](../../releases/latest)
2. Extract to any folder
3. Double-click **`1_INSTALL.cmd`** (first time only — installs dependencies)
4. Double-click **`2_START.cmd`** to launch

---

## 🏗️ Build from Source

```bash
git clone https://github.com/TheErsysEnding/teebot-yt-dlp-downloader.git
cd teebot-yt-dlp-downloader

pip install -r requirements.txt
python teebot_launcher.py
```

To build the standalone EXE (requires PyInstaller + Deno runtime in `runtime/deno.exe`):
```bash
pip install pyinstaller
pyinstaller --clean --noconfirm teebot.spec
```

---

## 🙏 Credits & Acknowledgements

This project would not exist without these outstanding open-source projects:

| Project | License | Used for |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense | Core download engine (1000+ sites) |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) | MIT | Modern dark/light GUI framework |
| [tkcalendar](https://github.com/j4321/tkcalendar) | MIT | Date-range picker |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | BSD-2-Clause | Bundled ffmpeg binary |
| [gallery-dl](https://github.com/mikf/gallery-dl) | GPL-2.0 | Image gallery downloads |
| [Playwright](https://playwright.dev/) | Apache-2.0 | Integrated browser for cookie extraction |
| [curl_cffi](https://github.com/lexiforest/curl_cffi) | MIT | TLS-fingerprint stealth requests |
| [Deno](https://deno.com/) | MIT | JS runtime for YouTube signature solving |
| [Babel](https://babel.pocoo.org/) | BSD-3-Clause | Locale & date formatting |
| [winotify](https://github.com/versa-syahptr/winotify) | MIT | Windows toast notifications |
| [TTDownloader](https://ttdownloader.com/) | — | TikTok HD download backend |
| [tikwm.com](https://www.tikwm.com/) | — | TikTok metadata API |

---

## ❤️ Follow the Creator — TheErsysEnding

If this tool saved you time, a follow or sub really helps me keep building free tools like this!

> ### 👉 [**linktr.ee/theersysending**](https://linktr.ee/theersysending) — all my links in one place

| Platform | Link |
|---|---|
| ▶️ **YouTube** | [@TheErsysEnding](https://www.youtube.com/@TheErsysEnding) |
| 🎵 **TikTok** | [@theersysending](https://www.tiktok.com/@theersysending) |
| 📸 **Instagram** | [@theersysending](https://www.instagram.com/theersysending) |
| 🎮 **Twitch** | [theersysending](https://www.twitch.tv/theersysending) |

Gaming content, mods and free tools. Thanks for the support! 🙌

---

## 📄 License

[GNU General Public License v2.0](LICENSE) — Copyright © 2026 [TheErsysEnding](https://www.youtube.com/@TheErsysEnding)

This project bundles [gallery-dl](https://github.com/mikf/gallery-dl), which is licensed
under **GPL-2.0**, so the project as a whole is distributed under the **GNU GPL v2.0**.
You may use, modify and redistribute it freely, provided that derivative works remain
under the GPL and that the corresponding source code is made available. See
[LICENSE](LICENSE) for the full terms.
