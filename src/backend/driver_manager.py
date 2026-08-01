# src/backend/driver_manager.py
"""
Driver Manager — Silent driver installation via pnputil (Windows only).

Uses `pnputil /add-driver` to silently install .inf-based USB drivers
without requiring user interaction at UAC prompts (caller must already
be elevated).

Platform note
-------------
This module is Windows-exclusive. On non-Windows systems the public API
will raise :class:`DriverManagerError` with a clear message rather than
crashing at import time.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

LineCallback = Callable[[str], None]

WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DriverManagerError(Exception):
    """Raised for all driver installation failures."""


class PlatformNotSupportedError(DriverManagerError):
    """Raised when the host OS is not Windows."""


# ---------------------------------------------------------------------------
# Elevation check
# ---------------------------------------------------------------------------

def is_elevated() -> bool:
    """
    Return True if the current process has Administrator privileges.
    Always returns False on non-Windows platforms.
    """
    if not WINDOWS:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Core installer
# ---------------------------------------------------------------------------

def _run_pnputil(args: list[str], callback: Optional[LineCallback] = None) -> tuple[int, str]:
    """
    Execute pnputil with the given arguments.

    Parameters
    ----------
    args : list[str]
        Arguments appended after 'pnputil'.
    callback : LineCallback, optional
        Called with each line of stdout/stderr.

    Returns
    -------
    tuple[int, str]
        (returncode, combined_output)
    """
    cmd = ["pnputil"] + args
    logger.debug("Running: %s", " ".join(cmd))

    output_lines: list[str] = []
    try:
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ) as proc:
            assert proc.stdout is not None
            for line in proc.stdout:
                stripped = line.rstrip()
                output_lines.append(stripped)
                logger.debug("[pnputil] %s", stripped)
                if callback:
                    callback(stripped)
            proc.wait(timeout=120)
            return proc.returncode, "\n".join(output_lines)
    except FileNotFoundError:
        msg = "pnputil not found — this tool requires Windows 10/11."
        logger.error(msg)
        raise DriverManagerError(msg) from None
    except subprocess.TimeoutExpired:
        proc.kill()
        msg = "pnputil timed out after 120 seconds."
        logger.error(msg)
        raise DriverManagerError(msg) from None
    except Exception as exc:  # noqa: BLE001
        logger.error("pnputil error: %s", exc)
        raise DriverManagerError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install_driver(
    inf_path: str | Path,
    *,
    install: bool = True,
    force_replace: bool = False,
    callback: Optional[LineCallback] = None,
) -> tuple[int, str]:
    """
    Silently add and optionally install a driver package via pnputil.

    Equivalent CLI:
        pnputil /add-driver <inf> [/install] [/force]

    Parameters
    ----------
    inf_path : str | Path
        Absolute path to the driver .inf file.
    install : bool
        If True, also attempt to install the driver on matching hardware.
    force_replace : bool
        If True, pass /force to overwrite an already-installed driver.
    callback : LineCallback, optional
        Receives each line of pnputil output for live UI display.

    Returns
    -------
    tuple[int, str]
        (returncode, pnputil_output)

    Raises
    ------
    PlatformNotSupportedError
        On non-Windows systems.
    DriverManagerError
        On pnputil execution failures.
    ValueError
        If inf_path does not exist or is not an .inf file.
    """
    if not WINDOWS:
        raise PlatformNotSupportedError(
            "driver_manager requires Windows. pnputil is not available on this platform."
        )

    inf = Path(inf_path).resolve()
    if not inf.exists():
        raise ValueError(f"INF file not found: {inf}")
    if inf.suffix.lower() != ".inf":
        raise ValueError(f"Expected an .inf file, got: {inf.suffix}")

    if not is_elevated():
        logger.warning(
            "Process is not elevated. pnputil /add-driver may fail. "
            "Re-run AutoFlash Tool as Administrator."
        )

    args = ["/add-driver", str(inf)]
    if install:
        args.append("/install")
    if force_replace:
        args.append("/force")

    logger.info("Installing driver: %s (install=%s, force=%s)", inf, install, force_replace)
    return _run_pnputil(args, callback=callback)


def install_drivers_from_directory(
    driver_dir: str | Path,
    *,
    recursive: bool = True,
    install: bool = True,
    force_replace: bool = False,
    callback: Optional[LineCallback] = None,
) -> dict[str, tuple[int, str]]:
    """
    Install all .inf files found in *driver_dir*.

    Parameters
    ----------
    driver_dir : str | Path
        Directory to search for .inf files.
    recursive : bool
        If True, search subdirectories as well.
    install : bool
        Passed to :func:`install_driver`.
    force_replace : bool
        Passed to :func:`install_driver`.
    callback : LineCallback, optional
        Passed to :func:`install_driver`.

    Returns
    -------
    dict[str, tuple[int, str]]
        Mapping of inf filename → (returncode, output).
    """
    driver_dir = Path(driver_dir).resolve()
    if not driver_dir.is_dir():
        raise ValueError(f"Not a directory: {driver_dir}")

    pattern = "**/*.inf" if recursive else "*.inf"
    inf_files = list(driver_dir.glob(pattern))

    if not inf_files:
        logger.warning("No .inf files found in %s", driver_dir)
        return {}

    results: dict[str, tuple[int, str]] = {}
    for inf in inf_files:
        if callback:
            callback(f"Installing driver: {inf.name}")
        try:
            results[inf.name] = install_driver(
                inf,
                install=install,
                force_replace=force_replace,
                callback=callback,
            )
        except DriverManagerError as exc:
            logger.error("Failed to install %s: %s", inf.name, exc)
            results[inf.name] = (-1, str(exc))

    return results


def list_installed_oem_drivers(callback: Optional[LineCallback] = None) -> tuple[int, str]:
    """
    List all third-party OEM drivers currently staged in the driver store.
    Equivalent to: pnputil /enum-drivers
    """
    if not WINDOWS:
        raise PlatformNotSupportedError("pnputil requires Windows.")
    return _run_pnputil(["/enum-drivers"], callback=callback)


def remove_driver(
    oem_inf_name: str,
    *,
    uninstall: bool = False,
    callback: Optional[LineCallback] = None,
) -> tuple[int, str]:
    """
    Remove a staged OEM driver from the driver store.

    Parameters
    ----------
    oem_inf_name : str
        The OEM INF filename as reported by pnputil (e.g. 'oem42.inf').
    uninstall : bool
        If True, also uninstall the driver from any matching devices.
    callback : LineCallback, optional
        Live output callback.
    """
    if not WINDOWS:
        raise PlatformNotSupportedError("pnputil requires Windows.")
    args = ["/delete-driver", oem_inf_name]
    if uninstall:
        args.append("/uninstall")
    return _run_pnputil(args, callback=callback)
