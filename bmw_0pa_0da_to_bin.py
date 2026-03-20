#!/usr/bin/env python3
"""
BMW SP-Daten 0PA/0DA to .BIN Converter
========================================
Converts BMW INPA / WinKFP SP-Daten flash files (.0PA, .0DA) into flat
binary .BIN files that can be flashed with:
  - MS4X Flasher
  - MS45 Quick Flash
  - JMGarageFlasher
  - Galletto 1260
  - WinOLS / TunerPro (for editing)

Supports:
  - Siemens MS42 (MDS42) — 512 KB full / 32 KB or 64 KB calibration (OSID-dependent)
  - Siemens MS43 (MDS43) — 512 KB full / 64 KB calibration
  - Siemens MS45.0 (MDS450) — 1024 KB full / 64-128 KB calibration
  - Siemens MS45.1 (MDS451) — 1024 KB full
  - Bosch ME7.2 (ME72)
  - Bosch GS8.60.x EGS (GD86xx)
  - Any BMW Austausch-Datei with Intel HEX payload

Per-OSID calibration sizes:
  MS42 0110AD / 011025 / 0110AB → 32 KB cal at 0x78000
  MS42 0110C6 / 0110SA          → 64 KB cal at 0x70000
  MS42 0110CA                   → 32 KB cal at 0x48000
  MS43 430037..430070           → 64 KB cal at 0x70000
  MS45 0044560                  → 128 KB cal at 0xE0000

Handles Siemens type 0x10 block-checksum records (proprietary Intel HEX
extension used in BMW SP-Daten files).

TODO (from user notes):
  - Partial, full, and MPC flash segment handling
  - Quality-of-life improvements per ECU / firmware OSID
  - Research what else is possible and useful

File format:
  .0PA = "Austausch-Datei Programm" (code/program flash partition)
  .0DA = "Austausch-Datei Daten"    (calibration/data flash partition)
  Both contain a text header with BMW metadata followed by Intel HEX records.

Usage:
  # Convert a single file
  python bmw_0pa_0da_to_bin.py path/to/file.0DA

  # Convert all 0PA/0DA in a folder
  python bmw_0pa_0da_to_bin.py path/to/folder/

  # Combine 0PA + 0DA into a single full .bin (e.g. program + data)
  python bmw_0pa_0da_to_bin.py --combine path/to/file.0PA path/to/file.0DA

  # Scan C:\\EC-APPS for a specific ECU group and convert all
  python bmw_0pa_0da_to_bin.py --scan MDS43

  # Output to a specific directory
  python bmw_0pa_0da_to_bin.py path/to/file.0DA -o output_folder/

  # Show info only (no conversion)
  python bmw_0pa_0da_to_bin.py --info path/to/file.0DA

Adapted from:  scan_gs8604_egs.py, find_austausch_files.py parsing logic
Author:        KingAI / Copilot
"""

import os
import sys
import re
import argparse
import hashlib
import string
import platform
from pathlib import Path
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VERSION = "1.0.0"

# Known ECU flash sizes (total flash memory)
ECU_FLASH_SIZES = {
    "MDS42":  512 * 1024,   # MS42 = 512 KB
    "MDS43":  512 * 1024,   # MS43 = 512 KB
    "MDS450": 1024 * 1024,  # MS45.0 = 1 MB
    "MDS451": 1024 * 1024,  # MS45.1 = 1 MB
    "ME72":   1024 * 1024,  # ME7.2 = 1 MB (varies)
    "GD8600": 256 * 1024,   # EGS GS8.60.0
    "GD8604": 256 * 1024,   # EGS GS8.60.4
}

# Calibration section sizes and offsets for known ECU + OSID combos
# Key = (ecu_type, osid) or (ecu_type, None) as fallback
ECU_CAL_INFO = {
    # MS42 — depends on OSID
    ("MDS42", "0110AD"): {"cal_offset": 0x78000, "cal_size": 32 * 1024},   # 32 KB at 0x78000
    ("MDS42", "011025"): {"cal_offset": 0x78000, "cal_size": 32 * 1024},   # 32 KB at 0x78000
    ("MDS42", "0110AB"): {"cal_offset": 0x78000, "cal_size": 32 * 1024},   # 32 KB at 0x78000
    ("MDS42", "0110C6"): {"cal_offset": 0x70000, "cal_size": 64 * 1024},   # 64 KB at 0x70000
    ("MDS42", "0110CA"): {"cal_offset": 0x48000, "cal_size": 32 * 1024},   # 32 KB at 0x48000
    ("MDS42", "0110SA"): {"cal_offset": 0x70000, "cal_size": 64 * 1024},   # 64 KB at 0x70000 (assumed)
    ("MDS42", None):     {"cal_offset": None,    "cal_size": None},         # auto-detect from HEX
    # MS43 — OSID sets (most are 64 KB at 0x70000)
    ("MDS43", "430037"): {"cal_offset": 0x70000, "cal_size": 64 * 1024},
    ("MDS43", "430055"): {"cal_offset": 0x70000, "cal_size": 64 * 1024},
    ("MDS43", "430056"): {"cal_offset": 0x70000, "cal_size": 64 * 1024},
    ("MDS43", "430064"): {"cal_offset": 0x70000, "cal_size": 64 * 1024},
    ("MDS43", "430066"): {"cal_offset": 0x70000, "cal_size": 64 * 1024},
    ("MDS43", "430069"): {"cal_offset": 0x70000, "cal_size": 64 * 1024},
    ("MDS43", "430070"): {"cal_offset": 0x70000, "cal_size": 64 * 1024},
    ("MDS43", None):     {"cal_offset": 0x70000, "cal_size": 64 * 1024},   # default
    # MS45.0 — 128 KB at 0x40000  (CPU 0x02040000-0x0205FFFF → flash 0x40000)
    ("MDS450", None):    {"cal_offset": 0x40000, "cal_size": 128 * 1024},
    # MS45.1 — 128 KB at 0x40000
    ("MDS451", None):    {"cal_offset": 0x40000, "cal_size": 128 * 1024},
}

