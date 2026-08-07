"""
utils/helpers.py - small shared helpers used by the controllers.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone


def h(text):
    """Hash a PIN/password. sha256 for prototype clarity - replace with
    bcrypt/argon2 before handling real credentials in production."""
    return hashlib.sha256(text.encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def find_role_permissions(db, role_id):
    if not role_id:
        return {}
    row = db.execute("SELECT permissions FROM roles WHERE id = ?", (role_id,)).fetchone()
    if not row:
        return {}
    return json.loads(row["permissions"])


def get_product(db, product_id):
    return db.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()


def get_recipe_ingredients(db, product_id):
    return db.execute(
        "SELECT ri.*, p.name AS ingredient_name, p.unit AS ingredient_unit, "
        "p.stock_qty AS ingredient_stock, p.cost_price AS ingredient_cost "
        "FROM recipe_ingredients ri JOIN products p ON p.id = ri.ingredient_product_id "
        "WHERE ri.product_id = ?", (product_id,)
    ).fetchall()


def compute_unit_cost(db, product):
    """Cost per unit sold - direct cost_price for simple products, or the sum
    of ingredient costs for recipe products (coffee = beans + milk, etc)."""
    if product["product_type"] == "recipe":
        ingredients = get_recipe_ingredients(db, product["id"])
        return sum(i["quantity"] * i["ingredient_cost"] for i in ingredients)
    return product["cost_price"]


def compute_available_qty(db, product):
    """How many units can be sold right now. Direct stock_qty for simple
    products; for recipe products, the bottleneck ingredient determines it
    (e.g. only enough milk left for 12 coffees even if beans could make 50)."""
    if product["product_type"] == "recipe":
        ingredients = get_recipe_ingredients(db, product["id"])
        if not ingredients:
            return 0
        return min(
            (i["ingredient_stock"] // i["quantity"]) if i["quantity"] > 0 else 0
            for i in ingredients
        )
    return product["stock_qty"]


def check_stock_available(db, product, quantity):
    """Returns None if there's enough stock, or an error message string."""
    if product["product_type"] == "recipe":
        for ing in get_recipe_ingredients(db, product["id"]):
            needed = ing["quantity"] * quantity
            if ing["ingredient_stock"] < needed:
                return (f"Ingredient insuffisant pour '{product['name']}': "
                        f"{ing['ingredient_name']} (besoin {needed}, disponible {ing['ingredient_stock']})")
        return None
    if product["stock_qty"] < quantity:
        return f"Not enough stock for '{product['name']}'"
    return None


def consume_stock(db, product, quantity):
    """Decrement stock for a sale - the recipe's ingredients for recipe
    products, the product itself for simple products."""
    if product["product_type"] == "recipe":
        for ing in get_recipe_ingredients(db, product["id"]):
            db.execute("UPDATE products SET stock_qty = stock_qty - ? WHERE id = ?",
                       (ing["quantity"] * quantity, ing["ingredient_product_id"]))
    else:
        db.execute("UPDATE products SET stock_qty = stock_qty - ? WHERE id = ?", (quantity, product["id"]))


def restock(db, product_id, quantity):
    """Reverse of consume_stock - used by cancellations/refunds."""
    product = get_product(db, product_id)
    if not product:
        return
    if product["product_type"] == "recipe":
        for ing in get_recipe_ingredients(db, product_id):
            db.execute("UPDATE products SET stock_qty = stock_qty + ? WHERE id = ?",
                       (ing["quantity"] * quantity, ing["ingredient_product_id"]))
    else:
        db.execute("UPDATE products SET stock_qty = stock_qty + ? WHERE id = ?", (quantity, product_id))
def insert_notification(db, ntype, message):
    db.execute(
        "INSERT INTO notifications (id, type, message, created_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), ntype, message, now()),
    )


def verify_approval(db, approval):
    """
    approval = {"method": "admin_pin"|"nfc_card"|"password"|"manager_approval",
                "credential": "...", "manager_id": "..." (for password/manager_approval)}
    Returns the approving employee row if valid AND authorized, else None.
    This is the single choke point every cancellation/refund must pass
    through - see controllers/app.py's cancel_order().
    """
    method = approval.get("method")
    credential = approval.get("credential", "")
    employee = None

    if method == "admin_pin":
        employee = db.execute(
            "SELECT * FROM employees WHERE pin_hash = ? AND active = 1", (h(credential),)
        ).fetchone()
    elif method == "nfc_card":
        employee = db.execute(
            "SELECT * FROM employees WHERE nfc_card_id = ? AND active = 1", (credential,)
        ).fetchone()
    elif method == "password":
        manager_id = approval.get("manager_id")
        employee = db.execute(
            "SELECT * FROM employees WHERE id = ? AND password_hash = ? AND active = 1",
            (manager_id, h(credential)),
        ).fetchone()
    elif method == "manager_approval":
        manager_id = approval.get("manager_id")
        employee = db.execute(
            "SELECT * FROM employees WHERE id = ? AND active = 1", (manager_id,)
        ).fetchone()
    else:
        return None

    if not employee:
        return None

    perms = find_role_permissions(db, employee["role_id"])
    if not perms.get("approve_cancellations"):
        return None

    return employee
