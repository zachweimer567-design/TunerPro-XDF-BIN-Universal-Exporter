#!/usr/bin/env python3
"""
Organize all MS42 and MS43 .bin files from A:\ into categorized folders.
Creates:
  A:\1bmw_ms42_tuning_guides\all_ms42_bins\  — MS42 / 0110AD / 0110C6 bins
  A:\1bmw_ms42_tuning_guides\all_ms43_bins\  — MS43 / 430069 / 430070 / 430037 bins
  
Copies (does NOT move) files, preserving originals.
Also generates a manifest with XDF-to-bin mapping.
"""

import os
import shutil
import hashlib
from pathlib import Path
from collections import defaultdict

BASE = Path(r"A:\\")
GUIDE_DIR = Path(r"A:\1bmw_ms42_tuning_guides")
MS42_DIR = GUIDE_DIR / "all_ms42_bins"
MS43_DIR = GUIDE_DIR / "all_ms43_bins"

# --- Classification rules ---
def classify_bin(name_lower, path_str_lower):
    """Return 'ms42', 'ms43', 'unknown', or 'skip'."""
    # Skip non-ECU files
    if any(x in name_lower for x in ['325ti', 'jednotka']):
        return 'ms43'  # 325ti is MS43 project
    
    # Explicit MS43 markers
    if any(x in name_lower for x in ['ms43', '430069', '430070', '430037']):
        return 'ms43'
    
    # Explicit MS42 markers  
    if any(x in name_lower for x in ['ms42', '0110c6', '0110ad', '0110sa', '0110ca', '011025']):
        return 'ms42'
    
    # M52TU or M54B in name without MS4x prefix — check path context
    if 'm52tu' in name_lower or 'm54b' in name_lower:
        if 'ms43' in path_str_lower or '430069' in path_str_lower:
            return 'ms43'
        if 'ms42' in path_str_lower or '0110' in path_str_lower:
            return 'ms42'
        # Default: if it has m54b it's likely MS43 territory
        if 'm54b' in name_lower:
            return 'ms43'
        return 'ms42'
    
    # racemode alpha-N is MS43 430069
    if 'racemode' in name_lower:
        return 'ms43'
    
    # alpina
    if 'alpina' in name_lower:
        if '430037' in name_lower or '430070' in name_lower:
            return 'ms43'
        if '0110c6' in name_lower:
            return 'ms42'
    
    return 'unknown'


def get_file_hash(filepath, block_size=65536):
    """SHA256 of file for dedup."""
    h = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for block in iter(lambda: f.read(block_size), b''):
                h.update(block)
        return h.hexdigest()[:16]
    except:
        return 'error'


def get_size_category(size):
    """Categorize by flash region size."""
    if size <= 35000:  # ~32KB
        return '32KB'
    elif size <= 70000:  # ~64KB
        return '64KB'
    elif size <= 130000:  # ~116KB
        return '116KB'
    elif size <= 530000:  # ~512KB
        return '512KB'
    elif size <= 1100000:  # ~1024KB
        return '1024KB'
    else:
        return f'{size}B'