# CPU-to-flash address translation for each ECU.
# Each entry is a list of (hex_addr_start, hex_addr_end, flash_offset) tuples.
# When a HEX record address falls in [hex_addr_start, hex_addr_end],
# it maps to flash offset: (addr - hex_addr_start) + flash_offset.
# Checked in order; first match wins.  None = identity (no translation).
ECU_ADDR_MAP = {
    "MDS42": None,  # Flash-relative addresses, no translation needed
    "MDS43": [
        # C167 maps flash at 0x080000.  0PA uses CPU addresses (0x80000+).
        # 0DA uses flash-relative addresses (0x00000+).
        # Both patterns need to work → two ranges:
        (0x080000, 0x0FFFFF, 0x000000),  # CPU addr → flash offset 0x00000+
        (0x000000, 0x07FFFF, 0x000000),  # Flash-relative → identity
    ],
    "MDS450": [
        # TriCore dual-bank mapping (type 04 selects bank, type 02 selects sector):
        #   Bank 0: 0x00000000+ → flash 0x00000+ (program sectors 0-6)
        #   Bank 1: 0x02000000+ → flash 0x00000+ (program sectors + cal/data)
        # The 0x020xxxxx addresses map identity (offset by 0x02000000), covering
        # sectors that overlap with bank 0 (0x60000+) and extend through cal.
        (0x02000000, 0x020FFFFF, 0x000000),   # Data/cal bank → identity
        (0x00000000, 0x000FFFFF, 0x000000),   # Program bank → identity
    ],
    "MDS451": [
        (0x02000000, 0x020FFFFF, 0x000000),
        (0x00000000, 0x000FFFFF, 0x000000),
    ],
}

# Austausch-Datei markers
MARKER_DATEN    = b"Austausch-Datei    Daten"
MARKER_PROGRAMM = b"Austausch-Datei    Programm"
MARKER_BROAD    = b"Austausch-Datei"

# Flash file extensions
FLASH_EXTS = {".0da", ".0pa", ".0di", ".0pi"}

# Directories to skip when scanning
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".vs", ".idea", "dist", "build", "__MACOSX",
    "System Volume Information", "$Recycle.Bin", "Recovery",
    "Windows", "ProgramData",
}

MAX_FILE_SIZE = 64 * 1024 * 1024  # 64 MB


