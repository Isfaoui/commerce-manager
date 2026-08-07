"""
controllers/documents.py - Documents module (Factures, Devis, Bons de
Livraison, Avoirs).

One shared table/API surface across all four types (see models/db.py for
the schema rationale) - the frontend (views/documents.html) renders the
type-specific fields conditionally, but the CRUD, numbering, and totals
logic underneath is identical.

Endpoints:
    GET    /api/documents?type=&status=&search=   list (filtered)
    GET    /api/documents/<id>                     one, with items
    POST   /api/documents                          create (auto-numbers)
    PATCH  /api/documents/<id>                      update (recomputes totals)
    POST   /api/documents/<id>/duplicate            clone as a new draft
    POST   /api/documents/<id>/status               change status only
    DELETE /api/documents/<id>
"""
from __future__ import annotations

import uuid
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from models.db import get_db
from utils.helpers import now

bp = Blueprint("documents", __name__, url_prefix="/api/documents")

DEFAULT_PREFIXES = {"facture": "FAC", "devis": "DEV", "bl": "BL", "avoir": "AVR"}
VALID_TYPES = set(DEFAULT_PREFIXES)


def _get_prefix(db, doc_type: str) -> str:
    row = db.execute(
        "SELECT value FROM settings WHERE key = ?", (f"doc_prefix_{doc_type}",)
    ).fetchone()
    return (row["value"] if row and row["value"] else DEFAULT_PREFIXES[doc_type])


def _next_doc_number(db, doc_type: str) -> str:
    year = datetime.now().year
    prefix = _get_prefix(db, doc_type)

    row = db.execute(
        "SELECT next_number FROM document_sequences WHERE doc_type = ? AND year = ?",
        (doc_type, year),
    ).fetchone()

    if row is None:
        db.execute(
            "INSERT INTO document_sequences (doc_type, year, next_number) VALUES (?, ?, 2)",
            (doc_type, year),
        )
        number = 1
    else:
        number = row["next_number"]
        db.execute(
            "UPDATE document_sequences SET next_number = next_number + 1 "
            "WHERE doc_type = ? AND year = ?",
            (doc_type, year),
        )

    return f"{prefix}-{year}-{number:04d}"


def _compute_totals(items: list[dict]) -> dict:
    subtotal = 0.0
    discount_total = 0.0
    tax_total = 0.0
    computed_items = []

    for idx, item in enumerate(items):
        qty = float(item.get("quantity", 0) or 0)
        unit_price = float(item.get("unit_price", 0) or 0)
        discount_pct = float(item.get("discount_pct", 0) or 0)
        tax_pct = float(item.get("tax_pct", 0) or 0)

        gross = qty * unit_price
        discount_amount = gross * (discount_pct / 100)
        net = gross - discount_amount
        tax_amount = net * (tax_pct / 100)
        line_total = net + tax_amount

        subtotal += gross
        discount_total += discount_amount
        tax_total += tax_amount

        computed_items.append({
            "id": item.get("id") or str(uuid.uuid4()),
            "position": idx,
            "description": item.get("description", ""),
            "quantity": qty,
            "unit_price": unit_price,
            "discount_pct": discount_pct,
            "tax_pct": tax_pct,
            "line_total": round(line_total, 2),
        })

    total = subtotal - discount_total + tax_total
    return {
        "items": computed_items,
        "subtotal": round(subtotal, 2),
        "discount_total": round(discount_total, 2),
        "tax_total": round(tax_total, 2),
        "total": round(total, 2),
    }


def _serialize(db, doc_id: str) -> dict | None:
    doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not doc:
        return None
    items = db.execute(
        "SELECT * FROM document_items WHERE document_id = ? ORDER BY position", (doc_id,)
    ).fetchall()
    d = dict(doc)
    d["items"] = [dict(i) for i in items]
    if d.get("linked_document_id"):
        linked = db.execute(
            "SELECT doc_number FROM documents WHERE id = ?", (d["linked_document_id"],)
        ).fetchone()
        d["linked_document_number"] = linked["doc_number"] if linked else None
    return d


