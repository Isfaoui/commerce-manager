"""
models/backup.py - local backup and restore.

Backups are ZIP archives containing caisse.db and every file in
uploads/products/ - a snapshot of everything that matters, not just the
raw database file. Stored in a persistent folder next to the database
(never inside the ephemeral bundled-resources folder used when packaged).
"""

import os
import shutil
import zipfile
from datetime import datetime, timezone

from models.db import DB_PATH, UPLOADS_DIR, APP_DIR

BACKUPS_DIR = os.path.join(APP_DIR, "backups")
os.makedirs(BACKUPS_DIR, exist_ok=True)

MAX_AUTO_BACKUPS = 5


def _timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def create_backup(prefix="backup"):
    filename = f"{prefix}_{_timestamp()}.zip"
    path = os.path.join(BACKUPS_DIR, filename)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(DB_PATH):
            zf.write(DB_PATH, "caisse.db")
        if os.path.isdir(UPLOADS_DIR):
            for name in os.listdir(UPLOADS_DIR):
                full = os.path.join(UPLOADS_DIR, name)
                if os.path.isfile(full):
                    zf.write(full, os.path.join("uploads", "products", name))
    return filename


def list_backups():
    result = []
    for name in sorted(os.listdir(BACKUPS_DIR), reverse=True):
        if not name.endswith(".zip"):
            continue
        full = os.path.join(BACKUPS_DIR, name)
        result.append({
            "filename": name,
            "size_bytes": os.path.getsize(full),
            "created_at": datetime.fromtimestamp(os.path.getmtime(full), tz=timezone.utc).isoformat(),
            "type": "auto" if name.startswith("auto_") else "manual",
        })
    return result


def prune_auto_backups(keep=MAX_AUTO_BACKUPS):
    auto_files = sorted(f for f in os.listdir(BACKUPS_DIR) if f.startswith("auto_") and f.endswith(".zip"))
    excess = len(auto_files) - keep
    for f in auto_files[:max(excess, 0)]:
        os.remove(os.path.join(BACKUPS_DIR, f))


def maybe_auto_backup():
    """Creates at most one automatic backup per calendar day, so restarting
    the app repeatedly in one day doesn't pile up redundant backups."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    already_today = any(f.startswith(f"auto_{today}") for f in os.listdir(BACKUPS_DIR))
    if not already_today:
        create_backup(prefix="auto")
        prune_auto_backups()


def restore_backup(filename):
    path = os.path.join(BACKUPS_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError("Sauvegarde introuvable")

    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        if "caisse.db" not in names:
            raise ValueError("Fichier de sauvegarde invalide (caisse.db manquant)")

        with zf.open("caisse.db") as src, open(DB_PATH, "wb") as dst:
            shutil.copyfileobj(src, dst)

        # Clear existing photos first so we don't mix old and restored ones.
        if os.path.isdir(UPLOADS_DIR):
            for f in os.listdir(UPLOADS_DIR):
                full = os.path.join(UPLOADS_DIR, f)
                if os.path.isfile(full):
                    os.remove(full)
        os.makedirs(UPLOADS_DIR, exist_ok=True)

        prefix = "uploads/products/"
        for name in names:
            if name.startswith(prefix) and not name.endswith("/"):
                target = os.path.join(UPLOADS_DIR, os.path.basename(name))
                with zf.open(name) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