# ---------------------------------------------------------------------------
# Safe string handling
# ---------------------------------------------------------------------------
def _decode_safe(data: bytes) -> str:
    """Decode bytes to string, trying utf-8 then latin-1."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def _safe_print(s: str) -> str:
    """Strip non-ASCII chars so print() never chokes on cp1252 stdout."""
    return s.encode("ascii", errors="replace").decode("ascii")


def _extract_osid(header: Dict[str, Any]) -> Optional[str]:
    """
    Extract OSID from the header's ZL_Referenz or referenz_line.
    
    Common patterns:
      ZL_Referenz: 11101102C600       → OSID 0110C6
      ZL_Referenz: 11101100CA010000   → OSID 0110CA
      ZL_Referenz: 111430533703       → OSID 430037 (MS43)
      $REFERENZ 11101102C600 C        → same
    
    For MS42 the reference encodes the OSID reversed/embedded.  We look for
    known OSID patterns in both the reference and the file-path/filename.
    """
    known_osids = [
        # MS42 OSIDs
        "0110AD", "0110AB", "011025", "0110C6", "0110CA", "0110SA",
        # MS43 OSIDs  
        "430037", "430055", "430056", "430064", "430066", "430069", "430070",
        "43X001",
        # MS45 OSIDs
        "0044560",
    ]
    
    # Check referenz_line first 
    ref = header.get("referenz_line", "") or ""
    ref_val = header.get("fields", {}).get("ZL_Referenz", "") or ""
    ref_val2 = header.get("fields", {}).get("ZL_REFERENZ", "") or ""
    
    candidates = [ref, ref_val, ref_val2]
    
    for text in candidates:
        text_upper = text.upper().replace(" ", "")
        for osid in known_osids:
            if osid.upper() in text_upper:
                return osid
    
    # Also check the Freigabenummer field (sometimes has OSID encoded)
    freigabe = header.get("fields", {}).get("ZL_Freigabenummer", "") or ""
    if freigabe:
        freigabe_upper = freigabe.upper().replace(" ", "").replace(":", "")
        for osid in known_osids:
            if osid.upper() in freigabe_upper:
                return osid
    
    return None


def _translate_addr(addr: int, addr_map: Optional[list]) -> Optional[int]:
    """
    Translate a HEX record address to a flash offset using the ECU address map.
    Returns the flash offset, or None if the address doesn't match any range.
    If addr_map is None, returns addr unchanged (identity mapping).
    """
    if addr_map is None:
        return addr
    for hex_start, hex_end, flash_offset in addr_map:
        if hex_start <= addr <= hex_end:
            return (addr - hex_start) + flash_offset
    return None  # Address not in any mapped range


def _align_cal_region(min_addr: int, max_addr: int) -> Tuple[int, int]:
    """
    Given raw HEX min/max addresses, compute an aligned calibration region.
    Aligns base down to 0x8000 (32 KB sector) boundary, size up to 
    nearest power-of-2 that is >= 8 KB.
    """
    SECTOR = 0x8000  # 32 KB sector alignment
    base = (min_addr // SECTOR) * SECTOR
    end = max_addr + 1
    raw_size = end - base
    
    # Round up to nearest power of 2 that is >= the raw size and >= 8KB
    size = max(8 * 1024, raw_size)
    # Find next power of 2
    p2 = 1
    while p2 < size:
        p2 <<= 1
    
    return base, p2


# ---------------------------------------------------------------------------
# Austausch-Datei header parser
# ---------------------------------------------------------------------------
def parse_austausch_header(data: bytes) -> Dict[str, Any]:
    """
    Find and parse the BMW DAMOS Austausch-Datei header in binary data.
    Returns dict with:
      - file_type: "Programm" or "Daten" or "Unknown"
      - fields: OrderedDict of header key-value pairs
      - referenz_line: the $REFERENZ line if found
      - hex_data_offset: byte offset where Intel HEX data begins
      - marker_offset: where the Austausch marker was found
    """
    result = {
        "file_type": "Unknown",
        "fields": OrderedDict(),
        "referenz_line": None,
        "hex_data_offset": None,
        "marker_offset": None,
    }

    # Find marker
    marker_offset = data.find(MARKER_PROGRAMM)
    if marker_offset >= 0:
        result["file_type"] = "Programm"
    else:
        marker_offset = data.find(MARKER_DATEN)
        if marker_offset >= 0:
            result["file_type"] = "Daten"
        else:
            marker_offset = data.find(MARKER_BROAD)
            if marker_offset >= 0:
                # Determine type from context
                context = _decode_safe(data[marker_offset:marker_offset + 80])
                if "Programm" in context:
                    result["file_type"] = "Programm"
                elif "Daten" in context:
                    result["file_type"] = "Daten"

    if marker_offset < 0:
        # No Austausch header — might be raw Intel HEX or S-record
        # Look for Intel HEX start directly
        hex_start = _find_intel_hex_start(data)
        if hex_start is not None:
            result["hex_data_offset"] = hex_start
        return result

    result["marker_offset"] = marker_offset

    # Parse backwards to find header start (;=== line)
    search_start = max(0, marker_offset - 500)
    header_start = data.rfind(b";===", search_start, marker_offset)
    if header_start == -1:
        header_start = marker_offset

    # Read up to 8KB of header
    header_chunk = data[header_start : header_start + 8192]
    text = _decode_safe(header_chunk)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # Parse header fields
    for line in lines:
        stripped = line.strip()

        # ;;Key: Value format
        m = re.match(r"^;;([A-Za-z0-9_\-]+):\s*(.*)", stripped)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if val and val != "---":
                result["fields"][key] = val

        # $REFERENZ marks end of header
        if stripped.upper().startswith("$REFERENZ"):
            result["referenz_line"] = stripped
            # HEX data starts on the next line after $REFERENZ
            ref_offset_in_text = text.index(stripped)
            # Find the newline after $REFERENZ
            after_ref = text[ref_offset_in_text + len(stripped):]
            newline_pos = 0
            for ch in after_ref:
                newline_pos += 1
                if ch == '\n':
                    break
            result["hex_data_offset"] = header_start + ref_offset_in_text + len(stripped) + newline_pos
            break

    # If no $REFERENZ found, look for first Intel HEX line after header
    if result["hex_data_offset"] is None:
        hex_start = _find_intel_hex_start(data, start_from=marker_offset)
        if hex_start is not None:
            result["hex_data_offset"] = hex_start

    return result


def _find_intel_hex_start(data: bytes, start_from: int = 0) -> Optional[int]:
    """Find the byte offset of the first Intel HEX record in data."""
    # Search for lines starting with ':' followed by hex digits
    pos = start_from
    while pos < len(data) - 11:
        # Find next ':'
        colon = data.find(b":", pos)
        if colon == -1:
            break

        # Check if this looks like a valid Intel HEX record
        # :LLAAAATT[DD...]CC format — at least 11 chars (:BBAAAATTCC)
        try:
            # Check that following bytes are hex ASCII
            after = data[colon + 1 : colon + 11]
            if len(after) == 10 and all(
                c in b"0123456789ABCDEFabcdef" for c in after
            ):
                # Verify it's at the start of a line (preceded by \n, \r, or BOF)
                if colon == 0 or data[colon - 1] in (0x0A, 0x0D):
                    return colon
        except IndexError:
            pass

        pos = colon + 1

    return None


# ---------------------------------------------------------------------------
# Intel HEX to binary converter (the core logic)
# ---------------------------------------------------------------------------
def intel_hex_to_binary(
    data: bytes,
    start_offset: int = 0,
    fill_byte: int = 0xFF,
    force_size: Optional[int] = None,
    force_base: Optional[int] = None,
    addr_map: Optional[list] = None,
) -> Tuple[Optional[bytearray], Dict[str, Any]]:
    """
    Parse Intel HEX records from data starting at start_offset.
    Returns (binary_data, info_dict).

    binary_data is a bytearray starting at min_addr (or force_base),
    with gaps filled with fill_byte (0xFF = erased flash).

    addr_map: optional list of (hex_start, hex_end, flash_offset) tuples
    for CPU-to-flash address translation (see ECU_ADDR_MAP).

    info_dict contains:
      - min_addr, max_addr: address range found in HEX records (after translation)
      - data_bytes: total number of data bytes decoded
      - record_count: total HEX records processed
      - eof_found: whether an EOF record was encountered
      - base_addr: the base address (min_addr or force_base)
      - unmapped_records: records with addresses outside all mapped ranges
      - warnings: list of warning messages
    """
    info = {
        "min_addr": None,
        "max_addr": None,
        "data_bytes": 0,
        "record_count": 0,
        "eof_found": False,
        "base_addr": 0,
        "unmapped_records": 0,
        "warnings": [],
    }

    # Collect all data records: list of (absolute_addr, data_bytes)
    records = []
    # BMW SP-Daten files use BOTH type 02 (Extended Segment Address) and
    # type 04 (Extended Linear Address) records together.  Type 04 selects
    # the flash bank (e.g. 0x00000000 = program, 0x02000000 = cal/data)
    # and type 02 selects the 64 KB sector within that bank.  The full
    # address is:  extended_linear + extended_segment + record_address.
    extended_linear  = 0   # Upper 16 bits from type 04 records
    extended_segment = 0   # Segment base from type 02 records

    text = _decode_safe(data[start_offset:])
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    for line_num, line in enumerate(lines, 1):
        line = line.strip()

        # Skip empty lines and comment/header lines
        if not line:
            continue
        if not line.startswith(":"):
            # If we've already seen records and hit non-hex, might be EOF region
            if info["record_count"] > 0:
                continue
            else:
                continue

        # Validate minimum length
        if len(line) < 11:
            info["warnings"].append(f"Line {line_num}: too short: {line[:20]}")
            continue

        try:
            # Parse Intel HEX fields
            byte_count = int(line[1:3], 16)
            address    = int(line[3:7], 16)
            rec_type   = int(line[7:9], 16)

            # Validate line has enough hex chars for data + checksum
            expected_len = 1 + 2 + 4 + 2 + byte_count * 2 + 2  # : LL AAAA TT DD..DD CC
            if len(line) < expected_len:
                info["warnings"].append(f"Line {line_num}: truncated record")
                continue

            # Extract data bytes
            data_hex = line[9 : 9 + byte_count * 2]
            try:
                record_data = bytes.fromhex(data_hex)
            except ValueError:
                info["warnings"].append(f"Line {line_num}: invalid hex in data field")
                continue

            # Verify checksum
            checksum_byte = int(line[9 + byte_count * 2 : 9 + byte_count * 2 + 2], 16)
            calc_sum = byte_count + (address >> 8) + (address & 0xFF) + rec_type
            for b in record_data:
                calc_sum += b
            calc_sum = (~calc_sum + 1) & 0xFF
            if calc_sum != checksum_byte:
                info["warnings"].append(
                    f"Line {line_num}: checksum mismatch "
                    f"(calc=0x{calc_sum:02X}, file=0x{checksum_byte:02X})"
                )
                # Continue anyway — some SP-Daten files have minor checksum issues

            info["record_count"] += 1

            if rec_type == 0x00:
                # Data record — apply address translation if configured
                full_addr = extended_linear + extended_segment + address
                flash_addr = _translate_addr(full_addr, addr_map)
                if flash_addr is None:
                    info["unmapped_records"] += 1
                    continue
                records.append((flash_addr, record_data))
                info["data_bytes"] += byte_count

                if info["min_addr"] is None or flash_addr < info["min_addr"]:
                    info["min_addr"] = flash_addr
                end_addr = flash_addr + byte_count - 1
                if info["max_addr"] is None or end_addr > info["max_addr"]:
                    info["max_addr"] = end_addr

            elif rec_type == 0x01:
                # End Of File
                info["eof_found"] = True
                break

            elif rec_type == 0x02:
                # Extended Segment Address — sets sector within current bank.
                # Combined with type 04 (bank select) for full address.
                if byte_count >= 2:
                    seg = int(data_hex[:4], 16)
                    extended_segment = seg << 4

            elif rec_type == 0x04:
                # Extended Linear Address — selects flash bank.
                # NOTE: In BMW SP-Daten files the type 02 record (segment)
                # appears BEFORE the type 04 record (bank), so we must NOT
                # reset extended_segment here — it was already set for the
                # upcoming data records.
                if byte_count >= 2:
                    upper = int(data_hex[:4], 16)
                    extended_linear = upper << 16

            elif rec_type == 0x03:
                # Start Segment Address — skip, not needed for bin
                pass

            elif rec_type == 0x05:
                # Start Linear Address — skip, not needed for bin
                pass

            elif rec_type == 0x10:
                # Siemens/BMW proprietary block checksum record.
                # If byte_count > 0, it may carry the last data bytes of a
                # flash sector (the record at the sector boundary).  Treat
                # those bytes as regular data so they end up in the output.
                if byte_count > 0:
                    full_addr = extended_linear + extended_segment + address
                    flash_addr = _translate_addr(full_addr, addr_map)
                    if flash_addr is None:
                        info["unmapped_records"] += 1
                        continue
                    records.append((flash_addr, record_data))
                    info["data_bytes"] += byte_count
                    if info["min_addr"] is None or flash_addr < info["min_addr"]:
                        info["min_addr"] = flash_addr
                    end_addr = flash_addr + byte_count - 1
                    if info["max_addr"] is None or end_addr > info["max_addr"]:
                        info["max_addr"] = end_addr
                # byte_count == 0 → pure checksum marker, nothing to store

            else:
                info["warnings"].append(
                    f"Line {line_num}: unknown record type 0x{rec_type:02X}"
                )

        except (ValueError, IndexError) as e:
            info["warnings"].append(f"Line {line_num}: parse error: {e}")
            continue

    # Bail if no data
    if not records or info["min_addr"] is None:
        info["warnings"].append("No valid Intel HEX data records found")
        return None, info

    # Determine base address and total size
    base_addr = force_base if force_base is not None else info["min_addr"]
    end_addr = info["max_addr"]

    if force_size is not None:
        total_size = force_size
    else:
        total_size = end_addr - base_addr + 1

    # Sanity check  
    if total_size > 16 * 1024 * 1024:
        info["warnings"].append(f"Computed size {total_size} bytes seems too large, capping at 16MB")
        total_size = 16 * 1024 * 1024
    if total_size <= 0:
        info["warnings"].append(f"Invalid size calculation: base=0x{base_addr:X}, end=0x{end_addr:X}")
        return None, info

    info["base_addr"] = base_addr

    # Build the binary buffer
    binary = bytearray([fill_byte]) * total_size

    out_of_range = 0
    for addr, rec_data in records:
        offset = addr - base_addr
        if offset < 0 or offset + len(rec_data) > total_size:
            out_of_range += 1
            continue
        binary[offset : offset + len(rec_data)] = rec_data

    if out_of_range > 0:
        info["warnings"].append(
            f"{out_of_range} records fell outside the output buffer range"
        )

    if info["unmapped_records"] > 0:
        info["warnings"].append(
            f"{info['unmapped_records']} records had addresses outside all mapped ranges"
        )

    return binary, info


# ---------------------------------------------------------------------------
# ECU type detection
# ---------------------------------------------------------------------------
def detect_ecu_type(filepath: str, header: Dict[str, Any]) -> Optional[str]:
    """
    Try to detect ECU type from file path and header fields.
    Returns ECU group string like 'MDS42', 'MDS43', 'MDS450', etc.
    """
    path_upper = filepath.upper()
    
    # Check path components
    for ecu in ["MDS451", "MDS450", "MDS43", "MDS42", "ME72", "GD8604", "GD8600"]:
        if ecu in path_upper:
            return ecu
    
    # Check alternate naming in path
    if "MS45.1" in path_upper or "MS451" in path_upper:
        return "MDS451"
    if "MS45.0" in path_upper or "MS450" in path_upper:
        return "MDS450"
    if "MS45" in path_upper:
        return "MDS450"  # default to 45.0
    if "MS43" in path_upper:
        return "MDS43"
    if "MS42" in path_upper:
        return "MDS42"
    if "ME7" in path_upper:
        return "ME72"
    if "GS8604" in path_upper or "GD8604" in path_upper:
        return "GD8604"
    if "GS8600" in path_upper or "GD8600" in path_upper:
        return "GD8600"

    # Check header fields
    fields = header.get("fields", {})
    for val in fields.values():
        val_upper = val.upper()
        if "MDS451" in val_upper:
            return "MDS451"
        if "MDS450" in val_upper or "MDS45" in val_upper:
            return "MDS450"
        if "MDS43" in val_upper:
            return "MDS43"
        if "MDS42" in val_upper:
            return "MDS42"

    return None


# ---------------------------------------------------------------------------
# Known SP-Daten locations
# ---------------------------------------------------------------------------
def get_spdaten_paths() -> List[str]:
    """Return standard BMW Standard Tools / SP-Daten paths."""
    paths = []
    known_roots = [
        r"C:\EC-APPS",
        r"C:\NFS\data",
        r"C:\NFS-Backup",
        r"C:\EDIABAS\Ecu",
        r"A:\BMW Standard Tools",
        r"A:\bmw-advanced-tools",
        r"A:\bmw-advanced-tools-master",
        r"A:\BMW_ECU_Downloads",
    ]
    for p in known_roots:
        if os.path.isdir(p):
            paths.append(p)
    return paths


def find_flash_files(
    search_paths: List[str],
    ecu_filter: Optional[str] = None,
    max_depth: int = 6,
) -> List[str]:
    """
    Find all .0DA/.0PA files under the given paths.
    If ecu_filter is set, only return files under folders matching that ECU group.
    """
    found = []
    ecu_upper = ecu_filter.upper() if ecu_filter else None

    for root_path in search_paths:
        for dirpath, dirnames, filenames in os.walk(root_path):
            # Depth check
            depth = dirpath[len(root_path):].count(os.sep)
            if depth > max_depth:
                dirnames.clear()
                continue

            # Skip known junk dirs
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

            # ECU filter on directory name
            if ecu_upper and ecu_upper not in dirpath.upper():
                continue

            for f in filenames:
                ext = os.path.splitext(f)[1].lower()
                if ext in FLASH_EXTS:
                    fp = os.path.join(dirpath, f)
                    if os.path.getsize(fp) <= MAX_FILE_SIZE:
                        found.append(fp)

    return sorted(found)


# ---------------------------------------------------------------------------
# Single file conversion
# ---------------------------------------------------------------------------
def convert_file(
    filepath: str,
    output_dir: Optional[str] = None,
    info_only: bool = False,
    force_ecu: Optional[str] = None,
    fill_byte: int = 0xFF,
) -> Dict[str, Any]:
    """
    Convert a single .0PA/.0DA file to .bin.

    Returns dict with conversion results and metadata.
    """
    result = {
        "input": filepath,
        "output": None,
        "success": False,
        "ecu_type": None,
        "file_type": None,
        "hex_info": {},
        "header_fields": {},
        "warnings": [],
        "error": None,
    }

    if not os.path.isfile(filepath):
        result["error"] = f"File not found: {filepath}"
        return result

    file_size = os.path.getsize(filepath)
    if file_size > MAX_FILE_SIZE:
        result["error"] = f"File too large: {file_size} bytes"
        return result

    print(f"\n{'='*70}")
    print(f"  INPUT:  {_safe_print(filepath)}")
    print(f"  SIZE:   {file_size:,} bytes")

    # Read file
    try:
        with open(filepath, "rb") as f:
            data = f.read()
    except (OSError, PermissionError) as e:
        result["error"] = str(e)
        print(f"  ERROR:  {e}")
        return result

    # Parse Austausch-Datei header
    header = parse_austausch_header(data)
    result["file_type"] = header["file_type"]
    result["header_fields"] = dict(header["fields"])

    print(f"  TYPE:   Austausch-Datei {header['file_type']}")

    if header["fields"]:
        print(f"  HEADER FIELDS:")
        for k, v in list(header["fields"].items())[:8]:
            print(f"    {k}: {_safe_print(v)}")
    
    if header["referenz_line"]:
        print(f"  REF:    {_safe_print(header['referenz_line'][:80])}")

    # Detect ECU type
    ecu_type = force_ecu or detect_ecu_type(filepath, header)
    result["ecu_type"] = ecu_type
    if ecu_type:
        print(f"  ECU:    {ecu_type}")

    # Find HEX data start
    hex_offset = header.get("hex_data_offset")
    if hex_offset is None:
        hex_offset = _find_intel_hex_start(data)

    if hex_offset is None:
        result["error"] = "No Intel HEX data found in file"
        result["warnings"].append("Could not locate Intel HEX records")
        print(f"  ERROR:  No Intel HEX data found")
        return result

    print(f"  HEX:    Intel HEX data starts at offset 0x{hex_offset:X}")

    # Extract OSID from header for per-OSID cal sizing
    osid = _extract_osid(header)
    if osid:
        print(f"  OSID:   {osid}")

    # Determine forced size based on ECU type and file type
    force_size = None
    force_base = None
    if ecu_type:
        total_flash = ECU_FLASH_SIZES.get(ecu_type)

        if header["file_type"] == "Daten":
            # Look up cal info by (ecu_type, osid), fall back to (ecu_type, None)
            cal_info = ECU_CAL_INFO.get((ecu_type, osid)) or ECU_CAL_INFO.get((ecu_type, None))
            if cal_info and cal_info.get("cal_offset") is not None:
                force_base = cal_info["cal_offset"]
                force_size = cal_info["cal_size"]
                print(f"  MODE:   Calibration partition  "
                      f"(0x{force_base:06X} - 0x{force_base + force_size - 1:06X}, "
                      f"{force_size // 1024} KB)")
            else:
                # Auto-detect: do a quick pre-parse to find address range,
                # then align base down and size up to sector boundaries
                print(f"  MODE:   Calibration partition  (auto-detect from HEX addresses)")
                # force_base/force_size stay None; we'll align after parsing
        elif header["file_type"] == "Programm" and total_flash:
            # Program partition — output from base 0 for the full flash range
            force_base = 0
            force_size = total_flash
            print(f"  MODE:   Program partition  "
                  f"(0x{force_base:06X} - 0x{force_base + force_size - 1:06X}, "
                  f"{force_size // 1024} KB)")

    # Look up CPU-to-flash address translation for this ECU
    addr_map = ECU_ADDR_MAP.get(ecu_type) if ecu_type else None

    # Convert Intel HEX → binary
    binary, hex_info = intel_hex_to_binary(
        data,
        start_offset=hex_offset,
        fill_byte=fill_byte,
        force_size=force_size,
        force_base=force_base,
        addr_map=addr_map,
    )
    result["hex_info"] = hex_info

    # Auto-detect alignment for Daten files when cal_offset was unknown
    if (binary is not None
        and header["file_type"] == "Daten"
        and force_base is None
        and hex_info["min_addr"] is not None):
        aligned_base, aligned_size = _align_cal_region(
            hex_info["min_addr"], hex_info["max_addr"]
        )
        # Re-parse with the aligned base/size
        binary, hex_info = intel_hex_to_binary(
            data,
            start_offset=hex_offset,
            fill_byte=fill_byte,
            force_size=aligned_size,
            force_base=aligned_base,
            addr_map=addr_map,
        )
        result["hex_info"] = hex_info
        print(f"  ALIGN:  Auto-detected cal region "
              f"0x{aligned_base:06X} - 0x{aligned_base + aligned_size - 1:06X} "
              f"({aligned_size // 1024} KB)")

    if hex_info["min_addr"] is not None:
        print(f"  ADDR:   0x{hex_info['min_addr']:08X} - 0x{hex_info['max_addr']:08X}")
        print(f"  DATA:   {hex_info['data_bytes']:,} bytes in {hex_info['record_count']} records")
        print(f"  EOF:    {'Yes' if hex_info['eof_found'] else 'No'}")

    for w in hex_info.get("warnings", [])[:5]:
        print(f"  WARN:   {w}")
        result["warnings"].append(w)

    if binary is None:
        result["error"] = "Failed to decode Intel HEX data"
        print(f"  ERROR:  Failed to decode Intel HEX data")
        return result

    print(f"  BIN:    {len(binary):,} bytes ({len(binary) // 1024} KB)")

    # Compute hash
    sha = hashlib.sha256(binary).hexdigest()[:16]
    print(f"  SHA256: {sha}...")

    if info_only:
        result["success"] = True
        result["output"] = "(info mode — no output written)"
        print(f"  (info only — skipping write)")
        return result

    # Determine output filename and path
    basename = Path(filepath).stem
    ext = Path(filepath).suffix.lower()
    type_tag = "cal" if header["file_type"] == "Daten" else "prg"
    ecu_tag = ecu_type if ecu_type else "unknown"
    size_kb = len(binary) // 1024

    out_name = f"{basename}_{ecu_tag}_{type_tag}_{size_kb}KB.bin"
    
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, out_name)
    else:
        out_path = os.path.join(os.path.dirname(filepath), out_name)

    # Avoid overwriting
    if os.path.exists(out_path):
        # Append hash to make unique
        out_name = f"{basename}_{ecu_tag}_{type_tag}_{size_kb}KB_{sha[:8]}.bin"
        out_path = os.path.join(
            output_dir if output_dir else os.path.dirname(filepath), out_name
        )

    # Write
    try:
        with open(out_path, "wb") as f:
            f.write(binary)
        result["output"] = out_path
        result["success"] = True
        print(f"  OUTPUT: {_safe_print(out_path)}")
        print(f"  STATUS: OK")
    except (OSError, PermissionError) as e:
        result["error"] = str(e)
        print(f"  ERROR:  Write failed: {e}")

    return result


# ---------------------------------------------------------------------------
# Combine 0PA + 0DA into a single full flash binary
# ---------------------------------------------------------------------------
def combine_pa_da(
    pa_path: str,
    da_path: str,
    output_dir: Optional[str] = None,
    force_ecu: Optional[str] = None,
    fill_byte: int = 0xFF,
) -> Dict[str, Any]:
    """
    Combine a .0PA (program) and .0DA (data/calibration) into a single
    full-flash .bin file.
    """
    result = {
        "pa_input": pa_path,
        "da_input": da_path,
        "output": None,
        "success": False,
        "ecu_type": None,
        "error": None,
        "warnings": [],
    }

    print(f"\n{'='*70}")
    print(f"  COMBINE MODE")
    print(f"  PROG:   {_safe_print(pa_path)}")
    print(f"  DATA:   {_safe_print(da_path)}")

    # Read and parse both files
    for path, label in [(pa_path, "0PA"), (da_path, "0DA")]:
        if not os.path.isfile(path):
            result["error"] = f"{label} file not found: {path}"
            print(f"  ERROR:  {result['error']}")
            return result

    # Detect ECU type from either file
    with open(pa_path, "rb") as f:
        pa_data = f.read()
    with open(da_path, "rb") as f:
        da_data = f.read()

    pa_header = parse_austausch_header(pa_data)
    da_header = parse_austausch_header(da_data)

    ecu_type = force_ecu or detect_ecu_type(pa_path, pa_header) or detect_ecu_type(da_path, da_header)
    result["ecu_type"] = ecu_type

    if not ecu_type:
        result["error"] = "Cannot determine ECU type — use --ecu to specify"
        print(f"  ERROR:  {result['error']}")
        return result

    total_flash = ECU_FLASH_SIZES.get(ecu_type, 512 * 1024)
    print(f"  ECU:    {ecu_type} ({total_flash // 1024} KB)")

    # Address translation for this ECU
    addr_map = ECU_ADDR_MAP.get(ecu_type)

    # Start with an empty flash image (all 0xFF = erased)
    combined = bytearray([fill_byte]) * total_flash

    # Parse and overlay PROGRAM data (base = 0x0)
    pa_hex_offset = pa_header.get("hex_data_offset") or _find_intel_hex_start(pa_data, 0)
    if pa_hex_offset is not None:
        pa_bin, pa_info = intel_hex_to_binary(
            pa_data, start_offset=pa_hex_offset, fill_byte=fill_byte,
            addr_map=addr_map
        )
        if pa_bin is not None:
            base = pa_info["base_addr"]
            end = base + len(pa_bin)
            if end > total_flash:
                end = total_flash
                pa_bin = pa_bin[:total_flash - base]
            if base < total_flash:
                combined[base:end] = pa_bin[:end - base]
                print(f"  PROG:   {pa_info['data_bytes']:,} bytes "
                      f"@ 0x{pa_info['min_addr']:06X}-0x{pa_info['max_addr']:06X}")
            for w in pa_info.get("warnings", [])[:3]:
                result["warnings"].append(f"0PA: {w}")
        else:
            result["warnings"].append("0PA: No hex data decoded")
    else:
        result["warnings"].append("0PA: No Intel HEX data found")

    # Parse and overlay DATA/CALIBRATION 
    da_hex_offset = da_header.get("hex_data_offset") or _find_intel_hex_start(da_data, 0)
    if da_hex_offset is not None:
        da_bin, da_info = intel_hex_to_binary(
            da_data, start_offset=da_hex_offset, fill_byte=fill_byte,
            addr_map=addr_map
        )
        if da_bin is not None:
            base = da_info["base_addr"]
            end = base + len(da_bin)
            if end > total_flash:
                end = total_flash
                da_bin = da_bin[:total_flash - base]
            if base < total_flash:
                combined[base:end] = da_bin[:end - base]
                print(f"  DATA:   {da_info['data_bytes']:,} bytes "
                      f"@ 0x{da_info['min_addr']:06X}-0x{da_info['max_addr']:06X}")
            for w in da_info.get("warnings", [])[:3]:
                result["warnings"].append(f"0DA: {w}")
        else:
            result["warnings"].append("0DA: No hex data decoded")
    else:
        result["warnings"].append("0DA: No Intel HEX data found")

    # Generate output filename
    basename = Path(pa_path).stem
    size_kb = len(combined) // 1024
    out_name = f"{basename}_{ecu_type}_full_{size_kb}KB.bin"

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, out_name)
    else:
        out_path = os.path.join(os.path.dirname(pa_path), out_name)

    if os.path.exists(out_path):
        sha = hashlib.sha256(combined).hexdigest()[:8]
        out_name = f"{basename}_{ecu_type}_full_{size_kb}KB_{sha}.bin"
        out_path = os.path.join(
            output_dir if output_dir else os.path.dirname(pa_path), out_name
        )

    try:
        with open(out_path, "wb") as f:
            f.write(combined)
        result["output"] = out_path
        result["success"] = True
        print(f"  OUTPUT: {_safe_print(out_path)}")
        print(f"  SIZE:   {len(combined):,} bytes ({size_kb} KB)")
        print(f"  STATUS: OK — combined full flash image")
    except (OSError, PermissionError) as e:
        result["error"] = str(e)
        print(f"  ERROR:  Write failed: {e}")

    for w in result["warnings"]:
        print(f"  WARN:   {w}")

    return result


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------
def process_path(
    path: str,
    output_dir: Optional[str] = None,
    info_only: bool = False,
    force_ecu: Optional[str] = None,
    recursive: bool = True,
) -> List[Dict[str, Any]]:
    """
    Process a file or folder. If folder, recursively find all 0PA/0DA files.
    """
    results = []

    if os.path.isfile(path):
        r = convert_file(path, output_dir=output_dir, info_only=info_only, force_ecu=force_ecu)
        results.append(r)
    elif os.path.isdir(path):
        files = find_flash_files([path], max_depth=6 if recursive else 0)
        if not files:
            print(f"No .0DA/.0PA files found in: {path}")
        for fp in files:
            r = convert_file(fp, output_dir=output_dir, info_only=info_only, force_ecu=force_ecu)
            results.append(r)
    else:
        print(f"Path not found: {path}")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="BMW SP-Daten 0PA/0DA to .BIN Converter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s  C:\\EC-APPS\\NFS\\data\\MDS43\\
  %(prog)s  7506537.0DA
  %(prog)s  --combine 7506537.0PA 7506537.0DA 
  %(prog)s  --scan MDS43
  %(prog)s  --info 7506537.0DA
  %(prog)s  7506537.0DA -o converted_bins/
  %(prog)s  --scan MDS42 --info

Supported ECU types:
  MDS42  = Siemens MS42  (512 KB)   E46 323i/325i M52TU
  MDS43  = Siemens MS43  (512 KB)   E46 325i/330i M54
  MDS450 = Siemens MS45.0 (1024 KB) E46 330i M54 (late)
  MDS451 = Siemens MS45.1 (1024 KB) E46 M3 S54
  ME72   = Bosch ME7.2   (1024 KB)  X5 E53 M62
  GD8604 = Bosch GS8.60.4 (256 KB)  EGS 5HP24/5HP19

Flash tool compatibility:
  MS4X Flasher      — partial (64 KB cal) or full (512/1024 KB)
  MS45 Quick Flash   — full 1 MB
  JMGarageFlasher    — full 512 KB (bootmode)
  Galletto 1260      — partial 64 KB cal (normal mode)
  WinOLS / TunerPro  — any size for editing
""",
    )
    parser.add_argument("input", nargs="*", help="Input .0DA/.0PA file(s) or folder(s)")
    parser.add_argument("-o", "--output", help="Output directory for converted .bin files")
    parser.add_argument("--info", action="store_true", help="Show file info only, don't write .bin")
    parser.add_argument("--combine", action="store_true",
                        help="Combine two files (0PA + 0DA) into single full-flash .bin")
    parser.add_argument("--scan", metavar="ECU",
                        help="Scan standard SP-Daten paths for ECU group (e.g. MDS43, MDS42)")
    parser.add_argument("--ecu", help="Force ECU type (MDS42, MDS43, MDS450, MDS451, ME72, GD8604)")
    parser.add_argument("--fill", type=lambda x: int(x, 0), default=0xFF,
                        help="Fill byte for gaps (default: 0xFF = erased flash)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    args = parser.parse_args()

    print(f"BMW SP-Daten 0PA/0DA to .BIN Converter v{VERSION}")
    print(f"{'='*70}")

    all_results = []

    # --scan mode: find and convert all files for an ECU group
    if args.scan:
        sp_paths = get_spdaten_paths()
        print(f"Scanning {len(sp_paths)} SP-Daten locations for {args.scan}...")
        files = find_flash_files(sp_paths, ecu_filter=args.scan)
        print(f"Found {len(files)} flash file(s)")
        for fp in files:
            r = convert_file(fp, output_dir=args.output, info_only=args.info, force_ecu=args.ecu)
            all_results.append(r)

    # --combine mode: merge 0PA + 0DA
    elif args.combine:
        if len(args.input) < 2:
            print("ERROR: --combine requires exactly 2 input files (0PA and 0DA)")
            sys.exit(1)
        
        # Figure out which is PA and which is DA
        pa_file = da_file = None
        for f in args.input[:2]:
            ext = os.path.splitext(f)[1].lower()
            if ext == ".0pa":
                pa_file = f
            elif ext == ".0da":
                da_file = f
            elif pa_file is None:
                pa_file = f  # First unrecognized → treat as PA
            else:
                da_file = f  # Second → treat as DA

        if pa_file and da_file:
            r = combine_pa_da(pa_file, da_file, output_dir=args.output, force_ecu=args.ecu)
            all_results.append(r)
        else:
            print("ERROR: Could not identify PA and DA files")
            sys.exit(1)

    # Normal mode: convert file(s) or folder(s)
    elif args.input:
        for inp in args.input:
            results = process_path(
                inp, output_dir=args.output, info_only=args.info, force_ecu=args.ecu
            )
            all_results.extend(results)
    else:
        parser.print_help()
        sys.exit(0)

    # Summary
    print(f"\n{'='*70}")
    print(f"  SUMMARY")
    print(f"{'='*70}")
    total = len(all_results)
    ok = sum(1 for r in all_results if r.get("success"))
    fail = total - ok
    print(f"  Total:     {total}")
    print(f"  Success:   {ok}")
    print(f"  Failed:    {fail}")

    if fail > 0:
        print(f"\n  Failed files:")
        for r in all_results:
            if not r.get("success"):
                inp = r.get("input") or r.get("pa_input", "?")
                err = r.get("error", "unknown error")
                print(f"    {_safe_print(inp)}: {err}")

    if ok > 0:
        print(f"\n  Converted files:")
        for r in all_results:
            if r.get("success") and r.get("output"):
                print(f"    {_safe_print(r['output'])}")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
