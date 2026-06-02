"""Portable-Reset: wipe all personal traces from the project.

Designed to be run before zipping the project folder to ship to another
person. Removes browser logins, cookie files, settings (with paths,
URL history, etc.), pycache (contains absolute paths), and logs.

The runtime/, venv/, source code, and downloaded Chromium binaries are
preserved so the recipient gets a working installation.

Usage:
    python -m autonomous.portable_reset --dry-run   # preview only
    python -m autonomous.portable_reset --confirm   # actually delete
    python -m autonomous.portable_reset --json      # machine-readable preview

The launcher GUI calls collect_targets() + execute_reset() directly so
it can show a preview before the user confirms.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
APPDATA = Path(os.environ.get("APPDATA", str(Path.home())))
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))


@dataclass
class ResetTarget:
    """A single thing the reset should remove or reset."""
    label: str
    path: Path
    kind: str  # "dir" | "file" | "settings_reset"
    bytes_size: int = 0
    detail: str = ""
    # For settings_reset: this is informational only; we won't delete
    # the file, we'll overwrite it with defaults at execute time.
    exists: bool = True


@dataclass
class ResetPlan:
    """Full plan: things to delete plus external warnings."""
    targets: list[ResetTarget] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_bytes: int = 0


def _dir_size(p: Path) -> int:
    """Sum of all file sizes under p. Returns 0 for missing or unreadable."""
    if not p.exists():
        return 0
    total = 0
    try:
        for f in p.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


def _read_settings(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def collect_targets() -> ResetPlan:
    """Inventory every file/dir we'd touch. No side effects."""
    plan = ResetPlan()

    # ─── Browser profiles (Playwright user-data-dirs with logins) ───
    profiles_dir = ROOT / "data" / "playwright_profiles"
    if profiles_dir.exists():
        for sub in sorted(profiles_dir.iterdir()):
            if sub.is_dir():
                size = _dir_size(sub)
                plan.targets.append(ResetTarget(
                    label=f"Browser-Login: {sub.name}",
                    path=sub, kind="dir", bytes_size=size,
                    detail="Persistente Chromium-Session inkl. Cookies, "
                           "LocalStorage, History",
                ))

    # ─── Exported cookies.txt files ───
    cookies_dir = ROOT / "data" / "cookies"
    if cookies_dir.exists():
        for f in sorted(cookies_dir.iterdir()):
            if f.is_file() and f.suffix == ".txt":
                plan.targets.append(ResetTarget(
                    label=f"Cookies-Export: {f.name}",
                    path=f, kind="file", bytes_size=f.stat().st_size,
                    detail="cookies.txt vom integrierten Browser-Login",
                ))

    # ─── yt-dlp GUI settings ───
    gui_settings = APPDATA / "teebot_yt_gui" / "settings.json"
    if gui_settings.exists():
        snap = _read_settings(gui_settings) or {}
        details = []
        if snap.get("output_dir"):
            details.append(f"output: {snap['output_dir']}")
        if snap.get("cookies_file"):
            details.append(f"cookies: {snap['cookies_file']}")
        hist = snap.get("url_history") or []
        if hist:
            details.append(f"{len(hist)} URLs in History")
        plan.targets.append(ResetTarget(
            label="yt-dlp GUI Settings",
            path=gui_settings, kind="settings_reset",
            bytes_size=gui_settings.stat().st_size,
            detail=" · ".join(details) if details else "auf Defaults",
        ))

    # Also wipe the whole settings dir (could contain old caches/files)
    gui_settings_dir = APPDATA / "teebot_yt_gui"
    if gui_settings_dir.exists():
        for f in gui_settings_dir.iterdir():
            if f.is_file() and f.name != "settings.json":
                plan.targets.append(ResetTarget(
                    label=f"yt-dlp GUI Extra: {f.name}",
                    path=f, kind="file", bytes_size=f.stat().st_size,
                    detail="Zusatzdatei im Settings-Ordner",
                ))

    # ─── TEE Launcher settings ───
    launcher_settings = APPDATA / "TEE_Launcher" / "settings.json"
    if launcher_settings.exists():
        plan.targets.append(ResetTarget(
            label="TEE Launcher Settings",
            path=launcher_settings, kind="settings_reset",
            bytes_size=launcher_settings.stat().st_size,
            detail="Theme, Fenstergröße, Polling-Intervall",
        ))

    # ─── pycache (contains absolute paths to user's drive) ───
    for cache_dir in ROOT.rglob("__pycache__"):
        # Skip pycache inside venv — that's not personal data
        if "venv" in cache_dir.parts:
            continue
        if cache_dir.is_dir():
            size = _dir_size(cache_dir)
            plan.targets.append(ResetTarget(
                label=f"Python-Cache: {cache_dir.relative_to(ROOT)}",
                path=cache_dir, kind="dir", bytes_size=size,
                detail="Enthält absolute Pfade zum Projekt-Ordner",
            ))

    # ─── Log files (keep .gitkeep) ───
    logs_dir = ROOT / "logs"
    if logs_dir.exists():
        for f in logs_dir.iterdir():
            if f.is_file() and f.name != ".gitkeep":
                plan.targets.append(ResetTarget(
                    label=f"Log: {f.name}",
                    path=f, kind="file", bytes_size=f.stat().st_size,
                ))

    # ─── External cookies.txt from settings (warning, not deletion) ───
    if gui_settings.exists():
        snap = _read_settings(gui_settings) or {}
        ext = (snap.get("cookies_file") or "").strip()
        if ext:
            ext_path = Path(ext)
            if ext_path.exists() and not str(ext_path).startswith(str(ROOT)):
                plan.warnings.append(
                    f"Externe cookies.txt ausserhalb des Projekts: "
                    f"{ext_path} ({ext_path.stat().st_size} bytes). "
                    f"Wird NICHT automatisch geloescht. Bitte manuell "
                    f"pruefen ob das versendet werden soll.")

    # ─── Chromium binaries (system-wide, won't ship anyway, warning) ───
    chromium_dir = LOCALAPPDATA / "ms-playwright"
    if chromium_dir.exists() and _dir_size(chromium_dir) > 0:
        plan.warnings.append(
            f"Playwright Chromium liegt unter {chromium_dir} (system-weit, "
            f"~{_dir_size(chromium_dir) // (1024*1024)} MB). Wird NICHT "
            f"ins Zip kommen. Der Empfaenger muss 'playwright install "
            f"chromium' beim ersten Browser-Login ausfuehren — oder du "
            f"baust einen Auto-Install-Hook ein.")

    plan.total_bytes = sum(t.bytes_size for t in plan.targets)
    return plan


