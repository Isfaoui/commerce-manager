"""
controllers/app.py - the Flask application and all API routes.

Covers: dashboard, POS (orders/tables/split bills), inventory, suppliers/
purchasing, staff/attendance, approval-gated cancellations & refunds with
audit log, settings.
"""

import uuid
import sqlite3
import json
import os
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, g, send_from_directory
from werkzeug.utils import secure_filename

from models.db import get_db, close_db, init_db, VIEWS_DIR, UPLOADS_DIR, COMPANY_ASSETS_DIR
from models.backup import create_backup, list_backups, restore_backup, BACKUPS_DIR
from utils.helpers import (
    h, now, find_role_permissions, verify_approval,
    get_product, get_recipe_ingredients, compute_unit_cost,
    compute_available_qty, check_stock_available, consume_stock, restock,
    insert_notification,
)

app = Flask(__name__, static_folder=VIEWS_DIR, static_url_path="")
# Needed for Flask's session cookie (used by the staff PIN switch-user
# feature). This server only ever binds to 127.0.0.1 for a single local
# user, so a fresh random key per process start is sufficient - sessions
# don't need to survive an app restart (switching back to full/owner
# access on restart is the intended, documented behavior).
app.secret_key = os.urandom(24)
app.teardown_appcontext(close_db)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB cap on uploaded photos

# Registers /api/license/{status,login,reactivate} and a before_request
# hook that blocks every other /api/* route unless the local, offline
# license check passes. See controllers/license_routes.py.
from controllers.license_routes import register_license_gate  # noqa: E402
register_license_gate(app)

from controllers.documents import bp as documents_bp  # noqa: E402
app.register_blueprint(documents_bp)

from controllers.staff_session import bp as staff_session_bp  # noqa: E402
app.register_blueprint(staff_session_bp)


@app.route("/")
def serve_dashboard():
    return app.send_static_file("dashboard.html")


@app.route("/license.html")
def serve_license_page():
    return app.send_static_file("license.html")


def cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


app.after_request(cors)


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def preflight(_any):
    return "", 204


# ----------------------------------------------------------------
# Products / categories
# ----------------------------------------------------------------

@app.get("/api/categories")
def list_categories():
    db = get_db()
    return jsonify([dict(r) for r in db.execute("SELECT * FROM categories ORDER BY name")])


@app.post("/api/categories")
def create_category():
    data = request.get_json()
    db = get_db()
    cid = str(uuid.uuid4())
    db.execute("INSERT INTO categories (id, name) VALUES (?, ?)", (cid, data["name"]))
    db.commit()
    return jsonify({"id": cid, "name": data["name"]}), 201


@app.get("/api/products")
def list_products():
    db = get_db()
    sellable_only = request.args.get("sellable_only") == "1"
    query = (
        "SELECT p.*, c.name AS category_name FROM products p "
        "LEFT JOIN categories c ON c.id = p.category_id WHERE p.active = 1"
    )
    if sellable_only:
        query += " AND p.sellable = 1"
    query += " ORDER BY p.name"

    rows = db.execute(query).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if row["product_type"] == "recipe":
            d["cost_price"] = compute_unit_cost(db, row)
            d["available_qty"] = compute_available_qty(db, row)
            ingredients = get_recipe_ingredients(db, row["id"])
            d["ingredients"] = [
                {"ingredient_product_id": i["ingredient_product_id"], "name": i["ingredient_name"],
                 "quantity": i["quantity"], "unit": i["ingredient_unit"]}
                for i in ingredients
            ]
        else:
            d["available_qty"] = row["stock_qty"]
            d["ingredients"] = []
        result.append(d)
    return jsonify(result)


@app.post("/api/products")
def create_product():
    data = request.get_json()
    if not data or not data.get("name") or data.get("sale_price") is None:
        return jsonify({"error": "name and sale_price are required"}), 400

    product_type = data.get("product_type", "simple")
    db = get_db()
    pid = str(uuid.uuid4())

    try:
        db.execute(
            "INSERT INTO products (id, name, barcode, category_id, product_type, sellable, unit, "
            "cost_price, sale_price, stock_qty, reorder_threshold, expiry_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, data["name"], data.get("barcode") or None, data.get("category_id"),
             product_type, 1 if data.get("sellable", True) else 0, data.get("unit", "unite"),
             data.get("cost_price", 0) if product_type == "simple" else 0,
             data["sale_price"],
             data.get("stock_qty", 0) if product_type == "simple" else 0,
             data.get("reorder_threshold", 5),
             data.get("expiry_date") or None),
        )

        if product_type == "recipe":
            for ing in data.get("ingredients", []):
                db.execute(
                    "INSERT INTO recipe_ingredients (id, product_id, ingredient_product_id, quantity) "
                    "VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), pid, ing["ingredient_product_id"], ing["quantity"]),
                )

        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify({"error": "Ce code-barres est deja utilise par un autre produit"}), 400

    row = db.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    return jsonify(dict(row)), 201


@app.patch("/api/products/<product_id>")
def update_product(product_id):
    db = get_db()
    existing = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Product not found"}), 404

    data = request.get_json()
    product_type = existing["product_type"]  # type can't change after creation

    try:
        db.execute(
            "UPDATE products SET name = ?, barcode = ?, category_id = ?, sellable = ?, unit = ?, "
            "cost_price = ?, sale_price = ?, stock_qty = ?, reorder_threshold = ?, expiry_date = ? WHERE id = ?",
            (data.get("name", existing["name"]),
             data.get("barcode", existing["barcode"]) or None,
             data.get("category_id", existing["category_id"]),
             1 if data.get("sellable", existing["sellable"]) else 0,
             data.get("unit", existing["unit"]),
             data.get("cost_price", existing["cost_price"]) if product_type == "simple" else existing["cost_price"],
             data.get("sale_price", existing["sale_price"]),
             data.get("stock_qty", existing["stock_qty"]) if product_type == "simple" else existing["stock_qty"],
             data.get("reorder_threshold", existing["reorder_threshold"]),
             data.get("expiry_date", existing["expiry_date"]) or None,
             product_id),
        )

        if product_type == "recipe" and "ingredients" in data:
            db.execute("DELETE FROM recipe_ingredients WHERE product_id = ?", (product_id,))
            for ing in data["ingredients"]:
                db.execute(
                    "INSERT INTO recipe_ingredients (id, product_id, ingredient_product_id, quantity) "
                    "VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), product_id, ing["ingredient_product_id"], ing["quantity"]),
                )

        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify({"error": "Ce code-barres est deja utilise par un autre produit"}), 400

    row = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return jsonify(dict(row))


