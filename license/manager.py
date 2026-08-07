"""
license/manager.py

The single entry point the desktop app talks to. Wires together:
crypto (verify), device (fingerprint), storage (persist), validator (decide),
and an HTTP client for the online-only operations (login/activate/renew).

Public API is intentionally small and app-facing:
    - manager.bootstrap()          -> ValidationOutcome (call at every launch)
    - manager.login_and_activate() -> ValidationOutcome (online, first run)
    - manager.reactivate()         -> ValidationOutcome (online, e.g. after upgrade)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .crypto import LicenseVerifier, SignedDocument
from .device import get_current_device_id
from .storage import LicenseStorage, license_path
from .validator import LicenseValidator, ValidationOutcome, ValidationResult

_STATE_FILENAME = "state.json"  # stores last_seen_timestamp, next to license.dat


class ActivationError(Exception):
    """Raised for any online activation/login failure (bad creds, no network,
    server rejected the device, etc). Message is safe to show to the user."""


class LicenseManager:
    def __init__(
        self,
        public_key_pem: bytes,
        server_base_url: str,
        storage: LicenseStorage | None = None,
        request_timeout_seconds: float = 10.0,
    ):
        self._verifier = LicenseVerifier(public_key_pem)
        self._validator = LicenseValidator(self._verifier)
        self._storage = storage or LicenseStorage()
        self._server_base_url = server_base_url.rstrip("/")
        self._timeout = request_timeout_seconds

    # ------------------------------------------------------------------
    # OFFLINE PATH — runs on every single launch, no network involved
    # ------------------------------------------------------------------
    def bootstrap(self) -> ValidationOutcome:
        document = self._storage.load()
        device_id = get_current_device_id()
        now = int(time.time())
        last_seen = self._read_last_seen()

        outcome = self._validator.validate(document, device_id, now, last_seen)

        if outcome.ok:
            self._write_last_seen(now)

        return outcome

    def _state_path(self) -> Path:
        return license_path().with_name(_STATE_FILENAME)

    def _read_last_seen(self) -> int | None:
        p = self._state_path()
        if not p.exists():
            return None
        try:
            return int(json.loads(p.read_text())["last_seen"])
        except Exception:
            return None

    def _write_last_seen(self, ts: int) -> None:
        self._state_path().write_text(json.dumps({"last_seen": ts}))

    # ------------------------------------------------------------------
    # ONLINE PATH — first login / activation / future renewal only
    # ------------------------------------------------------------------
    def login_and_activate(self, email: str, password: str) -> ValidationOutcome:
        """
        Contacts the server, authenticates, and receives a freshly signed
        license bound to THIS device's id. Stores it locally.
        """
        device_id = get_current_device_id()
        try:
            resp = requests.post(
                f"{self._server_base_url}/api/auth/login",
                json={"email": email, "password": password, "device_id": device_id},
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise ActivationError(
                "Could not reach the license server. Check your internet connection."
            ) from exc

        if resp.status_code == 401:
            raise ActivationError("Invalid email or password.")
        if resp.status_code == 403:
            raise ActivationError(resp.json().get("message", "Access denied."))
        if resp.status_code != 200:
            raise ActivationError(f"Server error ({resp.status_code}). Please try again.")

        document = SignedDocument(**resp.json()["license"])

        # Verify BEFORE trusting/persisting anything the server sent —
        # never assume "it came from our own server" implies integrity.
        self._verifier.verify(document.payload, document.signature)

        self._storage.save(document)
        self._write_last_seen(int(time.time()))

        return self._validator.validate(document, device_id, int(time.time()))

    def reactivate(self, license_key: str | None = None) -> ValidationOutcome:
        """
        Used for: paid upgrade pickup, license transfer to a new device after
        an admin device-reset, or future renewal. Requires network.
        """
        device_id = get_current_device_id()
        current = self._storage.load()
        customer_id = None
        if current is not None:
            customer_id = current.payload.get("customer_id")

        try:
            resp = requests.post(
                f"{self._server_base_url}/api/licenses/reactivate",
                json={
                    "device_id": device_id,
                    "customer_id": customer_id,
                    "license_key": license_key,
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise ActivationError(
                "Could not reach the license server. Check your internet connection."
            ) from exc

        if resp.status_code != 200:
            raise ActivationError(resp.json().get("message", "Activation failed."))

        document = SignedDocument(**resp.json()["license"])
        self._verifier.verify(document.payload, document.signature)
        self._storage.save(document)
        self._write_last_seen(int(time.time()))
        return self._validator.validate(document, device_id, int(time.time()))

    def current_status(self) -> ValidationOutcome:
        """Cheap read-only check, e.g. for a "Settings > License" screen."""
        return self.bootstrap()
