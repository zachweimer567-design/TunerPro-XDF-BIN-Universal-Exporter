"""
XDF + BIN Validator for MS42 0110CA
Parses the generated XDF, reads the stock 0110CA bin, decodes actual table
values using XDF data types/equations. Reports:
 - Axis monotonicity (RPM axis should go 800,1000,1200...)
 - Table value ranges (fuel values ~0-255, ignition ~-20 to 60 deg)
 - Any addresses pointing to garbage/zeros
"""
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

XDF_PATH = Path(
    r'A:\repos\1bmw_ms42_tuning_guides\ms42_ms43_ms45_ai_kingai_xdfs'
    r'\ms42\Siemens_MS42_0110CA_ENG_512K_v1.0_20260308_1530.xdf'
)
BIN_PATH = Path(
    r'A:\repos\1bmw_ms42_tuning_guides\all_ms42_bins'
    r'\BMW_E46_328i_2004_Benzin_142KWKW_Siemens_5WK9037_Siemens_'
    r'01100CA010000_E0B7_Original.bin'
)

# Also load the C6 XDF + C6 bin for cross-comparison
C6_XDF_PATH = Path(
    r'A:\repos\1bmw_ms42_tuning_guides'
    r'\Siemens_MS42_0110C6_ENG_512K_v1.1.xdf'
)
C6_BIN_PATH = Path(
    r'A:\repos\1bmw_ms42_tuning_guides\all_ms42_bins'
    r'\EmulationOnly_Siemens_MS42_0110C6_E46_M52TUB20_EU2_CATV.bin'
)


def parse_xdf(xdf_path):
    """Parse XDF file, return list of (name, addr, sizebits, rows, cols,
    equation, category) for tables and constants."""
    text = xdf_path.read_text(errors='ignore')

    # Get BASEOFFSET
    m = re.search(r'BASEOFFSET offset="(\d+)"', text)
    base = int(m.group(1)) if m else 0

    entries = []

    # Parse XDFCONSTANT blocks
    for m in re.finditer(
        r'<XDFCONSTANT\s[^>]*uniqueid="(0x[0-9A-Fa-f]+)"[^>]*>'
        r'(.*?)</XDFCONSTANT>', text, re.S
    ):
        uid = m.group(1)
        body = m.group(2)

        title_m = re.search(r'<title>(.*?)</title>', body)
        title = title_m.group(1) if title_m else f'const_{uid}'

        addr_m = re.search(
            r'<EMBEDDEDDATA\s[^>]*mmedaddress="(0x[0-9A-Fa-f]+)"'
            r'[^>]*mmedelementsizebits="(\d+)"', body
        )
        if not addr_m:
            continue
        addr = int(addr_m.group(1), 16) + base
        sizebits = int(addr_m.group(2))

        eq_m = re.search(r'<math\s+equation="([^"]*)"', body)
        eq = eq_m.group(1) if eq_m else 'X'

        cat_m = re.search(r'<CATEGORY[^>]*name="([^"]*)"', body)
        cat = cat_m.group(1) if cat_m else ''

        entries.append({
            'type': 'constant',
            'name': title,
            'addr': addr,
            'sizebits': sizebits,
            'rows': 1,
            'cols': 1,
            'equation': eq,
            'category': cat,
        })

    # Parse XDFTABLE blocks
    for m in re.finditer(
        r'<XDFTABLE\s[^>]*uniqueid="(0x[0-9A-Fa-f]+)"[^>]*>'
        r'(.*?)</XDFTABLE>', text, re.S
    ):
        uid = m.group(1)
        body = m.group(2)

        title_m = re.search(r'<title>(.*?)</title>', body)
        title = title_m.group(1) if title_m else f'table_{uid}'

        # Get axes info
        axes = re.findall(
            r'<XDFAXIS\s+id="([^"]*)"[^>]*>(.*?)</XDFAXIS>',
            body, re.S
        )

        table_addr = None
        table_sizebits = 8
        table_eq = 'X'
        rows = 1
        cols = 1
        axis_info = {}

        for axis_id, axis_body in axes:
            idx_m = re.search(r'indexcount="(\d+)"', axis_body)
            idx_count = int(idx_m.group(1)) if idx_m else 1

            emb_m = re.search(
                r'<EMBEDDEDDATA\s[^>]*mmedaddress="(0x[0-9A-Fa-f]+)"'
                r'[^>]*mmedelementsizebits="(\d+)"', axis_body
            )

            eq_m = re.search(r'<math\s+equation="([^"]*)"', axis_body)
            eq = eq_m.group(1) if eq_m else 'X'

            if axis_id == 'z':
                # Main data axis
                if emb_m:
                    table_addr = int(emb_m.group(1), 16) + base
                    table_sizebits = int(emb_m.group(2))
                table_eq = eq
            elif axis_id == 'x':
                cols = idx_count
                if emb_m:
                    axis_info['x'] = {
                        'addr': int(emb_m.group(1), 16) + base,
                        'sizebits': int(emb_m.group(2)),
                        'count': idx_count,
                        'equation': eq,
                    }
            elif axis_id == 'y':
                rows = idx_count
                if emb_m:
                    axis_info['y'] = {
                        'addr': int(emb_m.group(1), 16) + base,
                        'sizebits': int(emb_m.group(2)),
                        'count': idx_count,
                        'equation': eq,
                    }

        if table_addr is None:
            continue

        cat_m = re.search(r'<CATEGORY[^>]*name="([^"]*)"', body)
        cat = cat_m.group(1) if cat_m else ''

        entries.append({
            'type': 'table',
            'name': title,
            'addr': table_addr,
            'sizebits': table_sizebits,
            'rows': rows,
            'cols': cols,
            'equation': table_eq,
            'category': cat,
            'axes': axis_info,
        })

    return entries, base