@app.delete("/api/products/<product_id>")
def delete_product(product_id):
    db = get_db()
    existing = db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Product not found"}), 404

    # Refuse to remove a raw material that's still used in an active recipe -
    # deleting it out from under a recipe would silently break that recipe's
    # cost and stock calculations.
    used_in = db.execute(
        "SELECT p.name FROM recipe_ingredients ri JOIN products p ON p.id = ri.product_id "
        "WHERE ri.ingredient_product_id = ? AND p.active = 1", (product_id,)
    ).fetchall()
    if used_in:
        names = ", ".join(r["name"] for r in used_in)
        return jsonify({
            "error": f"Impossible de supprimer : utilise dans la recette de {names}. "
                     f"Retirez-le de ces recettes d'abord."
        }), 400

    # Soft delete - keeps historical ticket_items referencing this product
    # (and their unit_cost snapshots) intact for past reports.
    db.execute("UPDATE products SET active = 0 WHERE id = ?", (product_id,))
    db.commit()
    return jsonify({"ok": True})


ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}


@app.post("/api/products/<product_id>/image")
def upload_product_image(product_id):
    db = get_db()
    product = get_product(db, product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify({"error": "Aucun fichier recu"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({"error": "Format non supporte (utilisez PNG, JPG, WEBP ou GIF)"}), 400

    # Remove any previous photo for this product before saving the new one.
    if product["image_filename"]:
        old_path = os.path.join(UPLOADS_DIR, product["image_filename"])
        if os.path.exists(old_path):
            os.remove(old_path)

    filename = secure_filename(f"{product_id}.{ext}")
    file.save(os.path.join(UPLOADS_DIR, filename))
    db.execute("UPDATE products SET image_filename = ? WHERE id = ?", (filename, product_id))
    db.commit()
    return jsonify({"image_filename": filename})


@app.get("/uploads/products/<filename>")
def serve_product_image(filename):
    return send_from_directory(UPLOADS_DIR, filename)


ALLOWED_LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "svg"}


@app.post("/api/branding/logo")
def upload_company_logo():
    """Stores the company logo once, centrally - referenced everywhere
    (sidebar, login screen, receipts, and future invoice documents) via
    the company_logo_filename setting instead of duplicating the file."""
    db = get_db()
    file = request.files.get("logo")
    if not file or not file.filename:
        return jsonify({"error": "Aucun fichier recu"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_LOGO_EXTENSIONS:
        return jsonify({"error": "Format non supporte (utilisez PNG, JPG ou SVG)"}), 400

    existing = db.execute("SELECT value FROM settings WHERE key = 'company_logo_filename'").fetchone()
    if existing and existing["value"]:
        old_path = os.path.join(COMPANY_ASSETS_DIR, existing["value"])
        if os.path.exists(old_path):
            os.remove(old_path)

    filename = secure_filename(f"logo.{ext}")
    file.save(os.path.join(COMPANY_ASSETS_DIR, filename))
    db.execute(
        "INSERT INTO settings (key, value) VALUES ('company_logo_filename', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (filename,),
    )
    db.commit()
    return jsonify({"company_logo_filename": filename})


@app.get("/uploads/company/<filename>")
def serve_company_asset(filename):
    return send_from_directory(COMPANY_ASSETS_DIR, filename)


@app.get("/api/products/low-stock")
def low_stock():
    db = get_db()
    # Recipe products have no stock_qty of their own (it's derived from
    # ingredients) - alerting on the ingredients themselves already covers it.
    rows = db.execute(
        "SELECT * FROM products WHERE stock_qty <= reorder_threshold "
        "AND active = 1 AND product_type = 'simple' ORDER BY stock_qty"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/products/overstock")
def overstock():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM products WHERE stock_qty >= overstock_threshold "
        "AND active = 1 AND product_type = 'simple'"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/products/expiring-soon")
def expiring_soon():
    """Products with a tracked expiry_date within the next N days (default
    7, overridable with ?days=), including any already past their date."""
    db = get_db()
    days = request.args.get("days", 7, type=int)
    cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    rows = db.execute(
        "SELECT * FROM products WHERE expiry_date IS NOT NULL AND expiry_date != '' "
        "AND expiry_date <= ? AND active = 1 ORDER BY expiry_date",
        (cutoff,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ----------------------------------------------------------------
# Dining tables
# ----------------------------------------------------------------

@app.get("/api/tables")
def list_tables():
    db = get_db()
    return jsonify([dict(r) for r in db.execute("SELECT * FROM dining_tables ORDER BY label")])


@app.post("/api/tables")
def create_table():
    data = request.get_json()
    db = get_db()
    tid = str(uuid.uuid4())
    db.execute("INSERT INTO dining_tables (id, label, seats) VALUES (?, ?, ?)",
               (tid, data["label"], data.get("seats", 2)))
    db.commit()
    return jsonify({"id": tid, "label": data["label"], "seats": data.get("seats", 2), "status": "free"}), 201


# ----------------------------------------------------------------
# Orders (dine-in / takeaway / delivery) - open, add items, pay, split, cancel
# ----------------------------------------------------------------

def serialize_ticket(db, ticket_id):
    t = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not t:
        return None
    items = db.execute("SELECT * FROM ticket_items WHERE ticket_id = ?", (ticket_id,)).fetchall()
    payments = db.execute("SELECT * FROM payments WHERE ticket_id = ?", (ticket_id,)).fetchall()
    d = dict(t)
    d["items"] = [dict(i) for i in items]
    d["payments"] = [dict(p) for p in payments]
    if t["customer_id"]:
        customer = db.execute("SELECT name FROM customers WHERE id = ?", (t["customer_id"],)).fetchone()
        d["customer_name"] = customer["name"] if customer else None
    else:
        d["customer_name"] = None
    return d


def get_tax_rate(db):
    row = db.execute("SELECT value FROM settings WHERE key = 'default_tax_rate'").fetchone()
    try:
        return float(row["value"]) if row and row["value"] else 0.0
    except (ValueError, TypeError):
        return 0.0


def _create_order_internal(db, items, order_type, table_id=None, delivery_address=None, discount=None):
    resolved = []  # list of dicts: {kind, product, quantity, unit_price, unit_cost, name}
    tax_rate = get_tax_rate(db)

    for item in items:
        quantity = item["quantity"]
        if item.get("product_id"):
            product = get_product(db, item["product_id"])
            if not product:
                return None, f"Product {item['product_id']} not found"
            error = check_stock_available(db, product, quantity)
            if error:
                return None, error
            resolved.append({
                "kind": "catalog", "product": product, "quantity": quantity,
                "unit_price": product["sale_price"], "unit_cost": compute_unit_cost(db, product),
                "name": product["name"],
            })
        else:
            # Unlisted/custom item - no catalog entry, no stock tracking.
            name = item.get("custom_name", "Article")
            unit_price = item.get("unit_price", 0)
            resolved.append({
                "kind": "custom", "product": None, "quantity": quantity,
                "unit_price": unit_price, "unit_cost": 0, "name": name,
            })

    # Discount is applied to the raw TTC total, before tax is decomposed -
    # it reduces what the customer actually pays, and tax is calculated on
    # that reduced amount (not on the original price).
    raw_total = sum(r["unit_price"] * r["quantity"] for r in resolved)
    discount_amount = 0.0
    if discount and discount.get("value"):
        if discount.get("type") == "percent":
            discount_amount = raw_total * (discount["value"] / 100)
        else:
            discount_amount = discount["value"]
        discount_amount = max(0.0, min(discount_amount, raw_total))

    discount_ratio = (discount_amount / raw_total) if raw_total > 0 else 0.0
    total_ttc = raw_total - discount_amount
    tax_divisor = 100 + tax_rate

    last = db.execute("SELECT MAX(ticket_number) AS m FROM tickets").fetchone()
    next_number = (last["m"] or 0) + 1
    ticket_id = str(uuid.uuid4())

    tax_total = 0.0
    for r in resolved:
        raw_line_total = r["unit_price"] * r["quantity"]
        line_total = raw_line_total * (1 - discount_ratio)
        r["line_total"] = line_total
        r["tax_amount"] = (line_total * tax_rate / tax_divisor) if tax_divisor > 0 else 0.0
        tax_total += r["tax_amount"]
    subtotal_ht = total_ttc - tax_total

    db.execute(
        "INSERT INTO tickets (id, ticket_number, order_type, table_id, delivery_address, "
        "status, subtotal, tax_total, discount_total, total, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)",
        (ticket_id, next_number, order_type, table_id, delivery_address,
         subtotal_ht, tax_total, discount_amount, total_ttc, now()),
    )

    for r in resolved:
        db.execute(
            "INSERT INTO ticket_items (id, ticket_id, product_id, product_name, quantity, "
            "unit_price, unit_cost, tax_amount, line_total) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), ticket_id, r["product"]["id"] if r["product"] else None, r["name"],
             r["quantity"], r["unit_price"], r["unit_cost"], r["tax_amount"], r["line_total"]),
        )
        if r["kind"] == "catalog":
            consume_stock(db, r["product"], r["quantity"])

    if table_id:
        db.execute("UPDATE dining_tables SET status = 'occupied' WHERE id = ?", (table_id,))
    return ticket_id, None


@app.post("/api/orders")
def create_order():
    data = request.get_json()
    items = data.get("items") or []
    order_type = data.get("order_type", "takeaway")
    table_id = data.get("table_id")

    if order_type == "dine_in" and not table_id:
        return jsonify({"error": "table_id is required for dine-in orders"}), 400
    if not items:
        return jsonify({"error": "An order needs at least one item"}), 400

    db = get_db()
    ticket_id, error = _create_order_internal(
        db, items, order_type, table_id, data.get("delivery_address"), data.get("discount")
    )
    if error:
        return jsonify({"error": error}), 400
    db.commit()
    return jsonify(serialize_ticket(db, ticket_id)), 201


@app.post("/api/orders/<ticket_id>/pay")
def pay_order(ticket_id):
    data = request.get_json()
    payments = data.get("payments") or []
    db = get_db()
    ticket = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not ticket:
        return jsonify({"error": "Order not found"}), 404
    if ticket["status"] != "open":
        return jsonify({"error": f"Order is '{ticket['status']}', cannot be paid"}), 400

    paid = sum(p["amount"] for p in payments)
    if abs(paid - ticket["total"]) > 0.01:
        return jsonify({"error": f"Payments ({paid:.2f}) don't match total ({ticket['total']:.2f})"}), 400

    for p in payments:
        db.execute("INSERT INTO payments (id, ticket_id, method, amount, created_at) VALUES (?, ?, ?, ?, ?)",
                   (str(uuid.uuid4()), ticket_id, p["method"], p["amount"], now()))

    db.execute("UPDATE tickets SET status = 'completed', closed_at = ? WHERE id = ?", (now(), ticket_id))
    if ticket["table_id"]:
        remaining = db.execute(
            "SELECT COUNT(*) AS c FROM tickets WHERE table_id = ? AND status = 'open' AND id != ?",
            (ticket["table_id"], ticket_id),
        ).fetchone()["c"]
        if remaining == 0:
            db.execute("UPDATE dining_tables SET status = 'free' WHERE id = ?", (ticket["table_id"],))
    db.commit()
    return jsonify(serialize_ticket(db, ticket_id))


@app.post("/api/orders/<ticket_id>/split")
def split_order(ticket_id):
    data = request.get_json()
    groups = data.get("groups") or []
    db = get_db()
    parent = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not parent or parent["status"] != "open":
        return jsonify({"error": "Order not found or not open"}), 400

    last = db.execute("SELECT MAX(ticket_number) AS m FROM tickets").fetchone()
    next_number = (last["m"] or 0) + 1
    created = []

    for group in groups:
        child_id = str(uuid.uuid4())
        child_items = []
        child_total = 0.0
        child_tax = 0.0
        child_discount = 0.0
        for item_id in group:
            item = db.execute("SELECT * FROM ticket_items WHERE id = ? AND ticket_id = ?",
                              (item_id, ticket_id)).fetchone()
            if not item:
                continue
            child_items.append(item_id)
            child_total += item["line_total"]
            child_tax += item["tax_amount"]
            child_discount += (item["unit_price"] * item["quantity"]) - item["line_total"]

        db.execute(
            "INSERT INTO tickets (id, ticket_number, order_type, table_id, parent_ticket_id, "
            "status, subtotal, tax_total, discount_total, total, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)",
            (child_id, next_number, parent["order_type"], parent["table_id"], ticket_id,
             child_total - child_tax, child_tax, child_discount, child_total, now()),
        )
        for item_id in child_items:
            db.execute("UPDATE ticket_items SET ticket_id = ? WHERE id = ?", (child_id, item_id))
        next_number += 1
        created.append(child_id)

    remaining = db.execute(
        "SELECT COALESCE(SUM(line_total), 0) AS total, COALESCE(SUM(tax_amount), 0) AS tax, "
        "COALESCE(SUM(unit_price * quantity - line_total), 0) AS discount "
        "FROM ticket_items WHERE ticket_id = ?", (ticket_id,)
    ).fetchone()
    if remaining["total"] == 0:
        db.execute("UPDATE tickets SET status = 'split', subtotal = 0, tax_total = 0, discount_total = 0, total = 0 WHERE id = ?", (ticket_id,))
    else:
        db.execute("UPDATE tickets SET subtotal = ?, tax_total = ?, discount_total = ?, total = ? WHERE id = ?",
                   (remaining["total"] - remaining["tax"], remaining["tax"], remaining["discount"], remaining["total"], ticket_id))

    db.commit()
    return jsonify({"created": [serialize_ticket(db, c) for c in created]}), 201


@app.post("/api/orders/<ticket_id>/cancel")
def cancel_order(ticket_id):
    """Requires approval. Restocks items, logs to approval_audit_log."""
    data = request.get_json() or {}
    db = get_db()
    ticket = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not ticket:
        return jsonify({"error": "Order not found"}), 404
    if ticket["status"] not in ("open", "completed"):
        return jsonify({"error": f"Order already '{ticket['status']}'"}), 400
    if not data.get("reason"):
        return jsonify({"error": "A reason is required"}), 400

    approver = verify_approval(db, data.get("approval", {}))
    if not approver:
        return jsonify({"error": "Approval required: manager approval, admin PIN, NFC card, or password"}), 403

    action_type = "refund" if ticket["status"] == "completed" else "cancel_order"

    items = db.execute("SELECT * FROM ticket_items WHERE ticket_id = ?", (ticket_id,)).fetchall()
    for item in items:
        if item["product_id"]:
            restock(db, item["product_id"], item["quantity"])

    db.execute("UPDATE tickets SET status = ?, cancel_reason = ?, closed_at = ? WHERE id = ?",
               ("cancelled" if action_type == "cancel_order" else "refunded", data["reason"], now(), ticket_id))

    if ticket["table_id"]:
        remaining = db.execute(
            "SELECT COUNT(*) AS c FROM tickets WHERE table_id = ? AND status = 'open' AND id != ?",
            (ticket["table_id"], ticket_id),
        ).fetchone()["c"]
        if remaining == 0:
            db.execute("UPDATE dining_tables SET status = 'free' WHERE id = ?", (ticket["table_id"],))

    db.execute(
        "INSERT INTO approval_audit_log (id, action_type, reference_id, requested_by, approved_by, "
        "approval_method, reason, original_amount, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), action_type, ticket_id, data.get("requested_by"), approver["id"],
         data["approval"]["method"], data["reason"], ticket["total"], now()),
    )
    label = "Remboursement" if action_type == "refund" else "Annulation"
    insert_notification(db, action_type, f"{label} - ticket #{ticket['ticket_number']} ({ticket['total']:.2f} MAD) par {approver['name']}")
    db.commit()
    return jsonify(serialize_ticket(db, ticket_id))


@app.get("/api/orders/open")
def list_open_orders():
    db = get_db()
    rows = db.execute("SELECT id FROM tickets WHERE status = 'open' ORDER BY created_at").fetchall()
    return jsonify([serialize_ticket(db, r["id"]) for r in rows])


@app.get("/api/orders/active")
def list_active_orders():
    """Orders that still need attention: unpaid, OR paid but not yet served.
    Fulfillment (served/pending) is tracked independently of payment status,
    since takeaway/delivery are often paid before prep while dine-in is
    often paid after."""
    db = get_db()
    rows = db.execute(
        "SELECT id FROM tickets WHERE status = 'open' "
        "OR (status = 'completed' AND fulfillment_status = 'pending') "
        "ORDER BY created_at"
    ).fetchall()
    return jsonify([serialize_ticket(db, r["id"]) for r in rows])


@app.post("/api/orders/<ticket_id>/mark-served")
def mark_served(ticket_id):
    db = get_db()
    ticket = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not ticket:
        return jsonify({"error": "Order not found"}), 404
    db.execute("UPDATE tickets SET fulfillment_status = 'served' WHERE id = ?", (ticket_id,))
    db.commit()
    return jsonify(serialize_ticket(db, ticket_id))


@app.get("/api/audit-log")
def audit_log():
    db = get_db()
    rows = db.execute(
        "SELECT a.*, e.name AS approved_by_name FROM approval_audit_log a "
        "LEFT JOIN employees e ON e.id = a.approved_by ORDER BY a.created_at DESC LIMIT 50"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ----------------------------------------------------------------
# Legacy quick-sale endpoint (kept for the simple takeaway flow)
# ----------------------------------------------------------------

@app.post("/api/sales")
def quick_sale():
    data = request.get_json()
    items = data.get("items") or []
    if not items:
        return jsonify({"error": "A sale needs at least one item"}), 400

    db = get_db()
    ticket_id, error = _create_order_internal(db, items, "takeaway")
    if error:
        return jsonify({"error": error}), 400

    ticket = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    db.execute("INSERT INTO payments (id, ticket_id, method, amount, created_at) VALUES (?, ?, 'cash', ?, ?)",
               (str(uuid.uuid4()), ticket_id, ticket["total"], now()))
    db.execute("UPDATE tickets SET status = 'completed', closed_at = ? WHERE id = ?", (now(), ticket_id))
    db.commit()
    return jsonify(serialize_ticket(db, ticket_id)), 201


@app.get("/api/sales")
def list_sales():
    db = get_db()
    rows = db.execute(
        "SELECT id FROM tickets WHERE status IN ('completed','refunded') ORDER BY created_at DESC"
    ).fetchall()
    return jsonify([serialize_ticket(db, r["id"]) for r in rows])


# ----------------------------------------------------------------
# Suppliers & purchasing
# ----------------------------------------------------------------

@app.get("/api/suppliers")
def list_suppliers():
    db = get_db()
    return jsonify([dict(r) for r in db.execute("SELECT * FROM suppliers ORDER BY name")])


@app.post("/api/suppliers")
def create_supplier():
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "Le nom est requis"}), 400
    db = get_db()
    sid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO suppliers (id, name, contact_person, phone, email, address, ice, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (sid, data["name"], data.get("contact_person"), data.get("phone"), data.get("email"),
         data.get("address"), data.get("ice"), data.get("notes")),
    )
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM suppliers WHERE id = ?", (sid,)).fetchone())), 201


@app.patch("/api/suppliers/<supplier_id>")
def update_supplier(supplier_id):
    db = get_db()
    existing = db.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Fournisseur introuvable"}), 404
    data = request.get_json() or {}
    db.execute(
        "UPDATE suppliers SET name = ?, contact_person = ?, phone = ?, email = ?, "
        "address = ?, ice = ?, notes = ? WHERE id = ?",
        (
            data.get("name", existing["name"]),
            data.get("contact_person", existing["contact_person"]),
            data.get("phone", existing["phone"]),
            data.get("email", existing["email"]),
            data.get("address", existing["address"]),
            data.get("ice", existing["ice"]),
            data.get("notes", existing["notes"]),
            supplier_id,
        ),
    )
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()))


@app.delete("/api/suppliers/<supplier_id>")
def delete_supplier(supplier_id):
    db = get_db()
    existing = db.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Fournisseur introuvable"}), 404
    if abs(existing["balance_due"]) > 0.005:
        return jsonify({"error": "Impossible de supprimer : solde du a ce fournisseur non nul."}), 400
    linked_po = db.execute(
        "SELECT COUNT(*) AS c FROM purchase_orders WHERE supplier_id = ?", (supplier_id,)
    ).fetchone()
    if linked_po["c"] > 0:
        return jsonify({"error": "Ce fournisseur a des receptions enregistrees et ne peut pas etre supprime."}), 400
    db.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/purchase-orders")
def list_purchase_orders():
    db = get_db()
    rows = db.execute(
        "SELECT po.*, s.name AS supplier_name FROM purchase_orders po "
        "LEFT JOIN suppliers s ON s.id = po.supplier_id ORDER BY po.created_at DESC"
    ).fetchall()
    result = []
    for po in rows:
        items = db.execute("SELECT * FROM purchase_order_items WHERE purchase_order_id = ?", (po["id"],)).fetchall()
        d = dict(po)
        d["items"] = [dict(i) for i in items]
        result.append(d)
    return jsonify(result)


@app.post("/api/purchase-orders")
def create_purchase_order():
    """Receiving goods: immediately increases stock and updates cost price."""
    data = request.get_json()
    items = data.get("items") or []
    if not items:
        return jsonify({"error": "A purchase order needs at least one item"}), 400
    db = get_db()

    resolved = []
    total = 0.0
    for item in items:
        product = db.execute("SELECT * FROM products WHERE id = ?", (item["product_id"],)).fetchone()
        if not product:
            return jsonify({"error": f"Product {item['product_id']} not found"}), 404
        resolved.append((product, item["quantity"], item["unit_cost"]))
        total += item["quantity"] * item["unit_cost"]

    po_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO purchase_orders (id, supplier_id, status, total_amount, created_at) "
        "VALUES (?, ?, 'received', ?, ?)",
        (po_id, data.get("supplier_id"), total, now()),
    )

    for product, quantity, unit_cost in resolved:
        db.execute(
            "INSERT INTO purchase_order_items (id, purchase_order_id, product_id, quantity, unit_cost) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), po_id, product["id"], quantity, unit_cost),
        )
        db.execute("UPDATE products SET stock_qty = stock_qty + ?, cost_price = ? WHERE id = ?",
                   (quantity, unit_cost, product["id"]))

    if data.get("supplier_id"):
        db.execute("UPDATE suppliers SET balance_due = balance_due + ? WHERE id = ?",
                   (total, data["supplier_id"]))
    db.commit()
    return jsonify({"id": po_id, "total_amount": total}), 201


@app.delete("/api/purchase-orders/<po_id>")
def delete_purchase_order(po_id):
    """Deleting a purchase order reverses the stock it added - it was a real
    receiving event, so removing the record without undoing its effect
    would leave stock numbers wrong. Cost_price is NOT reverted (it may
    have been overwritten by later purchases since), which is disclosed
    to the user in the confirmation prompt."""
    db = get_db()
    po = db.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if not po:
        return jsonify({"error": "Purchase order not found"}), 404

    items = db.execute("SELECT * FROM purchase_order_items WHERE purchase_order_id = ?", (po_id,)).fetchall()
    for item in items:
        db.execute("UPDATE products SET stock_qty = stock_qty - ? WHERE id = ?",
                   (item["quantity"], item["product_id"]))

    if po["supplier_id"]:
        db.execute("UPDATE suppliers SET balance_due = balance_due - ? WHERE id = ?",
                   (po["total_amount"], po["supplier_id"]))

    db.execute("DELETE FROM purchase_order_items WHERE purchase_order_id = ?", (po_id,))
    db.execute("DELETE FROM purchase_orders WHERE id = ?", (po_id,))
    db.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------
# Staff: roles, employees, attendance
# ----------------------------------------------------------------
from controllers.staff_session import require_staff_page, ALL_PAGES  # noqa: E402


@app.get("/api/roles")
@require_staff_page("staff")
def list_roles():
    db = get_db()
    return jsonify([dict(r) for r in db.execute("SELECT * FROM roles ORDER BY name")])


@app.post("/api/roles")
@require_staff_page("staff")
def create_role():
    data = request.get_json() or {}
    if not data.get("name"):
        return jsonify({"error": "Le nom est requis"}), 400
    pages = [p for p in (data.get("pages") or []) if p in ALL_PAGES]
    db = get_db()
    rid = str(uuid.uuid4())
    db.execute("INSERT INTO roles (id, name, permissions) VALUES (?, ?, ?)",
               (rid, data["name"], json.dumps({"pages": pages})))
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM roles WHERE id = ?", (rid,)).fetchone())), 201


@app.patch("/api/roles/<role_id>")
@require_staff_page("staff")
def update_role(role_id):
    db = get_db()
    existing = db.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Role introuvable"}), 404
    data = request.get_json() or {}
    name = data.get("name", existing["name"])
    pages = data.get("pages")
    permissions = json.dumps({"pages": [p for p in pages if p in ALL_PAGES]}) if pages is not None else existing["permissions"]
    db.execute("UPDATE roles SET name = ?, permissions = ? WHERE id = ?", (name, permissions, role_id))
    db.commit()
    return jsonify(dict(db.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()))


@app.delete("/api/roles/<role_id>")
@require_staff_page("staff")
def delete_role(role_id):
    db = get_db()
    in_use = db.execute("SELECT COUNT(*) AS c FROM employees WHERE role_id = ?", (role_id,)).fetchone()
    if in_use["c"] > 0:
        return jsonify({"error": "Ce role est assigne a des employes et ne peut pas etre supprime."}), 400
    db.execute("DELETE FROM roles WHERE id = ?", (role_id,))
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/employees")
@require_staff_page("staff")
def list_employees():
    db = get_db()
    rows = db.execute(
        "SELECT e.id, e.name, e.email, e.phone, e.role_id, e.hourly_rate, e.hire_date, e.active, "
        "r.name AS role_name FROM employees e LEFT JOIN roles r ON r.id = e.role_id ORDER BY e.active DESC, e.name"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/employees")
@require_staff_page("staff")
def create_employee():
    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "Le nom est requis"}), 400
    db = get_db()
    eid = str(uuid.uuid4())
    try:
        db.execute(
            "INSERT INTO employees (id, name, email, phone, role_id, pin_hash, password_hash, nfc_card_id, "
            "hourly_rate, hire_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, data["name"], data.get("email") or None, data.get("phone"), data.get("role_id") or None,
             h(data["pin"]) if data.get("pin") else None,
             h(data["password"]) if data.get("password") else None,
             data.get("nfc_card_id") or None, data.get("hourly_rate") or None, data.get("hire_date") or None),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "Un employe avec cet email existe deja."}), 409
    db.commit()
    return jsonify({"id": eid, "name": data["name"]}), 201


