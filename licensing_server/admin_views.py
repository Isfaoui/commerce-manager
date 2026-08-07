"""
server/admin_views.py

Thin HTML wrapper around the /api/admin/* JSON endpoints, for humans.
Kept separate from licenses.py so the JSON API stays reusable (e.g. a
future React admin panel could call the same /api/admin endpoints).
"""
from __future__ import annotations

from flask import Blueprint, render_template, session

bp = Blueprint("admin_views", __name__, url_prefix="/admin")


@bp.get("/")
def dashboard():
    return render_template("admin_dashboard.html", is_logged_in=bool(session.get("admin_token")))


@bp.get("/login")
def login_page():
    return render_template("admin_login.html")