@bp.get("")
def list_documents():
    db = get_db()
    doc_type = request.args.get("type")
    status = request.args.get("status")
    search = request.args.get("search", "").strip()

    query = "SELECT * FROM documents WHERE 1=1"
    params: list = []
    if doc_type:
        query += " AND doc_type = ?"
        params.append(doc_type)
    if status:
        query += " AND status = ?"
        params.append(status)
    if search:
        query += " AND (doc_number LIKE ? OR customer_name LIKE ? OR customer_company LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    query += " ORDER BY created_at DESC"

    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.get("/<doc_id>")
def get_document(doc_id):
    db = get_db()
    doc = _serialize(db, doc_id)
    if not doc:
        return jsonify({"error": "Document introuvable"}), 404
    return jsonify(doc)


@bp.post("")
def create_document():
    data = request.get_json() or {}
    doc_type = data.get("doc_type")
    if doc_type not in VALID_TYPES:
        return jsonify({"error": "Type de document invalide"}), 400

    db = get_db()
    doc_id = str(uuid.uuid4())
    doc_number = _next_doc_number(db, doc_type)
    totals = _compute_totals(data.get("items", []))
    ts = now()

    db.execute(
        """INSERT INTO documents
           (id, doc_type, doc_number, status, issue_date, due_date, valid_until,
            delivery_date, customer_name, customer_company, customer_ice,
            customer_address, customer_phone, customer_email, driver_name,
            vehicle, hide_prices, linked_document_id, reason, subtotal,
            discount_total, tax_total, total, amount_paid, notes,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            doc_id, doc_type, doc_number, data.get("status", "draft"),
            data.get("issue_date") or ts[:10],
            data.get("due_date"), data.get("valid_until"), data.get("delivery_date"),
            data.get("customer_name"), data.get("customer_company"), data.get("customer_ice"),
            data.get("customer_address"), data.get("customer_phone"), data.get("customer_email"),
            data.get("driver_name"), data.get("vehicle"), 1 if data.get("hide_prices") else 0,
            data.get("linked_document_id"), data.get("reason"),
            totals["subtotal"], totals["discount_total"], totals["tax_total"], totals["total"],
            float(data.get("amount_paid", 0) or 0), data.get("notes"), ts, ts,
        ),
    )
    for item in totals["items"]:
        db.execute(
            """INSERT INTO document_items
               (id, document_id, position, description, quantity, unit_price,
                discount_pct, tax_pct, line_total)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["id"], doc_id, item["position"], item["description"], item["quantity"],
             item["unit_price"], item["discount_pct"], item["tax_pct"], item["line_total"]),
        )
    db.commit()
    return jsonify(_serialize(db, doc_id)), 201


