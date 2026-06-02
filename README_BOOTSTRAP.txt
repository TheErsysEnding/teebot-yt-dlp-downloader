TEE yt-dlp Downloader
=====================

A native Windows downloader for TikTok, YouTube, Instagram, Twitter/X,
Facebook and ~1000 more video platforms. Downloads in the highest
available quality, with audio track and clean file naming.

   -  TikTok videos in 1080p HEVC without watermark (TTDownloader backend)
   -  TikTok photo carousels (all images at once)
   -  YouTube up to 8K when available
   -  Channel downloader for entire accounts with date filter
   -  Built-in browser login for Instagram / Facebook (persistent)
   -  8 languages: EN / DE / ES / FR / IT / TR / RU / PL


===================================================
  *  FOLLOW THE CREATOR  --  TheErsysEnding  *
===================================================

   All my links in one place:

         >>>  https://linktr.ee/theersysending  <<<

   YouTube   -  https://www.youtube.com/@TheErsysEnding
   TikTok    -  https://www.tiktok.com/@theersysending
   Instagram -  https://www.instagram.com/theersysending
   Twitch    -  https://www.twitch.tv/theersysending

   Gaming content, mods and free tools like this one.
   If this saved you time, a follow or sub really helps!


===================================================
WHAT YOU NEED (system requirements)
===================================================

  -  Windows 10 or 11 (64-bit)
  -  Python 3.11 or higher
        -> https://www.python.org/downloads/
        -> During install, MAKE SURE to tick
           "Add Python to PATH"!
  -  Internet connection (for the first-time install
     + per download afterwards)
  -  About 500 MB free space for the installation
     (Python venv + Chromium + Deno)
  -  A browser (Chrome recommended) if you want to use
     Instagram / Facebook cookies


===================================================
INSTALLATION (one time)
===================================================

  1. Unzip this folder to a location of your choice.
     Recommended: C:\Program Files\TEE_yt_dlp\
     OR:          D:\Tools\TEE_yt_dlp\

  2. Double-click "1_INSTALL.cmd"

     The script:
       -  checks whether Python is present
       -  creates a 'venv' folder
       -  downloads yt-dlp + all other packages (~150 MB)
       -  downloads Chromium for the browser login (~150 MB)
       -  downloads Deno for the YouTube extraction (~40 MB)

     Duration: 3-10 minutes depending on your connection.


===================================================
HOW TO START
===================================================

  -> Double-click "2_START.cmd"

  If you use it often, you can create a desktop shortcut
  from "2_START.cmd" (right-click -> "Send to" -> "Desktop").


===================================================
HOW TO USE (quick tutorial)
===================================================

  SINGLE DOWNLOAD:
    1. Paste a URL into the URL field
       (one per line for several)
    2. Pick a quality (default: Best auto)
    3. Choose an output folder
    4. Click "Download"

  ENTIRE CHANNEL:
    1. Click the purple "Channel Downloader" button at the top
    2. Paste the channel URL
    3. Filter by date (optional, click the calendar)
    4. Choose max items
    5. Click "Load channel"

  TIKTOK HD:
    Automatic. The "TikTok quality" dropdown on the right is
    preset to "No Watermark (HD)" - it uses TTDownloader.com
    as the backend instead of yt-dlp so you get real 1080p.

  INSTAGRAM / FACEBOOK LOGIN:
    In the "Cookies" area:
    Click "Open browser + log in"
    -> a browser opens -> log in -> close the window
    Cookies are saved automatically.


===================================================
WHERE DO MY FILES GO?
===================================================

  Default output: %USERPROFILE%\Desktop\yt_dlp_GUI_Downloads\

  Structure:
    <Platform>/<Username>/Video/<Username>_video_<id>.mp4
    <Platform>/<Username>/Picture/<Username>_picture_<id>.jpg

  Examples:
    YouTube/TheErsysEnding/Video/TheErsysEnding_video_aBcd1234XyZ.mp4
    TikTok/TheErsysEnding/Picture/TheErsysEnding_picture_7589012345_01.jpg

  Settings + language:  %APPDATA%\teebot_yt_gui\settings.json


===================================================
TROUBLESHOOTING
===================================================

  -  "Python was not found" -> reinstall Python and tick
     "Add Python to PATH" during setup.

  -  "Playwright Chromium missing" -> run 1_INSTALL.cmd again.

  -  "TikTok only downloads 540p" -> see the TikTok quality
     dropdown, "No Watermark (HD)" must be active.

  -  "Instagram channel: user not found" -> you need a login.
     Click "Open browser + log in".


===================================================
LICENSE + CREDITS
===================================================

  Licensed under the GNU GPL v2.0. Built on these
  open-source tools:
    -  yt-dlp (Unlicense) - github.com/yt-dlp/yt-dlp
    -  gallery-dl (GPL-2.0) - github.com/mikf/gallery-dl
    -  CustomTkinter (MIT) - github.com/TomSchimansky/CustomTkinter
    -  Playwright (Apache-2) - playwright.dev
    -  tikwm.com & ttdownloader.com - external web services

  Frontend / integration: TheErsysEnding
  Full project: github.com/TheErsysEnding/teebot-yt-dlp-downloader

  This distribution downloads the tools on first launch
  from their official sources - the ZIP only contains the
  GUI source and small bootstrap scripts.


===================================================
DISCLAIMER
===================================================

  This tool uses reverse-engineered APIs (TikTok HD via
  TTDownloader.com, tikwm.com). These can change or go
  offline at any time.

  Please respect the copyright of your sources. Only use
  this tool for content you are allowed to download
  (your own videos, public domain, your own backups, ...).


===================================================
   >>  linktr.ee/theersysending   -   @TheErsysEnding  <<
===================================================
