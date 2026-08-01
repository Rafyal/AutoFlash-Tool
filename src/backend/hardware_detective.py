# src/backend/hardware_detective.py
"""
Hardware Detective — Tiered USB device polling module.
Detects devices in ADB, Fastboot, and BROM/EDL (emergency) modes
using WMI (Windows) and native VID/PID matching.

NOTE: This module intentionally avoids any payload injection tooling.
BROM/EDL detection is read-only polling — no SP Flash Tool / mtkclient
or any equivalent exploit-based approach is used.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known VID/PID tables  (read-only reference — no injection)
# ---------------------------------------------------------------------------

# MediaTek BROM / preloader (USB Download Mode)
MTK_BROM_VIDS = {0x0E8D}  # MediaTek Inc.
MTK_BROM_PIDS = {
    0x0003,  # MT65xx phone modem — BROM
    0x2000,  # MT6750 BROM
    0x3000,  # MT6771 / Helio P60 BROM
}

# Qualcomm EDL (Emergency Download Mode)
QCOM_EDL_VID = 0x05C6  # Qualcomm Inc.
QCOM_EDL_PID = 0x9008  # EDL / DIAG (generic)

# Standard ADB VID set (subset of commonly encountered OEMs)
ADB_KNOWN_VIDS = {
    0x18D1,  # Google
    0x04E8,  # Samsung
    0x2717,  # Xiaomi
    0x12D1,  # Huawei
    0x22D9,  # OPPO
    0x1BBB,  # Motorola
    0x0BB4,  # HTC
    0x054C,  # Sony
    0x0FCE,  # Sony Ericsson
    0x2A45,  # Meizu
    0x1D4D,  # Pegatron
    0x05AC,  # Apple (for reference; ADB unused)
    0x19D2,  # ZTE
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    """Represents a detected USB device."""
    serial: str = ""
    vid: Optional[int] = None
    pid: Optional[int] = None
    mode: str = "unknown"          # "adb" | "fastboot" | "brom" | "edl" | "unknown"
    manufacturer: str = ""
    description: str = ""
    extra: dict = field(default_factory=dict)

    def __str__(self) -> str:
        vid_str = f"{self.vid:#06x}" if self.vid is not None else "N/A"
        pid_str = f"{self.pid:#06x}" if self.pid is not None else "N/A"
        return (
            f"[{self.mode.upper()}] serial={self.serial or 'N/A'} "
            f"VID={vid_str} PID={pid_str} — {self.description or self.manufacturer}"
        )


# ---------------------------------------------------------------------------
# Tier 1 — ADB device polling
# ---------------------------------------------------------------------------

def poll_adb_devices(adb_path: str = "adb") -> list[DeviceInfo]:
    """
    Run `adb devices -l` and parse the output.

    Parameters
    ----------
    adb_path : str
        Absolute or relative path to the adb executable.

    Returns
    -------
    list[DeviceInfo]
        Devices currently detected in ADB mode.
    """
    devices: list[DeviceInfo] = []
    try:
        result = subprocess.run(
            [adb_path, "devices", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        lines = result.stdout.strip().splitlines()
        for line in lines[1:]:  # skip "List of devices attached" header
            line = line.strip()
            if not line or "offline" in line or "unauthorized" in line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial = parts[0]
            state = parts[1]  # "device", "recovery", "sideload", etc.
            extra = {}
            for token in parts[2:]:
                if ":" in token:
                    k, _, v = token.partition(":")
                    extra[k] = v
            devices.append(DeviceInfo(
                serial=serial,
                mode="adb",
                description=extra.get("model", state),
                extra=extra,
            ))
    except FileNotFoundError:
        logger.warning("adb not found at path: %s", adb_path)
    except subprocess.TimeoutExpired:
        logger.warning("adb devices timed out.")
    except Exception as exc:  # noqa: BLE001
        logger.error("ADB polling error: %s", exc)
    return devices


# ---------------------------------------------------------------------------
# Tier 2 — Fastboot device polling
# ---------------------------------------------------------------------------

def poll_fastboot_devices(fastboot_path: str = "fastboot") -> list[DeviceInfo]:
    """
    Run `fastboot devices` and parse the output.

    Parameters
    ----------
    fastboot_path : str
        Absolute or relative path to the fastboot executable.

    Returns
    -------
    list[DeviceInfo]
        Devices currently detected in Fastboot mode.
    """
    devices: list[DeviceInfo] = []
    try:
        result = subprocess.run(
            [fastboot_path, "devices"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "fastboot":
                devices.append(DeviceInfo(
                    serial=parts[0],
                    mode="fastboot",
                    description="Device in Fastboot mode",
                ))
    except FileNotFoundError:
        logger.warning("fastboot not found at path: %s", fastboot_path)
    except subprocess.TimeoutExpired:
        logger.warning("fastboot devices timed out.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Fastboot polling error: %s", exc)
    return devices


# ---------------------------------------------------------------------------
# Tier 3 — BROM / EDL WMI polling (Windows only, read-only)
# ---------------------------------------------------------------------------

def _parse_vid_pid(pnp_device_id: str) -> tuple[Optional[int], Optional[int]]:
    """
    Extract VID and PID integers from a Windows PnP Device ID string.
    E.g. 'USB\\VID_0E8D&PID_0003\\...' → (0x0E8D, 0x0003)
    """
    vid: Optional[int] = None
    pid: Optional[int] = None
    upper = pnp_device_id.upper()
    try:
        if "VID_" in upper:
            vid_str = upper.split("VID_")[1][:4]
            vid = int(vid_str, 16)
        if "PID_" in upper:
            pid_str = upper.split("PID_")[1][:4]
            pid = int(pid_str, 16)
    except (IndexError, ValueError):
        pass
    return vid, pid


def poll_brom_edl_devices() -> list[DeviceInfo]:
    """
    Poll Windows WMI for USB devices matching known BROM / EDL VID+PID pairs.
    This is strictly a read-only detection — no data is written to the device.

    Returns
    -------
    list[DeviceInfo]
        Detected BROM or EDL devices.

    Raises
    ------
    ImportError
        On non-Windows systems where the ``wmi`` package is unavailable.
    """
    try:
        import wmi  # type: ignore[import]
    except ImportError:
        logger.warning("wmi module not available. BROM/EDL detection requires Windows.")
        return []

    devices: list[DeviceInfo] = []
    try:
        c = wmi.WMI()
        for usb_dev in c.Win32_PnPEntity(ConfigManagerErrorCode=0):
            pnp_id: str = usb_dev.PNPDeviceID or ""
            if not pnp_id.startswith("USB\\"):
                continue
            vid, pid = _parse_vid_pid(pnp_id)
            if vid is None or pid is None:
                continue

            mode: Optional[str] = None

            # Check for MediaTek BROM
            if vid in MTK_BROM_VIDS and pid in MTK_BROM_PIDS:
                mode = "brom"

            # Check for Qualcomm EDL
            elif vid == QCOM_EDL_VID and pid == QCOM_EDL_PID:
                mode = "edl"

            if mode:
                devices.append(DeviceInfo(
                    vid=vid,
                    pid=pid,
                    mode=mode,
                    manufacturer=usb_dev.Manufacturer or "",
                    description=usb_dev.Description or usb_dev.Name or "",
                    extra={"pnp_id": pnp_id},
                ))
    except Exception as exc:  # noqa: BLE001
        logger.error("WMI polling error: %s", exc)

    return devices


# ---------------------------------------------------------------------------
# Unified poll — all tiers
# ---------------------------------------------------------------------------

def poll_all_devices(
    adb_path: str = "adb",
    fastboot_path: str = "fastboot",
) -> list[DeviceInfo]:
    """
    Run all three detection tiers and return a merged device list.

    Parameters
    ----------
    adb_path : str
        Path to adb executable.
    fastboot_path : str
        Path to fastboot executable.

    Returns
    -------
    list[DeviceInfo]
        All detected devices across ADB, Fastboot, and BROM/EDL modes.
    """
    found: list[DeviceInfo] = []
    found.extend(poll_adb_devices(adb_path))
    found.extend(poll_fastboot_devices(fastboot_path))
    found.extend(poll_brom_edl_devices())
    logger.info("Hardware Detective found %d device(s).", len(found))
    return found


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    for dev in poll_all_devices():
        print(dev)
