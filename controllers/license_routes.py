"""
controllers/license_routes.py - local licensing API consumed by
views/license.html, and the before_request gate that protects every
other /api/* route.

This runs INSIDE the desktop app (local Flask on 127.0.0.1:8000), not on
the licensing server. It talks to the remote server only for the three
online-only operations (login, reactivate) via license.manager.
"""

from flask import Blueprint, current_app, jsonify, request

from license.manager import ActivationError
from license.validator import USER_FACING_MESSAGES

bp = Blueprint("license_routes", __name__, url_prefix="/api/license")


def _manager():
    return current_app.config["LICENSE_MANAGER"]


@bp.get("/status")
def status():
    outcome = _manager().bootstrap()
    return jsonify({
        "ok": outcome.ok,
        "result": outcome.result.value,
        "message": USER_FACING_MESSAGES.get(outcome.result),
        "license_type": outcome.payload.license_type.value if outcome.payload else None,
        "expires_at": outcome.payload.expires_at if outcome.payload else None,
    })


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email, password = data.get("email", ""), data.get("password", "")
    if not email or not password:
        return jsonify({"ok": False, "message": "Email et mot de passe requis."}), 400

    try:
        outcome = _manager().login_and_activate(email, password)
    except ActivationError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    if outcome.ok:
        return jsonify({"ok": True}), 200
    return jsonify({
        "ok": False,
        "message": USER_FACING_MESSAGES.get(outcome.result, "Activation impossible."),
    }), 400


@bp.post("/reactivate")
def reactivate():
    """Used after an admin device reset, or to pull down a paid upgrade
    onto the same device without re-entering credentials."""
    data = request.get_json(silent=True) or {}
    try:
        outcome = _manager().reactivate(license_key=data.get("license_key"))
    except ActivationError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400

    if outcome.ok:
        return jsonify({"ok": True}), 200
    return jsonify({
        "ok": False,
        "message": USER_FACING_MESSAGES.get(outcome.result, "Reactivation impossible."),
    }), 400


def register_license_gate(app):
    """
    Call once from controllers/app.py. Blocks every /api/* route except
    /api/license/* behind an offline license check. This is the real
    enforcement point - the frontend routing in main.py (which page opens
    first) is only a convenience, never the security boundary.
    """
    app.register_blueprint(bp)

    @app.before_request
    def _require_license():
        path = request.path
        if not path.startswith("/api/"):
            return None  # static HTML/JS/CSS - gated indirectly, since none
                          # of it works without the API calls below
        if path.startswith("/api/license/"):
            return None
        if request.method == "OPTIONS":
            return None
        if path == "/api/settings" and request.method == "GET":
            # Read-only, non-sensitive (company name/logo/colors) - letting
            # the login/activation screen show them before a license exists
            # is a cosmetic nicety, not a security gap.
            return None

        outcome = _manager().bootstrap()
        if not outcome.ok:
            return jsonify({
                "ok": False,
                "license_error": outcome.result.value,
                "message": USER_FACING_MESSAGES.get(outcome.result),
            }), 403
        return None
