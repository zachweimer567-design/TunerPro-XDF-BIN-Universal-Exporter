"""
Cross-check: Are the 'all zeros' tables also zero in C6 stock bin?
If yes -> legitimate zero-filled calibration tables (normal)
If no -> address mapping error
"""
import re
import struct
from pathlib import Path

GUIDE_DIR = Path(r'A:\repos\1bmw_ms42_tuning_guides')
BINS_DIR = GUIDE_DIR / 'all_ms42_bins'

# Stock 512KB bins only
CA_BIN = None
for f in BINS_DIR.iterdir():
    if '01100CA' in f.name and 'Original' in f.name and f.suffix == '.bin':
        if f.stat().st_size == 524288:
            CA_BIN = f
            break
if CA_BIN is None:
    # Fallback to 93c9420r stock
    CA_BIN = BINS_DIR / '93c9420r_Ca011CA_Stok.bin'

C6_BIN = BINS_DIR / 'EmulationOnly_Siemens_MS42_0110C6_E46_M52TUB20_EU2_CATV.bin'

ca_data = CA_BIN.read_bytes()
c6_data = C6_BIN.read_bytes()
print(f"CA bin: {CA_BIN.name} ({len(ca_data)} bytes)")
print(f"C6 bin: {C6_BIN.name} ({len(c6_data)} bytes)")

# The zero-address tables from CA XDF (absolute addresses in 512KB bin)
zero_tables = [
    ('id_maf_tab', 0x497AA),
    ('kf_energ_tau_end_st_vk', 0x49A62),
    ('ip_fac_dec_cp__maf_kgh', 0x49AE2),
    ('ip_tps_sp_pvs_tco_1', 0x4AD38),
    ('ip_tps_sp_pvs_tco_2', 0x4AE58),
    ('ip_t_dly_hst', 0x4B62E),
    ('ip_t_dly_neg_2', 0x4B6D6),
    ('ip_t_dly_pos_1', 0x4B756),
    ('ip_isapwm_cor_isa', 0x4BA86),
    ('ip_cppwm_min_cat_var', 0x4C000),
    ('ip_ti_cat_var', 0x4C40A),
    ('id_pat_fcut', 0x4CC72),
    ('id_t_ch_ti', 0x4CC8E),
    ('id_isapwm_slow_pu', 0x4CDEE),
    ('id_ti_cor_cyl_off', 0x4CE1A),
    ('ip_iga_tqr', 0x4ED7A),
    ('ip_iga_tco_ch_at', 0x4F05F),
    ('ip_iga_tco_ch_is', 0x4F09F),
    ('ip_iga_tco_ch_mt', 0x4F0DF),
    ('id_stop_dec_fsd', 0x4F631),
    ('id_deacc_n', 0x4F7DC),
]

# Parse C6 XDF to get C6 addresses for the same tables
c6_xdf = GUIDE_DIR / 'Siemens_MS42_0110C6_ENG_512K_v1.1.xdf'
c6_text = c6_xdf.read_text(errors='ignore')
# Get C6 BASEOFFSET
m = re.search(r'BASEOFFSET offset="(\d+)"', c6_text)
c6_base = int(m.group(1)) if m else 0

# Build C6 address map from XDF (name -> abs address)
c6_addr_map = {}
for m in re.finditer(
    r'<XDFTABLE\s[^>]*>.*?<title>(.*?)</title>.*?'
    r'id="z".*?mmedaddress="(0x[0-9A-Fa-f]+)".*?</XDFTABLE>',
    c6_text, re.S
):
    name = m.group(1)
    addr = int(m.group(2), 16) + c6_base
    c6_addr_map[name] = addr

print(f"\nC6 XDF tables mapped: {len(c6_addr_map)}")
print(f"\nChecking {len(zero_tables)} 'zero' tables:\n")
print(f"{'Table Name':<35} {'CA Addr':>10} {'CA Data':>15} {'C6 Data':>15} {'Verdict'}")
print("-" * 90)

both_zero = 0
ca_only_zero = 0
mismatch = 0

