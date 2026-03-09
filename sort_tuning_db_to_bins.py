"""
sort_tuning_db_to_bins.py
Scans the BMW tuning database folder, identifies MS42/MS43/MS45 ECU files,
renames them (dots -> underscores, append .bin), and copies them to:
  - all_ms42_bins/
  - all_ms43_bins/
  - all_ms45_bins/

ECU identification logic:
  MS42 (Siemens MS42) - E46 M52TU / E38 728i / E39 M52TU:
    Software: 01100AD, 01100AB, 01100C6, 01100CA, 011025
    Hardware: 5WK9020, 5WK90329, 5WK9037 (on E46/E38/E39 only)
    Explicit: "MS42" in name
    Excludes: M3, MSS53, MSS54

  MS43 (Siemens MS43) - E46 M54 / E39 M54 / E53 X5:
    Software: 430037, 430055, 430056, 430064, 430066, 430069
    Hardware: 5WK9000x, 5WK9001x (5WK90007-5WK90019)
    Explicit: "MS43" in name

  MS45 (Siemens MS45.0/MS45.1) - E60/E61 M54 / E83 X3 / E85 Z4:
    Hardware: 5WK93014, 5WK93016, 5WK93018, 5WK93020, 5WK93022
    Must be ~1MB files (not 2.5MB MSV70)
    Excludes: 5WK980xx (MSV70/N52), diesel, M5, V10

Skips: .ols files, diesel-only files, M3/M5/M6 files, files > 1.5MB for MS45
"""

import os
import re
import shutil
from pathlib import Path

# === CONFIGURATION ===
SRC_DIR = r"A:\TUNED FILE DATABASE [STAGE1 - STAGE 2 - STAGE 3]\Tuning_DB_BIN\BMW"
BASE_DIR = r"A:\1bmw_ms42_tuning_guides"

DST_MS42 = os.path.join(BASE_DIR, "all_ms42_bins")
DST_MS43 = os.path.join(BASE_DIR, "all_ms43_bins")
DST_MS45 = os.path.join(BASE_DIR, "all_ms45_bins")

# Ensure destination dirs exist
for d in [DST_MS42, DST_MS43, DST_MS45]:
    os.makedirs(d, exist_ok=True)

# === PATTERNS ===

# MS42 software numbers (in filename)
MS42_SW = re.compile(r'01100AD|01100AB|01100C6|01100CA|011025', re.IGNORECASE)
# MS42 explicit mention
MS42_EXPLICIT = re.compile(r'\bMS42\b', re.IGNORECASE)
# MS42 hardware on E46/E38/E39 (5WK9020, 5WK90329, 5WK9037 - NOT on E60+)
MS42_HW_E46 = re.compile(r'5WK9020|5WK90329|5WK9037', re.IGNORECASE)
MS42_CHASSIS = re.compile(r'E46|E38|E39|E36', re.IGNORECASE)

# MS43 software numbers
MS43_SW = re.compile(r'430037|430055|430056|430064|430066|430069', re.IGNORECASE)
# MS43 explicit mention
MS43_EXPLICIT = re.compile(r'\bMS43\b|MS430\b', re.IGNORECASE)

# MS45 hardware (5WK930xx series)
MS45_HW = re.compile(r'5WK9301[0-9]|5WK9302[0-9]', re.IGNORECASE)
# MS45 explicit
MS45_EXPLICIT = re.compile(r'\bMS45\b', re.IGNORECASE)

# Exclusions
EXCLUDE_PATTERNS = re.compile(
    r'\.ols$|\.tun_pdg|M3_|_M3_|M5_|_M5_|M6_|_M6_|MSS53|MSS54|V10|V8|'
    r'Diesel|diesel|Turbodiesel|Turbo-Diesel|turbodiesel|EDC16|DPF|EGR|'
    r'Limited_Mappack|SuperMappack',
    re.IGNORECASE
)

# For MS42/MS43 we ALSO exclude M3
EXCLUDE_M3 = re.compile(r'_M3[_\s]|_M3$|^BMW_E46_M3|^BMW_E36_M3|^BMW_E46___M3', re.IGNORECASE)

# MSV70/N52 indicator - these are NOT MS45
MSV70_HW = re.compile(r'5WK980[0-9][0-9]', re.IGNORECASE)


def clean_name(original_name):
    """
    Replace all dots with underscores, then append .bin
    Example: BMW_E46_328i_1999...Stage1 -> BMW_E46_328i_1999..._Stage1.bin
    Also clean up +++ to _plus
    """
    # Replace dots with underscores
    cleaned = original_name.replace('.', '_')
    # Clean up +++ sequences
    cleaned = re.sub(r'\+{2,}', '_plus', cleaned)
    cleaned = cleaned.replace('+', '_')
    # Clean up multiple consecutive underscores
    cleaned = re.sub(r'_{2,}', '_', cleaned)
    # Remove trailing underscores before adding .bin
    cleaned = cleaned.rstrip('_')
    # Add .bin extension
    cleaned = cleaned + '.bin'
    return cleaned