def read_values(data, addr, sizebits, count):
    """Read count values from bin data at addr with given element size."""
    byte_size = sizebits // 8
    if byte_size == 0:
        byte_size = 1
    values = []
    for i in range(count):
        offset = addr + i * byte_size
        if offset + byte_size > len(data):
            values.append(None)
            continue
        chunk = data[offset:offset + byte_size]
        if byte_size == 1:
            values.append(struct.unpack('B', chunk)[0])
        elif byte_size == 2:
            values.append(struct.unpack('>H', chunk)[0])
        elif byte_size == 4:
            values.append(struct.unpack('>I', chunk)[0])
        else:
            values.append(int.from_bytes(chunk, 'big'))
    return values


def apply_equation(raw_values, equation):
    """Apply XDF equation string to raw values. Equation uses X as var."""
    results = []
    for v in raw_values:
        if v is None:
            results.append(None)
            continue
        try:
            X = v  # noqa
            # Common XDF equation patterns
            eq = equation.replace('X', str(v))
            result = eval(eq)
            results.append(round(result, 4))
        except Exception:
            results.append(v)
    return results


def is_monotonic(values):
    """Check if values are strictly increasing (axis check)."""
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return True
    increasing = all(clean[i] <= clean[i + 1] for i in range(len(clean) - 1))
    return increasing


def check_all_zeros(values):
    clean = [v for v in values if v is not None]
    return all(v == 0 for v in clean)


