"""Channel Downloader Modal Dialog (Author).

A standalone CTkToplevel window opened from the main yt-dlp GUI. Lets
the user:
    - Paste a channel URL (YouTube/TikTok/Instagram/Twitter/Facebook)
    - Pick a date range via tkcalendar DateEntry
    - Filter by media type (videos / pictures / both)
    - Cap the item count (0 = unlimited, warns if > 500)
    - Hit Download — runs in a background thread, progress bar updates

Folder layout produced (auto-created):
    <output_dir>/<Platform>/<Username>/Video/...
    <output_dir>/<Platform>/<Username>/Picture/...

This file is imported lazily by yt_dlp_gui.py to keep startup fast.
"""
from __future__ import annotations

import datetime as _dt
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

# Right-click context menu (cut/copy/paste). Class-level bindings from the
# main window usually already cover this dialog (same Tk interpreter), but we
# attach again for the standalone case — it's idempotent per interpreter.
try:
    from . import context_menu as _ctxmenu
except ImportError:
    import importlib.util as _ilu_cm
    _spec_cm = _ilu_cm.spec_from_file_location(
        "context_menu", Path(__file__).resolve().parent / "context_menu.py")
    _ctxmenu = _ilu_cm.module_from_spec(_spec_cm)
    _spec_cm.loader.exec_module(_ctxmenu)
    sys.modules["context_menu"] = _ctxmenu

# tkcalendar lives in venv; without it we degrade to manual date entry.
# NOTE: We use tkcalendar.Calendar (the full inline widget) NOT DateEntry.
# DateEntry is a popup-based widget where clicking the year arrows steals
# focus and closes the popup — making it impossible to change the year.
# Our custom popup uses Calendar inside a CTkToplevel that stays open
# until the user explicitly picks a date.
try:
    from tkcalendar import Calendar as _TkCal
    _HAS_TKCAL = True
except ImportError:
    _HAS_TKCAL = False
    _TkCal = None  # type: ignore


