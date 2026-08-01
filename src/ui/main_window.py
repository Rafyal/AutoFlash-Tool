# src/ui/main_window.py
"""
AutoFlash Tool — Main Window (CustomTkinter)

Panels
------
* Launchpad          — five quick-action buttons
* Hardware Detective — live USB device status
* Flashing Hub       — scatter/rawprogram-driven partition flash grid
* Driver Manager     — silent driver installation
* MTK BROM Toolkit   — DA-based MediaTek BROM operations

All backend calls run on daemon threads to prevent UI blocking.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Theme / appearance
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Brand palette
COLOR_BG        = "#0D0F14"
COLOR_SURFACE   = "#161B27"
COLOR_SURFACE2  = "#1E2535"
COLOR_ACCENT    = "#3B82F6"
COLOR_ACCENT_HV = "#2563EB"
COLOR_SUCCESS   = "#22C55E"
COLOR_WARNING   = "#F59E0B"
COLOR_ERROR     = "#EF4444"
COLOR_TEXT      = "#E2E8F0"
COLOR_MUTED     = "#64748B"
COLOR_BORDER    = "#2D3748"

FONT_TITLE      = ("Inter", 22, "bold")
FONT_SECTION    = ("Inter", 13, "bold")
FONT_BODY       = ("Inter", 12)
FONT_MONO       = ("Consolas", 11)
FONT_SMALL      = ("Inter", 10)


# ---------------------------------------------------------------------------
# Utility: run a callable on a background daemon thread
# ---------------------------------------------------------------------------

def run_in_thread(fn, *args, **kwargs) -> threading.Thread:
    """Launch *fn* on a daemon thread and return it."""
    t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Reusable widgets
# ---------------------------------------------------------------------------

class SectionLabel(ctk.CTkLabel):
    def __init__(self, master, text: str, **kwargs):
        super().__init__(
            master,
            text=text.upper(),
            font=FONT_SECTION,
            text_color=COLOR_MUTED,
            **kwargs,
        )


class AccentButton(ctk.CTkButton):
    def __init__(self, master, text: str, command=None, **kwargs):
        super().__init__(
            master,
            text=text,
            font=FONT_BODY,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HV,
            corner_radius=8,
            height=38,
            command=command,
            **kwargs,
        )


class StatusDot(ctk.CTkLabel):
    """A coloured dot used to indicate device connection status."""

    def __init__(self, master, **kwargs):
        super().__init__(master, text="●", font=("Inter", 16), **kwargs)
        self.set_unknown()

    def set_ok(self, label: str = ""):
        self.configure(text=f"● {label}", text_color=COLOR_SUCCESS)

    def set_warn(self, label: str = ""):
        self.configure(text=f"● {label}", text_color=COLOR_WARNING)

    def set_error(self, label: str = ""):
        self.configure(text=f"● {label}", text_color=COLOR_ERROR)

    def set_unknown(self, label: str = "Waiting…"):
        self.configure(text=f"● {label}", text_color=COLOR_MUTED)


class LogBox(ctk.CTkTextbox):
    """A read-only log output widget with thread-safe append."""

    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            font=FONT_MONO,
            fg_color=COLOR_BG,
            text_color=COLOR_TEXT,
            state="disabled",
            wrap="word",
            **kwargs,
        )

    def append(self, text: str) -> None:
        """Append *text* (thread-safe via after())."""
        self.after(0, self._append_safe, text)

    def _append_safe(self, text: str) -> None:
        self.configure(state="normal")
        self.insert("end", text + "\n")
        self.see("end")
        self.configure(state="disabled")

    def clear(self) -> None:
        self.after(0, self._clear_safe)

    def _clear_safe(self) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

class LaunchpadPanel(ctk.CTkFrame):
    """
    Panel 1 — four large shortcut buttons for the most common operations.
    """

    def __init__(self, master, *, app: "MainWindow", **kwargs):
        super().__init__(master, fg_color=COLOR_SURFACE, corner_radius=16, **kwargs)
        self.master_win = app
        self._build()

    def _build(self):
        pad = {"padx": 20, "pady": 10}

        ctk.CTkLabel(self, text="⚡  Launchpad", font=FONT_TITLE, text_color=COLOR_TEXT).pack(
            anchor="w", padx=24, pady=(20, 4)
        )
        SectionLabel(self, text="Quick Actions").pack(anchor="w", padx=24, pady=(0, 16))

        btn_grid = ctk.CTkFrame(self, fg_color="transparent")
        btn_grid.pack(fill="x", padx=20, pady=4)
        btn_grid.columnconfigure((0, 1, 2), weight=1)

        actions = [
            ("🔍  Detect Device",    self.master_win.action_detect_device),
            ("⚙️  Install Drivers",  self.master_win.action_install_drivers),
            ("📦  Flash Firmware",   self.master_win.action_open_flash_hub),
            ("🛠️  MTK BROM Toolkit", self.master_win.action_brom_toolkit),
            ("🔄  Reboot Device",    self.master_win.action_reboot_device),
        ]
        for idx, (label, cmd) in enumerate(actions):
            row, col = divmod(idx, 3)
            btn = AccentButton(btn_grid, text=label, command=cmd)
            btn.grid(row=row, column=col, padx=8, pady=8, sticky="ew")


class HardwareDetectivePanel(ctk.CTkFrame):
    """
    Panel 2 — live USB detection status, refresh button, device list.
    """

    def __init__(self, master, *, app: "MainWindow", **kwargs):
        super().__init__(master, fg_color=COLOR_SURFACE, corner_radius=16, **kwargs)
        self.master_win = app
        self._polling = False
        self._build()

    def _build(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 4))
        ctk.CTkLabel(header, text="🔬  Hardware Detective", font=FONT_TITLE, text_color=COLOR_TEXT).pack(
            side="left"
        )
        AccentButton(header, text="Refresh", command=self.refresh, width=90).pack(side="right")

        SectionLabel(self, text="Detection Tiers: ADB → Fastboot → BROM/EDL").pack(
            anchor="w", padx=24, pady=(0, 10)
        )

        # Status dots
        dots_frame = ctk.CTkFrame(self, fg_color=COLOR_SURFACE2, corner_radius=10)
        dots_frame.pack(fill="x", padx=20, pady=4)

        self.dot_adb      = StatusDot(dots_frame)
        self.dot_fastboot = StatusDot(dots_frame)
        self.dot_brom     = StatusDot(dots_frame)

        for dot, label in [
            (self.dot_adb,      "ADB"),
            (self.dot_fastboot, "Fastboot"),
            (self.dot_brom,     "BROM / EDL"),
        ]:
            row = ctk.CTkFrame(dots_frame, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=6)
            ctk.CTkLabel(row, text=f"{label}:", font=FONT_BODY, text_color=COLOR_MUTED, width=90, anchor="w").pack(
                side="left"
            )
            dot.pack(side="left")

        # Log box
        SectionLabel(self, text="Detection Log").pack(anchor="w", padx=24, pady=(12, 2))
        self.log = LogBox(self, height=160)
        self.log.pack(fill="both", expand=True, padx=20, pady=(0, 16))

    def refresh(self):
        if self._polling:
            return
        self._polling = True
        self.dot_adb.set_unknown("Scanning…")
        self.dot_fastboot.set_unknown("Scanning…")
        self.dot_brom.set_unknown("Scanning…")
        self.log.clear()
        run_in_thread(self._do_refresh)

    def _do_refresh(self):
        try:
            from src.backend.hardware_detective import (
                poll_adb_devices,
                poll_fastboot_devices,
                poll_brom_edl_devices,
            )
            adb_tools_path = self.master_win.config.get("adb_path", "adb")
            fb_tools_path  = self.master_win.config.get("fastboot_path", "fastboot")

            adb_devs = poll_adb_devices(adb_tools_path)
            self._update_dot(self.dot_adb, adb_devs, "ADB")

            fb_devs = poll_fastboot_devices(fb_tools_path)
            self._update_dot(self.dot_fastboot, fb_devs, "Fastboot")

            brom_devs = poll_brom_edl_devices()
            self._update_dot(self.dot_brom, brom_devs, "BROM/EDL")

            for dev in (*adb_devs, *fb_devs, *brom_devs):
                self.log.append(str(dev))
            if not (adb_devs or fb_devs or brom_devs):
                self.log.append("No devices detected.")
        except Exception as exc:  # noqa: BLE001
            self.log.append(f"ERROR: {exc}")
            logger.error("Hardware Detective refresh error: %s", exc)
        finally:
            self._polling = False

    def _update_dot(self, dot: StatusDot, devices: list, mode: str):
        if devices:
            dot.set_ok(f"{len(devices)} device(s)")
        else:
            dot.set_error("None")


class FlashingHubPanel(ctk.CTkFrame):
    """
    Panel 3 — Scatter/rawprogram-driven partition flash grid.

    Mimics the SP Flash Tool layout:
    each row = [ Checkbox | Partition name | Begin address | File path entry | Browse ]
    Populated dynamically after the user loads a scatter.txt or rawprogram.xml.
    """

    def __init__(self, master, *, app: "MainWindow", **kwargs):
        super().__init__(master, fg_color=COLOR_SURFACE, corner_radius=16, **kwargs)
        self.master_win = app
        self._scatter_dir: Optional[Path] = None  # base dir for resolving image files
        self._entries: list = []                   # list[PartitionEntry]
        self._row_widgets: list[dict] = []         # per-row widget refs
        self._flashing = False
        self._build()

    # ---- Layout --------------------------------------------------------

    def _build(self):
        # ── Header ──
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 4))
        ctk.CTkLabel(header, text="\U0001F4E6  Flashing Hub", font=FONT_TITLE, text_color=COLOR_TEXT).pack(
            side="left"
        )

        # Scatter loader button
        AccentButton(header, text="Load Scatter / XML", command=self._pick_scatter, width=150).pack(
            side="right"
        )

        SectionLabel(self, text="Partition Flash Table (SP Flash Tool style)").pack(
            anchor="w", padx=24, pady=(0, 6)
        )

        # ── Column header row ──
        col_hdr = ctk.CTkFrame(self, fg_color=COLOR_SURFACE2, corner_radius=6)
        col_hdr.pack(fill="x", padx=20, pady=(0, 2))
        col_hdr.columnconfigure(2, weight=1)  # file path column expands

        for col_idx, (lbl, w) in enumerate([
            ("DL",          44),
            ("Partition",  160),
            ("Begin Addr", 140),
            ("Image File",   0),   # 0 = expands
            ("",            80),   # Browse button col
        ]):
            sticky = "ew" if lbl == "Image File" else "w"
            ctk.CTkLabel(
                col_hdr, text=lbl, font=("Inter", 10, "bold"),
                text_color=COLOR_MUTED, **({"width": w} if w else {}),
            ).grid(row=0, column=col_idx, padx=6, pady=4, sticky=sticky)

        # ── Scrollable partition grid ──
        self.scroll_frame = ctk.CTkScrollableFrame(
            self, fg_color=COLOR_BG, scrollbar_button_color=COLOR_SURFACE2,
            scrollbar_button_hover_color=COLOR_ACCENT, corner_radius=8,
        )
        self.scroll_frame.pack(fill="both", expand=True, padx=20, pady=(0, 4))
        self.scroll_frame.columnconfigure(3, weight=1)  # file-path column expands

        # Placeholder label shown before a scatter is loaded
        self._placeholder = ctk.CTkLabel(
            self.scroll_frame,
            text="Load a scatter.txt or rawprogram.xml to populate the partition table.",
            font=FONT_BODY, text_color=COLOR_MUTED,
        )
        self._placeholder.grid(row=0, column=0, columnspan=5, pady=40)

        # ── Bottom controls ──
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=20, pady=(4, 16))

        # Flash mode selector
        ctk.CTkLabel(bottom, text="Mode:", font=FONT_BODY, text_color=COLOR_TEXT).pack(side="left")
        self.flash_mode_var = ctk.StringVar(value="SP Flash (scatter)")
        ctk.CTkOptionMenu(
            bottom,
            values=["SP Flash (scatter)", "Fastboot partition", "ADB sideload"],
            variable=self.flash_mode_var,
            fg_color=COLOR_SURFACE2,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HV,
            width=180,
        ).pack(side="left", padx=8)

        # Select All / None
        ctk.CTkButton(
            bottom, text="All", font=FONT_SMALL, width=48, height=30,
            fg_color=COLOR_SURFACE2, hover_color=COLOR_BORDER, corner_radius=6,
            command=lambda: self._set_all(True),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            bottom, text="None", font=FONT_SMALL, width=52, height=30,
            fg_color=COLOR_SURFACE2, hover_color=COLOR_BORDER, corner_radius=6,
            command=lambda: self._set_all(False),
        ).pack(side="left", padx=(0, 12))

        # Progress
        self.progress = ctk.CTkProgressBar(
            bottom, fg_color=COLOR_SURFACE2, progress_color=COLOR_ACCENT,
            width=200,
        )
        self.progress.set(0)
        self.progress.pack(side="left", padx=(0, 12))

        self.flash_btn = AccentButton(bottom, text="\u26A1  Flash Selected", command=self._do_flash)
        self.flash_btn.pack(side="left", padx=(0, 8))

        # Log
        SectionLabel(self, text="Flash Log").pack(anchor="w", padx=24, pady=(2, 2))
        self.log = LogBox(self, height=120)
        self.log.pack(fill="x", padx=20, pady=(0, 4))

    # ---- Scatter loading -----------------------------------------------

    def _pick_scatter(self):
        path = filedialog.askopenfilename(
            title="Select scatter.txt or rawprogram.xml",
            filetypes=[
                ("Scatter & rawprogram", "*.txt *.xml"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        run_in_thread(self._load_scatter, Path(path))

    def _load_scatter(self, path: Path):
        self.log.append(f"Loading: {path.name}")
        try:
            from src.backend.scatter_parser import parse_scatter, scatter_dir_from_file
            entries = parse_scatter(path)
            self._scatter_dir = scatter_dir_from_file(path)
            self._entries = entries
            self.log.append(f"Parsed {len(entries)} partition(s) from {path.name}")
            self.after(0, self._populate_grid)
        except Exception as exc:  # noqa: BLE001
            self.log.append(f"ERROR parsing scatter: {exc}")
            logger.error("Scatter load error: %s", exc)

    # ---- Grid population -----------------------------------------------

    def _populate_grid(self):
        """Rebuild the partition grid from self._entries (runs on UI thread)."""
        # Clear old widgets
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        self._row_widgets.clear()

        for row_idx, entry in enumerate(self._entries):
            row_bg = COLOR_BG if row_idx % 2 == 0 else COLOR_SURFACE2

            # --- DL checkbox ---
            dl_var = ctk.BooleanVar(value=entry.is_download)
            chk = ctk.CTkCheckBox(
                self.scroll_frame, text="", variable=dl_var,
                width=20, height=20,
                fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HV,
                checkbox_width=18, checkbox_height=18,
            )
            chk.grid(row=row_idx, column=0, padx=(8, 4), pady=3, sticky="w")

            # --- Partition name ---
            ctk.CTkLabel(
                self.scroll_frame, text=entry.name,
                font=FONT_MONO, text_color=COLOR_TEXT, anchor="w", width=155,
            ).grid(row=row_idx, column=1, padx=4, pady=3, sticky="w")

            # --- Begin address ---
            ctk.CTkLabel(
                self.scroll_frame,
                text=f"0x{entry.begin_addr:016X}",
                font=FONT_MONO, text_color=COLOR_MUTED, anchor="w", width=135,
            ).grid(row=row_idx, column=2, padx=4, pady=3, sticky="w")

            # --- File path entry ---
            # Pre-populate if a file matching entry.file_name exists beside the scatter
            initial_path = ""
            if entry.file_name and self._scatter_dir:
                candidate = self._scatter_dir / entry.file_name
                if candidate.exists():
                    initial_path = str(candidate)
                    entry.selected_path = candidate

            path_var = ctk.StringVar(value=initial_path)
            path_entry = ctk.CTkEntry(
                self.scroll_frame, textvariable=path_var,
                font=FONT_MONO, fg_color=COLOR_SURFACE2,
                border_color=COLOR_BORDER, text_color=COLOR_TEXT,
                placeholder_text="(no file selected)",
            )
            path_entry.grid(row=row_idx, column=3, padx=4, pady=3, sticky="ew")

            # --- Browse button ---
            browse_btn = ctk.CTkButton(
                self.scroll_frame, text="...", width=36, height=26,
                font=FONT_SMALL, fg_color=COLOR_SURFACE2, hover_color=COLOR_ACCENT,
                corner_radius=4,
                command=lambda e=entry, pv=path_var: self._browse_image(e, pv),
            )
            browse_btn.grid(row=row_idx, column=4, padx=(4, 8), pady=3)

            self._row_widgets.append({"dl_var": dl_var, "path_var": path_var, "entry": entry})

        self.scroll_frame.columnconfigure(3, weight=1)

    def _browse_image(self, entry, path_var: ctk.StringVar):
        """Open a file dialog for a single partition row."""
        initial = str(self._scatter_dir) if self._scatter_dir else ""
        path = filedialog.askopenfilename(
            title=f"Select image for {entry.name}",
            initialdir=initial,
            filetypes=[
                ("Image files", "*.img *.bin *.ext4 *.zip *.tar"),
                ("All files", "*.*"),
            ],
        )
        if path:
            entry.selected_path = Path(path)
            path_var.set(path)

    def _set_all(self, state: bool):
        """Select or deselect all partition checkboxes."""
        for row in self._row_widgets:
            row["dl_var"].set(state)

    # ---- Flash execution -----------------------------------------------

    def _do_flash(self):
        if self._flashing:
            self.log.append("Flash already in progress.")
            return
        if not self._row_widgets:
            messagebox.showwarning("No Scatter Loaded", "Load a scatter.txt or rawprogram.xml first.")
            return

        selected = [
            r for r in self._row_widgets
            if r["dl_var"].get() and r["path_var"].get()
        ]
        if not selected:
            messagebox.showwarning("Nothing Selected",
                "Enable the checkbox and set a file path for at least one partition.")
            return

        self._flashing = True
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.flash_btn.configure(state="disabled")
        run_in_thread(self._flash_worker, selected)

    def _flash_worker(self, selected: list[dict]):
        mode = self.flash_mode_var.get()
        fb_path  = self.master_win.config.get("fastboot_path", "fastboot")
        adb_path = self.master_win.config.get("adb_path", "adb")
        total = len(selected)
        ok_count = 0

        try:
            for idx, row in enumerate(selected, 1):
                entry    = row["entry"]
                img_path = Path(row["path_var"].get())
                self.log.append(f"[{idx}/{total}] Flashing {entry.name} <- {img_path.name}")

                if mode == "Fastboot partition":
                    from src.backend.flasher import FastbootFlasher
                    rc, _ = FastbootFlasher(fastboot_path=fb_path).flash(
                        entry.name, img_path, callback=self.log.append
                    )
                elif mode == "ADB sideload":
                    from src.backend.flasher import ADBFlasher
                    rc, _ = ADBFlasher(adb_path=adb_path).sideload(
                        img_path, callback=self.log.append
                    )
                else:  # SP Flash (scatter) — fastboot flash with scatter address info
                    from src.backend.flasher import FastbootFlasher
                    rc, _ = FastbootFlasher(fastboot_path=fb_path).flash(
                        entry.name, img_path, callback=self.log.append
                    )

                if rc == 0:
                    ok_count += 1
                    self.log.append(f"  OK: {entry.name}")
                else:
                    self.log.append(f"  FAILED: {entry.name} (exit code {rc})")

            self.log.append(
                f"\nFlash complete: {ok_count}/{total} partition(s) succeeded."
            )
        except Exception as exc:  # noqa: BLE001
            self.log.append(f"ERROR: {exc}")
            logger.error("Flash worker error: %s", exc)
        finally:
            self._flashing = False
            self.after(0, self._restore_ui)

    def _restore_ui(self):
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1)
        self.flash_btn.configure(state="normal")

    def _cancel(self):
        self.log.append("Cancel requested — waiting for current operation to finish...")




class BROMToolkitPanel(ctk.CTkFrame):
    """
    Panel 5 — MediaTek BROM Toolkit.

    All operations use direct serial DA communication or official ADB/Fastboot
    software commands.  No exploit payload injection is used.
    """

    def __init__(self, master, *, app: "MainWindow", **kwargs):
        super().__init__(master, fg_color=COLOR_SURFACE, corner_radius=16, **kwargs)
        self.master_win = app
        self._busy = False
        self._build()

    def _build(self):
        # ── Header ──
        ctk.CTkLabel(
            self, text="\U0001F9F2  MTK BROM Toolkit",
            font=FONT_TITLE, text_color=COLOR_TEXT,
        ).pack(anchor="w", padx=24, pady=(20, 2))
        SectionLabel(
            self, text="Direct DA serial communication — no payload injection"
        ).pack(anchor="w", padx=24, pady=(0, 10))

        # ── BROM port row ──
        port_row = ctk.CTkFrame(self, fg_color="transparent")
        port_row.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(port_row, text="BROM Port:", font=FONT_BODY, text_color=COLOR_TEXT, width=100, anchor="w").pack(
            side="left"
        )
        self.port_var = ctk.StringVar(value="Auto-detect")
        self.port_entry = ctk.CTkEntry(
            port_row, textvariable=self.port_var, width=110,
            font=FONT_MONO, fg_color=COLOR_SURFACE2, border_color=COLOR_BORDER,
        )
        self.port_entry.pack(side="left", padx=6)
        AccentButton(port_row, text="Detect", command=self._detect_port, width=80).pack(side="left", padx=4)
        self.port_status = ctk.CTkLabel(
            port_row, text="", font=FONT_SMALL, text_color=COLOR_MUTED
        )
        self.port_status.pack(side="left", padx=8)

        # ── Auth cert row ──
        auth_row = ctk.CTkFrame(self, fg_color="transparent")
        auth_row.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(auth_row, text="DA Auth Cert:", font=FONT_BODY, text_color=COLOR_TEXT, width=100, anchor="w").pack(
            side="left"
        )
        self.cert_var = ctk.StringVar(value="")
        ctk.CTkEntry(
            auth_row, textvariable=self.cert_var, width=220,
            font=FONT_MONO, fg_color=COLOR_SURFACE2, border_color=COLOR_BORDER,
            placeholder_text="Optional: .auth / .bin certificate",
        ).pack(side="left", padx=6)
        AccentButton(auth_row, text="Browse", command=self._pick_cert, width=70).pack(side="left", padx=4)

        # ── Partition picker (for dump operations) ──
        part_row = ctk.CTkFrame(self, fg_color="transparent")
        part_row.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(part_row, text="Partition:", font=FONT_BODY, text_color=COLOR_TEXT, width=100, anchor="w").pack(
            side="left"
        )
        self.part_var = ctk.StringVar(value="boot")
        ctk.CTkOptionMenu(
            part_row,
            values=["boot", "recovery", "lk", "preloader", "userdata", "frp", "metadata", "nvram"],
            variable=self.part_var,
            fg_color=COLOR_SURFACE2,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HV,
            width=140,
        ).pack(side="left", padx=6)

        # ── Dump output path ──
        dump_row = ctk.CTkFrame(self, fg_color="transparent")
        dump_row.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(dump_row, text="Dump output:", font=FONT_BODY, text_color=COLOR_TEXT, width=100, anchor="w").pack(
            side="left"
        )
        self.dump_path_var = ctk.StringVar(value="")
        ctk.CTkEntry(
            dump_row, textvariable=self.dump_path_var, width=220,
            font=FONT_MONO, fg_color=COLOR_SURFACE2, border_color=COLOR_BORDER,
            placeholder_text="Output .img path",
        ).pack(side="left", padx=6)
        AccentButton(dump_row, text="Browse", command=self._pick_dump_path, width=70).pack(side="left", padx=4)

        ctk.CTkFrame(self, fg_color=COLOR_BORDER, height=1).pack(fill="x", padx=20, pady=10)

        # ── Action buttons grid ──
        SectionLabel(self, text="BROM Actions").pack(anchor="w", padx=24, pady=(0, 6))

        btn_grid = ctk.CTkFrame(self, fg_color="transparent")
        btn_grid.pack(fill="x", padx=20, pady=4)
        btn_grid.columnconfigure((0, 1, 2), weight=1)

        actions = [
            ("\U0001F510  ADB -> BROM",      self._act_adb_to_brom,      "Sends adb reboot download (official MTK command)",     COLOR_ACCENT),
            ("\U0001F4E6  Fastboot -> BROM", self._act_fb_to_brom,       "Sends fastboot OEM download mode command",              COLOR_ACCENT),
            ("\U0001F512  DA Handshake",      self._act_da_handshake,     "Perform BROM DA serial handshake (device in BROM mode)",COLOR_ACCENT),
            ("\U0001F511  Send DA Auth Cert", self._act_da_auth,          "Send OEM auth certificate via DA protocol",             "#7C3AED"),
            ("\U0001F9F9  Format Data / FRP", self._act_format_data,      "Erase userdata + frp partitions via fastboot",          COLOR_WARNING),
            ("\U0001F4BE  Dump Boot / Recovery",self._act_dump_partition,  "Dump selected partition image via ADB (root required)", "#0891B2"),
        ]

        for idx, (label, cmd, tip, color) in enumerate(actions):
            row, col = divmod(idx, 3)
            frame = ctk.CTkFrame(btn_grid, fg_color=COLOR_SURFACE2, corner_radius=10)
            frame.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

            ctk.CTkButton(
                frame, text=label, font=FONT_BODY,
                fg_color=color, hover_color=self._darken(color),
                corner_radius=8, height=44,
                command=cmd,
            ).pack(fill="x", padx=8, pady=(10, 4))
            ctk.CTkLabel(
                frame, text=tip, font=FONT_SMALL, text_color=COLOR_MUTED,
                wraplength=200,
            ).pack(padx=8, pady=(0, 8))

        # ── Log ──
        ctk.CTkFrame(self, fg_color=COLOR_BORDER, height=1).pack(fill="x", padx=20, pady=8)
        SectionLabel(self, text="BROM Log").pack(anchor="w", padx=24, pady=(0, 2))
        self.log = LogBox(self, height=140)
        self.log.pack(fill="both", expand=True, padx=20, pady=(0, 16))

    @staticmethod
    def _darken(hex_color: str) -> str:
        """Return a slightly darkened hex colour for hover states."""
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            factor = 0.80
            return f"#{int(r*factor):02X}{int(g*factor):02X}{int(b*factor):02X}"
        except Exception:  # noqa: BLE001
            return hex_color

    # ---- UI helpers --------------------------------------------------------

    def _detect_port(self):
        run_in_thread(self._do_detect_port)

    def _do_detect_port(self):
        from src.backend.mtk_brom import find_brom_port
        self.port_status.configure(text="Scanning...", text_color=COLOR_MUTED)
        port = find_brom_port()
        if port:
            self.port_var.set(port)
            self.port_status.configure(text=f"Found: {port}", text_color=COLOR_SUCCESS)
            self.log.append(f"MTK BROM detected on {port}")
        else:
            self.port_status.configure(text="Not found", text_color=COLOR_ERROR)
            self.log.append(
                "No BROM device detected. Ensure the device is in BROM mode\n"
                "(Power OFF, hold Vol Down, connect USB)."
            )

    def _pick_cert(self):
        path = filedialog.askopenfilename(
            title="Select DA Auth Certificate",
            filetypes=[("Auth cert", "*.auth *.bin"), ("All files", "*.*")],
        )
        if path:
            self.cert_var.set(path)

    def _pick_dump_path(self):
        path = filedialog.asksaveasfilename(
            title="Save partition dump as",
            defaultextension=".img",
            filetypes=[("Image files", "*.img *.bin"), ("All files", "*.*")],
        )
        if path:
            self.dump_path_var.set(path)

    def _get_port(self) -> Optional[str]:
        """Return the selected COM port, or None if Auto-detect is set."""
        val = self.port_var.get().strip()
        return None if val.lower() in ("", "auto-detect") else val

    # ---- BROM Actions -------------------------------------------------------

    def _act_adb_to_brom(self):
        adb = self.master_win.config.get("adb_path", "adb")
        self.log.append("[ADB -> BROM] Sending reboot download command...")
        run_in_thread(self._run_brom_op, "adb_to_brom", {"adb_path": adb})

    def _act_fb_to_brom(self):
        fb = self.master_win.config.get("fastboot_path", "fastboot")
        self.log.append("[Fastboot -> BROM] Sending OEM download mode command...")
        run_in_thread(self._run_brom_op, "fastboot_to_brom", {"fastboot_path": fb})

    def _act_da_handshake(self):
        port = self._get_port()
        if not port:
            messagebox.showwarning(
                "No COM Port",
                "Select or detect a BROM COM port before performing the DA handshake.",
            )
            return
        self.log.append(f"[DA Handshake] Opening {port}...")
        run_in_thread(self._run_brom_op, "da_handshake", {"port": port})

    def _act_da_auth(self):
        port = self._get_port()
        cert = self.cert_var.get().strip()
        if not port:
            messagebox.showwarning("No COM Port", "Select a BROM COM port first.")
            return
        if not cert:
            messagebox.showwarning("No Certificate", "Browse to an .auth / .bin certificate file first.")
            return
        self.log.append(f"[DA Auth] Sending certificate {Path(cert).name} to {port}...")
        run_in_thread(self._run_brom_op, "da_auth", {"port": port, "cert_path": cert})

    def _act_format_data(self):
        if not messagebox.askyesno(
            "Format Data / FRP",
            "This will ERASE userdata and frp partitions.\n"
            "All user data will be permanently lost.\n\nContinue?",
        ):
            return
        fb = self.master_win.config.get("fastboot_path", "fastboot")
        self.log.append("[Format] Erasing userdata + frp via fastboot...")
        run_in_thread(self._run_brom_op, "format_data", {"fastboot_path": fb})

    def _act_dump_partition(self):
        part = self.part_var.get()
        out  = self.dump_path_var.get().strip()
        if not out:
            messagebox.showwarning("No Output Path", "Set a dump output path first.")
            return
        adb = self.master_win.config.get("adb_path", "adb")
        self.log.append(f"[Dump] Dumping {part} to {out}...")
        run_in_thread(self._run_brom_op, "dump_partition", {
            "partition": part, "output_path": out, "adb_path": adb
        })

    def _run_brom_op(self, operation: str, kwargs: dict):
        """Generic threaded BROM operation dispatcher."""
        from src.backend import mtk_brom
        try:
            if operation == "adb_to_brom":
                rc, _ = mtk_brom.adb_to_brom(callback=self.log.append, **kwargs)
            elif operation == "fastboot_to_brom":
                rc, _ = mtk_brom.fastboot_to_brom(callback=self.log.append, **kwargs)
            elif operation == "da_handshake":
                mtk_brom.perform_da_handshake(callback=self.log.append, **kwargs)
                rc = 0
            elif operation == "da_auth":
                mtk_brom.send_da_auth_certificate(callback=self.log.append, **kwargs)
                rc = 0
            elif operation == "format_data":
                fb = kwargs.get("fastboot_path", "fastboot")
                r1, _ = mtk_brom.format_partition("userdata", method="fastboot",
                    fastboot_path=fb, callback=self.log.append)
                r2, _ = mtk_brom.format_partition("frp", method="fastboot",
                    fastboot_path=fb, callback=self.log.append)
                rc = 0 if r1 == 0 and r2 == 0 else 1
            elif operation == "dump_partition":
                rc, _ = mtk_brom.dump_partition(callback=self.log.append, **kwargs)
            else:
                self.log.append(f"Unknown operation: {operation}")
                return

            if rc == 0:
                self.log.append(f"[OK] {operation} completed.")
            else:
                self.log.append(f"[FAILED] {operation} returned exit code {rc}.")
        except Exception as exc:  # noqa: BLE001
            self.log.append(f"ERROR [{operation}]: {exc}")
            logger.error("BROM op %s error: %s", operation, exc)


class DriverManagerPanel(ctk.CTkFrame):
    """
    Panel 4 — pnputil-based silent driver installation.
    """

    def __init__(self, master, *, app: "MainWindow", **kwargs):
        super().__init__(master, fg_color=COLOR_SURFACE, corner_radius=16, **kwargs)
        self.master_win = app
        self._inf_path: Optional[Path] = None
        self._busy = False
        self._build()

    def _build(self):
        ctk.CTkLabel(self, text="⚙️  Driver Manager", font=FONT_TITLE, text_color=COLOR_TEXT).pack(
            anchor="w", padx=24, pady=(20, 4)
        )
        SectionLabel(self, text="Silent pnputil Installation (Windows, Elevated)").pack(
            anchor="w", padx=24, pady=(0, 10)
        )

        # INF picker
        pick_row = ctk.CTkFrame(self, fg_color="transparent")
        pick_row.pack(fill="x", padx=20, pady=4)
        self.inf_label = ctk.CTkLabel(
            pick_row, text="No .inf selected", font=FONT_BODY, text_color=COLOR_MUTED, anchor="w"
        )
        self.inf_label.pack(side="left", fill="x", expand=True)
        AccentButton(pick_row, text="Browse…", command=self._pick_inf, width=100).pack(side="right")

        # Directory install option
        dir_row = ctk.CTkFrame(self, fg_color="transparent")
        dir_row.pack(fill="x", padx=20, pady=4)
        AccentButton(dir_row, text="📁  Install All from Directory", command=self._pick_dir).pack(
            side="left"
        )

        # Options
        opts_row = ctk.CTkFrame(self, fg_color="transparent")
        opts_row.pack(fill="x", padx=20, pady=4)
        self.install_var = ctk.BooleanVar(value=True)
        self.force_var   = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            opts_row, text="Install on matching hardware", variable=self.install_var,
            font=FONT_BODY, text_color=COLOR_TEXT,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HV,
        ).pack(side="left", padx=(0, 20))
        ctk.CTkCheckBox(
            opts_row, text="Force replace existing", variable=self.force_var,
            font=FONT_BODY, text_color=COLOR_TEXT,
            fg_color=COLOR_WARNING, hover_color="#D97706",
        ).pack(side="left")

        # Install button
        self.install_btn = AccentButton(self, text="⚙️  Install Driver", command=self._do_install)
        self.install_btn.pack(anchor="w", padx=20, pady=8)

        # Log
        SectionLabel(self, text="Installation Log").pack(anchor="w", padx=24, pady=(8, 2))
        self.log = LogBox(self, height=160)
        self.log.pack(fill="both", expand=True, padx=20, pady=(0, 16))

    def _pick_inf(self):
        path = filedialog.askopenfilename(
            title="Select driver .inf file",
            filetypes=[("INF Driver Files", "*.inf"), ("All files", "*.*")],
        )
        if path:
            self._inf_path = Path(path)
            self.inf_label.configure(text=self._inf_path.name, text_color=COLOR_TEXT)

    def _pick_dir(self):
        directory = filedialog.askdirectory(title="Select driver directory")
        if directory:
            self._inf_path = None
            run_in_thread(self._install_from_dir, Path(directory))

    def _do_install(self):
        if self._busy:
            return
        if not self._inf_path:
            messagebox.showwarning("No INF", "Please select an .inf driver file first.")
            return
        self._busy = True
        self.install_btn.configure(state="disabled")
        run_in_thread(self._install_single, self._inf_path)

    def _install_single(self, inf: Path):
        try:
            from src.backend.driver_manager import install_driver, PlatformNotSupportedError
            self.log.append(f"Installing: {inf.name}")
            rc, out = install_driver(
                inf,
                install=self.install_var.get(),
                force_replace=self.force_var.get(),
                callback=self.log.append,
            )
            if rc == 0:
                self.log.append("✅  Driver installed successfully.")
            else:
                self.log.append(f"❌  pnputil exited with code {rc}.")
        except Exception as exc:  # noqa: BLE001
            self.log.append(f"ERROR: {exc}")
        finally:
            self._busy = False
            self.after(0, lambda: self.install_btn.configure(state="normal"))

    def _install_from_dir(self, directory: Path):
        self._busy = True
        self.after(0, lambda: self.install_btn.configure(state="disabled"))
        try:
            from src.backend.driver_manager import install_drivers_from_directory
            self.log.append(f"Scanning directory: {directory}")
            results = install_drivers_from_directory(
                directory,
                install=self.install_var.get(),
                force_replace=self.force_var.get(),
                callback=self.log.append,
            )
            ok = sum(1 for rc, _ in results.values() if rc == 0)
            self.log.append(f"Done — {ok}/{len(results)} driver(s) installed.")
        except Exception as exc:  # noqa: BLE001
            self.log.append(f"ERROR: {exc}")
        finally:
            self._busy = False
            self.after(0, lambda: self.install_btn.configure(state="normal"))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(ctk.CTk):
    """
    Root application window.

    Attributes
    ----------
    config : dict
        Runtime configuration (tool paths, preferences).
    """

    def __init__(self, config: Optional[dict] = None):
        super().__init__()
        self.config: dict = config or {}

        self.title("AutoFlash Tool")
        self.geometry("1060x740")
        self.minsize(800, 600)
        self.configure(fg_color=COLOR_BG)

        self._build_layout()
        self._show_panel("launchpad")

    # ---- Layout ----

    def _build_layout(self):
        """Build sidebar + content area."""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Sidebar ──────────────────────────────────────────────────────
        self.sidebar = ctk.CTkFrame(self, fg_color=COLOR_SURFACE, width=210, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)

        # Logo / title
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", padx=16, pady=(24, 8))
        ctk.CTkLabel(logo_frame, text="⚡", font=("Inter", 28)).pack(side="left")
        ctk.CTkLabel(
            logo_frame, text="AutoFlash", font=("Inter", 17, "bold"), text_color=COLOR_TEXT
        ).pack(side="left", padx=6)

        ctk.CTkFrame(self.sidebar, fg_color=COLOR_BORDER, height=1).pack(fill="x", padx=16, pady=8)

        # Nav buttons
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("launchpad",   "\u26A1  Launchpad"),
            ("detective",   "\U0001F52C  Hardware Detective"),
            ("flashing",    "\U0001F4E6  Flashing Hub"),
            ("drivers",     "\u2699\uFE0F  Driver Manager"),
            ("brom",        "\U0001F9F2  MTK BROM Toolkit"),
        ]
        for key, label in nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=label,
                font=FONT_BODY,
                fg_color="transparent",
                hover_color=COLOR_SURFACE2,
                text_color=COLOR_TEXT,
                anchor="w",
                corner_radius=8,
                height=40,
                command=lambda k=key: self._show_panel(k),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self._nav_buttons[key] = btn

        # Footer
        ctk.CTkFrame(self.sidebar, fg_color=COLOR_BORDER, height=1).pack(fill="x", padx=16, pady=8, side="bottom")
        ctk.CTkLabel(
            self.sidebar, text="v1.0.0 · AutoFlash Tool",
            font=FONT_SMALL, text_color=COLOR_MUTED
        ).pack(side="bottom", pady=8)

        # ── Content area ─────────────────────────────────────────────────
        self.content = ctk.CTkFrame(self, fg_color=COLOR_BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew", padx=0)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        # Instantiate panels
        self.panels: dict[str, ctk.CTkFrame] = {
            "launchpad": LaunchpadPanel(self.content, app=self),
            "detective": HardwareDetectivePanel(self.content, app=self),
            "flashing":  FlashingHubPanel(self.content, app=self),
            "drivers":   DriverManagerPanel(self.content, app=self),
            "brom":      BROMToolkitPanel(self.content, app=self),
        }
        for panel in self.panels.values():
            panel.grid(row=0, column=0, sticky="nsew", padx=24, pady=24)

    def _show_panel(self, key: str):
        for k, panel in self.panels.items():
            panel.tkraise() if k == key else panel.lower()
        # Highlight active nav button
        for k, btn in self._nav_buttons.items():
            btn.configure(
                fg_color=COLOR_SURFACE2 if k == key else "transparent",
                text_color=COLOR_ACCENT if k == key else COLOR_TEXT,
            )

    # ---- Launchpad action bindings ----

    def action_detect_device(self):
        self._show_panel("detective")
        self.after(100, self.panels["detective"].refresh)

    def action_install_drivers(self):
        self._show_panel("drivers")

    def action_open_flash_hub(self):
        self._show_panel("flashing")

    def action_brom_toolkit(self):
        self._show_panel("brom")

    def action_reboot_device(self):
        if not messagebox.askyesno("Reboot Device", "Reboot the connected device now?"):
            return
        adb_path = self.config.get("adb_path", "adb")

        def _reboot():
            from src.backend.flasher import ADBFlasher
            rc, out = ADBFlasher(adb_path).reboot()
            if rc == 0:
                messagebox.showinfo("Reboot", "Reboot command sent successfully.")
            else:
                messagebox.showerror("Reboot Failed", f"adb reboot failed:\n{out}")

        run_in_thread(_reboot)
