"""
server/licenses.py

Customer-facing:
    POST /api/licenses/reactivate   (used after admin device-reset, or a
                                      paid upgrade the customer needs to
                                      pull down onto the same device)

Admin-facing (all require admin session, see server/admin.py:require_admin):
    POST /api/admin/licenses/trial
    POST /api/admin/licenses/professional
    POST /api/admin/licenses/<id>/disable
    POST /api/admin/licenses/<id>/revoke
    POST /api/admin/devices/reset
    GET  /api/admin/customers?search=...
"""
from __future__ import annotations

import json
import time

from flask import Blueprint, current_app, jsonify, request

from . import db
from .admin_auth import require_admin
from .license_core.models import FEATURES_TRIAL, TRIAL_DURATION_SECONDS, LicensePayload, LicenseStatus, LicenseType

bp = Blueprint("licenses", __name__, url_prefix="/api")


def _sign_and_persist(conn, *, customer_id, device_id, license_type, expires_at, issued_by):
    signer = current_app.config["LICENSE_SIGNER"]
    features = FEATURES_TRIAL if license_type is LicenseType.TRIAL else \
        current_app.config["FEATURES_PROFESSIONAL"]

    payload = LicensePayload(
        license_id=LicensePayload.new_id(),
        customer_id=customer_id,
        license_type=license_type,
        status=LicenseStatus.ACTIVE,
        device_id=device_id,
        features=features,
        issued_at=int(time.time()),
        expires_at=expires_at,
        issued_by=issued_by,
    )
    payload_dict = payload.to_dict()
    signature = signer.sign_payload(payload_dict)

    db.supersede_customer_licenses(conn, customer_id)
    db.insert_license(
        conn, license_id=payload.license_id, customer_id=customer_id,
        device_id=device_id, license_type=license_type.value,
        status=LicenseStatus.ACTIVE.value, features=features,
        issued_at=payload.issued_at, expires_at=expires_at, issued_by=issued_by,
        signature=signature, payload_json=json.dumps(payload_dict),
    )
    db.upsert_device(conn, customer_id, device_id)
    return {"payload": payload_dict, "signature": signature}


# ---------------------------------------------------------------- customer --
@bp.post("/licenses/reactivate")
def reactivate():
    data = request.get_json(silent=True) or {}
    customer_id = data.get("customer_id")
    device_id = (data.get("device_id") or "").strip()

    if not customer_id or not device_id:
        return jsonify({"message": "customer_id and device_id are required"}), 400

    with db.tx() as conn:
        user = db.get_user_by_id(conn, customer_id)
        if user is None or not user["is_active"]:
            return jsonify({"message": "Account not found or disabled."}), 403

        existing = db.get_active_license_for_customer(conn, customer_id)
        if existing is None:
            return jsonify({"message": "No license to reactivate. Please log in instead."}), 404

        # Device must either match, or have been freed by an admin reset
        # (devices.is_active flips to 0 on reset — see admin endpoint below).
        active_device = conn.execute(
            "SELECT * FROM devices WHERE customer_id = ? AND is_active = 1",
            (customer_id,),
        ).fetchone()

        if active_device is not None and active_device["device_id"] != device_id:
            return jsonify({
                "message": "License already active on another device. Ask an admin to reset it."
            }), 403

        license_out = _sign_and_persist(
            conn, customer_id=customer_id, device_id=device_id,
            license_type=LicenseType(existing["license_type"]),
            expires_at=existing["expires_at"], issued_by="reactivation",
        )
        db.log_event(conn, event_type="reactivate", customer_id=customer_id,
                     license_id=license_out["payload"]["license_id"],
                     detail={"device_id": device_id}, ip_address=request.remote_addr)
        return jsonify({"license": license_out}), 200


# ------------------------------------------------------------------- admin --
def _resolve_device_id(conn, customer_id: str, provided: str | None) -> tuple[str | None, str | None]:
    """
    Returns (device_id, error_message). If the admin explicitly typed a
    device_id, use it as-is. Otherwise, fall back to whichever device this
    customer already activated on (from a prior self-service login) - this
    is what makes the dashboard's "leave blank" option actually work.
    """
    provided = (provided or "").strip()
    if provided:
        return provided, None

    existing_device = conn.execute(
        "SELECT device_id FROM devices WHERE customer_id = ? AND is_active = 1 "
        "ORDER BY last_seen_at DESC LIMIT 1",
        (customer_id,),
    ).fetchone()
    if existing_device:
        return existing_device["device_id"], None

    return None, ("This customer hasn't activated on any device yet. Ask them to log in "
                   "once first (issues a trial automatically), or type a device ID manually.")


