"""
boundless.py — sovereign entry point. Run as `python boundless.py` (or `boundless` on PATH).
Auto-opens browser (configurable in settings.json), starts tray if enabled.
"""
from __future__ import annotations
import sys, os, webbrowser, time, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_settings() -> dict:
    p = ROOT / "settings.json"
    if p.exists():
        try:
            import json
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "host": "0.0.0.0",
        "port": 10200,
        "auto_open_browser_on_launch": True,
        "tray_enabled": False,
    }


def main():
    s = _load_settings()
    host = s.get("host", "0.0.0.0")
    port = int(s.get("port", 10200))
    if s.get("auto_open_browser_on_launch", True) and host in ("0.0.0.0", "127.0.0.1", "localhost"):
        def _open():
            time.sleep(1.5)
            webbrowser.open(f"http://localhost:{port}")
        threading.Thread(target=_open, daemon=True).start()
    if s.get("tray_enabled", False):
        try:
            from web.tray import start_tray
            start_tray(port)
        except Exception as e:
            print(f"[tray] unavailable: {e}")
    from web.server import run
    run()


if __name__ == "__main__":
    main()