def classify_file(name):
    """
    Returns 'ms42', 'ms43', 'ms45', or None
    """
    upper = name.upper()
    
    # Skip excluded patterns (diesel, M3, M5, M6, .ols, etc.)
    if EXCLUDE_PATTERNS.search(name):
        return None
    if EXCLUDE_M3.search(name):
        return None
    
    # === MS45 check first (most specific) ===
    if MS45_HW.search(name) or MS45_EXPLICIT.search(name):
        # Confirm it's NOT MSV70/N52
        if MSV70_HW.search(name):
            return None
        return 'ms45'
    
    # === MS43 check ===
    if MS43_SW.search(name) or MS43_EXPLICIT.search(name):
        return 'ms43'
    
    # === MS42 check ===
    if MS42_SW.search(name) or MS42_EXPLICIT.search(name):
        return 'ms42'
    
    # MS42 hardware but only on E46/E38/E39/E36 chassis
    if MS42_HW_E46.search(name) and MS42_CHASSIS.search(name):
        # Make sure it doesn't also have MS43 software numbers
        if MS43_SW.search(name):
            return 'ms43'
        return 'ms42'
    
    return None


def main():
    if not os.path.isdir(SRC_DIR):
        print(f"ERROR: Source directory not found: {SRC_DIR}")
        return

    # Get all files
    all_files = []
    try:
        all_files = os.listdir(SRC_DIR)
    except Exception as e:
        print(f"ERROR listing directory: {e}")
        return

    print(f"Total files in BMW tuning DB: {len(all_files)}")
    
    counts = {'ms42': 0, 'ms43': 0, 'ms45': 0, 'skipped': 0, 'errors': 0}
    results = {'ms42': [], 'ms43': [], 'ms45': []}
    
    for fname in sorted(all_files):
        ecu = classify_file(fname)
        if ecu is None:
            counts['skipped'] += 1
            continue
        
        src_path = os.path.join(SRC_DIR, fname)
        
        # Check file size sanity
        try:
            fsize = os.path.getsize(src_path)
        except:
            counts['errors'] += 1
            continue
        
        # MS42 should be ~32KB or ~512KB
        # MS43 should be ~64KB, ~128KB, or ~512KB
        # MS45 should be ~1MB (1048576)
        # Skip anything over 1.5MB for MS45 (that's MSV70)    
        if ecu == 'ms45' and fsize > 1572864:  # 1.5MB
            counts['skipped'] += 1
            continue
        
        # Skip very small files (< 16KB - probably corrupt or not a real bin)
        if fsize < 16384:
            counts['skipped'] += 1
            continue
        
        new_name = clean_name(fname)
        
        if ecu == 'ms42':
            dst_path = os.path.join(DST_MS42, new_name)
        elif ecu == 'ms43':
            dst_path = os.path.join(DST_MS43, new_name)
        elif ecu == 'ms45':
            dst_path = os.path.join(DST_MS45, new_name)
        
        try:
            shutil.copy2(src_path, dst_path)
            counts[ecu] += 1
            results[ecu].append(f"  {fsize:>10,} bytes  {new_name}")
        except Exception as e:
            print(f"  ERROR copying {fname}: {e}")
            counts['errors'] += 1
    
    # Print results
    print(f"\n{'='*80}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*80}")
    print(f"MS42 files copied to all_ms42_bins: {counts['ms42']}")
    print(f"MS43 files copied to all_ms43_bins: {counts['ms43']}")
    print(f"MS45 files copied to all_ms45_bins: {counts['ms45']}")
    print(f"Skipped (diesel/M3/M5/M6/other):   {counts['skipped']}")
    print(f"Errors:                             {counts['errors']}")
    
    for ecu in ['ms42', 'ms43', 'ms45']:
        if results[ecu]:
            print(f"\n{'='*80}")
            print(f"--- {ecu.upper()} FILES ({len(results[ecu])}) ---")
            print(f"{'='*80}")
            for line in results[ecu]:
                print(line)

    # Also check what's already in the destination folders (pre-existing files)
    for label, dst in [('MS42', DST_MS42), ('MS43', DST_MS43), ('MS45', DST_MS45)]:
        existing = [f for f in os.listdir(dst) if os.path.isfile(os.path.join(dst, f))]
        print(f"\n{label} folder total files now: {len(existing)}")


if __name__ == '__main__':
    main()
