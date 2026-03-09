"""
MS42 Address Comparison Tool
------------------------------
Compares table addresses between XML definition and XDF definition files
for each OSID. Supports all MS42 variants.

Usage:
  python _compare_xml_xdf_addresses.py [--osid 0110C6] [--verbose]

Output:
  Per-OSID report showing matched, mismatched, and missing tables.
"""
import argparse
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# =================================================================
# Configuration
# =================================================================
XML_PATH = Path(r"A:\repos\MS42_ECU_Definitions_v0.39.xml")
GUIDE_DIR = Path(r"A:\repos\1bmw_ms42_tuning_guides")
BIN_DIR = GUIDE_DIR / "all_ms42_bins"
BASE_OFFSET = 0x48000

XDF_MAP = {
    "0110AD_512kb": GUIDE_DIR / "MS42_01100AD_ENG_512KB.xdf",
    "0110AD_32kb":  GUIDE_DIR / "MS42_01100AD_ENG_32KB.xdf",
    "0110C6_512kb": GUIDE_DIR / "Siemens_MS42_0110C6_ENG_512K_v1.1.xdf",
    "0110C6_32kb":  GUIDE_DIR / "Siemens_MS42_0110C6_ENG_32K_v1.1.xdf",
    "0110CA_512kb": GUIDE_DIR / "Siemens_MS42_0110CA_ENG_512K_v1.0.xdf",
    "0110CA_32kb":  GUIDE_DIR / "Siemens_MS42_0110CA_ENG_32K_v1.0.xdf",
    "011025_512kb": GUIDE_DIR / "Siemens_MS42_011025_ENG_512K_v1.0.xdf",
    "011025_32kb":  GUIDE_DIR / "Siemens_MS42_011025_ENG_32K_v1.0.xdf",
}