@app.patch("/api/employees/<employee_id>")
@require_staff_page("staff")
def update_employee(employee_id):
    db = get_db()
    existing = db.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Employe introuvable"}), 404
    data = request.get_json() or {}
    try:
        db.execute(
            "UPDATE employees SET name = ?, email = ?, phone = ?, role_id = ?, hourly_rate = ?, "
            "hire_date = ? WHERE id = ?",
            (
                data.get("name", existing["name"]),
                data.get("email", existing["email"]) or None,
                data.get("phone", existing["phone"]),
                data.get("role_id", existing["role_id"]) or None,
                data.get("hourly_rate", existing["hourly_rate"]) or None,
                data.get("hire_date", existing["hire_date"]) or None,
                employee_id,
            ),
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "Un employe avec cet email existe deja."}), 409
    if data.get("pin"):
        db.execute("UPDATE employees SET pin_hash = ? WHERE id = ?", (h(data["pin"]), employee_id))
    if data.get("password"):
        db.execute("UPDATE employees SET password_hash = ? WHERE id = ?", (h(data["password"]), employee_id))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/employees/<employee_id>/deactivate")
@require_staff_page("staff")
def deactivate_employee(employee_id):
    db = get_db()
    existing = db.execute("SELECT id FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Employe introuvable"}), 404
    db.execute("UPDATE employees SET active = 0 WHERE id = ?", (employee_id,))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/employees/<employee_id>/reactivate")
