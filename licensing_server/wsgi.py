"""
licensing_server/wsgi.py

Production hosts (Render, Railway, any gunicorn-based deploy) look for an
importable WSGI callable, not a "python app.py" script. This file gives
them one.

Start command on your host:
    gunicorn licensing_server.wsgi:app --bind 0.0.0.0:$PORT
"""
from .app import create_app

app = create_app()
