"""Windows-Toast-Notification Helper.

Versucht in dieser Reihenfolge:
  1. winotify (pip-Paket, native Toast-API)
  2. PowerShell BurntToast / Windows.UI.Notifications via .NET
  3. tkinter.messagebox als Fallback (immer funktioniert)

Returns True wenn Toast ueberhaupt angezeigt werden konnte.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional


def _try_winotify(title: str, body: str) -> bool:
    """Versuche winotify (pip install winotify)."""
    try:
        from winotify import Notification, audio  # type: ignore
        n = Notification(
            app_id="yt-dlp GUI",
            title=title[:64],
            msg=body[:200],
            duration="short",
        )
        n.set_audio(audio.Default, loop=False)
        n.show()
        return True
    except Exception:
        return False


def _try_powershell(title: str, body: str) -> bool:
    """Versuche PowerShell mit Windows-Native-Toast-API.

    Nutzt [Windows.UI.Notifications.ToastNotificationManager] direkt -
    keine zusaetzliche Dependency. Funktioniert auf Win10/Win11.
    """
    if sys.platform != "win32":
        return False
    # Title und Body XML-escapen
    safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ps_script = f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime] | Out-Null
$xml = @'
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{safe_title}</text>
      <text>{safe_body}</text>
    </binding>
  </visual>
</toast>
'@
$doc = [Windows.Data.Xml.Dom.XmlDocument]::new()
$doc.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('yt-dlp GUI')
$notifier.Show($toast)
"""
    try:
        # -NoProfile schneller, -WindowStyle Hidden = kein PS-Fenster sichtbar
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden",
             "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=10,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        return result.returncode == 0
    except Exception:
        return False


def _try_tk_messagebox(title: str, body: str) -> bool:
    """Last-Resort Fallback: Tk-Popup. Funktioniert immer."""
    try:
        import threading

        def _show():
            try:
                from tkinter import messagebox, Tk
                root = Tk()
                root.withdraw()
                messagebox.showinfo(title, body)
                root.destroy()
            except Exception:
                pass

        # In separatem Thread damit nicht blockierend
        t = threading.Thread(target=_show, daemon=True)
        t.start()
        return True
    except Exception:
        return False


def show_toast(title: str, body: str, force: bool = False) -> bool:
    """Zeigt einen Windows-Toast.

    Args:
      title: Title-Zeile (max 64 Zeichen)
      body:  Body-Text  (max 200 Zeichen)
      force: True = niemals fallback auf Tk-Messagebox (sonst doch)

    Returns True wenn Toast (irgendwie) angezeigt wurde.
    """
    # 1. winotify
    if _try_winotify(title, body):
        return True
    # 2. PowerShell native
    if _try_powershell(title, body):
        return True
    # 3. Fallback Tk
    if not force:
        return _try_tk_messagebox(title, body)
    return False


def is_available() -> tuple[bool, str]:
    """Quick-Check ob Toast-Notifications technisch moeglich sind.

    Returns (available, mechanism). mechanism = 'winotify' | 'powershell'
    | 'tk-fallback' | 'none'.
    """
    try:
        from winotify import Notification  # noqa
        return True, "winotify"
    except ImportError:
        pass
    if sys.platform == "win32":
        return True, "powershell"
    return True, "tk-fallback"
