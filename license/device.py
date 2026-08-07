"""
license/device.py

Generates a stable Device ID for the current Windows machine by combining
several hardware/OS identifiers and hashing them together. No single
identifier is trusted alone (MAC addresses change with USB dongles, disk
serials can be blank on some virtual disks, etc.) — combining several and
requiring a MAJORITY match on re-validation makes the fingerprint both
stable across minor hardware changes (e.g. swapped RAM) and hard to spoof
with a single registry edit.
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
import winreg
from dataclasses import dataclass, field


def _safe(fn):
    """Run a collector, return '' on any failure instead of raising."""
    try:
        return fn() or ""
    except Exception:
        return ""


def _machine_guid() -> str:
    """HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid — set once at Windows
    install time, survives most hardware changes, wiped only by OS reinstall."""
    key = winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
    )
    value, _ = winreg.QueryValueEx(key, "MachineGuid")
    return value


def _wmic(alias: str, prop: str) -> str:
    """
    Query WMI via PowerShell's CIM cmdlets (wmic.exe is deprecated/removed on
    newer Windows builds; Get-CimInstance is the supported replacement).

    Retries once on failure/timeout with a slightly longer window - a cold
    PowerShell process can be slow to start (module loading), which was
    previously enough to cause a false negative and change the resulting
    device_id from run to run on the SAME machine. Timeouts are kept modest
    (4s then 6s = 10s worst case per component) since this runs on every
    app launch and three of these run in parallel (see collect() below).
    """
    cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"(Get-CimInstance -ClassName {alias}).{prop}",
    ]
    for timeout in (4, 6):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout)
            result = out.decode(errors="ignore").strip()
            if result:
                return result
        except Exception:
            continue
    return ""


def _cpu_id() -> str:
    return _wmic("Win32_Processor", "ProcessorId")


def _motherboard_serial() -> str:
    return _wmic("Win32_BaseBoard", "SerialNumber")


def _disk_serial() -> str:
    return _wmic("Win32_DiskDrive", "SerialNumber")


@dataclass(frozen=True)
class DeviceFingerprint:
    machine_guid: str = field(default="")
    cpu_id: str = field(default="")
    motherboard_serial: str = field(default="")
    disk_serial: str = field(default="")

    @classmethod
    def collect(cls) -> "DeviceFingerprint":
        # machine_guid is a fast registry read - do it inline. The three
        # WMI-based lookups each involve spawning PowerShell, so run them
        # concurrently rather than one after another (worst case ~10s
        # instead of ~30s if every single one needs its retry).
        from concurrent.futures import ThreadPoolExecutor

        machine_guid = _safe(_machine_guid)
        with ThreadPoolExecutor(max_workers=3) as pool:
            cpu_future = pool.submit(_safe, _cpu_id)
            board_future = pool.submit(_safe, _motherboard_serial)
            disk_future = pool.submit(_safe, _disk_serial)
            cpu_id = cpu_future.result()
            motherboard_serial = board_future.result()
            disk_serial = disk_future.result()

        return cls(
            machine_guid=machine_guid,
            cpu_id=cpu_id,
            motherboard_serial=motherboard_serial,
            disk_serial=disk_serial,
        )

    def component_hashes(self) -> dict[str, str]:
        """Individual hashes, used for the fuzzy/majority-match comparison."""
        return {
            name: hashlib.sha256(value.encode()).hexdigest()
            for name, value in {
                "machine_guid": self.machine_guid,
                "cpu_id": self.cpu_id,
                "motherboard_serial": self.motherboard_serial,
                "disk_serial": self.disk_serial,
            }.items()
            if value
        }

    def device_id(self) -> str:
        """
        The single Device ID stored inside the license. Deterministic,
        order-independent (sorted), and platform-tagged so we can extend
        with a macOS/Linux collector later without ID collisions.
        """
        parts = sorted(self.component_hashes().values())
        blob = "|".join(parts) + f"|{platform.system()}"
        return hashlib.sha256(blob.encode()).hexdigest()


def get_current_device_id() -> str:
    return DeviceFingerprint.collect().device_id()


def matches_with_tolerance(
    stored: DeviceFingerprint, current: DeviceFingerprint, min_matches: int = 2
) -> bool:
    """
    Optional soft-check used only for admin "why did this fail" diagnostics
    (e.g. showing partial matches in the admin panel before a manual reset).
    The hard gate used by the validator is always the exact device_id()
    equality — this helper never grants access on its own.
    """
    a, b = stored.component_hashes(), current.component_hashes()
    common_keys = set(a) & set(b)
    matches = sum(1 for k in common_keys if a[k] == b[k])
    return matches >= min_matches