def execute_reset(plan: ResetPlan, log=print) -> dict:
    """Actually delete / reset. Returns a result summary dict."""
    deleted_dirs = 0
    deleted_files = 0
    reset_settings = 0
    errors: list[str] = []
    freed_bytes = 0

    for t in plan.targets:
        try:
            if t.kind == "dir":
                if t.path.exists():
                    shutil.rmtree(t.path, ignore_errors=False)
                    deleted_dirs += 1
                    freed_bytes += t.bytes_size
                    log(f"  [rmdir] {t.path}")
            elif t.kind == "file":
                if t.path.exists():
                    t.path.unlink()
                    deleted_files += 1
                    freed_bytes += t.bytes_size
                    log(f"  [rm]    {t.path}")
            elif t.kind == "settings_reset":
                if t.path.exists():
                    t.path.unlink()
                    reset_settings += 1
                    freed_bytes += t.bytes_size
                    log(f"  [reset] {t.path}")
        except Exception as e:
            errors.append(f"{t.label} ({t.path}): {e}")
            log(f"  [FAIL] {t.path}: {e}")

    # Also wipe empty parent dirs we just emptied — but leave the
    # data/ folder itself with a .gitkeep so the layout stays valid.
    for keep_dir in (ROOT / "data" / "playwright_profiles",
                      ROOT / "data" / "cookies"):
        if keep_dir.exists():
            try:
                # If empty, leave it; rmtree would also remove the dir,
                # but we want the structure to persist for next run.
                pass
            except Exception:
                pass

    return {
        "deleted_dirs": deleted_dirs,
        "deleted_files": deleted_files,
        "reset_settings": reset_settings,
        "freed_bytes": freed_bytes,
        "errors": errors,
        "warnings": plan.warnings,
    }


def format_plan(plan: ResetPlan) -> str:
    """Human-readable preview text."""
    if not plan.targets:
        out = ["Nichts zu loeschen — Projekt ist bereits sauber."]
    else:
        out = [f"Werde {len(plan.targets)} Ziele bereinigen "
                f"(~{plan.total_bytes // 1024} KB):", ""]
        for t in plan.targets:
            kb = t.bytes_size // 1024 if t.bytes_size >= 1024 else 0
            size_str = f"{kb} KB" if kb else f"{t.bytes_size} B"
            out.append(f"  • {t.label:<40} [{size_str:>10}]")
            if t.detail:
                out.append(f"      {t.detail}")
    if plan.warnings:
        out.append("")
        out.append("⚠️ Hinweise (kein automatisches Loeschen):")
        for w in plan.warnings:
            out.append(f"  • {w}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="Show plan, do not delete")
    g.add_argument("--confirm", action="store_true",
                   help="Execute the reset")
    g.add_argument("--json", action="store_true",
                   help="Output plan as JSON")
    args = ap.parse_args(argv)

    plan = collect_targets()
    if args.json:
        print(json.dumps({
            "targets": [
                {"label": t.label, "path": str(t.path), "kind": t.kind,
                 "bytes_size": t.bytes_size, "detail": t.detail}
                for t in plan.targets
            ],
            "warnings": plan.warnings,
            "total_bytes": plan.total_bytes,
        }, indent=2, ensure_ascii=False))
        return 0
    if args.dry_run:
        print(format_plan(plan))
        return 0
    if args.confirm:
        print(format_plan(plan))
        print()
        print("=== Loesche jetzt … ===")
        result = execute_reset(plan)
        print()
        print(f"Fertig. Geloescht: {result['deleted_dirs']} Ordner, "
              f"{result['deleted_files']} Dateien, "
              f"{result['reset_settings']} Settings-Files. "
              f"Freigegeben: {result['freed_bytes'] // 1024} KB.")
        if result["errors"]:
            print(f"⚠️ {len(result['errors'])} Fehler:")
            for e in result["errors"]:
                print(f"  • {e}")
        return 0 if not result["errors"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