class _DatePopupButton(ctk.CTkFrame):
    """A button that opens a calendar popup. The popup contains the full
    tkcalendar.Calendar widget (NOT the broken DateEntry popup).

    Click button -> popup opens with calendar + Year arrows that WORK.
    Click date or press OK -> popup closes, button shows the date.
    Click "Löschen" -> date cleared (= no filter).
    """

    def __init__(self, master, label_when_empty: str = "—", **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._date: Optional[_dt.date] = None
        self._label_empty = label_when_empty
        self._popup: Optional[ctk.CTkToplevel] = None
        self._cal_widget = None
        self.btn = ctk.CTkButton(
            self, text=label_when_empty, width=120, height=28,
            fg_color=("gray85", "gray25"),
            hover_color=("gray75", "gray35"),
            text_color=("gray20", "gray80"),
            command=self._open_popup,
        )
        self.btn.pack()

    def get_date(self) -> Optional[_dt.date]:
        return self._date

    def set_date(self, d: Optional[_dt.date]) -> None:
        self._date = d
        self.btn.configure(
            text=d.isoformat() if d else self._label_empty,
            fg_color=("#7c3aed", "#7c3aed") if d else ("gray85", "gray25"),
            text_color=("white", "white") if d else ("gray20", "gray80"),
        )

    def clear(self) -> None:
        self.set_date(None)

    def _open_popup(self) -> None:
        if not _HAS_TKCAL:
            return  # fallback: do nothing (caller can use a text entry)
        # Singleton-popup per button
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.lift()
            return
        self._popup = ctk.CTkToplevel(self)
        self._popup.title("Datum wählen")
        self._popup.resizable(False, False)
        # Position popup near the button
        try:
            x = self.btn.winfo_rootx()
            y = self.btn.winfo_rooty() + self.btn.winfo_height() + 2
            self._popup.geometry(f"+{x}+{y}")
        except Exception:
            pass

        # Build the full Calendar widget. Year navigation works because
        # it's INSIDE the popup, not a popup-of-popup.
        init = self._date or _dt.date.today()
        self._cal_widget = _TkCal(
            self._popup, selectmode="day",
            year=init.year, month=init.month, day=init.day,
            date_pattern="yyyy-mm-dd",
            locale="de_DE",
            showweeknumbers=False,
            background="#7c3aed", foreground="white",
            headersbackground="#1f1f1f", headersforeground="white",
            selectbackground="#7c3aed", selectforeground="white",
            normalbackground="#ffffff", normalforeground="black",
            weekendbackground="#ffffff", weekendforeground="black",
            othermonthbackground="#f5f5f5", othermonthwebackground="#f5f5f5",
            bordercolor="#cccccc",
        )
        self._cal_widget.pack(padx=8, pady=8)

        # Buttons row
        btns = ctk.CTkFrame(self._popup, fg_color="transparent")
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(
            btns, text="OK", width=80,
            fg_color="#7c3aed", hover_color="#6d28d9",
            command=self._on_pick,
        ).pack(side="right", padx=2)
        ctk.CTkButton(
            btns, text="Abbrechen", width=80,
            fg_color="gray40", hover_color="gray30",
            command=self._on_cancel,
        ).pack(side="right", padx=2)
        ctk.CTkButton(
            btns, text="🗑 Löschen", width=100,
            fg_color="gray40", hover_color="gray30",
            command=self._on_clear,
        ).pack(side="left", padx=2)
        # Double-click on a day fires OK directly
        try:
            self._cal_widget.bind("<<CalendarSelected>>",
                                    lambda _e: None)  # placeholder
            # Real shortcut: <Double-Button-1> on the widget commits
            self._cal_widget.bind("<Double-Button-1>",
                                    lambda _e: self._on_pick())
        except Exception:
            pass
        self._popup.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._popup.transient(self.winfo_toplevel())
        # NOT grab_set — that breaks the Year arrows in some Tk builds.
        # User can still interact with main window which is fine.

    def _on_pick(self) -> None:
        if self._cal_widget is None:
            return
        try:
            ds = self._cal_widget.get_date()
            self.set_date(_dt.date.fromisoformat(ds))
        except Exception:
            pass
        self._close_popup()

    def _on_clear(self) -> None:
        self.clear()
        self._close_popup()

    def _on_cancel(self) -> None:
        self._close_popup()

    def _close_popup(self) -> None:
        try:
            if self._popup is not None:
                self._popup.destroy()
        finally:
            self._popup = None
            self._cal_widget = None

# Lazy import to avoid pulling yt-dlp at GUI-construction time
_cd = None  # filled on first use


def _ensure_channel_downloader():
    global _cd
    if _cd is None:
        try:
            from . import channel_downloader as _cd_mod
        except ImportError:
            import importlib.util as _ilu
            _here = Path(__file__).resolve().parent
            _spec = _ilu.spec_from_file_location(
                "channel_downloader", _here / "channel_downloader.py")
            _cd_mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_cd_mod)
        _cd = _cd_mod
    return _cd