for name, ca_addr in zero_tables:
    # Read 16 bytes at CA address
    ca_chunk = ca_data[ca_addr:ca_addr+16]
    ca_hex = ca_chunk.hex()
    ca_is_zero = all(b == 0 for b in ca_chunk)

    # Find in C6 - try exact name match first, then partial
    c6_addr = c6_addr_map.get(name)
    if c6_addr is None:
        # Try partial match
        for cname, caddr in c6_addr_map.items():
            if name in cname or cname in name:
                c6_addr = caddr
                break

    if c6_addr is not None:
        c6_chunk = c6_data[c6_addr:c6_addr+16]
        c6_hex = c6_chunk.hex()
        c6_is_zero = all(b == 0 for b in c6_chunk)

        if ca_is_zero and c6_is_zero:
            verdict = "BOTH ZERO (normal)"
            both_zero += 1
        elif ca_is_zero and not c6_is_zero:
            verdict = "CA=0, C6 HAS DATA!"
            ca_only_zero += 1
        else:
            verdict = "OK"
    else:
        c6_hex = "NOT FOUND"
        c6_is_zero = None
        if ca_is_zero:
            verdict = "CA=0, C6 N/A"
            mismatch += 1
        else:
            verdict = "OK (no C6 match)"

    print(f"{name:<35} 0x{ca_addr:05X}  {ca_hex[:16]:<15} {str(c6_hex)[:16]:<15} {verdict}")

print(f"\n{'='*60}")
print(f"Both zero (normal):     {both_zero}")
print(f"CA zero, C6 has data:   {ca_only_zero}  <-- ADDRESS ERRORS")
print(f"No C6 match:            {mismatch}")

# Now do the REAL test: key tuning tables with actual decoded values
print(f"\n{'='*70}")
print("KEY TABLE DECODED VALUES")
print(f"{'='*70}")

# These are the critical tuning tables we MUST get right
# Reading from BOTH bins at the XDF-specified addresses
key_checks = [
    # (name, CA_addr, C6_addr, size_bits, count, equation)
    ('RPM axis (load map)', 0x495A8, 0x495A4, 16, 16, 'X/4'),
    ('Load axis (load map)', 0x495CA, 0x495C6, 16, 16, 'X*0.01'),
    ('MAF sensor curve', 0x497AA, 0x497A6, 16, 32, 'X*0.01'),
    ('Ignition basic map row1', 0x4F2B5, 0x4F2B5, 8, 16, 'X*0.75-54'),
    ('Fuel injection base row1', 0x4C82E, 0x4C82E, 16, 8, 'X*0.004'),
    ('IACV cold', 0x4BACA, 0x4BAC6, 16, 8, 'X*0.004'),
    ('IACV warm', 0x4BBBA, 0x4BBB6, 16, 8, 'X*0.004'),
    ('Alpha/n load row1', 0x49E2C, 0x49E28, 16, 8, 'X*0.01'),
    ('Vehicle speed limiter', 0x4842F, 0x4842F, 8, 2, 'X'),
    ('Soft limiter AT (CA)', 0x4F689, 0x4F69E, 8, 3, 'X*25'),
    ('Soft limiter MT (CA)', 0x4F69E, 0x4F689, 8, 3, 'X*25'),
    ('Hard limiter AT', 0x4F698, 0x4F698, 8, 3, 'X*25'),
    ('Hard limiter MT', 0x4F69B, 0x4F69B, 8, 3, 'X*25'),
    ('Lambda feedback', 0x48287, 0x48287, 8, 1, 'X'),
    ('SAP (sec air pump)', 0x4828E, 0x4828E, 8, 1, 'X'),
]

for name, ca_addr, c6_addr, bits, count, eq in key_checks:
    byte_sz = bits // 8
    # MS42 uses LITTLE-ENDIAN for 16-bit values
    fmt = '<H' if byte_sz == 2 else 'B'

    ca_vals = []
    c6_vals = []
    for i in range(count):
        off = i * byte_sz
        if byte_sz == 2:
            ca_v = struct.unpack(fmt, ca_data[ca_addr+off:ca_addr+off+2])[0]
            c6_v = struct.unpack(fmt, c6_data[c6_addr+off:c6_addr+off+2])[0]
        else:
            ca_v = ca_data[ca_addr+off]
            c6_v = c6_data[c6_addr+off]
        # Apply equation
        try:
            ca_scaled = eval(eq.replace('X', str(ca_v)))
            c6_scaled = eval(eq.replace('X', str(c6_v)))
        except:
            ca_scaled = ca_v
            c6_scaled = c6_v
        ca_vals.append(round(ca_scaled, 2))
        c6_vals.append(round(c6_scaled, 2))

    print(f"\n{name}  (CA@0x{ca_addr:05X}  C6@0x{c6_addr:05X})")
    print(f"  CA: {ca_vals}")
    print(f"  C6: {c6_vals}")

    # Check if RPM axis is monotonic
    if 'axis' in name.lower() or 'RPM' in name:
        mono = all(ca_vals[i] <= ca_vals[i+1] for i in range(len(ca_vals)-1))
        print(f"  Monotonic: {'YES' if mono else 'NO - BROKEN!'}")