# =================================================================
# XML Parser
# =================================================================
def parse_xml_tables(xml_path):
    """Returns {rom_key: {table_name: abs_address}}."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    roms = root.findall("rom")

    base_tables = {}
    for t in roms[0].findall("table"):
        name = (t.get("name") or "").strip()
        ttype = (t.get("type") or "").strip()
        cat = (t.get("category") or "").strip()
        base_tables[name] = {"type": ttype, "category": cat}

    rom_tables = {}
    for rom in roms[1:]:
        romid = rom.find("romid")
        if romid is None:
            continue
        osid = (romid.findtext("internalidstring") or "").strip()
        fs = (romid.findtext("filesize") or "").strip()
        key = f"{osid}_{fs}".lower().replace(" ", "")

        tables = {}
        for t in rom.findall("table"):
            tname = (t.get("name") or "").strip()
            addr = (t.get("storageaddress") or "").strip()
            if tname and addr:
                try:
                    tables[tname] = int(addr, 16)
                except ValueError:
                    pass
        rom_tables[key] = tables

    return rom_tables, base_tables


# =================================================================
# XDF Parser
# =================================================================
def parse_xdf_addresses(xdf_path):
    """Returns {abs_address: [(type, title), ...]}."""
    text = xdf_path.read_text(encoding="utf-8", errors="ignore")

    # Get base offset
    bm = re.search(r'BASEOFFSET\s+offset="(\d+)"', text)
    base = int(bm.group(1)) if bm else 0

    entries = {}

    for tag, pattern in [
        ("const", r'<XDFCONSTANT[^>]*>.*?<title>(.*?)</title>.*?'
                  r'<EMBEDDEDDATA[^>]*mmedaddress="(0x[0-9A-Fa-f]+)"'),
        ("table", r'<XDFTABLE[^>]*>.*?<title>(.*?)</title>.*?'
                  r'<EMBEDDEDDATA[^>]*mmedaddress="(0x[0-9A-Fa-f]+)"'),
    ]:
        for m in re.finditer(pattern, text, re.S):
            title = m.group(1).strip()
            try:
                raw = int(m.group(2).strip(), 16)
                addr = raw + base
                entries.setdefault(addr, []).append((tag, title))
            except ValueError:
                pass

    return entries, base


# =================================================================
# BIN Hash Scanner
# =================================================================
def scan_bins(bin_dir):
    """Returns {md5: {path, size, osid}}."""
    if not bin_dir.exists():
        return {}
    results = {}
    for f in sorted(bin_dir.glob("*.bin")):
        data = f.read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        osid = "unknown"
        # Try to find OSID string at known locations
        for offset in [0x48000 + 0x7F00, 0x48000 + 0x7E00, 0x0]:
            if offset + 10 < len(data):
                chunk = data[offset:offset + 20]
                for pat in [b"0110C6", b"0110CA", b"0110AD", b"011025",
                            b"0110AB", b"0110SA"]:
                    if pat in chunk:
                        osid = pat.decode()
                        break
                if osid != "unknown":
                    break
        # Fallback: scan the full calibration area header
        if osid == "unknown" and len(data) >= 0x50000:
            cal_area = data[0x48000:0x48100]
            for pat in [b"0110C6", b"0110CA", b"0110AD", b"011025",
                        b"0110AB", b"0110SA"]:
                if pat in cal_area:
                    osid = pat.decode()
                    break
        results[f.name] = {"md5": md5, "size": len(data), "osid": osid}
    return results


# =================================================================
# Main Comparison
# =================================================================
def compare(osid_filter=None, verbose=False):
    print("=" * 70)
    print("MS42 XML ↔ XDF Address Comparison Report")
    print("=" * 70)

    rom_tables, base_tables = parse_xml_tables(XML_PATH)

    total_matched = 0
    total_xml_only = 0
    total_xdf_only = 0

    for rom_key, xml_tables in sorted(rom_tables.items()):
        osid = rom_key.split("_")[0].upper()
        if osid_filter and osid.upper() != osid_filter.upper():
            continue

        xdf_key = f"{osid}_{rom_key.split('_')[1]}"
        xdf_path = XDF_MAP.get(xdf_key)
        if not xdf_path or not xdf_path.exists():
            print(f"\n--- {rom_key} --- SKIPPED (no XDF at {xdf_key})")
            continue

        xdf_addrs, xdf_base = parse_xdf_addresses(xdf_path)

        print(f"\n--- {rom_key} (XDF: {xdf_path.name}, base=0x{xdf_base:X}) ---")
        print(f"  XML tables: {len(xml_tables)}")
        print(f"  XDF unique addresses: {len(xdf_addrs)}")

        matched = []
        xml_only = []
        for name, addr in sorted(xml_tables.items()):
            if addr in xdf_addrs:
                xdf_names = "; ".join(f"{t}:{n}" for t, n in xdf_addrs[addr])
                matched.append((name, addr, xdf_names))
            else:
                xml_only.append((name, addr))

        # Find XDF addresses not in XML
        xml_addr_set = set(xml_tables.values())
        xdf_only = [(addr, entries) for addr, entries
                     in sorted(xdf_addrs.items())
                     if addr not in xml_addr_set]

        total_matched += len(matched)
        total_xml_only += len(xml_only)
        total_xdf_only += len(xdf_only)

        print(f"  MATCHED: {len(matched)}")
        print(f"  XML-only (no XDF at that address): {len(xml_only)}")
        print(f"  XDF-only (no XML at that address): {len(xdf_only)}")

        if verbose:
            if matched:
                print(f"\n  {'XML Name':<45} {'Addr':<10} XDF Name(s)")
                print(f"  {'-'*45} {'-'*10} {'-'*40}")
                for name, addr, xdf_names in matched[:20]:
                    print(f"  {name:<45} 0x{addr:05X}  {xdf_names}")
                if len(matched) > 20:
                    print(f"  ... and {len(matched) - 20} more")

            if xml_only:
                print(f"\n  XML-only tables:")
                for name, addr in xml_only[:10]:
                    print(f"    {name:<45} 0x{addr:05X}")
                if len(xml_only) > 10:
                    print(f"    ... and {len(xml_only) - 10} more")

    print(f"\n{'='*70}")
    print(f"TOTALS: {total_matched} matched, {total_xml_only} XML-only, "
          f"{total_xdf_only} XDF-only")
    print(f"{'='*70}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare MS42 XML and XDF table addresses")
    parser.add_argument("--osid", help="Filter to specific OSID (e.g., 0110C6)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show individual table matches")
    args = parser.parse_args()
    compare(args.osid, args.verbose)
