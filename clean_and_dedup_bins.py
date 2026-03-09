#!/usr/bin/env python3
"""
1. Remove non-BMW files from all_ms43_bins that came from downloaded_ecu_files (GM/Ford/other)
2. Remove internal hash duplicates from all_ms42_bins and all_ms43_bins
3. Print final clean counts
"""
import os, hashlib, re

MS42_DIR = r"A:\repos\1bmw_ms42_tuning_guides\all_ms42_bins"
MS43_DIR = r"A:\repos\1bmw_ms42_tuning_guides\all_ms43_bins"
MS45_DIR = r"A:\repos\1bmw_ms42_tuning_guides\all_ms45_bins"

# Patterns for non-BMW files (GM, Ford, Holden, etc.)
NON_BMW_PATTERNS = [
    r'LM7|LR4|LQ4|LQ9|LS1|LS2|LS3|LS6|L18|L83|L86|L96',  # GM engines
    r'Chevy|Chevrolet|GMC|Cadillac|Pontiac|Buick',  # GM brands
    r'K1500|K2500|C1500|C2500|Silverado|Sierra|Tahoe|Yukon|Suburban|Blazer',  # GM trucks/SUVs
    r'Camaro|Corvette|Impala|Malibu|Monte_Carlo',  # GM cars
    r'os\d{8}',  # GM OS identifiers like os12208322
    r'12202088|12208322|12216125|12579405|12593058',  # Known GM OS numbers
    r'Mustang|Explorer|F150|F250|Ranger|Bronco|Focus|Fusion|Taurus',  # Ford
    r'Commodore|Calais|Statesman|Berlina|Monaro|VT|VX|VY|VZ|VE|VF',  # Holden
    r'Sonic_ABM|ABMW_Flex',  # Sonic BMW badge variant (GM product)
    r'Subaru|Toyota|Honda|Nissan|Mazda|Mitsubishi|Kia|Hyundai',  # Asian brands
    r'Audi|VW|Volkswagen|Porsche|Mercedes|Benz',  # Audi/VW/Merc (not BMW)
]

NON_BMW_RE = re.compile('|'.join(NON_BMW_PATTERNS), re.IGNORECASE)

def sha16(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()[:16]

def clean_folder(folder, label):
    removed_non_bmw = 0
    removed_dupes = 0
    seen_hashes = {}
    files = sorted(os.listdir(folder))
    
    for fname in files:
        fp = os.path.join(folder, fname)
        if not os.path.isfile(fp):
            continue
        
        # Remove obvious non-BMW by filename
        if NON_BMW_RE.search(fname):
            os.remove(fp)
            removed_non_bmw += 1
            print(f"  REMOVED non-BMW: {fname}")
            continue
        
        # Deduplicate by hash
        try:
            h = sha16(fp)
        except Exception as e:
            print(f"  ERROR reading {fname}: {e}")
            continue
        
        if h in seen_hashes:
            # Keep the one with the more descriptive/longer name
            existing_fname = seen_hashes[h]
            if len(fname) > len(existing_fname):
                # Remove existing shorter name, keep this one
                os.remove(os.path.join(folder, existing_fname))
                seen_hashes[h] = fname
            else:
                # Remove this one
                os.remove(fp)
            removed_dupes += 1
        else:
            seen_hashes[h] = fname
    
    remaining = len([f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))])
    print(f"\n{label}:")
    print(f"  Removed non-BMW: {removed_non_bmw}")
    print(f"  Removed hash dupes: {removed_dupes}")
    print(f"  Remaining unique files: {remaining}")
    return remaining

print("=== Cleaning and deduplicating bin folders ===\n")
r42 = clean_folder(MS42_DIR, "MS42")
r43 = clean_folder(MS43_DIR, "MS43")
r45 = clean_folder(MS45_DIR, "MS45")

print(f"\n=== FINAL TOTALS ===")
print(f"  all_ms42_bins: {r42} unique files")
print(f"  all_ms43_bins: {r43} unique files")
print(f"  all_ms45_bins: {r45} unique files")
print(f"  TOTAL: {r42+r43+r45}")