class ChannelDownloaderDialog(ctk.CTkToplevel):
    """Modal-ish window for channel/bulk downloads.

    Not strictly modal (user can still use the main window), but visually
    a separate window with its own progress + log. Closing the window
    cancels the background download.
    """

    def __init__(self, master, default_output_dir: str = "",
                 default_cookies_file: str = "",
                 use_id_filename: bool = True):
        super().__init__(master)
        self.title("📥 Channel-Downloader — gesamte Accounts ziehen")
        self.geometry("780x720")
        self.minsize(720, 600)

        # Inherit launcher icon if available
        try:
            ico = (Path(__file__).resolve().parent.parent
                    / "tools" / "branding" / "teebot.ico")
            if ico.exists():
                self.after(200, lambda: self.iconbitmap(str(ico)))
        except Exception:
            pass

        # Defaults from settings
        self._default_output = default_output_dir or str(
            Path.home() / "Desktop" / "yt_dlp_GUI_Downloads")
        self._default_cookies = default_cookies_file
        self._use_id_filename = use_id_filename

        # Background worker state
        self._log_queue: queue.Queue = queue.Queue()
        self._cancel_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        self._build_ui()
        # Rechtsklick-Menü (Ausschneiden/Kopieren/Einfügen) für alle Felder
        try:
            _ctxmenu.attach_context_menu(self)
        except Exception:
            pass
        self._poll_log_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.lift()
        self.focus_force()

    # ───────────────── UI ─────────────────

    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=15, pady=(12, 5))
        ctk.CTkLabel(
            hdr, text="📥 Channel-Downloader",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            hdr,
            text="Lade gesamte YouTube/TikTok/Instagram/Twitter-Kanäle "
                 "mit Datums- und Medientyp-Filter.",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            wraplength=500,
        ).pack(side="left", padx=15)

        # Scrollable body so small windows still show everything
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=5)

        # ── Channel URL ──
        url_frame = ctk.CTkFrame(body)
        url_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(
            url_frame, text="🔗  Channel-URL:",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(
            url_frame,
            text="z.B. https://www.youtube.com/@channelname/videos\n"
                 "      https://www.tiktok.com/@username\n"
                 "      https://www.instagram.com/username/",
            font=ctk.CTkFont(size=10, family="Consolas"),
            text_color=("gray40", "gray60"),
            anchor="w", justify="left",
        ).pack(fill="x", padx=10, pady=(0, 4))
        self.url_var = ctk.StringVar()
        ctk.CTkEntry(url_frame, textvariable=self.url_var,
                     placeholder_text="Kanal-URL hier einfügen",
                     ).pack(fill="x", padx=10, pady=(0, 10))

        # ── Date range (tkcalendar) ──
        date_frame = ctk.CTkFrame(body)
        date_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(
            date_frame, text="📅  Zeitraum:",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(
            date_frame,
            text="Leer lassen für ALLES. Nur Posts in diesem Zeitraum "
                 "werden geladen.",
            font=ctk.CTkFont(size=10),
            text_color=("gray40", "gray60"),
            anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 4))
        row = ctk.CTkFrame(date_frame, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(row, text="Von:", width=40).pack(side="left", padx=(0, 5))
        self._build_date_picker(row, "from")
        ctk.CTkLabel(row, text="Bis:", width=40).pack(side="left",
                                                       padx=(20, 5))
        self._build_date_picker(row, "to")
        # Clear button — empties both pickers (= "all dates")
        ctk.CTkButton(
            row, text="🗑 Datum löschen", width=130,
            fg_color="gray40", hover_color="gray30",
            command=self._clear_dates,
        ).pack(side="left", padx=(20, 0))

        # Quick-pick buttons for common ranges
        qrow = ctk.CTkFrame(date_frame, fg_color="transparent")
        qrow.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(qrow, text="Schnellwahl:",
                     font=ctk.CTkFont(size=10),
                     text_color=("gray50", "gray50"),
                     ).pack(side="left", padx=(0, 5))
        for label, days in [("letzte 7 Tage", 7), ("letzte 30 Tage", 30),
                              ("letzte 90 Tage", 90),
                              ("dieses Jahr", -1), ("letztes Jahr", -2)]:
            ctk.CTkButton(
                qrow, text=label, width=110, height=24,
                fg_color=("gray85", "gray25"),
                hover_color=("gray75", "gray35"),
                text_color=("gray20", "gray80"),
                command=lambda d=days: self._quick_date(d),
            ).pack(side="left", padx=2)

        # ── Media type ──
        mt_frame = ctk.CTkFrame(body)
        mt_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(
            mt_frame, text="🎬  Medientyp:",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 2))
        self.media_type_var = ctk.StringVar(value="both")
        rrow = ctk.CTkFrame(mt_frame, fg_color="transparent")
        rrow.pack(fill="x", padx=10, pady=(0, 10))
        for val, label in [("both", "🎞 Beide (Video + Bilder)"),
                             ("video", "🎥 Nur Videos"),
                             ("picture", "🖼 Nur Bilder")]:
            ctk.CTkRadioButton(
                rrow, text=label, variable=self.media_type_var, value=val,
            ).pack(side="left", padx=10)

        # ── Quality + Format + Audio-Only + Item-cap (PARITY mit Haupt-GUI) ──
        qf = ctk.CTkFrame(body)
        qf.pack(fill="x", pady=5)
        ctk.CTkLabel(
            qf, text="⚙️  Qualität + Format + Limit:",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 2))

        # Row 1: Quality (full list) + Format + Audio-Only
        qrow1 = ctk.CTkFrame(qf, fg_color="transparent")
        qrow1.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(qrow1, text="Youtube Qualität:", width=120
                     ).pack(side="left", padx=(0, 5))
        # Full quality list matching the main GUI's QUALITY_OPTIONS
        self.quality_var = ctk.StringVar(value="Best (auto)")
        ctk.CTkOptionMenu(
            qrow1, variable=self.quality_var, width=160,
            values=["Best (auto)",
                    "8K (4320p)", "4K (2160p)", "1440p (2K)",
                    "1080p (Full HD)", "720p (HD)", "480p (SD)",
                    "360p", "240p", "Worst (smallest)"],
        ).pack(side="left", padx=5)
        ctk.CTkLabel(qrow1, text="  Format:",
                     ).pack(side="left", padx=(15, 5))
        self.format_var = ctk.StringVar(value="mp4")
        ctk.CTkOptionMenu(
            qrow1, variable=self.format_var, width=100,
            values=["mp4", "webm", "mkv", "original"],
        ).pack(side="left", padx=5)
        self.audio_only_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            qrow1, text="🎵 Nur Audio (MP3)",
            variable=self.audio_only_var,
        ).pack(side="left", padx=(15, 5))

        # Row 2: TikTok-specific quality (always visible, active when TikTok URL)
        qrow_tk = ctk.CTkFrame(qf, fg_color="transparent")
        qrow_tk.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(qrow_tk, text="TikTok Qualität:", width=120,
                     text_color=("#ff0050", "#ff3370"),
                     font=ctk.CTkFont(size=11, weight="bold"),
                     ).pack(side="left", padx=(0, 5))
        self.tiktok_quality_var = ctk.StringVar(
            value="No Watermark (HD)")
        self.tiktok_quality_menu = ctk.CTkOptionMenu(
            qrow_tk, variable=self.tiktok_quality_var, width=260,
            fg_color=("#ff0050", "#ff3370"),
            button_color=("#cc0040", "#cc0040"),
            button_hover_color=("#990030", "#990030"),
            values=["No Watermark (HD)", "Only Sound (MP3)", "Watermark (SD)"],
        )
        self.tiktok_quality_menu.pack(side="left", padx=5)
        self.tiktok_quality_hint = ctk.CTkLabel(
            qrow_tk, text="(nur für TikTok-Channels relevant)",
            font=ctk.CTkFont(size=10), text_color=("gray50", "gray50"),
        )
        self.tiktok_quality_hint.pack(side="left", padx=(10, 5))

        # Row 3: Max Items
        qrow2 = ctk.CTkFrame(qf, fg_color="transparent")
        qrow2.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(qrow2, text="Max Items:", width=120,
                     ).pack(side="left", padx=(0, 5))
        self.max_var = ctk.StringVar(value="50")
        ctk.CTkEntry(qrow2, textvariable=self.max_var, width=80,
                     ).pack(side="left", padx=5)
        ctk.CTkLabel(qrow2, text="(0 = unbegrenzt, Warnung ab 500)",
                     font=ctk.CTkFont(size=10),
                     text_color=("gray50", "gray50"),
                     ).pack(side="left", padx=10)

        # Row 4: Upload-date toggle
        date_row = ctk.CTkFrame(qf, fg_color="transparent")
        date_row.pack(fill="x", padx=10, pady=(0, 10))
        self.set_file_date_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            date_row,
            text="📅 Upload-Datum als File-Datum setzen "
                 "(Sortieren im Explorer nach Upload-Zeit)",
            variable=self.set_file_date_var,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left", padx=5)

        # ── Output dir + cookies ──
        oc = ctk.CTkFrame(body)
        oc.pack(fill="x", pady=5)
        ctk.CTkLabel(oc, text="📁  Output + Cookies:",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     anchor="w",
                     ).pack(fill="x", padx=10, pady=(8, 2))
        orow = ctk.CTkFrame(oc, fg_color="transparent")
        orow.pack(fill="x", padx=10, pady=(0, 6))
        ctk.CTkLabel(orow, text="Output:", width=60).pack(side="left")
        self.out_var = ctk.StringVar(value=self._default_output)
        ctk.CTkEntry(orow, textvariable=self.out_var
                     ).pack(side="left", fill="x", expand=True, padx=5)
        ctk.CTkButton(orow, text="Durchsuchen…", width=110,
                       command=self._pick_output_dir,
                       ).pack(side="left", padx=5)
        crow = ctk.CTkFrame(oc, fg_color="transparent")
        crow.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkLabel(crow, text="Cookies:", width=60).pack(side="left")
        self.cookies_var = ctk.StringVar(value=self._default_cookies)
        ctk.CTkEntry(crow, textvariable=self.cookies_var,
                     placeholder_text="(nur für Instagram/Twitter/FB nötig)"
                     ).pack(side="left", fill="x", expand=True, padx=5)
        ctk.CTkButton(crow, text="Durchsuchen…", width=110,
                       command=self._pick_cookies,
                       ).pack(side="left", padx=5)

        # ── Action buttons + progress ──
        ab = ctk.CTkFrame(body, fg_color="transparent")
        ab.pack(fill="x", pady=(15, 5))
        self.start_btn = ctk.CTkButton(
            ab, text="📥 Channel laden",
            fg_color="#7c3aed", hover_color="#6d28d9",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40, command=self._start_download,
        )
        self.start_btn.pack(side="left", padx=5, fill="x", expand=True)
        self.cancel_btn = ctk.CTkButton(
            ab, text="✖ Abbrechen", height=40, width=120,
            fg_color="gray40", hover_color="gray30",
            command=self._cancel, state="disabled",
        )
        self.cancel_btn.pack(side="left", padx=5)
        # NEU 2026-05-24: Output-Ordner im Explorer öffnen
        self.open_dir_btn = ctk.CTkButton(
            ab, text="📁 Dateipfad anzeigen", height=40, width=180,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0d9488", hover_color="#0f766e",
            command=self._open_output_in_explorer,
        )
        self.open_dir_btn.pack(side="left", padx=5)

        self.progress = ctk.CTkProgressBar(body)
        self.progress.pack(fill="x", pady=(8, 2))
        self.progress.set(0)
        self.progress_lbl = ctk.CTkLabel(
            body, text="Bereit.", font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            anchor="w",
        )
        self.progress_lbl.pack(fill="x")

        # ── Log textbox + Popout-Button ──
        log_frame = ctk.CTkFrame(body)
        log_frame.pack(fill="both", expand=True, pady=(8, 5))
        log_hdr = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_hdr.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(log_hdr, text="📋 Log:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     anchor="w",
                     ).pack(side="left", fill="x", expand=True)
        # NEU 2026-05-30: Log in großem, separatem Fenster öffnen (live-sync)
        ctk.CTkButton(
            log_hdr, text="🔍 Vergrößern", width=130, height=26,
            font=ctk.CTkFont(size=11),
            fg_color="#0d9488", hover_color="#0f766e",
            command=self._open_log_popout,
        ).pack(side="right", padx=(5, 0))
        self.log_text = ctk.CTkTextbox(
            log_frame, height=180,
            font=ctk.CTkFont(family="Consolas", size=10),
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        # Popout-Fenster-Referenzen (None solange geschlossen)
        self._log_popout_win: Optional[ctk.CTkToplevel] = None
        self._log_popout_text: Optional[ctk.CTkTextbox] = None

    def _build_date_picker(self, parent, role: str):
        """Custom date picker — full Calendar in a popup (year arrows work)."""
        if _HAS_TKCAL:
            picker = _DatePopupButton(parent, label_when_empty="— kein Filter")
            picker.pack(side="left", padx=5)
            setattr(self, f"date_{role}", picker)
        else:
            # Fallback: plain entry
            var = ctk.StringVar()
            e = ctk.CTkEntry(parent, textvariable=var, width=110,
                             placeholder_text="YYYY-MM-DD")
            e.pack(side="left", padx=5)
            setattr(self, f"date_{role}", var)

    # ───────────────── Event handlers ─────────────────

    def _pick_output_dir(self):
        d = filedialog.askdirectory(initialdir=self.out_var.get() or ".",
                                     title="Output-Ordner")
        if d:
            self.out_var.set(d)

    def _open_output_in_explorer(self):
        """Open output dir in Windows Explorer."""
        out = self.out_var.get().strip()
        if not out:
            messagebox.showinfo("", "Kein Output-Ordner gesetzt.")
            return
        p = Path(out)
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Fehler",
                                  f"Ordner konnte nicht angelegt werden:\n{e}")
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer.exe", str(p)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            messagebox.showerror("Fehler",
                                  f"Explorer konnte nicht geöffnet werden:\n{e}")

    def _pick_cookies(self):
        f = filedialog.askopenfilename(
            title="cookies.txt wählen",
            filetypes=[("Cookie files", "*.txt"), ("All files", "*.*")])
        if f:
            self.cookies_var.set(f)

    def _clear_dates(self):
        for role in ("from", "to"):
            w = getattr(self, f"date_{role}")
            try:
                if _HAS_TKCAL:
                    w.clear()
                else:
                    w.set("")
            except Exception:
                pass

    def _quick_date(self, days: int):
        """Quick date-range picker:
            >0   = last N days
            -1   = current year (Jan 1 — today)
            -2   = previous year (Jan 1 — Dec 31)
        """
        today = _dt.date.today()
        if days > 0:
            df, dt = today - _dt.timedelta(days=days), today
        elif days == -1:
            df, dt = _dt.date(today.year, 1, 1), today
        elif days == -2:
            df = _dt.date(today.year - 1, 1, 1)
            dt = _dt.date(today.year - 1, 12, 31)
        else:
            return
        self._set_date("from", df)
        self._set_date("to", dt)

    def _set_date(self, role: str, d: _dt.date):
        w = getattr(self, f"date_{role}")
        try:
            if _HAS_TKCAL:
                w.set_date(d)
            else:
                w.set(d.isoformat())
        except Exception:
            pass

    def _get_date(self, role: str) -> Optional[_dt.date]:
        w = getattr(self, f"date_{role}")
        try:
            if _HAS_TKCAL:
                return w.get_date()
            else:
                s = (w.get() or "").strip()
                if not s:
                    return None
                return _dt.date.fromisoformat(s)
        except Exception:
            return None

    # ───────────────── Download flow ─────────────────

    def _start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("", "Bitte Channel-URL eingeben.")
            return
        out = self.out_var.get().strip()
        if not out:
            messagebox.showwarning("", "Bitte Output-Ordner wählen.")
            return
        try:
            max_n = int(self.max_var.get())
        except ValueError:
            messagebox.showwarning("", "Max Items muss eine Zahl sein.")
            return
        if max_n < 0:
            max_n = 0
        # Warn for big downloads
        if max_n > 500:
            if not messagebox.askyesno(
                "⚠️ Großer Download",
                f"{max_n} Items ist viel — das kann sehr lange dauern und "
                f"viel Speicher belegen. Fortfahren?"):
                return
        if max_n == 0:
            if not messagebox.askyesno(
                "⚠️ Unbegrenzter Download",
                "Max Items = 0 bedeutet ALLE Posts des Kanals — bei großen "
                "Accounts können das Tausende sein. Fortfahren?"):
                return

        df = self._get_date("from")
        dt = self._get_date("to")
        if df and dt and df > dt:
            messagebox.showwarning("", "'Von'-Datum liegt nach 'Bis'-Datum.")
            return

        cookies = self.cookies_var.get().strip()

        cd = _ensure_channel_downloader()
        # Map "Best (auto)" / "8K (4320p)" / "Worst (smallest)" → integer height
        quality_height_map = {
            "Best (auto)": None,
            "8K (4320p)": 4320, "4K (2160p)": 2160, "1440p (2K)": 1440,
            "1080p (Full HD)": 1080, "720p (HD)": 720, "480p (SD)": 480,
            "360p": 360, "240p": 240, "Worst (smallest)": 0,
        }
        opts = cd.ChannelOptions(
            max_items=max_n,
            date_from=df, date_to=dt,
            media_type=self.media_type_var.get(),
            quality=self.quality_var.get(),
            cookies_file=Path(cookies) if cookies else None,
            use_id_filename=self._use_id_filename,
            set_upload_date_as_file_date=self.set_file_date_var.get(),
            # NEU 2026-05-24: full main-GUI parity
            quality_height=quality_height_map.get(self.quality_var.get(), None),
            format_container=self.format_var.get(),
            audio_only=self.audio_only_var.get(),
            tiktok_quality=self.tiktok_quality_var.get(),
        )

        # Lock UI
        self.start_btn.configure(state="disabled", text="… läuft …")
        self.cancel_btn.configure(state="normal")
        self._cancel_event.clear()
        self.progress.set(0)
        self.progress_lbl.configure(text="Starte…")
        self._log_clear()

        self._worker_thread = threading.Thread(
            target=self._worker, args=(url, Path(out), opts), daemon=True)
        self._worker_thread.start()

    def _worker(self, url: str, out: Path, opts):
        cd = _ensure_channel_downloader()

        def log(m: str):
            self._log_queue.put(("LOG", m))

        def prog(done: int, total: int, label: str):
            self._log_queue.put(("PROGRESS", (done, total, label)))

        try:
            stats = cd.download_channel(
                url, out, opts, progress_cb=prog, log_cb=log,
                cancel_flag=lambda: self._cancel_event.is_set(),
            )
            self._log_queue.put(("DONE", stats))
        except Exception as e:
            self._log_queue.put(("ERROR", str(e)))

    def _cancel(self):
        self._cancel_event.set()
        self.progress_lbl.configure(text="Abbrechen angefragt…")

    def _poll_log_queue(self):
        try:
            while True:
                kind, payload = self._log_queue.get_nowait()
                if kind == "LOG":
                    self._log_append(payload)
                elif kind == "PROGRESS":
                    done, total, label = payload
                    pct = done / total if total else 0
                    self.progress.set(pct)
                    self.progress_lbl.configure(
                        text=f"[{done}/{total}] {label}")
                elif kind == "DONE":
                    stats = payload
                    self._log_append(
                        f"\n✅ FERTIG\n"
                        f"  Videos:  {stats.downloaded_video}\n"
                        f"  Bilder:  {stats.downloaded_picture}\n"
                        f"  Skipped: {stats.skipped_existing}\n"
                        f"  Failed:  {stats.failed}\n")
                    self.progress.set(1.0)
                    self.progress_lbl.configure(
                        text=f"Fertig — {stats.downloaded_video} Videos, "
                             f"{stats.downloaded_picture} Bilder")
                    self.start_btn.configure(state="normal",
                                              text="📥 Channel laden")
                    self.cancel_btn.configure(state="disabled")
                elif kind == "ERROR":
                    self._log_append(f"\n❌ FEHLER: {payload}")
                    self.start_btn.configure(state="normal",
                                              text="📥 Channel laden")
                    self.cancel_btn.configure(state="disabled")
        except queue.Empty:
            pass
        # Re-arm — aber nur solange das Fenster lebt. Sonst feuert der
        # erneut eingeplante Callback nach dem Schließen auf zerstörten
        # Widgets → TclError.
        if not getattr(self, "_closing", False):
            self._poll_after_id = self.after(150, self._poll_log_queue)

    def _log_append(self, msg: str):
        line = str(msg) + "\n"
        try:
            self.log_text.insert("end", line)
            self.log_text.see("end")
        except Exception:
            pass
        # NEU 2026-05-30: ALSO ins Popout-Fenster spiegeln (falls offen)
        if (self._log_popout_text is not None
                and self._log_popout_win is not None
                and self._log_popout_win.winfo_exists()):
            try:
                self._log_popout_text.insert("end", line)
                self._log_popout_text.see("end")
            except Exception:
                pass

    def _log_clear(self):
        try:
            self.log_text.delete("1.0", "end")
        except Exception:
            pass
        if (self._log_popout_text is not None
                and self._log_popout_win is not None
                and self._log_popout_win.winfo_exists()):
            try:
                self._log_popout_text.delete("1.0", "end")
            except Exception:
                pass

    def _open_log_popout(self):
        """Öffnet das Log in einem großen, separat skalierbaren Fenster.

        Non-modal + live-synchron: jede neue Log-Zeile landet im Inline-Log
        UND im Popout. Schließen des Popouts lässt das Inline-Log weiterlaufen.
        """
        if (self._log_popout_win is not None
                and self._log_popout_win.winfo_exists()):
            try:
                self._log_popout_win.lift()
                self._log_popout_win.focus_force()
            except Exception:
                pass
            return

        win = ctk.CTkToplevel(self)
        win.title("📋 Channel-Downloader — Log (vergrößertes Fenster)")
        win.geometry("1100x650")
        win.minsize(700, 400)
        try:
            ico = (Path(__file__).resolve().parent.parent
                    / "tools" / "branding" / "teebot.ico")
            if ico.exists():
                win.after(200, lambda: win.iconbitmap(str(ico)))
        except Exception:
            pass

        hdr = ctk.CTkFrame(win, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(
            hdr, text="📋 Live-Log (synchronisiert mit Hauptfenster)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            hdr, text="🧹 Löschen", width=110, height=26,
            fg_color="gray40", hover_color="gray30",
            command=self._log_clear,
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            hdr, text="📋 Kopieren", width=110, height=26,
            fg_color="#0d9488", hover_color="#0f766e",
            command=self._copy_log_to_clipboard,
        ).pack(side="right", padx=4)

        popout_text = ctk.CTkTextbox(
            win, font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
        )
        popout_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        # Mit aktuellem Inhalt vorbefüllen
        try:
            popout_text.insert("end", self.log_text.get("1.0", "end"))
            popout_text.see("end")
        except Exception:
            pass

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

    def _copy_log_to_clipboard(self):
        """Kopiert den gesamten Log-Inhalt in die Zwischenablage."""
        try:
            text = (self._log_popout_text or self.log_text).get("1.0", "end")
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    def _on_close(self):
        if self._worker_thread and self._worker_thread.is_alive():
            if not messagebox.askyesno(
                "Download läuft", "Ein Download läuft noch — wirklich "
                                   "abbrechen und schließen?"):
                return
            self._cancel_event.set()
        # Polling-Loop stoppen, sonst feuert der re-armte after-Callback
        # nach destroy() auf zerstörten Widgets (TclError).
        self._closing = True
        try:
            if getattr(self, "_poll_after_id", None) is not None:
                self.after_cancel(self._poll_after_id)
        except Exception:
            pass
        self.destroy()
