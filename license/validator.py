"""
license/validator.py

Pure, side-effect-free validation logic. Given a SignedDocument and the
current device id, decide whether the app is allowed to run. No network
calls happen here — this is what makes offline operation possible.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

from .crypto import LicenseVerifier, SignatureVerificationError, SignedDocument
from .models import LicensePayload, LicenseStatus


class ValidationResult(enum.Enum):
    VALID = "valid"
    NO_LICENSE = "no_license"
    TAMPERED = "tampered"           # signature failed
    EXPIRED = "expired"
    WRONG_DEVICE = "wrong_device"
    DISABLED = "disabled"
    REVOKED = "revoked"
    CLOCK_TAMPERED = "clock_tampered"  # system clock rolled back past issue date


@dataclass(frozen=True)
class ValidationOutcome:
    result: ValidationResult
    payload: LicensePayload | None = None

    @property
    def ok(self) -> bool:
        return self.result is ValidationResult.VALID


USER_FACING_MESSAGES = {
    ValidationResult.NO_LICENSE: "No license found. Please log in to activate.",
    ValidationResult.TAMPERED: "License file is invalid or corrupted. Please reactivate.",
    ValidationResult.EXPIRED: "Your trial has expired.\nPlease activate your license.",
    ValidationResult.WRONG_DEVICE: "This license is bound to a different computer. "
                                    "Please contact support to transfer your license.",
    ValidationResult.DISABLED: "Your license has been disabled. Please contact support.",
    ValidationResult.REVOKED: "Your license has been revoked. Please contact support.",
    ValidationResult.CLOCK_TAMPERED: "System clock appears invalid. Please correct your "
                                      "system date/time and restart the application.",
}


class LicenseValidator:
    def __init__(self, verifier: LicenseVerifier):
        self._verifier = verifier

    def validate(
        self,
        document: SignedDocument | None,
        current_device_id: str,
        now: int,
        last_seen_timestamp: int | None = None,
    ) -> ValidationOutcome:
        if document is None:
            return ValidationOutcome(ValidationResult.NO_LICENSE)

        # 1. Signature / integrity check — must happen before trusting ANY field.
        try:
            self._verifier.verify(document.payload, document.signature)
        except SignatureVerificationError:
            return ValidationOutcome(ValidationResult.TAMPERED)

        payload = LicensePayload.from_dict(document.payload)

        # 2. Anti-clock-rollback: reject if the OS clock is now earlier than the
        #    last time we successfully validated. Prevents "roll the clock back
        #    to before expiry" bypass on a trial license.
        if last_seen_timestamp is not None and now < last_seen_timestamp:
            return ValidationOutcome(ValidationResult.CLOCK_TAMPERED, payload)

        # 3. Status checks (server can flip these on next reactivation/renewal)
        if payload.status is LicenseStatus.DISABLED:
            return ValidationOutcome(ValidationResult.DISABLED, payload)
        if payload.status is LicenseStatus.REVOKED:
            return ValidationOutcome(ValidationResult.REVOKED, payload)

        # 4. Device lock
        if payload.device_id != current_device_id:
            return ValidationOutcome(ValidationResult.WRONG_DEVICE, payload)

        # 5. Expiration
        if payload.is_expired(now):
            return ValidationOutcome(ValidationResult.EXPIRED, payload)

        return ValidationOutcome(ValidationResult.VALID, payload)