@bp.patch("/<doc_id>")
def update_document(doc_id):
    db = get_db()
    existing = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Document introuvable"}), 404

    data = request.get_json() or {}
    totals = _compute_totals(data.get("items", []))

    db.execute(
        """UPDATE documents SET
             status = ?, issue_date = ?, due_date = ?, valid_until = ?, delivery_date = ?,
             customer_name = ?, customer_company = ?, customer_ice = ?, customer_address = ?,
             customer_phone = ?, customer_email = ?, driver_name = ?, vehicle = ?,
             hide_prices = ?, linked_document_id = ?, reason = ?, subtotal = ?,
             discount_total = ?, tax_total = ?, total = ?, amount_paid = ?, notes = ?,
             updated_at = ?
           WHERE id = ?""",
        (
            data.get("status", existing["status"]),
            data.get("issue_date", existing["issue_date"]),
            data.get("due_date", existing["due_date"]),
            data.get("valid_until", existing["valid_until"]),
            data.get("delivery_date", existing["delivery_date"]),
            data.get("customer_name", existing["customer_name"]),
            data.get("customer_company", existing["customer_company"]),
            data.get("customer_ice", existing["customer_ice"]),
            data.get("customer_address", existing["customer_address"]),
            data.get("customer_phone", existing["customer_phone"]),
            data.get("customer_email", existing["customer_email"]),
            data.get("driver_name", existing["driver_name"]),
            data.get("vehicle", existing["vehicle"]),
            1 if data.get("hide_prices", existing["hide_prices"]) else 0,
            data.get("linked_document_id", existing["linked_document_id"]),
            data.get("reason", existing["reason"]),
            totals["subtotal"], totals["discount_total"], totals["tax_total"], totals["total"],
            float(data.get("amount_paid", existing["amount_paid"]) or 0),
            data.get("notes", existing["notes"]),
            now(), doc_id,
        ),
    )
    db.execute("DELETE FROM document_items WHERE document_id = ?", (doc_id,))
    for item in totals["items"]:
        db.execute(
            """INSERT INTO document_items
               (id, document_id, position, description, quantity, unit_price,
                discount_pct, tax_pct, line_total)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item["id"], doc_id, item["position"], item["description"], item["quantity"],
             item["unit_price"], item["discount_pct"], item["tax_pct"], item["line_total"]),
        )
    db.commit()
    return jsonify(_serialize(db, doc_id))


@bp.post("/<doc_id>/duplicate")
def duplicate_document(doc_id):
    db = get_db()
    original = _serialize(db, doc_id)
    if not original:
        return jsonify({"error": "Document introuvable"}), 404

    new_id = str(uuid.uuid4())
    new_number = _next_doc_number(db, original["doc_type"])
    ts = now()

    db.execute(
        """INSERT INTO documents
           (id, doc_type, doc_number, status, issue_date, due_date, valid_until,
            delivery_date, customer_name, customer_company, customer_ice,
            customer_address, customer_phone, customer_email, driver_name,
            vehicle, hide_prices, linked_document_id, reason, subtotal,
            discount_total, tax_total, total, amount_paid, notes,
            created_at, updated_at)
           VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
        (
            new_id, original["doc_type"], new_number, ts[:10],
            original["due_date"], original["valid_until"], original["delivery_date"],
            original["customer_name"], original["customer_company"], original["customer_ice"],
            original["customer_address"], original["customer_phone"], original["customer_email"],
            original["driver_name"], original["vehicle"], original["hide_prices"],
            original["linked_document_id"], original["reason"],
            original["subtotal"], original["discount_total"], original["tax_total"],
            original["total"], original["notes"], ts, ts,
        ),
    )
    for item in original["items"]:
        db.execute(
            """INSERT INTO document_items
               (id, document_id, position, description, quantity, unit_price,
                discount_pct, tax_pct, line_total)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), new_id, item["position"], item["description"],
             item["quantity"], item["unit_price"], item["discount_pct"],
             item["tax_pct"], item["line_total"]),
        )
    db.commit()
    return jsonify(_serialize(db, new_id)), 201


@bp.post("/<doc_id>/status")
def update_status(doc_id):
    db = get_db()
    existing = db.execute("SELECT id FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Document introuvable"}), 404
    data = request.get_json() or {}
    status = data.get("status")
    if not status:
        return jsonify({"error": "status requis"}), 400
    db.execute("UPDATE documents SET status = ?, updated_at = ? WHERE id = ?", (status, now(), doc_id))
    db.commit()
    return jsonify({"ok": True})


@bp.delete("/<doc_id>")
def delete_document(doc_id):
    db = get_db()
    existing = db.execute("SELECT id FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Document introuvable"}), 404
    db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    db.commit()
    return jsonify({"ok": True})


@bp.get("/facture-options")
def facture_options():
    """Lightweight list of completed factures, for the Avoir editor's
    'linked invoice' picker."""
    db = get_db()
    rows = db.execute(
        "SELECT id, doc_number, customer_name, total FROM documents "
        "WHERE doc_type = 'facture' ORDER BY created_at DESC LIMIT 200"
    ).fetchall()
    return jsonify([dict(r) for r in rows])
