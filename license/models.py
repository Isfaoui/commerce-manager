"""
license/models.py — the License payload contract.

This dict shape is the thing that gets signed. ANY field listed here is
tamper-protected by the Ed25519 signature. Never read license fields from
anywhere except a verified SignedDocument.
"""
from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any


class LicenseType(str, enum.Enum):
    TRIAL = "trial"
    PROFESSIONAL = "professional"


class LicenseStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"


@dataclass(frozen=True)
class LicensePayload:
    license_id: str
    customer_id: str
    license_type: LicenseType
    status: LicenseStatus
    device_id: str
    features: list[str]
    issued_at: int          # unix epoch seconds
    expires_at: int | None  # None => never expires (Professional)
    issued_by: str          # admin username / "self-service"
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["license_type"] = self.license_type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LicensePayload":
        return cls(
            license_id=d["license_id"],
            customer_id=d["customer_id"],
            license_type=LicenseType(d["license_type"]),
            status=LicenseStatus(d["status"]),
            device_id=d["device_id"],
            features=list(d["features"]),
            issued_at=int(d["issued_at"]),
            expires_at=(int(d["expires_at"]) if d.get("expires_at") is not None else None),
            issued_by=d["issued_by"],
            schema_version=int(d.get("schema_version", 1)),
        )

    def is_expired(self, now: int | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or int(time.time())) >= self.expires_at

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())


TRIAL_DURATION_SECONDS = 7 * 24 * 60 * 60

# Feature flags Version 1 cares about — extend freely, this list is signed
# so a modified license can never grant an unpurchased feature.
FEATURES_TRIAL = ["pos_sales", "inventory_basic", "reports_basic"]
FEATURES_PROFESSIONAL = ["pos_sales", "inventory_full", "reports_full", "multi_till", "priority_support"]
