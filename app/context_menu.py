"""Right-click context menu (cut / copy / paste / select-all) for every
tk Entry and Text widget — including CustomTkinter's CTkEntry / CTkTextbox,
which wrap real tk.Entry / tk.Text underneath.

Usage:
    from . import context_menu
    context_menu.attach_context_menu(self)   # once, on the main window/root

Why class-level binding:
    bind_class("Entry", …) / bind_class("Text", …) attaches to the WIDGET
    CLASS inside the Tk interpreter, so it covers every Entry/Text that
    exists now OR is created later — across the main window AND all its
    child Toplevels (log popouts, the channel-downloader dialog, date
    pickers, …) — with zero per-widget wiring. One call per process is
    enough.

stdlib-only (tkinter) — safe for the offline bundle.
"""
from __future__ import annotations

import tkinter as tk

# German labels (the app's primary audience). Callers may override via the
# `labels` arg (e.g. to plug in the app's i18n) without touching this module.
_DEFAULT_LABELS = {
    "cut": "Ausschneiden",
    "copy": "Kopieren",
    "paste": "Einfügen",
    "select_all": "Alles auswählen",
}

# Widget classes we treat as editable text inputs.
_ENTRY_CLASSES = ("Entry", "TEntry")
_TEXT_CLASSES = ("Text",)
_ALL_CLASSES = _ENTRY_CLASSES + _TEXT_CLASSES

# Guard so repeated calls in the same interpreter don't stack bindings.
_ATTACHED_INTERPRETERS: set[str] = set()


def _is_text(widget) -> bool:
    try:
        return widget.winfo_class() in _TEXT_CLASSES
    except Exception:
        return False


def _is_editable(widget) -> bool:
    """True unless the widget is explicitly disabled / readonly."""
    try:
        state = str(widget.cget("state"))
    except Exception:
        return True
    return state in ("normal", "")


def _select_all(widget) -> str:
    """Select the whole field. Returns 'break' to swallow the event."""
    try:
        if _is_text(widget):
            widget.tag_add("sel", "1.0", "end-1c")
            widget.mark_set("insert", "end-1c")
        else:
            widget.select_range(0, "end")
            widget.icursor("end")
    except Exception:
        pass
    return "break"


def _gen(widget, virtual_event: str):
    """Fire a Tk virtual event (<<Cut>>/<<Copy>>/<<Paste>>) on the widget."""
    try:
        widget.event_generate(virtual_event)
    except Exception:
        pass


def _popup(event, labels) -> None:
    w = event.widget
    try:
        cls = w.winfo_class()
    except Exception:
        return
    if cls not in _ALL_CLASSES:
        return

    # Focus the widget so the virtual events target it, like a native menu.
    try:
        w.focus_set()
    except Exception:
        pass

    editable = _is_editable(w)
    menu = tk.Menu(w, tearoff=0)
    menu.add_command(
        label=labels["cut"], state=("normal" if editable else "disabled"),
        command=lambda: _gen(w, "<<Cut>>"))
    menu.add_command(
        label=labels["copy"],
        command=lambda: _gen(w, "<<Copy>>"))
    menu.add_command(
        label=labels["paste"], state=("normal" if editable else "disabled"),
        command=lambda: _gen(w, "<<Paste>>"))
    menu.add_separator()
    menu.add_command(
        label=labels["select_all"],
        command=lambda: _select_all(w))
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


def attach_context_menu(root, labels: dict | None = None) -> None:
    """Wire the right-click menu + Ctrl+A onto ALL Entry/Text widgets.

    Safe to call more than once; only the first call per Tk interpreter
    actually installs the class bindings.
    """
    lab = dict(_DEFAULT_LABELS)
    if labels:
        lab.update(labels)

    try:
        interp = root.tk.interpaddr()  # unique per Tcl interpreter
        key = str(interp)
    except Exception:
        key = str(id(root))
    if key in _ATTACHED_INTERPRETERS:
        return
    _ATTACHED_INTERPRETERS.add(key)

    for cls in _ALL_CLASSES:
        # Right-click → context menu
        root.bind_class(cls, "<Button-3>",
                        lambda e, _l=lab: _popup(e, _l), add="+")
        # Ctrl+A → select all (often unbound on Windows tk for Entry)
        root.bind_class(cls, "<Control-a>",
                        lambda e: _select_all(e.widget), add="+")
        root.bind_class(cls, "<Control-A>",
                        lambda e: _select_all(e.widget), add="+")
