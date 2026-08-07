"""
license/crypto.py

Cryptographic primitives for the licensing system.

Design decision: Ed25519 (via the `cryptography` package) instead of RSA-2048.
Reasons:
    - Signatures are 64 bytes vs 256+ bytes for RSA -> smaller license.dat
    - Verification is extremely fast, deterministic, no padding-scheme footguns
      (no PKCS1v15 vs PSS mistakes, no hash-algorithm confusion)
    - Keys are 32 bytes, trivial to embed as a constant in the compiled app

Only the PUBLIC key ever ships inside the desktop application (embedded in
license/public_key.py, generated at build time). The PRIVATE key lives only
on the license server and is never distributed.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization


class SignatureVerificationError(Exception):
    """Raised when a license's signature does not match its payload."""


def canonical_json(payload: dict[str, Any]) -> bytes:
    """
    Deterministic JSON serialization.

    Signatures are only meaningful if signer and verifier hash the EXACT
    same bytes. sort_keys + fixed separators guarantee that regardless of
    dict insertion order on either side.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


# --------------------------------------------------------------------------
# SERVER-SIDE (private key holder) — never ship this class inside the .exe
# --------------------------------------------------------------------------
class LicenseSigner:
    """Wraps the server's Ed25519 private key. Lives ONLY on the server."""

    def __init__(self, private_key_pem: bytes, password: bytes | None = None):
        self._key: Ed25519PrivateKey = serialization.load_pem_private_key(
            private_key_pem, password=password
        )

    @classmethod
    def generate_new_keypair(cls) -> tuple[bytes, bytes]:
        """
        One-time setup utility. Run manually, store the private PEM in a
        secrets manager / HSM, and bake the public PEM into the client build.

        Returns (private_pem, public_pem)
        """
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return private_pem, public_pem

    def sign_payload(self, payload: dict[str, Any]) -> str:
        """Returns base64-encoded signature over the canonical JSON payload."""
        message = canonical_json(payload)
        signature = self._key.sign(message)
        return base64.b64encode(signature).decode("ascii")


# --------------------------------------------------------------------------
# CLIENT-SIDE (public key holder) — this is what ships inside the .exe
# --------------------------------------------------------------------------
class LicenseVerifier:
    """Wraps the embedded Ed25519 public key. Ships inside the desktop app."""

    def __init__(self, public_key_pem: bytes):
        self._key: Ed25519PublicKey = serialization.load_pem_public_key(
            public_key_pem
        )

    def verify(self, payload: dict[str, Any], signature_b64: str) -> None:
        """
        Raises SignatureVerificationError if the payload does not match
        the signature. Callers MUST treat any raised exception as
        "license invalid / tampered" and refuse to run.
        """
        message = canonical_json(payload)
        try:
            signature = base64.b64decode(signature_b64)
            self._key.verify(signature, message)
        except (InvalidSignature, ValueError) as exc:
            raise SignatureVerificationError(
                "License signature is invalid or the payload was modified."
            ) from exc


@dataclass(frozen=True)
class SignedDocument:
    """Generic envelope: { payload: {...}, signature: 'base64...' }"""

    payload: dict[str, Any]
    signature: str

    def to_json(self) -> str:
        return json.dumps({"payload": self.payload, "signature": self.signature})

    @classmethod
    def from_json(cls, raw: str) -> "SignedDocument":
        data = json.loads(raw)
        return cls(payload=data["payload"], signature=data["signature"])
