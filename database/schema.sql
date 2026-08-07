-- ============================================================
-- Commerce Manager - Database Schema (reference)
--
-- This file documents the schema for human reading. The actual tables
-- are created at runtime by models/db.py::init_db() (SQLite, via
-- executescript) - the two are kept in sync by hand. If you change one,
-- change the other.
-- ============================================================

CREATE TABLE categories (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL
);

CREATE TABLE products (
    id                      TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    barcode                 TEXT UNIQUE,
    category_id             TEXT REFERENCES categories(id),
    cost_price              REAL NOT NULL DEFAULT 0,
    sale_price              REAL NOT NULL DEFAULT 0,
    stock_qty               REAL NOT NULL DEFAULT 0,
    reorder_threshold       REAL NOT NULL DEFAULT 5,
    overstock_threshold     REAL NOT NULL DEFAULT 200,
    active                  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE roles (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    permissions     TEXT NOT NULL DEFAULT '{}'   -- JSON: {"approve_cancellations": true, ...}
);

CREATE TABLE employees (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT UNIQUE,
    role_id         TEXT REFERENCES roles(id),
    pin_hash        TEXT,     -- sha256, see utils/helpers.py::h()
    password_hash   TEXT,
    nfc_card_id     TEXT UNIQUE,
    hourly_rate     REAL,
    hire_date       TEXT,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE attendance (
    id              TEXT PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employees(id),
    clock_in        TEXT NOT NULL,
    clock_out       TEXT
);

CREATE TABLE work_schedules (
    id              TEXT PRIMARY KEY,
    employee_id     TEXT NOT NULL REFERENCES employees(id),
    shift_date      TEXT NOT NULL,
    start_time      TEXT NOT NULL,
    end_time        TEXT NOT NULL
);

CREATE TABLE dining_tables (
    id              TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    seats           INTEGER NOT NULL DEFAULT 2,
    status          TEXT NOT NULL DEFAULT 'free'   -- free, occupied
);

CREATE TABLE suppliers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    balance_due     REAL NOT NULL DEFAULT 0
);

CREATE TABLE purchase_orders (
    id              TEXT PRIMARY KEY,
    supplier_id     TEXT REFERENCES suppliers(id),
    status          TEXT NOT NULL DEFAULT 'received',
    total_amount    REAL NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE purchase_order_items (
    id                      TEXT PRIMARY KEY,
    purchase_order_id       TEXT NOT NULL REFERENCES purchase_orders(id),
    product_id              TEXT NOT NULL REFERENCES products(id),
    quantity                REAL NOT NULL,
    unit_cost               REAL NOT NULL
);

-- A ticket is an order: dine-in, takeaway, or delivery. "open" means
-- items are placed but not yet paid; "completed" means paid;
-- "cancelled"/"refunded" go through the approval flow; "split" means
-- all its items were moved to child tickets (see parent_ticket_id).
CREATE TABLE tickets (
    id                  TEXT PRIMARY KEY,
    ticket_number       INTEGER UNIQUE NOT NULL,
    order_type          TEXT NOT NULL DEFAULT 'takeaway',  -- dine_in, takeaway, delivery
    table_id            TEXT REFERENCES dining_tables(id),
    parent_ticket_id    TEXT REFERENCES tickets(id),        -- set when split off another ticket
    delivery_address    TEXT,
    status              TEXT NOT NULL DEFAULT 'open',       -- open, completed, cancelled, refunded, split
    subtotal            REAL NOT NULL DEFAULT 0,
    discount_total       REAL NOT NULL DEFAULT 0,
    total                REAL NOT NULL DEFAULT 0,
    cancel_reason        TEXT,
    created_at           TEXT NOT NULL,
    closed_at            TEXT
);

CREATE TABLE ticket_items (
    id              TEXT PRIMARY KEY,
    ticket_id       TEXT NOT NULL REFERENCES tickets(id),
    product_id      TEXT NOT NULL REFERENCES products(id),
    product_name    TEXT NOT NULL,     -- snapshot at time of sale
    quantity        REAL NOT NULL,
    unit_price      REAL NOT NULL,
    line_total      REAL NOT NULL
);

CREATE TABLE payments (
    id              TEXT PRIMARY KEY,
    ticket_id       TEXT NOT NULL REFERENCES tickets(id),
    method          TEXT NOT NULL,     -- cash, card, tpe
    amount          REAL NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE payment_methods (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    is_tpe          INTEGER NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1
);

-- Every cancellation/refund writes exactly one row here, in the same
-- transaction as the cancellation itself. See utils/helpers.py::verify_approval()
-- for the gate this passes through before anything is written.
CREATE TABLE approval_audit_log (
    id                  TEXT PRIMARY KEY,
    action_type         TEXT NOT NULL,      -- cancel_order, refund
    reference_id        TEXT NOT NULL,      -- ticket id
    requested_by        TEXT,               -- employee who asked (optional)
    approved_by         TEXT NOT NULL,      -- employee who approved
    approval_method     TEXT NOT NULL,      -- admin_pin, nfc_card, password, manager_approval
    reason              TEXT NOT NULL,
    original_amount     REAL NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE settings (
    key             TEXT PRIMARY KEY,
    value           TEXT
);