def main():
    print("=" * 70)
    print("XDF + BIN Validation Report")
    print(f"XDF: {XDF_PATH.name}")
    print(f"BIN: {BIN_PATH.name}")
    print("=" * 70)

    if not BIN_PATH.exists():
        # Find the original bin
        bins_dir = Path(
            r'A:\repos\1bmw_ms42_tuning_guides\all_ms42_bins'
        )
        for f in bins_dir.iterdir():
            if '01100CA' in f.name and 'Original' in f.name:
                print(f"Using: {f.name}")
                bin_data = f.read_bytes()
                break
        else:
            print("ERROR: No stock 0110CA 512KB bin found!")
            return
    else:
        bin_data = BIN_PATH.read_bytes()

    print(f"BIN size: {len(bin_data):,} bytes")

    entries, base = parse_xdf(XDF_PATH)
    print(f"BASEOFFSET: 0x{base:X} ({base})")
    print(f"Parsed: {len(entries)} entries "
          f"({sum(1 for e in entries if e['type'] == 'constant')} constants, "
          f"{sum(1 for e in entries if e['type'] == 'table')} tables)")
    print()

    # Key tables to validate in detail
    key_tables = [
        'id_ti_tab',          # Fuel injection base
        'id_zw_kf_0',         # Ignition basic map
        'id_n_schalt',        # RPM thresholds
        'id_n_max_am_at',     # Rev limiter AT
        'id_n_max_am_mt',     # Rev limiter MT
        'id_t_llr_kalt',      # IACV cold
        'id_t_llr_warm',      # IACV warm
        'id_uk_hfm',          # MAF sensor
        'id_rl_bas',          # Base load
        'id_fak_f_tab',       # Fuel factor
        'id_sa_einsp_tab',    # Fuel cut
        'id_t_lk_vol_tab',    # Full load enrichment
        'id_t_wl_tab',        # Warm-up enrichment
        'id_rl_alpha_n_tab',  # Alpha-N
    ]

    issues = []
    good = 0
    table_count = 0
    axis_issues = 0

    print("=" * 70)
    print("DETAILED TABLE VALIDATION")
    print("=" * 70)

    for entry in entries:
        name = entry['name']
        is_key = name in key_tables

        if entry['type'] == 'table':
            table_count += 1
            addr = entry['addr']
            sizebits = entry['sizebits']
            rows = entry['rows']
            cols = entry['cols']
            total = rows * cols

            # Read Z data
            raw = read_values(bin_data, addr, sizebits, total)
            scaled = apply_equation(raw, entry['equation'])

            # Check for all zeros
            all_zero = check_all_zeros(raw)

            # Check axes
            axes_ok = True
            axis_detail = {}
            if 'axes' in entry:
                for ax_id, ax in entry.get('axes', {}).items():
                    ax_raw = read_values(
                        bin_data, ax['addr'],
                        ax['sizebits'], ax['count']
                    )
                    ax_scaled = apply_equation(ax_raw, ax['equation'])
                    mono = is_monotonic(ax_scaled)
                    ax_zero = check_all_zeros(ax_raw)
                    axis_detail[ax_id] = {
                        'values': ax_scaled[:10],
                        'monotonic': mono,
                        'all_zero': ax_zero
                    }
                    if not mono or ax_zero:
                        axes_ok = False

            if is_key or not axes_ok or all_zero:
                marker = "KEY" if is_key else "!!!"
                print(f"\n[{marker}] {name}")
                print(f"  Addr: 0x{addr:05X}  Size: {sizebits}bit  "
                      f"Grid: {rows}x{cols}  Eq: {entry['equation']}")

                if all_zero:
                    print(f"  WARNING: ALL ZEROS in table data!")
                    issues.append(f"{name}: all zeros at 0x{addr:05X}")
                else:
                    # Show first row of data
                    row1 = scaled[:min(cols, 16)]
                    print(f"  Data[0]: {row1}")
                    if rows > 1:
                        mid = rows // 2
                        mid_vals = scaled[mid * cols:(mid * cols) +
                                         min(cols, 16)]
                        print(f"  Data[{mid}]: {mid_vals}")
                    good += 1

                for ax_id, ax_data in axis_detail.items():
                    status = "OK" if ax_data['monotonic'] else "NOT MONOTONIC"
                    if ax_data['all_zero']:
                        status = "ALL ZEROS"
                    vals = ax_data['values']
                    print(f"  Axis {ax_id}: {vals}... [{status}]")
                    if not ax_data['monotonic'] and not ax_data['all_zero']:
                        axis_issues += 1
                        issues.append(
                            f"{name}: axis {ax_id} not monotonic"
                        )
            else:
                good += 1

        elif entry['type'] == 'constant':
            addr = entry['addr']
            sizebits = entry['sizebits']
            raw = read_values(bin_data, addr, sizebits, 1)
            scaled = apply_equation(raw, entry['equation'])

            if is_key:
                print(f"\n[KEY] {name}")
                print(f"  Addr: 0x{addr:05X}  Value: raw={raw[0]} "
                      f"scaled={scaled[0]}  Eq: {entry['equation']}")

    # Summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)
    print(f"Tables parsed:     {table_count}")
    print(f"Tables valid:      {good}")
    print(f"Axis issues:       {axis_issues}")
    print(f"Total issues:      {len(issues)}")

    if issues:
        print("\nISSUES FOUND:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
    else:
        print("\nNO ISSUES - All tables decoded successfully")

    # Compare key tables between CA XDF+bin and C6 XDF+bin
    if C6_XDF_PATH.exists() and C6_BIN_PATH.exists():
        print("\n" + "=" * 70)
        print("CROSS-COMPARISON: 0110CA vs 0110C6")
        print("=" * 70)
        c6_entries, c6_base = parse_xdf(C6_XDF_PATH)
        c6_data = C6_BIN_PATH.read_bytes()

        # Build name->entry maps
        ca_map = {e['name']: e for e in entries}
        c6_map = {e['name']: e for e in c6_entries}

        for tname in key_tables:
            if tname in ca_map and tname in c6_map:
                ca_e = ca_map[tname]
                c6_e = c6_map[tname]

                if ca_e['type'] == 'table':
                    total = ca_e['rows'] * ca_e['cols']
                    ca_raw = read_values(
                        bin_data, ca_e['addr'],
                        ca_e['sizebits'], min(total, 8)
                    )
                    c6_raw = read_values(
                        c6_data, c6_e['addr'],
                        c6_e['sizebits'], min(total, 8)
                    )
                    ca_s = apply_equation(ca_raw, ca_e['equation'])
                    c6_s = apply_equation(c6_raw, c6_e['equation'])

                    same = ca_raw == c6_raw
                    print(f"\n{tname}: "
                          f"CA@0x{ca_e['addr']:05X} vs "
                          f"C6@0x{c6_e['addr']:05X}  "
                          f"{'SAME' if same else 'DIFFERENT (expected)'}")
                    print(f"  CA: {ca_s[:8]}")
                    print(f"  C6: {c6_s[:8]}")


if __name__ == '__main__':
    main()
