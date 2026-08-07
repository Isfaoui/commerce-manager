"""
server/auth.py

POST /api/auth/login
    Body: { email, password, device_id }

    - Validates credentials (argon2id).
    - If the customer has no active license yet -> issues a 7-day TRIAL
      bound to the device_id supplied by the client.
    - If the customer already has an active license -> re-signs/returns it
      IF the device_id matches, otherwise rejects (one PC per license).
    - Rate-limited per IP + per email to slow down credential stuffing.
"""
from __future__ import annotations

import time

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask import Blueprint, current_app, jsonify, request

from . import db
from .rate_limit import rate_limited
from .license_core.models import (
    FEATURES_TRIAL,
    TRIAL_DURATION_SECONDS,
    LicensePayload,
    LicenseStatus,
    LicenseType,
)

bp = Blueprint("auth", __name__, url_prefix="/api/auth")
_hasher = PasswordHasher()


def _issue_and_store_license(
    conn, *, customer_id: str, device_id: str, license_type: LicenseType,
    expires_at: int | None, issued_by: str,
) -> dict:
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
        conn,
        license_id=payload.license_id,
        customer_id=customer_id,
        device_id=device_id,
        license_type=license_type.value,
        status=LicenseStatus.ACTIVE.value,
        features=features,
        issued_at=payload.issued_at,
        expires_at=expires_at,
        issued_by=issued_by,
        signature=signature,
        payload_json=__import__("json").dumps(payload_dict),
    )
    db.upsert_device(conn, customer_id, device_id)

    return {"payload": payload_dict, "signature": signature}


@bp.post("/login")
@rate_limited(limit=5, window_seconds=60, key_fn=lambda: request.json.get("email", "") if request.is_json else "")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    device_id = (data.get("device_id") or "").strip()

    if not email or not password or not device_id:
        return jsonify({"message": "email, password and device_id are required"}), 400

    with db.tx() as conn:
        user = db.get_user_by_email(conn, email)
        if user is None:
            # Do NOT reveal whether the email exists — generic message.
            db.log_event(conn, event_type="login_failed", detail={"email": email},
                         ip_address=request.remote_addr)
            return jsonify({"message": "Invalid email or password."}), 401

        try:
            _hasher.verify(user["password_hash"], password)
        except VerifyMismatchError:
            db.log_event(conn, event_type="login_failed", customer_id=user["id"],
                         ip_address=request.remote_addr)
            return jsonify({"message": "Invalid email or password."}), 401

        if not user["is_active"]:
            return jsonify({"message": "This account has been disabled."}), 403

        existing = db.get_active_license_for_customer(conn, user["id"])

        if existing is not None:
            if existing["device_id"] != device_id:
                db.log_event(
                    conn, event_type="login_device_mismatch", customer_id=user["id"],
                    detail={"existing_device": existing["device_id"], "new_device": device_id},
                    ip_address=request.remote_addr,
                )
                return jsonify({
                    "message": "This account's license is already activated on another "
                                "computer. Contact support to transfer your license."
                }), 403

            # Same device re-logging in -> just return the existing signed license
            # rather than minting a new one.
            license_out = {
                "payload": __import__("json").loads(existing["payload_json"]),
                "signature": existing["signature"],
            }
            db.log_event(conn, event_type="login", customer_id=user["id"],
                         detail={"device_id": device_id}, ip_address=request.remote_addr)
            return jsonify({"license": license_out}), 200

        # First login ever for this account -> issue the 7-day trial.
        expires_at = int(time.time()) + TRIAL_DURATION_SECONDS
        license_out = _issue_and_store_license(
            conn, customer_id=user["id"], device_id=device_id,
            license_type=LicenseType.TRIAL, expires_at=expires_at,
            issued_by="self-service",
        )
        db.log_event(conn, event_type="issue_trial", customer_id=user["id"],
                     license_id=license_out["payload"]["license_id"],
                     detail={"device_id": device_id}, ip_address=request.remote_addr)

        return jsonify({"license": license_out}), 200