@bp.post("/admin/licenses/trial")
@require_admin
def admin_issue_trial():
    data = request.get_json(silent=True) or {}
    customer_id = data.get("customer_id")
    if not customer_id:
        return jsonify({"message": "customer_id required"}), 400
    with db.tx() as conn:
        device_id, error = _resolve_device_id(conn, customer_id, data.get("device_id"))
        if error:
            return jsonify({"message": error}), 400
        expires_at = int(time.time()) + TRIAL_DURATION_SECONDS
        out = _sign_and_persist(conn, customer_id=customer_id, device_id=device_id,
                                 license_type=LicenseType.TRIAL, expires_at=expires_at,
                                 issued_by=request.admin_username)
        db.log_event(conn, event_type="issue_trial", customer_id=customer_id,
                     license_id=out["payload"]["license_id"], ip_address=request.remote_addr)
        return jsonify({"license": out}), 200


@bp.post("/admin/licenses/professional")
@require_admin
def admin_issue_professional():
    data = request.get_json(silent=True) or {}
    customer_id = data.get("customer_id")
    if not customer_id:
        return jsonify({"message": "customer_id required"}), 400
    with db.tx() as conn:
        device_id, error = _resolve_device_id(conn, customer_id, data.get("device_id"))
        if error:
            return jsonify({"message": error}), 400
        out = _sign_and_persist(conn, customer_id=customer_id, device_id=device_id,
                                 license_type=LicenseType.PROFESSIONAL, expires_at=None,
                                 issued_by=request.admin_username)
        db.log_event(conn, event_type="issue_paid", customer_id=customer_id,
                     license_id=out["payload"]["license_id"], ip_address=request.remote_addr)
        return jsonify({"license": out}), 200


@bp.post("/admin/licenses/<license_id>/disable")
@require_admin
def admin_disable(license_id: str):
    with db.tx() as conn:
        db.set_license_status(conn, license_id, LicenseStatus.DISABLED.value)
        db.log_event(conn, event_type="disable", license_id=license_id,
                     ip_address=request.remote_addr)
    return jsonify({"message": "License disabled."}), 200


@bp.post("/admin/licenses/<license_id>/revoke")
@require_admin
def admin_revoke(license_id: str):
    with db.tx() as conn:
        db.set_license_status(conn, license_id, LicenseStatus.REVOKED.value)
        db.log_event(conn, event_type="revoke", license_id=license_id,
                     ip_address=request.remote_addr)
    return jsonify({"message": "License revoked."}), 200


@bp.post("/admin/devices/reset")
@require_admin
def admin_reset_device():
    data = request.get_json(silent=True) or {}
    customer_id = data.get("customer_id")
    if not customer_id:
        return jsonify({"message": "customer_id required"}), 400
    with db.tx() as conn:
        db.deactivate_devices(conn, customer_id)
        db.log_event(conn, event_type="device_reset", customer_id=customer_id,
                     ip_address=request.remote_addr)
    return jsonify({"message": "Device binding reset. Customer can activate on a new PC."}), 200


@bp.post("/admin/customers")
@require_admin
def admin_create_customer():
    """
    Lets the admin dashboard create a customer account directly - the web
    equivalent of running create_account.py, so day-to-day account
    creation never needs a Bash console.
    """
    from argon2 import PasswordHasher

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    full_name = (data.get("full_name") or "").strip()

    if not email or "@" not in email:
        return jsonify({"message": "A valid email is required."}), 400
    if len(password) < 8:
        return jsonify({"message": "Password must be at least 8 characters."}), 400

    hasher = PasswordHasher()
    with db.tx() as conn:
        if db.get_user_by_email(conn, email) is not None:
            return jsonify({"message": "An account with this email already exists."}), 409

        password_hash = hasher.hash(password)
        user_id = db.create_user(conn, email, password_hash, full_name)
        db.log_event(conn, event_type="admin_create_customer", customer_id=user_id,
                     detail={"created_by": request.admin_username}, ip_address=request.remote_addr)

    return jsonify({"message": "Customer account created.", "email": email}), 201


