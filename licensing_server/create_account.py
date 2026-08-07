"""
licensing_server/create_account.py

There is no public signup endpoint by design (accounts are provisioned by
you). Use this script to create your first test customer account and/or
an admin account for the dashboard.

Run from the licensing_server/ directory:
    python create_account.py customer isfaouimedrayan@gmail.com "YourPassword123"
    python create_account.py admin admin@yourcompany.com "AdminPassword123"
"""
import sys
import time
import uuid

from argon2 import PasswordHasher

import db

hasher = PasswordHasher()


def create_account(kind: str, email: str, password: str, full_name: str = "") -> None:
    if kind not in ("customer", "admin"):
        raise SystemExit("First argument must be 'customer' or 'admin'")

    db.init_db()
    password_hash = hasher.hash(password)

    with db.tx() as conn:
        existing = db.get_user_by_email(conn, email)
        if existing is not None:
            print(f"Account already exists for {email} (id={existing['id']}).")
            return

        user_id = str(uuid.uuid4())
        ts = int(time.time())
        is_admin = 1 if kind == "admin" else 0
        conn.execute(
            """INSERT INTO users (id, email, password_hash, full_name, is_admin,
                                   is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (user_id, email.lower().strip(), password_hash, full_name, is_admin, ts, ts),
        )
        print(f"Created {kind} account: {email} (id={user_id})")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    create_account(sys.argv[1], sys.argv[2], sys.argv[3])
