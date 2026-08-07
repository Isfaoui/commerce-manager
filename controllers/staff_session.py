"""
controllers/staff_session.py - the "Changer d'utilisateur" PIN session.

This is a lightweight, OPTIONAL layer on top of the existing owner/license
gate, not a replacement for it. Default state (no staff session active) is
full, unrestricted access - exactly today's behavior. An owner can hand the
register to a cashier by clicking "Changer d'utilisateur", picking that
employee, and entering their PIN; from then on the frontend hides/redirects
away from pages their role doesn't permit, and this module also protects
the highest-value backend endpoints (managing employees/roles themselves)
so a restricted session can't just call the API directly to grant itself
more access.

This is NOT meant to be airtight defense against a determined technical
attacker - it's a single-PC retail app, not a multi-tenant system. The goal
is "the cashier's screen only shows Caisse," which this achieves.

Pages a role's permissions can list (matches the sidebar 1:1):
    dashboard, pos, management, staff, documents, branding, settings
"""
from __future__ import annotations

import json
from functools import wraps

from flask import Blueprint, jsonify, request, session

from models.db import get_db
from utils.helpers import h

bp = Blueprint("staff_session", __name__, url_prefix="/api/staff-session")

ALL_PAGES = ["dashboard", "pos", "management", "staff", "documents", "branding", "settings"]


def _current_employee(db):
    employee_id = session.get("staff_employee_id")
    if not employee_id:
        return None
    row = db.execute(
        "SELECT e.*, r.name AS role_name, r.permissions AS role_permissions "
        "FROM employees e LEFT JOIN roles r ON r.id = e.role_id WHERE e.id = ?",
        (employee_id,),
    ).fetchone()
    if not row or not row["active"]:
        session.pop("staff_employee_id", None)
        return None
    return row


def _permitted_pages(employee_row) -> list[str]:
    if employee_row is None:
        return ALL_PAGES  # owner / unrestricted mode
    try:
        perms = json.loads(employee_row["role_permissions"] or "{}")
    except (TypeError, ValueError):
        perms = {}
    pages = perms.get("pages")
    if pages is None:
        return ALL_PAGES  # a role with no permissions configured yet defaults to full access,
                           # so creating a role doesn't silently lock everyone out before the
                           # owner has had a chance to configure it
    return pages


def require_staff_page(page_key: str):
    """
    Decorator for backend routes that should be blocked for a restricted
    staff session that doesn't have `page_key` in their role's permitted
    pages. Owner/unrestricted mode (no staff session) always passes.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            db = get_db()
            employee = _current_employee(db)
            if employee is not None and page_key not in _permitted_pages(employee):
                return jsonify({"error": "Acces non autorise pour votre role."}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@bp.get("/current")
def current():
    db = get_db()
    employee = _current_employee(db)
    if employee is None:
        return jsonify({"active": False, "permitted_pages": ALL_PAGES})
    return jsonify({
        "active": True,
        "employee_id": employee["id"],
        "name": employee["name"],
        "role_name": employee["role_name"],
        "permitted_pages": _permitted_pages(employee),
    })


@bp.get("/employees")
def selectable_employees():
    """Lightweight list for the switch-user picker - no sensitive fields."""
    db = get_db()
    rows = db.execute(
        "SELECT id, name, role_id FROM employees WHERE active = 1 AND pin_hash IS NOT NULL ORDER BY name"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.post("/login")
def login():
    data = request.get_json() or {}
    employee_id = data.get("employee_id")
    pin = data.get("pin", "")
    if not employee_id or not pin:
        return jsonify({"error": "employee_id et pin requis"}), 400

    db = get_db()
    row = db.execute(
        "SELECT id, pin_hash, active FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    if not row or not row["active"] or not row["pin_hash"]:
        return jsonify({"error": "Code PIN incorrect"}), 401
    if row["pin_hash"] != h(pin):
        return jsonify({"error": "Code PIN incorrect"}), 401

    session["staff_employee_id"] = employee_id
    employee = _current_employee(db)
    return jsonify({
        "ok": True,
        "name": employee["name"],
        "role_name": employee["role_name"],
        "permitted_pages": _permitted_pages(employee),
    })


@bp.post("/logout")
def logout():
    session.pop("staff_employee_id", None)
    return jsonify({"ok": True})