@bp.get("/admin/customers")
@require_admin
def admin_search_customers():
    query = request.args.get("search", "")
    status_filter = request.args.get("status", "")
    sort_by = request.args.get("sort_by", "created_at")
    sort_dir = request.args.get("sort_dir", "desc")
    with db.tx() as conn:
        customers = db.search_customers_advanced(conn, query, status_filter, sort_by, sort_dir)
        result = [{
            "id": c["id"], "email": c["email"], "full_name": c["full_name"],
            "is_active": bool(c["is_active"]), "license": c["license"],
            "computed_status": c["computed_status"], "created_at": c["created_at"],
        } for c in customers]
    return jsonify({"customers": result}), 200


@bp.patch("/admin/customers/<customer_id>")
@require_admin
def admin_update_customer(customer_id):
    data = request.get_json(silent=True) or {}
    with db.tx() as conn:
        existing = db.get_user_by_id(conn, customer_id)
        if existing is None:
            return jsonify({"message": "Customer not found."}), 404
        if data.get("email"):
            clash = db.get_user_by_email(conn, data["email"])
            if clash is not None and clash["id"] != customer_id:
                return jsonify({"message": "Another account already uses this email."}), 409
        try:
            db.update_user(conn, customer_id, email=data.get("email"), full_name=data.get("full_name"))
        except ValueError:
            return jsonify({"message": "Customer not found."}), 404
        db.log_event(conn, event_type="admin_edit_customer", customer_id=customer_id,
                     detail={"by": request.admin_username}, ip_address=request.remote_addr)
        updated = db.get_user_by_id(conn, customer_id)
    return jsonify({"id": updated["id"], "email": updated["email"], "full_name": updated["full_name"]}), 200


@bp.delete("/admin/customers/<customer_id>")
@require_admin
def admin_delete_customer(customer_id):
    with db.tx() as conn:
        existing = db.get_user_by_id(conn, customer_id)
        if existing is None:
            return jsonify({"message": "Customer not found."}), 404
        db.log_event(conn, event_type="admin_delete_customer", customer_id=None,
                     detail={"deleted_email": existing["email"], "by": request.admin_username},
                     ip_address=request.remote_addr)
        db.delete_user(conn, customer_id)
    return jsonify({"message": "Customer deleted."}), 200


@bp.post("/admin/customers/bulk-delete")
@require_admin
def admin_bulk_delete_customers():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return jsonify({"message": "ids (non-empty list) required."}), 400
    deleted = 0
    with db.tx() as conn:
        for customer_id in ids:
            existing = db.get_user_by_id(conn, customer_id)
            if existing is None:
                continue
            db.log_event(conn, event_type="admin_delete_customer", customer_id=None,
                         detail={"deleted_email": existing["email"], "by": request.admin_username, "bulk": True},
                         ip_address=request.remote_addr)
            db.delete_user(conn, customer_id)
            deleted += 1
    return jsonify({"message": f"{deleted} customer(s) deleted.", "deleted": deleted}), 200


@bp.get("/admin/stats")
@require_admin
def admin_stats():
    with db.tx() as conn:
        stats = db.get_stats(conn)
        stats["expiring_soon"] = db.get_expiring_soon(conn, within_days=7)
    return jsonify(stats), 200


@bp.get("/admin/logs")
@require_admin
def admin_logs():
    customer_id = request.args.get("customer_id", "")
    event_type = request.args.get("event_type", "")
    limit = min(request.args.get("limit", 200, type=int) or 200, 500)
    with db.tx() as conn:
        logs = db.get_logs(conn, customer_id, event_type, limit)
    return jsonify({"logs": logs}), 200


@bp.get("/admin/settings")
@require_admin
def admin_get_settings():
    with db.tx() as conn:
        monthly_price = db.get_setting(conn, "monthly_price")
    return jsonify({"monthly_price": monthly_price}), 200


@bp.post("/admin/settings")
@require_admin
def admin_update_settings():
    data = request.get_json(silent=True) or {}
    with db.tx() as conn:
        if "monthly_price" in data:
            db.set_setting(conn, "monthly_price", str(data["monthly_price"]))
    return jsonify({"message": "Settings updated."}), 200
