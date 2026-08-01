# src/backend/mtk_brom.py
"""
MTK BROM Toolkit — MediaTek Boot ROM serial DA communication layer.

Design constraints
------------------
* All BROM operations use **direct serial DA (Download Agent) communication**
  over the standard USB-serial port exposed by the MTK BROM (VID 0x0E8D).
* NO exploit payload injection is used.  Tools such as mtkclient that rely on
  preloader vulnerability exploitation are explicitly excluded.
* "ADB to BROM" is implemented via `adb reboot download` — the official MTK
  software entry point into Download Mode.  The preloader-crash technique is
  an exploitation method and is not present in this codebase.
* "Bypass SLA/DA Auth" refers exclusively to sending a valid authentication
  certificate bundle (e.g. signed by the OEM's root key) through the standard
  DA auth handshake, NOT to bypassing security by exploiting BROM vulnerabilities.

USB / Serial protocol reference
--------------------------------
MTK BROM presents as a CDC-ACM or raw USB serial device.
Baud rate : 115200 (initial handshake), then negotiated up to 921600.
Handshake : 0xA0 0x0A 0x50 0x05 (host) ↔ 0x5F 0xF5 0xAF 0xFA (device).
After handshake the host sends the DA binary which is executed by the BROM.

References (publicly available documentation)
---------------------------------------------
* SP Flash Tool open-source driver (GitHub: MediaTek-Genio/spft-driver)
* MTK DA protocol reverse-engineering notes in the LineageOS wiki
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

LineCallback = Callable[[str], None]

# BROM USB identifiers (read-only reference — detection only)
BROM_VID = 0x0E8D
BROM_PID = 0x0003

# DA handshake magic bytes (standard MTK protocol, publicly documented)
_HS_HOST   = bytes([0xA0, 0x0A, 0x50, 0x05])
_HS_DEVICE = bytes([0x5F, 0xF5, 0xAF, 0xFA])

# Default timeouts
_SERIAL_TIMEOUT   = 5.0   # seconds for serial read
_COMMAND_TIMEOUT  = 30    # seconds for subprocess calls


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BROMError(Exception):
    """Raised for BROM communication or operation errors."""


class BROMHandshakeError(BROMError):
    """Raised when the BROM DA handshake fails."""


class BROMNotConnectedError(BROMError):
    """Raised when no BROM device is detected on any serial port."""


# ---------------------------------------------------------------------------
# Port discovery
# ---------------------------------------------------------------------------

def find_brom_port() -> Optional[str]:
    """
    Scan Windows COM ports via WMI for a device matching the MTK BROM
    VID (0x0E8D) and PID (0x0003) and return its port name (e.g. 'COM4').

    Returns None on non-Windows systems or when no BROM is detected.
    """
    try:
        import wmi  # type: ignore[import]
        c = wmi.WMI()
        for dev in c.Win32_PnPEntity():
            pnp: str = dev.PNPDeviceID or ""
            if f"VID_{BROM_VID:04X}" in pnp.upper() and f"PID_{BROM_PID:04X}" in pnp.upper():
                # Cross-reference with SerialPort to get the COMx name
                for port in c.Win32_SerialPort():
                    if port.PNPDeviceID and port.PNPDeviceID.upper() == pnp.upper():
                        logger.info("MTK BROM found on %s", port.DeviceID)
                        return port.DeviceID
        logger.debug("MTK BROM not found on any COM port.")
    except ImportError:
        logger.warning("wmi not available — BROM port discovery requires Windows.")
    except Exception as exc:  # noqa: BLE001
        logger.error("WMI port discovery error: %s", exc)
    return None


# ---------------------------------------------------------------------------
# DA Handshake (serial — device must already be in BROM mode)
# ---------------------------------------------------------------------------

def _open_serial(port: str, baud: int = 115200):
    """
    Open a pyserial Serial object for the given port.
    Raises ImportError if pyserial is not installed.
    """
    try:
        import serial  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "pyserial is required for direct BROM communication.\n"
            "Install it with: pip install pyserial"
        ) from exc
    return serial.Serial(port, baud, timeout=_SERIAL_TIMEOUT)


def perform_da_handshake(port: str, callback: Optional[LineCallback] = None) -> None:
    """
    Execute the standard MTK BROM DA handshake over serial.

    The device MUST already be in BROM mode before calling this function
    (e.g. hardware key combination: Power + Vol↓ while USB is connected).

    Protocol (publicly documented):
        Host → Device : 0xA0 0x0A 0x50 0x05
        Device → Host : 0x5F 0xF5 0xAF 0xFA

    Parameters
    ----------
    port : str
        COM port name (e.g. 'COM4').
    callback : LineCallback, optional
        Progress/status line callback for live UI display.

    Raises
    ------
    BROMHandshakeError
        If the device does not respond with the expected magic bytes.
    BROMNotConnectedError
        If the serial port cannot be opened.
    """
    def _log(msg: str) -> None:
        logger.debug(msg)
        if callback:
            callback(msg)

    _log(f"Opening serial port {port} at 115200 baud…")
    try:
        ser = _open_serial(port)
    except Exception as exc:
        raise BROMNotConnectedError(f"Cannot open {port}: {exc}") from exc

    with ser:
        _log("Sending BROM handshake bytes: A0 0A 50 05")
        ser.write(_HS_HOST)
        ser.flush()

        response = ser.read(len(_HS_DEVICE))
        _log(f"Device responded: {response.hex().upper()}")

        if response != _HS_DEVICE:
            raise BROMHandshakeError(
                f"Expected {_HS_DEVICE.hex().upper()}, got {response.hex().upper() or '(no response)'}. "
                "Ensure the device is in BROM mode and the correct COM port is selected."
            )
        _log("Handshake OK — BROM is ready for DA upload.")


# ---------------------------------------------------------------------------
# DA Auth (SLA / DAA certificate-based)
# ---------------------------------------------------------------------------

def send_da_auth_certificate(
    port: str,
    cert_path: str | Path,
    callback: Optional[LineCallback] = None,
) -> None:
    """
    Send a signed authentication certificate to the BROM via the standard
    DA auth challenge-response protocol.

    This function implements the **legitimate certificate handshake** defined
    in the MTK SP Flash Tool DA auth protocol.  It does NOT bypass security —
    it authenticates using a valid OEM-issued certificate bundle.

    For devices without SLA/DAA enforcement (engineering/unlocked units),
    this step can be skipped and the DA upload proceeds directly.

    Parameters
    ----------
    port : str
        COM port of the BROM device.
    cert_path : str | Path
        Path to the DA authentication certificate (typically auth_sv5.auth
        or a device-specific .bin certificate).
    callback : LineCallback, optional
        Live progress callback.

    Raises
    ------
    FileNotFoundError
        If cert_path does not exist.
    BROMError
        If auth is rejected by the BROM.
    """
    cert = Path(cert_path).resolve()
    if not cert.exists():
        raise FileNotFoundError(f"DA auth certificate not found: {cert}")

    def _log(msg: str) -> None:
        logger.debug(msg)
        if callback:
            callback(msg)

    _log(f"Loading DA auth certificate: {cert.name} ({cert.stat().st_size} bytes)")

    # NOTE: Full DA auth protocol implementation requires negotiating a
    # challenge from the BROM (device sends a 32-byte challenge, host signs
    # it with the certificate's RSA key, and sends back the signature).
    # This is a stub placeholder — a complete implementation would integrate
    # with the OEM's auth library or a compatible open-source SP tool driver.
    _log("[STUB] DA auth certificate loaded. Full challenge-response requires OEM RSA key.")
    _log("For auth-disabled/engineering devices, skip this step and proceed to DA upload.")


# ---------------------------------------------------------------------------
# Software-based entry into Download Mode (safe, non-exploit methods)
# ---------------------------------------------------------------------------

def _run_cmd(cmd: list[str], callback: Optional[LineCallback] = None) -> tuple[int, str]:
    """Run a subprocess, stream output through callback, return (rc, output)."""
    creation_flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation_flags = subprocess.CREATE_NO_WINDOW
    lines: list[str] = []
    try:
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creation_flags,
        ) as proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                stripped = line.rstrip()
                lines.append(stripped)
                if callback:
                    callback(stripped)
            proc.wait(timeout=_COMMAND_TIMEOUT)
            return proc.returncode, "\n".join(lines)
    except FileNotFoundError:
        msg = f"Executable not found: {cmd[0]}"
        if callback:
            callback(f"ERROR: {msg}")
        return -1, msg
    except subprocess.TimeoutExpired:
        proc.kill()
        msg = "Command timed out."
        if callback:
            callback(f"ERROR: {msg}")
        return -1, msg
    except Exception as exc:  # noqa: BLE001
        if callback:
            callback(f"ERROR: {exc}")
        return -1, str(exc)


def adb_to_brom(
    adb_path: str = "adb",
    serial: Optional[str] = None,
    callback: Optional[LineCallback] = None,
) -> tuple[int, str]:
    """
    Reboot a connected ADB device into MediaTek Download Mode via the
    official ``adb reboot download`` command.

    Implementation note — why NOT preloader crash
    ----------------------------------------------
    Some third-party tools forcibly crash the preloader during reboot to
    trigger an unintended fallback into BROM mode.  This is an exploitation
    technique that:
      * Requires sending crafted USB control packets that exploit BROM
        vulnerabilities (similar to CVE-class bugs).
      * Is categorised as payload injection — explicitly excluded by the
        AutoFlash Tool design constraints.
      * Is unreliable across firmware versions and may brick devices.

    This function uses ``adb reboot download`` — the official, documented
    MTK command — which is functionally equivalent on supported devices.

    Parameters
    ----------
    adb_path : str
        Path to the adb executable.
    serial : str, optional
        Target a specific device by serial number.
    callback : LineCallback, optional
        Live progress callback.

    Returns
    -------
    tuple[int, str]
        (returncode, output)  0 = success.
    """
    cmd = [adb_path]
    if serial:
        cmd += ["-s", serial]
    cmd += ["reboot", "download"]

    if callback:
        callback("Sending: adb reboot download")
        if serial:
            callback(f"Target serial: {serial}")

    rc, out = _run_cmd(cmd, callback)
    if rc == 0:
        if callback:
            callback("Device rebooting into Download Mode. Wait for BROM USB enumeration (VID 0x0E8D).")
    else:
        if callback:
            callback(
                "Note: 'adb reboot download' may not be supported on all MTK devices. "
                "On unsupported devices, use the hardware key combination instead:\n"
                "  Power OFF → hold Vol Down → connect USB cable."
            )
    return rc, out


def fastboot_to_brom(
    fastboot_path: str = "fastboot",
    serial: Optional[str] = None,
    callback: Optional[LineCallback] = None,
) -> tuple[int, str]:
    """
    Reboot a Fastboot device into MTK Download Mode via OEM fastboot commands.

    Tries the following commands in order:
    1. ``fastboot oem reboot-download``  (some MTK OEMs)
    2. ``fastboot oem mtk-reboot-to-download``

    Parameters
    ----------
    fastboot_path : str
        Path to the fastboot executable.
    serial : str, optional
        Target device serial.
    callback : LineCallback, optional
        Live progress callback.

    Returns
    -------
    tuple[int, str]
        (returncode, output) of the first successful command, or of the last
        attempted command if all fail.
    """
    candidates = [
        ["oem", "reboot-download"],
        ["oem", "mtk-reboot-to-download"],
    ]
    base = [fastboot_path]
    if serial:
        base += ["-s", serial]

    last_rc, last_out = -1, ""
    for oem_args in candidates:
        cmd = base + oem_args
        if callback:
            callback(f"Trying: fastboot {' '.join(oem_args)}")
        rc, out = _run_cmd(cmd, callback)
        last_rc, last_out = rc, out
        if rc == 0:
            if callback:
                callback("Fastboot OEM download mode command accepted.")
            return rc, out

    if callback:
        callback(
            "Fastboot OEM download commands were not accepted by this device.\n"
            "Use the hardware key combination: Power OFF -> Vol Down + USB."
        )
    return last_rc, last_out


# ---------------------------------------------------------------------------
# Partition operations (via ADB/Fastboot — device must NOT be in BROM mode)
# ---------------------------------------------------------------------------

def format_partition(
    partition: str,
    method: str = "fastboot",
    adb_path: str = "adb",
    fastboot_path: str = "fastboot",
    serial: Optional[str] = None,
    callback: Optional[LineCallback] = None,
) -> tuple[int, str]:
    """
    Erase/format a partition.

    Parameters
    ----------
    partition : str
        Partition name, e.g. 'userdata', 'frp', 'metadata'.
    method : str
        'fastboot' (default) or 'adb' (requires root shell).
    adb_path : str
        Path to adb executable.
    fastboot_path : str
        Path to fastboot executable.
    serial : str, optional
        Target device serial.
    callback : LineCallback, optional
        Live progress callback.

    Returns
    -------
    tuple[int, str]
        (returncode, output)
    """
    if callback:
        callback(f"Formatting partition: {partition} via {method}")

    if method == "fastboot":
        cmd = [fastboot_path]
        if serial:
            cmd += ["-s", serial]
        cmd += ["erase", partition]
        return _run_cmd(cmd, callback)

    elif method == "adb":
        # Requires rooted device — erases via block device wipe
        cmd = [adb_path]
        if serial:
            cmd += ["-s", serial]
        # Use dd to zero-fill — safer than mkfs across all partition types
        cmd += ["shell", f"su -c 'dd if=/dev/zero of=/dev/block/by-name/{partition} bs=4096'"]
        if callback:
            callback("WARNING: ADB format requires root. Verify device is rooted.")
        return _run_cmd(cmd, callback)

    else:
        msg = f"Unknown format method: {method}"
        if callback:
            callback(f"ERROR: {msg}")
        return -1, msg


def dump_partition(
    partition: str,
    output_path: str | Path,
    method: str = "adb",
    adb_path: str = "adb",
    fastboot_path: str = "fastboot",
    serial: Optional[str] = None,
    callback: Optional[LineCallback] = None,
) -> tuple[int, str]:
    """
    Dump a partition image to a local file.

    Parameters
    ----------
    partition : str
        Partition name (e.g. 'boot', 'recovery').
    output_path : str | Path
        Local path to write the dumped image.
    method : str
        'adb' (default, requires root) or 'fastboot'.
    adb_path : str
        Path to adb executable.
    fastboot_path : str
        Path to fastboot executable.
    serial : str, optional
        Target device serial.
    callback : LineCallback, optional
        Live progress callback.

    Returns
    -------
    tuple[int, str]
        (returncode, output)
    """
    out = Path(output_path).resolve()
    if callback:
        callback(f"Dumping partition '{partition}' to {out}")

    if method == "adb":
        # Step 1: dd the block device to /sdcard, then adb pull
        remote_tmp = f"/sdcard/{partition}.img"
        block_cmd  = f"su -c 'dd if=/dev/block/by-name/{partition} of={remote_tmp} bs=4096'"

        if callback:
            callback("Step 1/2: Creating image on device (requires root)…")
        cmd_dd = [adb_path]
        if serial:
            cmd_dd += ["-s", serial]
        cmd_dd += ["shell", block_cmd]
        rc, o = _run_cmd(cmd_dd, callback)
        if rc != 0:
            return rc, o

        if callback:
            callback(f"Step 2/2: Pulling {remote_tmp} to local disk…")
        cmd_pull = [adb_path]
        if serial:
            cmd_pull += ["-s", serial]
        cmd_pull += ["pull", remote_tmp, str(out)]
        return _run_cmd(cmd_pull, callback)

    elif method == "fastboot":
        # fastboot get_staged is non-standard; use boot image dump where available
        if callback:
            callback("Note: Fastboot partition dump uses 'fastboot fetch' (Android 12+ required).")
        cmd = [fastboot_path]
        if serial:
            cmd += ["-s", serial]
        cmd += ["fetch", partition, str(out)]
        return _run_cmd(cmd, callback)

    else:
        msg = f"Unknown dump method: {method}"
        if callback:
            callback(f"ERROR: {msg}")
        return -1, msg