@require_staff_page("staff")
def reactivate_employee(employee_id):
    db = get_db()
    existing = db.execute("SELECT id FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Employe introuvable"}), 404
    db.execute("UPDATE employees SET active = 1 WHERE id = ?", (employee_id,))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/attendance/clock-in")
def clock_in():
    data = request.get_json()
    db = get_db()
    aid = str(uuid.uuid4())
    db.execute("INSERT INTO attendance (id, employee_id, clock_in) VALUES (?, ?, ?)",
               (aid, data["employee_id"], now()))
    db.commit()
    return jsonify({"id": aid}), 201


@app.post("/api/attendance/clock-out")
def clock_out():
    data = request.get_json()
    db = get_db()
    row = db.execute(
        "SELECT * FROM attendance WHERE employee_id = ? AND clock_out IS NULL "
        "ORDER BY clock_in DESC LIMIT 1", (data["employee_id"],)
    ).fetchone()
    if not row:
        return jsonify({"error": "No open shift for this employee"}), 400
    db.execute("UPDATE attendance SET clock_out = ? WHERE id = ?", (now(), row["id"]))
    db.commit()
    return jsonify({"id": row["id"]})


@app.get("/api/attendance/today")
def attendance_today():
    db = get_db()
    today = datetime.now(timezone.utc).date().isoformat()
    rows = db.execute(
        "SELECT a.*, e.name AS employee_name FROM attendance a "
        "JOIN employees e ON e.id = a.employee_id WHERE date(a.clock_in) = date(?) "
        "ORDER BY a.clock_in DESC", (today,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/attendance/history")
def attendance_history():
    db = get_db()
    employee_id = request.args.get("employee_id")
    start = request.args.get("start")
    end = request.args.get("end")

    query = "SELECT a.*, e.name AS employee_name, e.hourly_rate FROM attendance a JOIN employees e ON e.id = a.employee_id WHERE 1=1"
    params: list = []
    if employee_id:
        query += " AND a.employee_id = ?"
        params.append(employee_id)
    if start:
        query += " AND date(a.clock_in) >= date(?)"
        params.append(start)
    if end:
        query += " AND date(a.clock_in) <= date(?)"
        params.append(end)
    query += " ORDER BY a.clock_in DESC LIMIT 500"

    rows = db.execute(query, params).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d["clock_in"] and d["clock_out"]:
            in_dt = datetime.fromisoformat(d["clock_in"])
            out_dt = datetime.fromisoformat(d["clock_out"])
            hours = (out_dt - in_dt).total_seconds() / 3600
            d["hours"] = round(hours, 2)
            d["estimated_pay"] = round(hours * (d["hourly_rate"] or 0), 2) if d["hourly_rate"] else None
        else:
            d["hours"] = None
            d["estimated_pay"] = None
        result.append(d)
    return jsonify(result)


# ----------------------------------------------------------------
# Settings & payment methods
# ----------------------------------------------------------------

@app.get("/api/settings")
def get_settings():
    db = get_db()
    rows = db.execute("SELECT * FROM settings").fetchall()
    return jsonify({r["key"]: r["value"] for r in rows})


DEFAULT_CATEGORIES_BY_TYPE = {
    "restaurant": ["Entrees", "Plats", "Desserts", "Boissons"],
    "cafe": ["Boissons chaudes", "Boissons froides", "Patisseries", "Snacks"],
    "grocery": ["Epicerie", "Boissons", "Hygiene", "Frais"],
    "service": ["Prestations", "Produits"],
    "other": ["General"],
}

DEFAULT_ROLES = {
    "owner": {"approve_cancellations": True, "view_reports": True, "manage_staff": True, "manage_settings": True},
    "manager": {"approve_cancellations": True, "view_reports": True, "manage_staff": True, "manage_settings": False},
    "cashier": {"approve_cancellations": False, "view_reports": False, "manage_staff": False, "manage_settings": False},
}


@app.post("/api/settings")
def update_settings():
    data = request.get_json()
    db = get_db()

    is_first_business_type = False
    if "business_type" in data:
        existing = db.execute("SELECT value FROM settings WHERE key = 'business_type'").fetchone()
        if existing and existing["value"]:
            return jsonify({
                "error": "Le type de commerce a deja ete defini et ne peut plus etre modifie."
            }), 403
        is_first_business_type = True

    for key, value in data.items():
        db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    if is_first_business_type:
        category_count = db.execute("SELECT COUNT(*) AS c FROM categories").fetchone()["c"]
        if category_count == 0:
            names = DEFAULT_CATEGORIES_BY_TYPE.get(data["business_type"], DEFAULT_CATEGORIES_BY_TYPE["other"])
            for name in names:
                db.execute("INSERT INTO categories (id, name) VALUES (?, ?)", (str(uuid.uuid4()), name))

        role_count = db.execute("SELECT COUNT(*) AS c FROM roles").fetchone()["c"]
        if role_count == 0:
            for name, perms in DEFAULT_ROLES.items():
                db.execute("INSERT INTO roles (id, name, permissions) VALUES (?, ?, ?)",
                           (str(uuid.uuid4()), name, json.dumps(perms)))

    db.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------
# Backup & restore
# ----------------------------------------------------------------

@app.get("/api/backups")
def get_backups():
    return jsonify(list_backups())


@app.post("/api/backups")
def make_backup():
    filename = create_backup(prefix="backup")
    db = get_db()
    insert_notification(db, "backup", f"Sauvegarde manuelle creee ({filename})")
    db.commit()
    return jsonify({"filename": filename}), 201


@app.post("/api/backups/<filename>/restore")
def do_restore_backup(filename):
    try:
        restore_backup(filename)
    except (FileNotFoundError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.delete("/api/backups/<filename>")
def delete_backup(filename):
    path = os.path.join(BACKUPS_DIR, filename)
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"ok": True})


@app.get("/api/backups/<filename>/download")
def download_backup(filename):
    return send_from_directory(BACKUPS_DIR, filename, as_attachment=True)


# ----------------------------------------------------------------
# Notifications
# ----------------------------------------------------------------

@app.get("/api/notifications")
def get_notifications():
    db = get_db()
    events = db.execute(
        "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    low_stock = db.execute(
        "SELECT name, stock_qty FROM products WHERE stock_qty <= reorder_threshold "
        "AND active = 1 AND product_type = 'simple' ORDER BY stock_qty"
    ).fetchall()
    expiry_cutoff = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    expiring_soon = db.execute(
        "SELECT name, expiry_date FROM products WHERE expiry_date IS NOT NULL "
        "AND expiry_date != '' AND expiry_date <= ? AND active = 1 ORDER BY expiry_date",
        (expiry_cutoff,),
    ).fetchall()
    unread_count = db.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE read = 0"
    ).fetchone()["c"]
    return jsonify({
        "events": [dict(e) for e in events],
        "low_stock": [dict(p) for p in low_stock],
        "expiring_soon": [dict(p) for p in expiring_soon],
        "unread_count": unread_count + len(low_stock) + len(expiring_soon),
    })


