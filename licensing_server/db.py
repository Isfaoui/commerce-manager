"""
server/db.py — connection handling + thin repository functions.

Kept deliberately framework-agnostic (no ORM) for a v1 licensing server:
the schema is small and stable, and raw SQL keeps the signed-payload
audit trail (payload_json/signature columns) unambiguous. Swap for
SQLAlchemy later if the schema grows.
"""
from __future__ import annotations

import os
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# On most easy-deploy hosts (Render, Railway, etc.) the app's own folder is
# wiped on every redeploy. Point DB_PATH at a persistent disk by setting
# the DB_PATH env var (e.g. "/var/data/licensing.db") when you deploy;
# falls back to a local file for local testing.
DB_PATH = Path(os.environ.get("DB_PATH", str(Path(__file__).parent / "licensing.db")))
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA_PATH.read_text())


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now() -> int:
    return int(time.time())


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------- users ----
def get_user_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
    ).fetchone()


def get_user_by_id(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def create_user(
    conn: sqlite3.Connection, email: str, password_hash: str, full_name: str = ""
) -> str:
    user_id = new_id()
    ts = now()
    conn.execute(
        """INSERT INTO users (id, email, password_hash, full_name, is_admin,
                               is_active, created_at, updated_at)
           VALUES (?, ?, ?, ?, 0, 1, ?, ?)""",
        (user_id, email.lower().strip(), password_hash, full_name, ts, ts),
    )
    return user_id


def search_customers(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    like = f"%{query}%"
    return conn.execute(
        """SELECT * FROM users WHERE is_admin = 0
           AND (email LIKE ? OR full_name LIKE ?)
           ORDER BY created_at DESC LIMIT 200""",
        (like, like),
    ).fetchall()


VALID_SORT_COLUMNS = {"created_at", "email", "full_name"}


def search_customers_advanced(
    conn: sqlite3.Connection,
    query: str = "",
    status_filter: str = "",
    sort_by: str = "created_at",
    sort_dir: str = "desc",
) -> list[dict]:
    """
    Like search_customers, but also filters by the customer's current
    license status (including two states that aren't a literal `licenses.status`
    value: 'none' for never-issued, and 'expired' computed from expires_at)
    and supports sorting. Returns plain dicts (not Rows) since each result
    is enriched with its active license, which callers need alongside the
    user fields.
    """
    like = f"%{query}%" if query else "%"
    sort_col = sort_by if sort_by in VALID_SORT_COLUMNS else "created_at"
    sort_dir = "ASC" if sort_dir.lower() == "asc" else "DESC"

    rows = conn.execute(
        f"""SELECT * FROM users WHERE is_admin = 0
            AND (email LIKE ? OR full_name LIKE ?)
            ORDER BY {sort_col} {sort_dir} LIMIT 500""",
        (like, like),
    ).fetchall()

    now_ts = now()
    results = []
    for r in rows:
        lic = get_active_license_for_customer(conn, r["id"])
        computed_status = "none"
        if lic:
            if lic["expires_at"] and lic["expires_at"] < now_ts:
                computed_status = "expired"
            else:
                computed_status = lic["license_type"]  # 'trial' or 'professional'

        if status_filter and status_filter != computed_status:
            continue

        d = dict(r)
        d["license"] = dict(lic) if lic else None
        d["computed_status"] = computed_status
        results.append(d)

    return results


def update_user(conn: sqlite3.Connection, user_id: str, *, email: str | None = None, full_name: str | None = None) -> None:
    existing = get_user_by_id(conn, user_id)
    if not existing:
        raise ValueError("User not found")
    conn.execute(
        "UPDATE users SET email = ?, full_name = ?, updated_at = ? WHERE id = ?",
        (
            (email.lower().strip() if email else existing["email"]),
            full_name if full_name is not None else existing["full_name"],
            now(), user_id,
        ),
    )


def delete_user(conn: sqlite3.Connection, user_id: str) -> None:
    """Hard delete - cascades to devices/licenses via FK, license_logs keep
    their row with customer_id set to NULL (ON DELETE SET NULL) so the
    audit trail survives even after the account itself is gone."""
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def get_stats(conn: sqlite3.Connection) -> dict:
    now_ts = now()
    total_customers = conn.execute(
        "SELECT COUNT(*) AS c FROM users WHERE is_admin = 0"
    ).fetchone()["c"]

    active_licenses = conn.execute(
        "SELECT license_type, expires_at FROM licenses WHERE status = 'active'"
    ).fetchall()

    active_trials = sum(1 for l in active_licenses if l["license_type"] == "trial" and (not l["expires_at"] or l["expires_at"] >= now_ts))
    active_paid = sum(1 for l in active_licenses if l["license_type"] == "professional" and (not l["expires_at"] or l["expires_at"] >= now_ts))
    expired = sum(1 for l in active_licenses if l["expires_at"] and l["expires_at"] < now_ts)

    monthly_price = get_setting(conn, "monthly_price")
    mrr = (active_paid * float(monthly_price)) if monthly_price else None

    return {
        "total_customers": total_customers,
        "active_trials": active_trials,
        "active_paid": active_paid,
        "expired": expired,
        "no_license": total_customers - len(active_licenses),
        "mrr": mrr,
        "monthly_price": float(monthly_price) if monthly_price else None,
    }


def get_expiring_soon(conn: sqlite3.Connection, within_days: int = 7) -> list[dict]:
    now_ts = now()
    cutoff = now_ts + within_days * 86400
    rows = conn.execute(
        """SELECT l.*, u.email, u.full_name FROM licenses l
           JOIN users u ON u.id = l.customer_id
           WHERE l.status = 'active' AND l.expires_at IS NOT NULL
             AND l.expires_at BETWEEN ? AND ?
           ORDER BY l.expires_at ASC""",
        (now_ts, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


# -------------------------------------------------------------- logs ----
def get_logs(
    conn: sqlite3.Connection, customer_id: str = "", event_type: str = "", limit: int = 200
) -> list[dict]:
    query = """SELECT ll.*, u.email AS customer_email FROM license_logs ll
               LEFT JOIN users u ON u.id = ll.customer_id WHERE 1=1"""
    params: list = []
    if customer_id:
        query += " AND ll.customer_id = ?"
        params.append(customer_id)
    if event_type:
        query += " AND ll.event_type = ?"
        params.append(event_type)
    query += " ORDER BY ll.created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(query, params).fetchall()]


# ---------------------------------------------------------- settings ----
def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM server_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO server_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# ------------------------------------------------------------- licenses ----
def get_active_license_for_customer(
    conn: sqlite3.Connection, customer_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT * FROM licenses WHERE customer_id = ? AND status = 'active'
           ORDER BY created_at DESC LIMIT 1""",
        (customer_id,),
    ).fetchone()


def insert_license(
    conn: sqlite3.Connection,
    *,
    license_id: str,
    customer_id: str,
    device_id: str,
    license_type: str,
    status: str,
    features: list[str],
    issued_at: int,
    expires_at: int | None,
    issued_by: str,
    signature: str,
    payload_json: str,
) -> None:
    ts = now()
    conn.execute(
        """INSERT INTO licenses
           (id, customer_id, device_id, license_type, status, features,
            issued_at, expires_at, issued_by, signature, payload_json,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            license_id, customer_id, device_id, license_type, status,
            json.dumps(features), issued_at, expires_at, issued_by,
            signature, payload_json, ts, ts,
        ),
    )


def supersede_customer_licenses(conn: sqlite3.Connection, customer_id: str) -> None:
    """Marks all currently-active licenses for a customer as revoked before
    issuing a new one — a customer has exactly one active license at a time."""
    conn.execute(
        "UPDATE licenses SET status = 'revoked', updated_at = ? "
        "WHERE customer_id = ? AND status = 'active'",
        (now(), customer_id),
    )


def set_license_status(conn: sqlite3.Connection, license_id: str, status: str) -> None:
    conn.execute(
        "UPDATE licenses SET status = ?, updated_at = ? WHERE id = ?",
        (status, now(), license_id),
    )


# --------------------------------------------------------------- devices ----
def upsert_device(conn: sqlite3.Connection, customer_id: str, device_id: str) -> None:
    ts = now()
    conn.execute(
        """INSERT INTO devices (id, customer_id, device_id, first_seen_at, last_seen_at, is_active)
           VALUES (?, ?, ?, ?, ?, 1)
           ON CONFLICT(customer_id, device_id)
           DO UPDATE SET last_seen_at = excluded.last_seen_at, is_active = 1""",
        (new_id(), customer_id, device_id, ts, ts),
    )


def deactivate_devices(conn: sqlite3.Connection, customer_id: str) -> None:
    """Used by admin 'Reset Device' so the customer's next login can bind
    a brand-new device_id."""
    conn.execute(
        "UPDATE devices SET is_active = 0 WHERE customer_id = ?", (customer_id,)
    )


# ------------------------------------------------------------------ logs ----
def log_event(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    customer_id: str | None = None,
    license_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO license_logs
           (license_id, customer_id, event_type, detail, ip_address, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            license_id, customer_id, event_type,
            json.dumps(detail or {}), ip_address, now(),
        ),
    )
