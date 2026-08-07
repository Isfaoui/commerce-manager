"""
server/admin_auth.py

Separate, simple session-token auth for the admin dashboard. Deliberately
NOT reusing customer JWTs/sessions — admin and customer auth are different
trust domains and should be able to evolve independently (e.g. add 2FA to
admin without touching the customer login flow).
"""
from __future__ import annotations

import secrets
import time
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask import Blueprint, jsonify, request, session

from . import db
from .rate_limit import rate_limited

bp = Blueprint("admin_auth", __name__, url_prefix="/api/admin")
_hasher = PasswordHasher()

SESSION_TTL_SECONDS = 8 * 60 * 60


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Admin-Token") or session.get("admin_token")
        if not token:
            return jsonify({"message": "Admin authentication required."}), 401
        with db.tx() as conn:
            row = conn.execute(
                "SELECT * FROM admin_sessions WHERE token = ?", (token,)
            ).fetchone()
            if row is None or row["expires_at"] < int(time.time()):
                return jsonify({"message": "Session expired. Please log in again."}), 401
            admin = db.get_user_by_id(conn, row["admin_user_id"])
        request.admin_username = admin["email"] if admin else "unknown"
        request.admin_user_id = admin["id"] if admin else None
        return fn(*args, **kwargs)
    return wrapper


@bp.post("/login")
@rate_limited(limit=5, window_seconds=60, key_fn=lambda: (request.json or {}).get("email", ""))
def admin_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    with db.tx() as conn:
        user = db.get_user_by_email(conn, email)
        if user is None or not user["is_admin"]:
            return jsonify({"message": "Invalid credentials."}), 401
        try:
            _hasher.verify(user["password_hash"], password)
        except VerifyMismatchError:
            return jsonify({"message": "Invalid credentials."}), 401

        token = secrets.token_urlsafe(32)
        now = int(time.time())
        conn.execute(
            "INSERT INTO admin_sessions (token, admin_user_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (token, user["id"], now, now + SESSION_TTL_SECONDS),
        )
    session["admin_token"] = token
    return jsonify({"token": token}), 200


@bp.get("/me")
@require_admin
def admin_me():
    with db.tx() as conn:
        admin = db.get_user_by_id(conn, request.admin_user_id)
    return jsonify({
        "id": admin["id"], "email": admin["email"], "full_name": admin["full_name"],
        "created_at": admin["created_at"],
    }), 200


@bp.patch("/me")
@require_admin
def admin_update_me():
    """Lets the logged-in admin view/edit their own account: display name
    always, email or password only when they confirm their current
    password (so a hijacked-but-unlocked dashboard tab can't be used to
    silently take over the account)."""
    data = request.get_json(silent=True) or {}
    with db.tx() as conn:
        admin = db.get_user_by_id(conn, request.admin_user_id)

        wants_sensitive_change = bool(data.get("email") or data.get("new_password"))
        if wants_sensitive_change:
            current_password = data.get("current_password") or ""
            try:
                _hasher.verify(admin["password_hash"], current_password)
            except VerifyMismatchError:
                return jsonify({"message": "Current password is incorrect."}), 401

        new_email = admin["email"]
        if data.get("email"):
            new_email = data["email"].strip().lower()
            clash = db.get_user_by_email(conn, new_email)
            if clash is not None and clash["id"] != admin["id"]:
                return jsonify({"message": "Another account already uses this email."}), 409

        new_full_name = data.get("full_name", admin["full_name"])
        new_password_hash = admin["password_hash"]
        if data.get("new_password"):
            new_password_hash = _hasher.hash(data["new_password"])

        conn.execute(
            "UPDATE users SET email = ?, full_name = ?, password_hash = ?, updated_at = ? WHERE id = ?",
            (new_email, new_full_name, new_password_hash, int(time.time()), admin["id"]),
        )
        db.log_event(conn, event_type="admin_update_self", customer_id=None,
                     detail={"by": admin["email"]}, ip_address=request.remote_addr)

    return jsonify({"message": "Account updated.", "email": new_email, "full_name": new_full_name}), 200