def main():
    print("=" * 80)
    print("MS42/MS43 BIN FILE ORGANIZER")
    print("=" * 80)
    
    # Create output directories
    MS42_DIR.mkdir(parents=True, exist_ok=True)
    MS43_DIR.mkdir(parents=True, exist_ok=True)
    
    # Scan KNOWN directories where MS42/MS43/MS45 bins live
    # (Full A:\ walk is too slow — 100GB+ drive)
    SCAN_DIRS = [
        # Root-level bins
        (r"A:\\", False),  # Non-recursive root only
        # Kings tuning folders
        (r"A:\1kings bmw tuning", True),
        # Output folders (already created bins)
        (r"A:\1bmw_ms42_tuning_guides\ms42_outputs_and_bins_xdfs", True),
        (r"A:\1bmw_ms42_tuning_guides\ms43_outputs_and_bins_xdfs", True),
        # Racemode folders
        (r"A:\binfilesracemode", True),
        (r"A:\ms42 to ms43 racemode m52tu tunes", True),
        # Stock tune repos
        (r"A:\ms43-main", True),
        (r"A:\ms43-main v1.13 latest", True),
        # BMW ECUs repo
        (r"A:\BMW_ECUs-main", True),
        # 325ti MS43 project
        (r"A:\325ti_MS43-main", True),
        # Tune packs
        (r"A:\MS43_M52TUB28_M50B25_Tune_Pack (1)", True),
        # Touched up tunes
        (r"A:\touched up ms42", True),
        # BMW work directories
        (r"A:\BMW_ms42_workinprogress", True),
        (r"A:\BMW_ms42_carproductions", True),
        (r"A:\BMW_ECU_Organization", True),
        # Kingai patchlist work
        (r"A:\kingai_bmw_siemens_ms42x_0110C6_patchlist_and_patchs_work_in_progress", True),
        # Siemens MS42 0110C6 folder 
        (r"A:\Siemens_MS42_0110C6_ENG_32K_v1.1", True),
        # Alpina folders
        (r"A:\Alp_na-B3S-EGS-GS8.60.4", True),
        # Bosch MAF on MS43
        (r"A:\Bosch_Audi_RS4_MAF_on_Siemens_MS43", True),
        # MS43X custom firmware
        (r"A:\ms43x-custom-firmware", True),
    ]
    
    all_bins = []
    skip_dirs = {'all_ms42_bins', 'all_ms43_bins', 'ms45_combo_output'}
    
    for scan_path, recursive in SCAN_DIRS:
        if not os.path.isdir(scan_path):
            print(f"  [skip] {scan_path} — not found")
            continue
        
        if recursive:
            for root, dirs, files in os.walk(scan_path):
                # Skip destination/output folders
                if any(s in root for s in skip_dirs):
                    continue
                for f in files:
                    if f.lower().endswith('.bin'):
                        all_bins.append(os.path.join(root, f))
        else:
            # Non-recursive — root-level files only
            for f in os.listdir(scan_path):
                full = os.path.join(scan_path, f)
                if os.path.isfile(full) and f.lower().endswith('.bin'):
                    all_bins.append(full)
    
    print(f"\nTotal .bin files found on A:\\: {len(all_bins)}")
    
    # Classify
    ms42_bins = []
    ms43_bins = []
    unknown_bins = []
    
    for bp in all_bins:
        name_lower = os.path.basename(bp).lower()
        path_lower = bp.lower()
        cat = classify_bin(name_lower, path_lower)
        
        if cat == 'ms42':
            ms42_bins.append(bp)
        elif cat == 'ms43':
            ms43_bins.append(bp)
        else:
            unknown_bins.append(bp)
    
    print(f"  MS42: {len(ms42_bins)} bins")
    print(f"  MS43: {len(ms43_bins)} bins")
    print(f"  Unknown: {len(unknown_bins)} bins")
    
    # Copy and deduplicate
    manifest = []
    seen_hashes = {}
    
    def copy_bins(bin_list, dest_dir, ecu_label):
        copied = 0
        dupes = 0
        for bp in sorted(bin_list):
            fsize = os.path.getsize(bp)
            fhash = get_file_hash(bp)
            size_cat = get_size_category(fsize)
            basename = os.path.basename(bp)
            
            # Track for manifest
            entry = {
                'source': bp,
                'name': basename,
                'size': fsize,
                'size_cat': size_cat,
                'hash': fhash,
                'ecu': ecu_label
            }
            manifest.append(entry)
            
            # Check for exact duplicate in destination
            dest = dest_dir / basename
            if dest.exists():
                dest_hash = get_file_hash(str(dest))
                if dest_hash == fhash:
                    dupes += 1
                    continue
                # Different content, same name — suffix with source hint
                src_hint = os.path.basename(os.path.dirname(bp)).replace(' ', '_')[:30]
                stem = Path(basename).stem
                ext = Path(basename).suffix
                dest = dest_dir / f"{stem}_from_{src_hint}{ext}"
            
            if fhash in seen_hashes and seen_hashes[fhash] != bp:
                # Same content already copied under different name
                entry['duplicate_of'] = seen_hashes[fhash]
                # Still copy it, user wants all bins in one place
            
            seen_hashes.setdefault(fhash, bp)
            
            try:
                shutil.copy2(bp, str(dest))
                copied += 1
            except Exception as e:
                print(f"  ERROR copying {basename}: {e}")
        
        return copied, dupes
    
    print(f"\n--- Copying MS42 bins to {MS42_DIR} ---")
    c42, d42 = copy_bins(ms42_bins, MS42_DIR, 'MS42')
    print(f"  Copied: {c42}, Skipped duplicates: {d42}")
    
    print(f"\n--- Copying MS43 bins to {MS43_DIR} ---")
    c43, d43 = copy_bins(ms43_bins, MS43_DIR, 'MS43')
    print(f"  Copied: {c43}, Skipped duplicates: {d43}")
    
    # --- Generate manifest with XDF mapping ---
    print("\n" + "=" * 80)
    print("BIN-TO-XDF MAPPING GUIDE")
    print("=" * 80)
    
    xdf_guide = []
    xdf_guide.append("# MS42 / MS43 Bin File Inventory & XDF Mapping\n")
    xdf_guide.append(f"Generated by organize_bins.py\n")
    xdf_guide.append(f"Total bins cataloged: {len(manifest)}\n\n")
    
    # XDF mapping rules
    xdf_guide.append("## XDF Assignment Rules\n\n")
    xdf_guide.append("### MS42 (0110C6) Bins\n")
    xdf_guide.append("| Size | XDF to Use | Notes |\n")
    xdf_guide.append("|------|-----------|-------|\n")
    xdf_guide.append("| 32KB  | `Siemens_MS42_0110C6_ENG_32K_v1.1.xdf` | Calibration-only region |\n")
    xdf_guide.append("| 512KB | `Siemens_MS42_0110C6_ENG_512K_v1.1.xdf` | Full flash image |\n")
    xdf_guide.append("| 512KB + Patchlist | `Siemens_MS42_0110C6_Community_Patchlist_v1.7.1.xdf` | Emulation firmware with patches |\n\n")
    
    xdf_guide.append("### MS42 (0110AD) Bins\n")
    xdf_guide.append("| Size | XDF to Use | Notes |\n")
    xdf_guide.append("|------|-----------|-------|\n")
    xdf_guide.append("| 32KB  | `MS42_01100AD_ENG_32KB.xdf` | Calibration-only |\n")
    xdf_guide.append("| 512KB | `MS42_01100AD_ENG_512KB.xdf` | Full flash image |\n\n")
    
    xdf_guide.append("### MS43 (430069) Bins\n")
    xdf_guide.append("| Size | XDF to Use | Notes |\n")
    xdf_guide.append("|------|-----------|-------|\n")
    xdf_guide.append("| 64KB  | `Siemens_MS43_430069_64K.xdf` | Calibration-only region |\n")
    xdf_guide.append("| 512KB | `Siemens_MS43_430069_512K_1.1.3v.xdf` | Full flash (latest v1.1.3) |\n")
    xdf_guide.append("| 512KB + Patchlist | `Siemens_MS43_MS430069_Community_Patchlist_v2.9.2.xdf` | Emulation firmware with patches |\n\n")
    
    xdf_guide.append("### MS4X Flash Emulation Firmware\n")
    xdf_guide.append("| XDF | Applies To |\n")
    xdf_guide.append("|-----|----------|\n")
    xdf_guide.append("| `MS4X_Flash_Emulation_Firmware_Patchlist.xdf` | Both MS42 & MS43 emulation-only bins |\n\n")
    
    # --- MS42 Bin Catalog ---
    xdf_guide.append("---\n\n## MS42 Bin Catalog\n\n")
    xdf_guide.append("| # | Filename | Size | Size Cat | Hash | Correct XDF | Source |\n")
    xdf_guide.append("|---|----------|------|----------|------|------------|--------|\n")
    
    ms42_entries = [e for e in manifest if e['ecu'] == 'MS42']
    ms42_entries.sort(key=lambda e: (e['size_cat'], e['name'].lower()))
    
    for i, e in enumerate(ms42_entries, 1):
        name = e['name']
        # Determine correct XDF
        name_l = name.lower()
        if '0110ad' in name_l:
            if e['size_cat'] == '32KB':
                xdf = 'MS42_01100AD_ENG_32KB.xdf'
            else:
                xdf = 'MS42_01100AD_ENG_512KB.xdf'
        elif 'emulationonly' in name_l or 'emulation' in name_l:
            xdf = 'MS4X_Flash_Emulation_Firmware_Patchlist.xdf + 0110C6_Community_Patchlist'
        else:
            if e['size_cat'] == '32KB':
                xdf = 'Siemens_MS42_0110C6_ENG_32K_v1.1.xdf'
            else:
                xdf = 'Siemens_MS42_0110C6_ENG_512K_v1.1.xdf'
        
        src = os.path.dirname(e['source']).replace('A:\\', '')[:50]
        xdf_guide.append(f"| {i} | {name[:60]} | {e['size']:,} | {e['size_cat']} | {e['hash']} | {xdf} | {src} |\n")
    
    # --- MS43 Bin Catalog ---
    xdf_guide.append("\n---\n\n## MS43 Bin Catalog\n\n")
    xdf_guide.append("| # | Filename | Size | Size Cat | Hash | Correct XDF | Source |\n")
    xdf_guide.append("|---|----------|------|----------|------|------------|--------|\n")
    
    ms43_entries = [e for e in manifest if e['ecu'] == 'MS43']
    ms43_entries.sort(key=lambda e: (e['size_cat'], e['name'].lower()))
    
    for i, e in enumerate(ms43_entries, 1):
        name = e['name']
        name_l = name.lower()
        if 'emulationonly' in name_l or 'emulation' in name_l:
            xdf = 'MS4X_Flash_Emulation_Firmware_Patchlist.xdf + 430069_Community_Patchlist'
        elif '430037' in name_l:
            xdf = 'Alpina MS43 430037 (no standard XDF available)'
        elif '430070' in name_l:
            xdf = 'Alpina MS43 430070 (no standard XDF available)'
        elif e['size_cat'] == '64KB':
            xdf = 'Siemens_MS43_430069_64K.xdf'
        elif e['size_cat'] == '512KB':
            xdf = 'Siemens_MS43_430069_512K_1.1.3v.xdf'
        else:
            xdf = 'Siemens_MS43_430069_512K_1.1.3v.xdf (check size!)'
        
        src = os.path.dirname(e['source']).replace('A:\\', '')[:50]
        xdf_guide.append(f"| {i} | {name[:60]} | {e['size']:,} | {e['size_cat']} | {e['hash']} | {xdf} | {src} |\n")
    
    # --- Racemode Analysis ---
    xdf_guide.append("\n---\n\n## Racemode Alpha-N Bins (Key Interest)\n\n")
    racemode_bins = [e for e in manifest if 'racemode' in e['name'].lower() or 'alpha' in e['name'].lower()]
    if racemode_bins:
        for e in racemode_bins:
            xdf_guide.append(f"- **{e['name']}**\n")
            xdf_guide.append(f"  - Size: {e['size']:,} bytes ({e['size_cat']})\n")
            xdf_guide.append(f"  - Hash: {e['hash']}\n")
            xdf_guide.append(f"  - Source: `{e['source']}`\n")
            xdf_guide.append(f"  - XDF: `Siemens_MS43_430069_512K_1.1.3v.xdf` (base) + `Siemens_MS43_MS430069_Community_Patchlist_v2.9.2.xdf` (racemode patches)\n")
            xdf_guide.append(f"  - **This is MS43 430069 with M52TUB28 Alpha-N racemode — key file for M52TUB25 port**\n\n")
    
    # --- M52TUB28 swap bins on MS43 ---
    xdf_guide.append("\n## M52TUB28-on-MS43 Swap/Tune Bins\n\n")
    swap_bins = [e for e in manifest if 'm52tu' in e['name'].lower() and e['ecu'] == 'MS43']
    for e in swap_bins:
        xdf_guide.append(f"- **{e['name']}**\n")
        xdf_guide.append(f"  - Size: {e['size']:,} ({e['size_cat']}), Source: `{os.path.dirname(e['source'])}`\n")
    
    # --- Unknown bins ---
    if unknown_bins:
        xdf_guide.append("\n---\n\n## Unclassified Bins\n\n")
        for bp in sorted(unknown_bins):
            xdf_guide.append(f"- `{bp}`\n")
    
    # --- Duplicate detection ---
    xdf_guide.append("\n---\n\n## Duplicate Detection (Same Hash)\n\n")
    hash_groups = defaultdict(list)
    for e in manifest:
        hash_groups[e['hash']].append(e)
    
    dupe_count = 0
    for h, entries in sorted(hash_groups.items()):
        if len(entries) > 1:
            dupe_count += 1
            xdf_guide.append(f"### Hash {h} ({entries[0]['size_cat']})\n")
            for e in entries:
                xdf_guide.append(f"- `{e['source']}`\n")
            xdf_guide.append("\n")
    
    if dupe_count == 0:
        xdf_guide.append("No duplicate bins found.\n")
    else:
        xdf_guide.append(f"\n**{dupe_count} groups of duplicate bins found.**\n")
    
    # Write manifest
    manifest_path = GUIDE_DIR / "bin_inventory_and_xdf_mapping.md"
    with open(str(manifest_path), 'w', encoding='utf-8') as f:
        f.writelines(xdf_guide)
    
    print(f"\nManifest written to: {manifest_path}")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"MS42 bins copied to: {MS42_DIR}")
    print(f"  Files: {len(list(MS42_DIR.glob('*.bin')))} bins")
    print(f"MS43 bins copied to: {MS43_DIR}")
    print(f"  Files: {len(list(MS43_DIR.glob('*.bin')))} bins")
    print(f"Manifest: {manifest_path}")
    
    # Print key racemode info
    print("\n--- KEY RACEMODE ALPHA-N FILES ---")
    for e in racemode_bins:
        print(f"  {e['name']} ({e['size_cat']}) → in {MS43_DIR}")


if __name__ == '__main__':
    main()
