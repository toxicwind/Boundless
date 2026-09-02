"""
web/tray.py — cross-platform system tray (macOS/Windows/Linux).
Graceful no-op if pystray not installed.
"""
from __future__ import annotations
import sys, threading, subprocess
from pathlib import Path

def start_tray(port: int = 10200):
    """Start a system tray icon with quick actions. Returns immediately if pystray unavailable."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return None  # boundless: tray is optional, never crash the server
    import webbrowser, os

    def make_icon():
        img = Image.new("RGB", (64,64), "#161b22")
        d = ImageDraw.Draw(img)
        d.rectangle([8,8,56,56], fill="#58a6ff")
        d.text((20,22), "ADA", fill="#000")
        return img

    def open_ui(icon, item):
        webbrowser.open(f"http://localhost:{port}")

    def open_settings(icon, item):
        webbrowser.open(f"http://localhost:{port}/settings")

    def open_profiles(icon, item):
        webbrowser.open(f"http://localhost:{port}/api/profiles")

    def quit_app(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Open boundless", open_ui, default=True),
        pystray.MenuItem("Settings", open_settings),
        pystray.MenuItem("Profiles JSON", open_profiles),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("boundless", make_icon(), "Boundless", menu)
    t = threading.Thread(target=icon.run, daemon=True)
    t.start()
    return icon
