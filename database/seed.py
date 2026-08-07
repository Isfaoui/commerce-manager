"""
database/seed.py - seeds roles, employees, tables, categories, products.
Run once with: python database/seed.py  (from the project root)
"""

import os
import sys
import sqlite3
import uuid
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.db import DB_PATH, init_db  # noqa: E402
from utils.helpers import h  # noqa: E402

init_db()
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

if conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0] > 0:
    print("Already seeded - skipping. Delete caisse.db to reseed.")
else:
    roles = {
        "owner": {"approve_cancellations": True, "view_reports": True, "manage_staff": True, "manage_settings": True},
        "manager": {"approve_cancellations": True, "view_reports": True, "manage_staff": True, "manage_settings": False},
        "cashier": {"approve_cancellations": False, "view_reports": False, "manage_staff": False, "manage_settings": False},
    }
    role_ids = {}
    for name, perms in roles.items():
        rid = str(uuid.uuid4())
        role_ids[name] = rid
        conn.execute("INSERT INTO roles (id, name, permissions) VALUES (?, ?, ?)",
                     (rid, name, json.dumps(perms)))

    employees = [
        {"name": "Ahmed (Owner)", "email": "ahmed@shop.ma", "role": "owner",
         "pin": "1234", "password": "owner123", "nfc_card_id": "NFC-OWNER-01"},
        {"name": "Sara (Manager)", "email": "sara@shop.ma", "role": "manager",
         "pin": "5678", "password": "manager123", "nfc_card_id": "NFC-MGR-01"},
        {"name": "Youssef (Cashier)", "email": "youssef@shop.ma", "role": "cashier",
         "pin": "0000", "password": "cashier123", "nfc_card_id": "NFC-CASH-01"},
    ]
    for e in employees:
        eid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO employees (id, name, email, role_id, pin_hash, password_hash, nfc_card_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (eid, e["name"], e["email"], role_ids[e["role"]], h(e["pin"]), h(e["password"]), e["nfc_card_id"]),
        )

    for label, seats in [("Table 1", 2), ("Table 2", 4), ("Table 3", 4), ("Terrasse 1", 6)]:
        conn.execute("INSERT INTO dining_tables (id, label, seats) VALUES (?, ?, ?)",
                     (str(uuid.uuid4()), label, seats))

    categories = ["Boissons", "Epicerie", "Hygiene"]
    category_ids = {}
    for name in categories:
        cid = str(uuid.uuid4())
        category_ids[name] = cid
        conn.execute("INSERT INTO categories (id, name) VALUES (?, ?)", (cid, name))

    products = [
        {"name": "Coca-Cola 33cl", "barcode": "6111000000011", "category": "Boissons", "cost_price": 3.5, "sale_price": 6.0, "stock_qty": 48},
        {"name": "Pain traditionnel", "barcode": "6111000000028", "category": "Epicerie", "cost_price": 1.0, "sale_price": 1.5, "stock_qty": 30},
        {"name": "Lait 1L", "barcode": "6111000000035", "category": "Epicerie", "cost_price": 6.5, "sale_price": 8.0, "stock_qty": 20},
        {"name": "Huile d'olive 1L", "barcode": "6111000000042", "category": "Epicerie", "cost_price": 45.0, "sale_price": 60.0, "stock_qty": 12},
        {"name": "Chips 100g", "barcode": "6111000000059", "category": "Epicerie", "cost_price": 4.0, "sale_price": 7.0, "stock_qty": 40},
        {"name": "Eau minerale 1.5L", "barcode": "6111000000066", "category": "Boissons", "cost_price": 2.5, "sale_price": 4.0, "stock_qty": 60},
        {"name": "Cafe moulu 250g", "barcode": "6111000000073", "category": "Epicerie", "cost_price": 22.0, "sale_price": 32.0, "stock_qty": 15},
        {"name": "Savon liquide", "barcode": "6111000000080", "category": "Hygiene", "cost_price": 12.0, "sale_price": 18.0, "stock_qty": 3},
    ]
    for p in products:
        conn.execute(
            "INSERT INTO products (id, name, barcode, category_id, cost_price, sale_price, stock_qty) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), p["name"], p["barcode"], category_ids[p["category"]],
             p["cost_price"], p["sale_price"], p["stock_qty"]),
        )

    for name, is_tpe, is_credit in [("Especes", 0, 0), ("Carte (TPE)", 1, 0), ("Credit client", 0, 1)]:
        conn.execute("INSERT INTO payment_methods (id, name, is_tpe, is_credit) VALUES (?, ?, ?, ?)",
                     (str(uuid.uuid4()), name, is_tpe, is_credit))

    for key, value in [("store_name", "Mon Commerce"), ("currency", "MAD"), ("default_tax_rate", "20")]:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))

    conn.commit()
    print(f"Seeded {len(roles)} roles, {len(employees)} employees, 4 tables, "
          f"{len(categories)} categories, {len(products)} products.")
    print()
    print("Test credentials for the approval flow:")
    for e in employees:
        print(f"  {e['name']}: PIN={e['pin']}  password={e['password']}  NFC={e['nfc_card_id']}")

conn.close()
