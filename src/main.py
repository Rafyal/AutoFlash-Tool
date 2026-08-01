# src/main.py
"""
AutoFlash Tool — entry point.

Usage
-----
    python -m src.main
    python src/main.py

The script:
1. Configures root-level logging.
2. Resolves paths to the bundled adb/fastboot tools in ./tools/.
3. Instantiates and runs the CustomTkinter MainWindow.
"""

import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging setup (before any imports that might log)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("autoflash")


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_tools_dir() -> Path:
    """
    Return the absolute path to the tools/ directory whether we're running
    from source or as a PyInstaller bundle.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller sets sys._MEIPASS to the temp extraction dir
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        # Running from source: tools/ sits next to src/
        base = Path(__file__).parent.parent

    tools = base / "tools"
    if not tools.exists():
        logger.warning("tools/ directory not found at %s — using system PATH for adb/fastboot", tools)
    return tools


def _build_config(tools_dir: Path) -> dict:
    """Build the runtime config dict passed to the UI."""
    adb_exe      = "adb.exe"      if sys.platform == "win32" else "adb"
    fastboot_exe = "fastboot.exe" if sys.platform == "win32" else "fastboot"

    adb_path      = str(tools_dir / adb_exe)      if (tools_dir / adb_exe).exists()      else "adb"
    fastboot_path = str(tools_dir / fastboot_exe) if (tools_dir / fastboot_exe).exists() else "fastboot"

    return {
        "adb_path":      adb_path,
        "fastboot_path": fastboot_path,
        "tools_dir":     str(tools_dir),
    }


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("AutoFlash Tool starting…")

    tools_dir = _resolve_tools_dir()
    config    = _build_config(tools_dir)

    logger.debug("adb      -> %s", config["adb_path"])
    logger.debug("fastboot -> %s", config["fastboot_path"])

    # Import here so logging is configured first
    try:
        from src.ui.main_window import MainWindow
    except ImportError:
        # Allow running as `python src/main.py` from the project root
        import importlib, importlib.util
        spec = importlib.util.spec_from_file_location(
            "main_window",
            Path(__file__).parent / "ui" / "main_window.py",
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        MainWindow = mod.MainWindow  # type: ignore[assignment]

    app = MainWindow(config=config)
    logger.info("MainWindow created — entering event loop.")
    app.mainloop()
    logger.info("AutoFlash Tool exited cleanly.")


if __name__ == "__main__":
    main()
