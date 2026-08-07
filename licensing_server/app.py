"""
licensing_server/app.py — Flask application factory for the licensing server.

This runs on YOUR infrastructure (a VPS, a small cloud instance, etc.) —
it is NOT bundled into the Commerce Manager .exe. Deploy it separately,
behind TLS.

Run with (from the CommerceManager/ project root, with licensing_server/
and its license_core/ subpackage on the path):
    export FLASK_SECRET_KEY=...              (set x on Windows)
    export LICENSE_PRIVATE_KEY_PATH=keys/private_key.pem
    python -m licensing_server.app
"""
from __future__ import annotations

import os

from flask import Flask

from . import db
from .admin_auth import bp as admin_auth_bp
from .auth import bp as auth_bp
from .licenses import bp as licenses_bp
from .license_core.crypto import LicenseSigner
from .license_core.models import FEATURES_PROFESSIONAL


def create_app() -> Flask:
    app = Flask(__name__)

    app.config["SECRET_KEY"] = _require_env("FLASK_SECRET_KEY")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = True     # requires HTTPS in production
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"

    private_key_path = os.environ.get("LICENSE_PRIVATE_KEY_PATH")
    private_key_pem_inline = os.environ.get("LICENSE_PRIVATE_KEY_PEM")

    if private_key_pem_inline:
        # Paste the full contents of private_key.pem (including the
        # -----BEGIN/END----- lines) as one env var - easiest option on
        # hosts where there's no simple way to upload a file.
        key_bytes = private_key_pem_inline.encode("utf-8")
    elif private_key_path:
        with open(private_key_path, "rb") as f:
            key_bytes = f.read()
    else:
        raise RuntimeError(
            "Set either LICENSE_PRIVATE_KEY_PATH (path to a .pem file) or "
            "LICENSE_PRIVATE_KEY_PEM (the key's contents directly)."
        )

    app.config["LICENSE_SIGNER"] = LicenseSigner(key_bytes)

    app.config["FEATURES_PROFESSIONAL"] = FEATURES_PROFESSIONAL

    db.init_db()

    app.register_blueprint(auth_bp)
    app.register_blueprint(licenses_bp)
    app.register_blueprint(admin_auth_bp)

    from .admin_views import bp as admin_views_bp
    app.register_blueprint(admin_views_bp)

    @app.after_request
    def set_security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    return app


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Required environment variable {name} is not set.")
    return val


if __name__ == "__main__":
    application = create_app()
    # Behind a reverse proxy (nginx/Caddy) with TLS termination in production.
    application.run(host="0.0.0.0", port=8443)
