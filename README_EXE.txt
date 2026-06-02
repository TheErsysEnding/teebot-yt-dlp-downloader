TEE yt-dlp Downloader  -  Plug & Play EXE
==========================================

A Windows downloader for TikTok, YouTube, Instagram, Twitter/X,
Facebook and ~1000 more platforms. This is the "just run it"
edition:

   >  NO Python required.
   >  NO installation, no pip, no setup.
   >  Just unzip and double-click the .exe.


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
HOW TO START
===================================================

  1. Unzip the WHOLE folder to a location of your choice
     (e.g. your Desktop or C:\Tools\).

     IMPORTANT: Extract the COMPLETE folder - do not pull
     out just the .exe. The .exe needs the "_internal"
     subfolder right next to it.

  2. Double-click:

         TEEbot_yt_dlp_Downloader.exe

  3. Done. The window opens and you can start downloading
     right away.

  Tip: Right-click the .exe -> "Send to" -> "Desktop
  (create shortcut)" for quick access.


===================================================
WHAT IS ALREADY INCLUDED (bundled)
===================================================

   -  yt-dlp (download engine)
   -  ffmpeg (merges video + audio)
   -  Deno runtime (for YouTube)
   -  gallery-dl (Instagram / Twitter / Facebook)
   -  Full GUI in 8 languages (EN/DE/ES/FR/IT/TR/RU/PL)

   YouTube, TikTok (HD, no watermark) and TikTok photos
   work instantly with no additional download.


===================================================
ONE-TIME DOWNLOAD: only for browser login
===================================================

   If you want to use Instagram / Facebook via the built-in
   browser login ("Open browser + log in"), the program
   downloads Chromium once on the FIRST click (~150 MB).
   This happens automatically with a progress bar. After
   that, never again.

   For plain YouTube / TikTok downloads you do NOT need this.


===================================================
HOW TO USE (quick)
===================================================

  SINGLE DOWNLOAD:
    1. Paste URL(s) into the field (one per line)
    2. Pick a quality (default: Best auto)
    3. Click "Download"

  ENTIRE CHANNEL:
    1. Purple "Channel Downloader" button at the top
    2. Paste the channel URL, filter by date (optional)
    3. Click "Load channel"

  TIKTOK HD:
    The "TikTok quality" dropdown is set to "No Watermark
    (HD)". It uses TTDownloader.com as the backend for
    real 1080p.


===================================================
WHERE DO MY FILES GO?
===================================================

  Default output:  %USERPROFILE%\Desktop\yt_dlp_GUI_Downloads\

    <Platform>/<Username>/Video/<Username>_video_<id>.mp4
    <Platform>/<Username>/Picture/<Username>_picture_<id>.jpg

  Settings + language:  %APPDATA%\teebot_yt_gui\settings.json


===================================================
TROUBLESHOOTING
===================================================

  -  Windows SmartScreen warns ("Unknown publisher"):
     -> "More info" -> "Run anyway".
     The .exe is not code-signed - that is normal for
     self-built tools.

  -  Antivirus flags the .exe -> false positive from
     PyInstaller builds. The full source is public on
     GitHub, so you can verify it or build it yourself:
     https://github.com/TheErsysEnding/teebot-yt-dlp-downloader

  -  "TikTok only downloads 540p" -> the "No Watermark (HD)"
     dropdown must be active.

  -  "Instagram: user not found" -> browser login needed
     ("Open browser + log in") OR provide a cookies.txt.


===================================================
LICENSE + CREDITS
===================================================

  Licensed under the GNU GPL v2.0. Built on open source:
    -  yt-dlp (Unlicense)      github.com/yt-dlp/yt-dlp
    -  gallery-dl (GPL-2.0)    github.com/mikf/gallery-dl
    -  CustomTkinter (MIT)     github.com/TomSchimansky/CustomTkinter
    -  Playwright (Apache-2)   playwright.dev
    -  Deno (MIT)              deno.com
    -  ffmpeg (LGPL/GPL)       ffmpeg.org

  Frontend / integration: TheErsysEnding
  Full project: github.com/TheErsysEnding/teebot-yt-dlp-downloader


===================================================
DISCLAIMER
===================================================

  Uses partly reverse-engineered APIs (TikTok HD via
  TTDownloader.com / tikwm.com). These can change or go
  offline at any time. Please respect copyright and only
  download content you are allowed to.


===================================================
   >>  linktr.ee/theersysending   -   @TheErsysEnding  <<
===================================================
