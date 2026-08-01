# src/backend/scatter_parser.py
"""
MediaTek Scatter File Parser

Supports both formats encountered in the wild:
  * V1  — legacy key=value block format (MT65xx era, scatter_version = V1.x.x)
  * V2  — YAML-like block format with '- !BitDesc' stanzas (MT67xx/MT68xx era)

Usage
-----
    from src.backend.scatter_parser import parse_scatter, PartitionEntry

    entries = parse_scatter("/path/to/MT6765_Android_scatter.txt")
    for e in entries:
        print(e.name, hex(e.begin_addr), e.file_name)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PartitionEntry:
    """Represents a single flashable partition from a scatter / rawprogram file."""

    name: str                      # partition_name / partition_index
    begin_addr: int                # linear_start_addr or begin_address (bytes)
    size: int                      # partition_size (bytes), 0 if unknown
    file_name: str                 # suggested image filename (may be empty)
    is_download: bool              # whether this partition should be flashed by default
    region: str                    # e.g. EMMC_USER, EMMC_BOOT_1 (empty if unknown)
    storage: str                   # HW_STORAGE_EMMC / HW_STORAGE_UFS (empty if unknown)
    selected_path: Optional[Path]  # resolved file path chosen by the user

    def __post_init__(self):
        if self.selected_path is None:
            self.selected_path = None  # explicit None — caller sets after UI browse

    def __str__(self) -> str:
        addr = f"0x{self.begin_addr:016X}"
        sz   = f"0x{self.size:X}" if self.size else "?"
        dl   = "[DL]" if self.is_download else "[  ]"
        return f"{dl} {self.name:<30s} @ {addr}  size={sz}  file={self.file_name or '—'}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_hex_or_int(value: str) -> int:
    """Parse '0x1234ABCD' or decimal string → int, return 0 on failure."""
    v = value.strip()
    try:
        return int(v, 16) if v.startswith("0x") or v.startswith("0X") else int(v)
    except (ValueError, TypeError):
        return 0


def _detect_format(text: str) -> str:
    """
    Heuristically determine the scatter format.

    Returns
    -------
    'v1'  — legacy key=value blocks
    'v2'  — YAML-like '- !BitDesc' blocks
    """
    if "- !BitDesc" in text or "partition_name:" in text:
        return "v2"
    return "v1"


# ---------------------------------------------------------------------------
# V1 parser — legacy key=value block format
# ---------------------------------------------------------------------------

_V1_BLOCK_RE = re.compile(
    r"partition_index\s*=\s*(?P<name>\S+).*?"   # partition_index = FOO
    r"(?:begin_address|linear_start_addr)\s*=\s*(?P<addr>0x[\dA-Fa-f]+|\d+)"
    r".*?file_name\s*=\s*(?P<file>\S*)",
    re.DOTALL,
)

# Some V1 files use 'is_download' as a boolean keyword
_V1_DL_RE     = re.compile(r"is_download\s*=\s*(\w+)", re.IGNORECASE)
_V1_SIZE_RE   = re.compile(r"partition_size\s*=\s*(0x[\dA-Fa-f]+|\d+)", re.IGNORECASE)
_V1_REGION_RE = re.compile(r"region\s*=\s*(\w+)", re.IGNORECASE)


def _parse_v1(text: str) -> list[PartitionEntry]:
    """
    Parse the legacy V1 scatter format.
    Splits on 'partition_index' boundaries and extracts fields within each block.
    """
    entries: list[PartitionEntry] = []
    # Split into per-partition blocks on 'partition_index'
    blocks = re.split(r"(?=partition_index\s*=)", text)

    for block in blocks:
        m_name = re.search(r"partition_index\s*=\s*(\S+)", block)
        m_addr = re.search(r"(?:begin_address|linear_start_addr)\s*=\s*(0x[\dA-Fa-f]+|\d+)", block)
        if not m_name or not m_addr:
            continue

        name     = m_name.group(1).strip('"').strip()
        addr     = _parse_hex_or_int(m_addr.group(1))

        m_file   = re.search(r"file_name\s*=\s*(\S+)", block)
        m_dl     = _V1_DL_RE.search(block)
        m_size   = _V1_SIZE_RE.search(block)
        m_region = _V1_REGION_RE.search(block)

        file_name   = (m_file.group(1).strip('"') if m_file else "").strip()
        is_download = m_dl.group(1).lower() in ("true", "1", "yes") if m_dl else (file_name != "")
        size        = _parse_hex_or_int(m_size.group(1))   if m_size   else 0
        region      = m_region.group(1)                     if m_region else ""

        # Skip meta entries that are never flashed
        if name in ("PMIC_Setting", "BROM_Header"):
            continue

        entries.append(PartitionEntry(
            name=name,
            begin_addr=addr,
            size=size,
            file_name=file_name,
            is_download=is_download,
            region=region,
            storage="",
            selected_path=None,
        ))

    return entries


# ---------------------------------------------------------------------------
# V2 parser — YAML-like '- !BitDesc' format
# ---------------------------------------------------------------------------

def _parse_v2_block(block: str) -> Optional[PartitionEntry]:
    """Parse a single '- !BitDesc' stanza from a V2 scatter file."""

    def _field(key: str) -> str:
        m = re.search(rf"^\s*{re.escape(key)}\s*:\s*(.+)$", block, re.MULTILINE)
        return m.group(1).strip().strip('"') if m else ""

    name      = _field("partition_name") or _field("partition_index")
    addr_str  = _field("linear_start_addr") or _field("begin_address")
    size_str  = _field("partition_size")
    file_name = _field("file_name")
    dl_str    = _field("is_download")
    region    = _field("region")
    storage   = _field("storage")

    if not name:
        return None

    addr        = _parse_hex_or_int(addr_str)
    size        = _parse_hex_or_int(size_str)
    is_download = dl_str.lower() in ("true", "1") if dl_str else (file_name != "")

    return PartitionEntry(
        name=name,
        begin_addr=addr,
        size=size,
        file_name=file_name,
        is_download=is_download,
        region=region,
        storage=storage,
        selected_path=None,
    )


def _parse_v2(text: str) -> list[PartitionEntry]:
    """Parse the modern V2 scatter format."""
    entries: list[PartitionEntry] = []
    # Each partition block starts with '- !BitDesc'
    raw_blocks = re.split(r"(?=^\s*-\s*!BitDesc)", text, flags=re.MULTILINE)
    for block in raw_blocks:
        if "partition_name" not in block and "partition_index" not in block:
            continue
        entry = _parse_v2_block(block)
        if entry:
            entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# rawprogram XML parser (Qualcomm / generic format bonus support)
# ---------------------------------------------------------------------------

def _parse_rawprogram_xml(path: Path) -> list[PartitionEntry]:
    """
    Parse a Qualcomm rawprogram*.xml file.
    Each <program> element maps to one PartitionEntry.
    """
    entries: list[PartitionEntry] = []
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        for prog in root.iter("program"):
            label     = prog.get("label", "")
            file_name = prog.get("filename", "")
            start_str = prog.get("start_sector", "0")
            size_str  = prog.get("num_partition_sectors", "0")
            sector_sz = int(prog.get("SECTOR_SIZE_IN_BYTES", "512") or "512")

            try:
                start_sector = int(start_str)
                num_sectors  = int(size_str)
            except ValueError:
                start_sector = 0
                num_sectors  = 0

            if not label:
                continue

            entries.append(PartitionEntry(
                name=label,
                begin_addr=start_sector * sector_sz,
                size=num_sectors * sector_sz,
                file_name=file_name,
                is_download=bool(file_name),
                region="",
                storage="",
                selected_path=None,
            ))
    except ET.ParseError as exc:
        raise ValueError(f"Invalid rawprogram XML: {exc}") from exc
    return entries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_scatter(path: str | Path) -> list[PartitionEntry]:
    """
    Parse a MediaTek scatter (.txt) or rawprogram (.xml) file and return
    a list of :class:`PartitionEntry` objects ready for the UI grid.

    Parameters
    ----------
    path : str | Path
        Absolute path to the scatter or rawprogram file.

    Returns
    -------
    list[PartitionEntry]
        Ordered list of partitions as they appear in the file.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    ValueError
        If the file cannot be parsed (empty, unknown format, malformed XML).
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Scatter file not found: {p}")

    # rawprogram XML
    if p.suffix.lower() in (".xml",):
        return _parse_rawprogram_xml(p)

    text = p.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise ValueError(f"Scatter file is empty: {p}")

    fmt = _detect_format(text)
    if fmt == "v2":
        entries = _parse_v2(text)
    else:
        entries = _parse_v1(text)

    if not entries:
        raise ValueError(
            f"No partition entries found in {p.name}. "
            "Check that this is a valid MTK scatter or rawprogram file."
        )

    return entries


def scatter_dir_from_file(scatter_path: str | Path) -> Path:
    """
    Return the directory containing the scatter file.
    Useful for resolving relative image file names stored in the scatter.
    """
    return Path(scatter_path).resolve().parent


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.backend.scatter_parser <scatter.txt>")
        sys.exit(1)
    for e in parse_scatter(sys.argv[1]):
        print(e)
