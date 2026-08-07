"""
models/db.py - database connection, path resolution, and schema.
"""

import os
import sys
import sqlite3
from flask import g

# ----------------------------------------------------------------
# Path resolution: works whether running as a normal Python script
# or as a packaged .exe (PyInstaller sets sys.frozen = True).
# ----------------------------------------------------------------

if getattr(sys, "frozen", False):
    # Packaged .exe: keep the database next to the .exe so it persists
    # between launches. Bundled files (like views/) are extracted to a
    # temp folder exposed as sys._MEIPASS - not next to the .exe.
    APP_DIR = os.path.dirname(sys.executable)
    RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    # Normal script: models/db.py -> go up one level to the project root.
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RESOURCE_DIR = APP_DIR

DB_PATH = os.path.join(APP_DIR, "caisse.db")
VIEWS_DIR = os.path.join(RESOURCE_DIR, "views")
# Uploaded content (product photos) must survive restarts, so it lives next
# to the database (APP_DIR), never inside RESOURCE_DIR - when packaged as a
# .exe, RESOURCE_DIR is a temp extraction folder that gets deleted on close.
UPLOADS_DIR = os.path.join(APP_DIR, "uploads", "products")
os.makedirs(UPLOADS_DIR, exist_ok=True)

COMPANY_ASSETS_DIR = os.path.join(APP_DIR, "uploads", "company")
os.makedirs(COMPANY_ASSETS_DIR, exist_ok=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        # WAL mode: writes go to a separate log file instead of forcing a
        # full fsync of the main database file on every single commit.
        # This is the standard fix for "every save feels slow" in SQLite
        # apps - previously every settings save (and every other write in
        # the app) blocked on a full disk sync. Still fully crash-safe;
        # just a different (faster) durability mechanism than the default
        # rollback-journal mode. Persists for the file once set.
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA synchronous = NORMAL")
    return g.db


def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS customers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT,
        email TEXT,
        address TEXT,
        credit_balance REAL NOT NULL DEFAULT 0,  -- positive = customer owes this amount
        notes TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    -- A payment made against a customer's running balance (not tied to a
    -- specific sale) - e.g. they come in and pay down part of their tab.
    CREATE TABLE IF NOT EXISTS customer_payments (
        id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL REFERENCES customers(id),
        amount REAL NOT NULL,
        method TEXT NOT NULL,
        note TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS categories (
        id TEXT PRIMARY KEY, name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS products (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        barcode TEXT UNIQUE,
        category_id TEXT REFERENCES categories(id),
        product_type TEXT NOT NULL DEFAULT 'simple',   -- simple (buy/resell) or recipe (made from ingredients)
        sellable INTEGER NOT NULL DEFAULT 1,           -- 0 = raw material only, never sold directly
        unit TEXT NOT NULL DEFAULT 'unite',            -- unite, g, kg, ml, l - what stock_qty is measured in
        cost_price REAL NOT NULL DEFAULT 0,            -- ignored for product_type='recipe' (computed from ingredients)
        sale_price REAL NOT NULL DEFAULT 0,
        stock_qty REAL NOT NULL DEFAULT 0,             -- ignored for product_type='recipe'
        reorder_threshold REAL NOT NULL DEFAULT 5,
        overstock_threshold REAL NOT NULL DEFAULT 200,
        expiry_date TEXT,                              -- ISO date (YYYY-MM-DD), NULL = no expiry tracked
        image_filename TEXT,                           -- filename in the persistent uploads folder, not bundled resources
        active INTEGER NOT NULL DEFAULT 1
    );

    -- Ingredients consumed per 1 unit sold of a product_type='recipe' product.
    -- Both sides reference products: the finished item (product_id) and the
    -- raw material consumed (ingredient_product_id, itself a 'simple' product).
    CREATE TABLE IF NOT EXISTS recipe_ingredients (
        id TEXT PRIMARY KEY,
        product_id TEXT NOT NULL REFERENCES products(id),
        ingredient_product_id TEXT NOT NULL REFERENCES products(id),
        quantity REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS roles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        permissions TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS employees (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE,
        phone TEXT,
        role_id TEXT REFERENCES roles(id),
        pin_hash TEXT,
        password_hash TEXT,
        nfc_card_id TEXT UNIQUE,
        hourly_rate REAL,
        hire_date TEXT,
        active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS attendance (
        id TEXT PRIMARY KEY,
        employee_id TEXT NOT NULL REFERENCES employees(id),
        clock_in TEXT NOT NULL,
        clock_out TEXT
    );

    CREATE TABLE IF NOT EXISTS work_schedules (
        id TEXT PRIMARY KEY,
        employee_id TEXT NOT NULL REFERENCES employees(id),
        shift_date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS dining_tables (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        seats INTEGER NOT NULL DEFAULT 2,
        status TEXT NOT NULL DEFAULT 'free'
    );

    CREATE TABLE IF NOT EXISTS suppliers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        contact_person TEXT,
        phone TEXT,
        email TEXT,
        address TEXT,
        ice TEXT,
        notes TEXT,
        balance_due REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS purchase_orders (
        id TEXT PRIMARY KEY,
        supplier_id TEXT REFERENCES suppliers(id),
        status TEXT NOT NULL DEFAULT 'received',
        total_amount REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS purchase_order_items (
        id TEXT PRIMARY KEY,
        purchase_order_id TEXT NOT NULL REFERENCES purchase_orders(id),
        product_id TEXT NOT NULL REFERENCES products(id),
        quantity REAL NOT NULL,
        unit_cost REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS tickets (
        id TEXT PRIMARY KEY,
        ticket_number INTEGER UNIQUE NOT NULL,
        order_type TEXT NOT NULL DEFAULT 'takeaway',
        customer_id TEXT REFERENCES customers(id),
        table_id TEXT REFERENCES dining_tables(id),
        parent_ticket_id TEXT REFERENCES tickets(id),
        delivery_address TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        fulfillment_status TEXT NOT NULL DEFAULT 'pending',  -- pending, served - independent of payment status
        subtotal REAL NOT NULL DEFAULT 0,       -- HT (tax-excluded), derived from TTC prices
        tax_total REAL NOT NULL DEFAULT 0,      -- tax portion extracted from the TTC prices
        discount_total REAL NOT NULL DEFAULT 0,
        total REAL NOT NULL DEFAULT 0,          -- TTC - what the customer actually pays, unchanged by tax display
        cancel_reason TEXT,
        created_at TEXT NOT NULL,
        closed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS ticket_items (
        id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL REFERENCES tickets(id),
        product_id TEXT REFERENCES products(id),   -- NULL for unlisted/custom items
        product_name TEXT NOT NULL,
        quantity REAL NOT NULL,
        unit_price REAL NOT NULL,
        unit_cost REAL NOT NULL DEFAULT 0,          -- cost snapshot at time of sale (recipe-aware)
        tax_amount REAL NOT NULL DEFAULT 0,         -- tax portion of line_total, extracted from the TTC price
        line_total REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS payments (
        id TEXT PRIMARY KEY,
        ticket_id TEXT NOT NULL REFERENCES tickets(id),
        method TEXT NOT NULL,
        amount REAL NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS payment_methods (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        is_tpe INTEGER NOT NULL DEFAULT 0,
        is_credit INTEGER NOT NULL DEFAULT 0,   -- marks this method as "customer credit/tab" - requires a customer
        active INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS approval_audit_log (
        id TEXT PRIMARY KEY,
        action_type TEXT NOT NULL,
        reference_id TEXT NOT NULL,
        requested_by TEXT,
        approved_by TEXT NOT NULL,
        approval_method TEXT NOT NULL,
        reason TEXT NOT NULL,
        original_amount REAL NOT NULL,
        created_at TEXT NOT NULL
    );

    -- ------------------------------------------------------------
    -- Documents module: Factures, Devis, Bons de Livraison, Avoirs.
    -- One shared table (doc_type discriminates), since the four share
    -- the large majority of their structure (header, customer, line
    -- items, totals, footer) - type-specific columns are simply NULL
    -- for types that don't use them.
    -- ------------------------------------------------------------
    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        doc_type TEXT NOT NULL CHECK (doc_type IN ('facture', 'devis', 'bl', 'avoir')),
        doc_number TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'draft',
        issue_date TEXT NOT NULL,
        due_date TEXT,                          -- facture
        valid_until TEXT,                       -- devis
        delivery_date TEXT,                     -- bl
        customer_name TEXT,
        customer_company TEXT,
        customer_ice TEXT,
        customer_address TEXT,
        customer_phone TEXT,
        customer_email TEXT,
        driver_name TEXT,                       -- bl
        vehicle TEXT,                           -- bl
        hide_prices INTEGER NOT NULL DEFAULT 0, -- bl: many Moroccan BLs print without prices
        linked_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,  -- avoir -> the facture it credits
        reason TEXT,                            -- avoir
        subtotal REAL NOT NULL DEFAULT 0,
        discount_total REAL NOT NULL DEFAULT 0,
        tax_total REAL NOT NULL DEFAULT 0,
        total REAL NOT NULL DEFAULT 0,
        amount_paid REAL NOT NULL DEFAULT 0,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(doc_type);
    CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);

    CREATE TABLE IF NOT EXISTS document_items (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        description TEXT NOT NULL,
        quantity REAL NOT NULL DEFAULT 1,
        unit_price REAL NOT NULL DEFAULT 0,
        discount_pct REAL NOT NULL DEFAULT 0,
        tax_pct REAL NOT NULL DEFAULT 0,
        line_total REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_document_items_doc ON document_items(document_id);

    -- Per-type, per-year running counter backing the auto-numbering
    -- (e.g. FAC-2026-0001). Prefixes themselves are configurable, stored
    -- in the settings table (doc_prefix_facture, doc_prefix_devis, ...).
    CREATE TABLE IF NOT EXISTS document_sequences (
        doc_type TEXT NOT NULL,
        year INTEGER NOT NULL,
        next_number INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (doc_type, year)
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,        -- backup, cancel_order, refund
        message TEXT NOT NULL,
        read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)

    # Lightweight migration: CREATE TABLE IF NOT EXISTS above only applies to
    # brand-new installs - an existing products table from before this
    # column existed needs it added explicitly, or every install that's
    # already run once would keep failing on expiry_date going forward.
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
    if "expiry_date" not in existing_columns:
        conn.execute("ALTER TABLE products ADD COLUMN expiry_date TEXT")

    existing_supplier_columns = {row[1] for row in conn.execute("PRAGMA table_info(suppliers)").fetchall()}
    if "contact_person" not in existing_supplier_columns:
        conn.execute("ALTER TABLE suppliers ADD COLUMN contact_person TEXT")
    if "ice" not in existing_supplier_columns:
        conn.execute("ALTER TABLE suppliers ADD COLUMN ice TEXT")
    if "notes" not in existing_supplier_columns:
        conn.execute("ALTER TABLE suppliers ADD COLUMN notes TEXT")

    existing_employee_columns = {row[1] for row in conn.execute("PRAGMA table_info(employees)").fetchall()}
    if "phone" not in existing_employee_columns:
        conn.execute("ALTER TABLE employees ADD COLUMN phone TEXT")

    conn.commit()
    conn.close()
