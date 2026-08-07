"""
license/storage.py

Persists the signed license document to disk as `license.dat`.

Two independent layers of protection:
    1. INTEGRITY - the Ed25519 signature (crypto.py) means the payload
       cannot be edited without invalidating the license. This is the
       real security boundary and holds even if layer 2 below is bypassed.
    2. CONFIDENTIALITY / ANTI-COPY (defense in depth) - the signed JSON is
       additionally wrapped with Windows DPAPI (CryptProtectData), scoped
       to the current Windows user. This means a raw copy of license.dat
       taken to another machine (or another Windows user account on the
       same machine) fails to even decrypt, without relying purely on the
       device-id check inside the payload. DPAPI is NOT a substitute for
       the signature check — it just raises the bar for casual copying.

Storage location: %PROGRAMDATA%\\CommerceManager\\license.dat
   ProgramData (not AppData\\Roaming) is used deliberately: it is
   machine-scoped and requires admin rights to write, which matches "one
   license per PC" better than a per-user roaming folder that could be
   synced/copied via OneDrive.
"""
from __future__ import annotations

import os
from pathlib import Path

import win32crypt  # pywin32

from .crypto import SignedDocument

_APP_DIR_NAME = "CommerceManager"
_LICENSE_FILENAME = "license.dat"
_DPAPI_ENTROPY = b"CommerceManager.license.v1"  # additional entropy, not a secret


def _license_dir() -> Path:
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    d = Path(program_data) / _APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def license_path() -> Path:
    return _license_dir() / _LICENSE_FILENAME


class LicenseStorage:
    """Read/write the local encrypted license file."""

    def save(self, document: SignedDocument) -> None:
        raw = document.to_json().encode("utf-8")
        encrypted = win32crypt.CryptProtectData(
            raw,
            "CommerceManager License",  # description
            _DPAPI_ENTROPY,
            None,
            None,
            0,  # CRYPTPROTECT_UI_FORBIDDEN not needed, no UI is triggered server-side
        )
        path = license_path()
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_bytes(encrypted)
        os.replace(tmp_path, path)  # atomic on Windows (same volume)

    def load(self) -> SignedDocument | None:
        path = license_path()
        if not path.exists():
            return None
        encrypted = path.read_bytes()
        try:
            decrypted = win32crypt.CryptUnprotectData(
                encrypted, _DPAPI_ENTROPY, None, None, 0
            )[1]
        except Exception:
            # Corrupted, copied from another machine/user, or tampered wrapper.
            # Treat identically to "no license" -> caller routes to activation.
            return None
        return SignedDocument.from_json(decrypted.decode("utf-8"))

    def delete(self) -> None:
        path = license_path()
        if path.exists():
            path.unlink()