@app.post("/api/notifications/read-all")
def mark_notifications_read():
    db = get_db()
    db.execute("UPDATE notifications SET read = 1 WHERE read = 0")
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/payment-methods")
def list_payment_methods():
    db = get_db()
    return jsonify([dict(r) for r in db.execute("SELECT * FROM payment_methods WHERE active = 1")])


@app.post("/api/payment-methods")
def create_payment_method():
    data = request.get_json()
    db = get_db()
    pmid = str(uuid.uuid4())
    db.execute("INSERT INTO payment_methods (id, name, is_tpe, is_credit) VALUES (?, ?, ?, ?)",
               (pmid, data["name"], 1 if data.get("is_tpe") else 0, 1 if data.get("is_credit") else 0))
    db.commit()
    return jsonify({"id": pmid}), 201


# ----------------------------------------------------------------
# TPE (payment terminal) integration point - stub
# ----------------------------------------------------------------

@app.post("/api/tpe/charge")
def tpe_charge():
    """
    Stub for electronic payment terminal integration. A real integration
    calls the terminal vendor's SDK/API here and blocks until the
    terminal confirms approval or decline. This stub simulates approval
    so the rest of the payment flow can be built and tested against it.
    """
    data = request.get_json()
    return jsonify({
        "status": "approved",
        "amount": data.get("amount"),
        "terminal_ref": f"SIMULATED-{uuid.uuid4().hex[:8]}",
        "note": "Simulated - wire this to your TPE vendor SDK before production",
    })


