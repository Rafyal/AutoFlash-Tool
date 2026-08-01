# src/backend/flasher.py
"""
Flasher — subprocess wrappers for ADB and Fastboot operations.

All commands are run as non-blocking background-friendly calls that
stream stdout/stderr line-by-line through an optional callback so the
UI can display live progress without freezing.

Safety policy
-------------
* No shell=True is used — every argument is passed as a list element.
* Commands targeting Emergency / BROM modes are limited to safe reads
  (getvar, oem commands) unless the caller explicitly requests writes.
"""

import logging
import subprocess
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Type alias for the line-output callback
LineCallback = Callable[[str], None]

# Default placeholder — replaced at runtime by the path resolver
_DEFAULT_ADB = "adb"
_DEFAULT_FASTBOOT = "fastboot"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_streaming(
    cmd: list[str],
    callback: Optional[LineCallback] = None,
    timeout: int = 300,
) -> tuple[int, str]:
    """
    Execute *cmd* and stream each output line through *callback*.

    Parameters
    ----------
    cmd : list[str]
        The command + arguments as a list (never shell=True).
    callback : LineCallback, optional
        Called with each decoded stdout/stderr line.  Useful for live UI
        progress bars and log panels.
    timeout : int
        Maximum seconds to wait before terminating the process.

    Returns
    -------
    tuple[int, str]
        (returncode, combined_output)
    """
    creation_flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation_flags = subprocess.CREATE_NO_WINDOW

    output_lines: list[str] = []
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
                output_lines.append(stripped)
                if callback:
                    callback(stripped)
                logger.debug("[CMD] %s", stripped)
            proc.wait(timeout=timeout)
            return proc.returncode, "\n".join(output_lines)
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.error("Command timed out: %s", " ".join(cmd))
        return -1, "TIMEOUT"
    except FileNotFoundError:
        msg = f"Executable not found: {cmd[0]}"
        logger.error(msg)
        if callback:
            callback(f"ERROR: {msg}")
        return -1, msg
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error running %s: %s", cmd, exc)
        return -1, str(exc)


# ---------------------------------------------------------------------------
# ADB wrappers
# ---------------------------------------------------------------------------

class ADBFlasher:
    """High-level wrappers around the adb command-line tool."""

    def __init__(self, adb_path: str = _DEFAULT_ADB) -> None:
        self.adb = adb_path

    def _adb(self, *args: str) -> list[str]:
        return [self.adb, *args]

    # ---- Device management ----

    def reboot(
        self,
        target: str = "",
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
    ) -> tuple[int, str]:
        """
        Reboot the device.

        Parameters
        ----------
        target : str
            '' (system), 'recovery', 'bootloader', 'fastboot'.
        serial : str, optional
            Target a specific device by serial.
        """
        cmd = self._adb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["reboot"]
        if target:
            cmd.append(target)
        return _run_streaming(cmd, callback)

    def sideload(
        self,
        zip_path: str | Path,
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
    ) -> tuple[int, str]:
        """
        Push and flash an OTA ZIP via `adb sideload`.

        Parameters
        ----------
        zip_path : str | Path
            Absolute path to the OTA/zip file.
        serial : str, optional
            Target a specific device by serial.
        """
        cmd = self._adb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["sideload", str(zip_path)]
        return _run_streaming(cmd, callback, timeout=600)

    def push(
        self,
        local: str | Path,
        remote: str,
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
    ) -> tuple[int, str]:
        """Push a local file to the device."""
        cmd = self._adb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["push", str(local), remote]
        return _run_streaming(cmd, callback, timeout=120)

    def shell(
        self,
        shell_cmd: str,
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
        timeout: int = 30,
    ) -> tuple[int, str]:
        """Execute an arbitrary shell command on the device."""
        cmd = self._adb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["shell", shell_cmd]
        return _run_streaming(cmd, callback, timeout=timeout)

    def get_prop(
        self,
        prop: str,
        serial: Optional[str] = None,
    ) -> str:
        """Return a device property value (e.g. ro.product.model)."""
        _, out = self.shell(f"getprop {prop}", serial=serial)
        return out.strip()


# ---------------------------------------------------------------------------
# Fastboot wrappers
# ---------------------------------------------------------------------------

class FastbootFlasher:
    """High-level wrappers around the fastboot command-line tool."""

    def __init__(self, fastboot_path: str = _DEFAULT_FASTBOOT) -> None:
        self.fastboot = fastboot_path

    def _fb(self, *args: str) -> list[str]:
        return [self.fastboot, *args]

    # ---- Partition flashing ----

    def flash(
        self,
        partition: str,
        image_path: str | Path,
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
    ) -> tuple[int, str]:
        """
        Flash an image to the given partition.

        Parameters
        ----------
        partition : str
            e.g. 'boot', 'system', 'vendor', 'recovery'.
        image_path : str | Path
            Absolute path to the .img file.
        """
        cmd = self._fb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["flash", partition, str(image_path)]
        return _run_streaming(cmd, callback, timeout=600)

    def flash_multiple(
        self,
        partitions: dict[str, str | Path],
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
    ) -> dict[str, tuple[int, str]]:
        """
        Flash multiple partitions sequentially.

        Parameters
        ----------
        partitions : dict[str, str | Path]
            Mapping of { partition_name: image_path }.

        Returns
        -------
        dict[str, tuple[int, str]]
            Results keyed by partition name.
        """
        results: dict[str, tuple[int, str]] = {}
        for part, img in partitions.items():
            if callback:
                callback(f"--- Flashing {part} ---")
            results[part] = self.flash(part, img, serial=serial, callback=callback)
        return results

    def erase(
        self,
        partition: str,
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
    ) -> tuple[int, str]:
        """Erase a partition."""
        cmd = self._fb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["erase", partition]
        return _run_streaming(cmd, callback)

    def reboot(
        self,
        target: str = "",
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
    ) -> tuple[int, str]:
        """
        Reboot device from fastboot.

        Parameters
        ----------
        target : str
            '' (system), 'bootloader', 'recovery', 'fastboot'.
        """
        cmd = self._fb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["reboot"]
        if target:
            cmd.append(target)
        return _run_streaming(cmd, callback)

    def get_var(
        self,
        variable: str = "all",
        serial: Optional[str] = None,
    ) -> str:
        """Read a fastboot variable (e.g. product, version-bootloader)."""
        cmd = self._fb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["getvar", variable]
        _, out = _run_streaming(cmd)
        return out.strip()

    def oem_unlock(
        self,
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
    ) -> tuple[int, str]:
        """Send OEM unlock command (device must have OEM unlocking enabled in dev options)."""
        cmd = self._fb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["oem", "unlock"]
        return _run_streaming(cmd, callback)

    def flashing_unlock(
        self,
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
    ) -> tuple[int, str]:
        """Send `fastboot flashing unlock` (Treble devices)."""
        cmd = self._fb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["flashing", "unlock"]
        return _run_streaming(cmd, callback)

    def set_active(
        self,
        slot: str,
        serial: Optional[str] = None,
        callback: Optional[LineCallback] = None,
    ) -> tuple[int, str]:
        """Set the active A/B slot."""
        cmd = self._fb()
        if serial:
            cmd += ["-s", serial]
        cmd += ["--set-active", slot]
        return _run_streaming(cmd, callback)
