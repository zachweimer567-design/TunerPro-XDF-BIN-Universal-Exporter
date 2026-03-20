#!/usr/bin/env python3
"""Quick scan of ms42/ms43/ms45 folders to find files that don't belong."""
import os, re, sys, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SCAN_DIRS = {
    "all_ms42_bins": r"A:\1bmw_ms42_tuning_guides\all_ms42_bins",
    "all_ms43_bins": r"A:\1bmw_ms42_tuning_guides\all_ms43_bins",
    "all_ms45_bins": r"A:\1bmw_ms42_tuning_guides\all_ms45_bins",
    "checksum_files": r"A:\1bmw_ms42_tuning_guides\checksum_files",
    "gs8604_egs_work": r"A:\1bmw_ms42_tuning_guides\gs8604_egs_work",
    "ms42_damos": r"A:\1bmw_ms42_tuning_guides\ms42_damos",
    "ms42_outputs_and_bins_xdfs": r"A:\1bmw_ms42_tuning_guides\ms42_outputs_and_bins_xdfs",
    "ms43_damos": r"A:\1bmw_ms42_tuning_guides\ms43_damos",
    "ms43_outputs_and_bins_xdfs": r"A:\1bmw_ms42_tuning_guides\ms43_outputs_and_bins_xdfs",
    "ms45_combo_output": r"A:\1bmw_ms42_tuning_guides\ms45_combo_output",
    "ms45_damos": r"A:\1bmw_ms42_tuning_guides\ms45_damos",
    "ms45_work": r"A:\1bmw_ms42_tuning_guides\ms45_work",
}

# Cal ID patterns in binary data
MS42_PAT = re.compile(rb'(ca0110[A-Z0-9]{2})', re.IGNORECASE)  
MS43_PAT = re.compile(rb'(ca4300[0-9]{2})', re.IGNORECASE)
MS45_PAT = re.compile(rb'(ca45[0-9]{2})', re.IGNORECASE)
# Broader binary string searches - scan only first 8KB header area for speed
MS42_STR = re.compile(rb'0110[A-Z][A-Z0-9]', re.IGNORECASE)
MS43_STR = re.compile(rb'4300[0-9]{2}', re.IGNORECASE)  
MS45_STR = re.compile(rb'MS45|MSS54|7589121|7532228|7542310|7585885|DME_MS45', re.IGNORECASE)
ALPINA_STR = re.compile(rb'alpina|1357650|1357659|B3S|B3_3|Roadster.S', re.IGNORECASE)
GS86_STR = re.compile(rb'GS8\.60|GS860|2410644|5HP19|EGS_TCU', re.IGNORECASE)
BOSCH_ME7 = re.compile(rb'ME7\.|0261204|0261207|Bosch_ME', re.IGNORECASE)
# Don't try to match GM patterns in raw binary - too many false positives
# Instead, just detect by absence of BMW cal IDs

EXPECTED = {
    "all_ms42_bins": "MS42",
    "all_ms43_bins": "MS43", 
    "all_ms45_bins": "MS45",
    "ms42_damos": "MS42",
    "ms42_outputs_and_bins_xdfs": "MS42",
    "ms43_damos": "MS43",
    "ms43_outputs_and_bins_xdfs": "MS43",
    "ms45_combo_output": "MS45",
    "ms45_damos": "MS45",
    "ms45_work": "MS45",
}

def scan_bin(path):
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        # Cal IDs are in first 64KB; read only that for pattern matching
        data = f.read(65536)
    types = set()
    # First check for specific cal ID patterns (ca0110xx, ca4300xx, ca45xx)
    if MS42_PAT.search(data):
        types.add('MS42')
    if MS43_PAT.search(data):
        types.add('MS43')
    if MS45_PAT.search(data):
        types.add('MS45')
    # Broader string matches on header
    header = data[:16384]
    if not types:
        if MS42_STR.search(header):
            types.add('MS42')
        if MS43_STR.search(header):
            types.add('MS43')
        if MS45_STR.search(header):
            types.add('MS45')
    if ALPINA_STR.search(header):
        types.add('ALPINA')
    if GS86_STR.search(header):
        types.add('GS8604')
    if BOSCH_ME7.search(header):
        types.add('BOSCH_ME7')
    
    cal_ids = set()
    for m in MS42_PAT.finditer(data):
        cal_ids.add(('MS42', m.group(1).decode('ascii', errors='replace')))
    for m in MS43_PAT.finditer(data):
        cal_ids.add(('MS43', m.group(1).decode('ascii', errors='replace')))
    for m in MS45_PAT.finditer(data):
        cal_ids.add(('MS45', m.group(1).decode('ascii', errors='replace')))
    
    return types, cal_ids, size

def main():
    misplaced = []
    unknown_type = []
    total = 0
    
    for folder_name, folder_path in sorted(SCAN_DIRS.items()):
        if not os.path.isdir(folder_path):
            continue
        bins = sorted([f for f in os.listdir(folder_path) if f.lower().endswith('.bin')])
        expected_type = EXPECTED.get(folder_name)
        
        for fname in bins:
            total += 1
            fpath = os.path.join(folder_path, fname)
            try:
                types, cal_ids, size = scan_bin(fpath)
            except Exception as e:
                unknown_type.append((folder_name, fname, str(e), 0))
                continue
            
            size_kb = f"{size // 1024}KB"
            
            if expected_type:
                # Check if the expected type is NOT in the detected types
                if types and expected_type not in types:
                    misplaced.append((folder_name, fname, sorted(types), size_kb, sorted(cal_ids)))
                elif not types:
                    unknown_type.append((folder_name, fname, size_kb, sorted(cal_ids)))
    
    # Write results
    out = r"A:\1bmw_ms42_tuning_guides\misplaced_bins_report.txt"
    with open(out, 'w', encoding='utf-8') as f:
        f.write(f"BMW Binary File Classification Report\n")
        f.write(f"{'='*80}\n")
        f.write(f"Total .bin files scanned: {total}\n")
        f.write(f"Misplaced files: {len(misplaced)}\n")
        f.write(f"Unknown type files: {len(unknown_type)}\n\n")
        
        f.write(f"{'='*80}\n")
        f.write(f"MISPLACED FILES (file is in wrong folder based on detected ECU type)\n")
        f.write(f"{'='*80}\n")
        for folder, fname, types, size, cals in misplaced:
            f.write(f"  [{folder}] {fname}\n")
            f.write(f"    Size: {size} | Detected: {', '.join(types)} | Cal IDs: {cals}\n")
        
        f.write(f"\n{'='*80}\n")
        f.write(f"UNKNOWN TYPE FILES (no MS42/MS43/MS45 cal IDs found at all)\n")
        f.write(f"{'='*80}\n")
        for item in unknown_type:
            if len(item) == 4:
                folder, fname, size, cals = item
                f.write(f"  [{folder}] {fname} ({size})\n")
            else:
                f.write(f"  [{item[0]}] {item[1]} (ERROR: {item[2]})\n")
    
    print(f"Report written to: {out}")
    print(f"Total: {total} | Misplaced: {len(misplaced)} | Unknown: {len(unknown_type)}")
    
    # Also print to stdout
    with open(out, 'r', encoding='utf-8') as f:
        print(f.read())

if __name__ == '__main__':
    main()