# ----------------------------------------------------------------
# Reports
# ----------------------------------------------------------------

@app.get("/api/reports/sales")
def report_sales():
    period = request.args.get("period", "week")
    days = {"today": 1, "week": 7, "month": 30, "year": 365}.get(period, 7)
    db = get_db()
    rows = db.execute(
        "SELECT date(created_at) AS day, COUNT(*) AS orders, COALESCE(SUM(total),0) AS revenue "
        "FROM tickets WHERE status = 'completed' AND created_at >= datetime('now', ?) "
        "GROUP BY day ORDER BY day", (f"-{days} days",)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/reports/profit")
def report_profit():
    db = get_db()
    row = db.execute("""
        SELECT COALESCE(SUM(ti.line_total - ti.tax_amount), 0) AS revenue,
               COALESCE(SUM(ti.quantity * ti.unit_cost), 0) AS cost,
               COALESCE(SUM(ti.tax_amount), 0) AS tax_collected
        FROM ticket_items ti
        JOIN tickets t ON t.id = ti.ticket_id
        WHERE t.status = 'completed'
    """).fetchone()
    revenue, cost = row["revenue"], row["cost"]
    return jsonify({"revenue": revenue, "cost": cost, "profit": revenue - cost, "tax_collected": row["tax_collected"]})


@app.get("/api/reports/best-sellers")
def report_best_sellers():
    db = get_db()
    rows = db.execute("""
        SELECT ti.product_name, SUM(ti.quantity) AS qty_sold, SUM(ti.line_total) AS revenue
        FROM ticket_items ti JOIN tickets t ON t.id = ti.ticket_id
        WHERE t.status = 'completed'
        GROUP BY ti.product_name ORDER BY qty_sold DESC LIMIT 10
    """).fetchall()
    return jsonify([dict(r) for r in rows])


# ----------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------

@app.get("/api/dashboard")
def dashboard():
    db = get_db()
    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    today_row = db.execute(
        "SELECT COUNT(*) AS c, COALESCE(SUM(total), 0) AS s FROM tickets "
        "WHERE status = 'completed' AND date(created_at) = date(?)", (today,)
    ).fetchone()

    yesterday_row = db.execute(
        "SELECT COALESCE(SUM(total), 0) AS s FROM tickets "
        "WHERE status = 'completed' AND date(created_at) = date(?)", (yesterday,)
    ).fetchone()

    recent = db.execute(
        "SELECT id, ticket_number, total, order_type, status, created_at FROM tickets "
        "WHERE status IN ('completed','open') ORDER BY created_at DESC LIMIT 6"
    ).fetchall()
    recent_transactions = []
    for t in recent:
        items = db.execute("SELECT product_name, quantity FROM ticket_items WHERE ticket_id = ?", (t["id"],)).fetchall()
        item_summary = ", ".join(f"{i['product_name']} x{int(i['quantity'])}" for i in items)
        recent_transactions.append({
            "ticket_number": t["ticket_number"], "total": t["total"], "status": t["status"],
            "order_type": t["order_type"], "created_at": t["created_at"], "items_summary": item_summary,
        })

    low_stock_rows = db.execute(
        "SELECT name, stock_qty FROM products WHERE stock_qty <= reorder_threshold AND active = 1 ORDER BY stock_qty"
    ).fetchall()

    expiry_cutoff = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    expiring_soon_rows = db.execute(
        "SELECT name, expiry_date FROM products WHERE expiry_date IS NOT NULL "
        "AND expiry_date != '' AND expiry_date <= ? AND active = 1 ORDER BY expiry_date",
        (expiry_cutoff,),
    ).fetchall()

    best_sellers = db.execute("""
        SELECT ti.product_name, SUM(ti.quantity) AS qty_sold, SUM(ti.line_total) AS revenue
        FROM ticket_items ti JOIN tickets t ON t.id = ti.ticket_id
        WHERE t.status = 'completed'
        GROUP BY ti.product_name ORDER BY qty_sold DESC LIMIT 5
    """).fetchall()

    on_shift = db.execute(
        "SELECT a.employee_id, e.name FROM attendance a JOIN employees e ON e.id = a.employee_id "
        "WHERE a.clock_out IS NULL"
    ).fetchall()

    product_count = db.execute("SELECT COUNT(*) AS c FROM products WHERE active = 1").fetchone()["c"]
    open_orders_count = db.execute("SELECT COUNT(*) AS c FROM tickets WHERE status = 'open'").fetchone()["c"]

    return jsonify({
        "today_revenue": today_row["s"],
        "yesterday_revenue": yesterday_row["s"],
        "today_sales_count": today_row["c"],
        "open_orders_count": open_orders_count,
        "recent_transactions": recent_transactions,
        "low_stock": [{"name": p["name"], "stock_qty": p["stock_qty"]} for p in low_stock_rows],
        "expiring_soon": [{"name": p["name"], "expiry_date": p["expiry_date"]} for p in expiring_soon_rows],
        "best_sellers": [{"name": b["product_name"], "qty_sold": b["qty_sold"], "revenue": b["revenue"]} for b in best_sellers],
        "on_shift": [{"employee_id": s["employee_id"], "name": s["name"]} for s in on_shift],
        "product_count": product_count,
    })
