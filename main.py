"""
main.py - Commerce Manager entry point.

Starts the Flask server in the background and opens it in a native
app window (pywebview) - no browser tabs, no address bar. Once
packaged with PyInstaller (see BUILD.md), this is the single .exe.

Run with: python main.py
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import webview  # noqa: E402  (pip install pywebview)
from controllers.app import app  # noqa: E402
from models.db import init_db  # noqa: E402
from models.backup import maybe_auto_backup  # noqa: E402
from license.manager import LicenseManager  # noqa: E402
from license.public_key import PUBLIC_KEY_PEM  # noqa: E402

# Your production licensing server (see licensing_server/, deployed
# separately). Internet is only needed for the /api/license/* calls this
# manager makes - everything else in the POS stays fully offline.
LICENSE_SERVER_URL = "https://isfaoui.pythonanywhere.com"

license_manager = LicenseManager(
    public_key_pem=PUBLIC_KEY_PEM,
    server_base_url=LICENSE_SERVER_URL,
)
app.config["LICENSE_MANAGER"] = license_manager


def run_server():
    init_db()
    maybe_auto_backup()
    # use_reloader=False is required: the reloader spawns a second
    # process, which breaks the packaged .exe.
    app.run(host="127.0.0.1", port=8000, debug=False, use_reloader=False)


if __name__ == "__main__":
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # give Flask a moment to bind the port before the window loads it
    time.sleep(1.2)

    # Offline check, every launch: signature + device + expiry, no network.
    # If it fails for ANY reason, open the login/activation screen instead
    # of the POS UI - that screen is the only place internet gets used.
    outcome = license_manager.bootstrap()
    start_path = "/" if outcome.ok else "/license.html"

    webview.create_window(
        "Commerce Manager",
        f"http://127.0.0.1:8000{start_path}",
        width=1440,
        height=900,
        min_size=(1024, 640),
    )
    webview.start()
    # blocks until the window closes; the daemon server thread is
    # killed automatically when the process exits.
