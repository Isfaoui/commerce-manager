"""
server/rate_limit.py

Simple in-process sliding-window rate limiter. Fine for a single-instance
v1 deployment; swap for Redis-backed limiting (e.g. flask-limiter with a
Redis storage backend) once the server runs behind a load balancer with
multiple worker processes/instances.
"""
from __future__ import annotations

import time
from collections import defaultdict
from functools import wraps
from threading import Lock

from flask import jsonify, request

_hits: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def rate_limited(limit: int, window_seconds: int, key_fn=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key_suffix = key_fn() if key_fn else ""
            key = f"{request.remote_addr}:{request.path}:{key_suffix}"
            now = time.time()
            with _lock:
                hits = [t for t in _hits[key] if now - t < window_seconds]
                if len(hits) >= limit:
                    _hits[key] = hits
                    return jsonify({"message": "Too many attempts. Please try again later."}), 429
                hits.append(now)
                _hits[key] = hits
            return fn(*args, **kwargs)
        return wrapper
    return decorator
