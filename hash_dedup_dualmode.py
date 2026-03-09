#!/usr/bin/env python3
"""
Hash-based dedup ANALYZER — DRY RUN, no files are copied.
Shows every bin in a source folder that is NOT already in all_ms42_bins / all_ms43_bins.
Review the output, then copy manually.

Usage:
    python hash_dedup_dualmode.py                         # defaults
    python hash_dedup_dualmode.py SOURCE_DIR              # override source
    python hash_dedup_dualmode.py SOURCE --ms42 DIR42 --ms43 DIR43
    python hash_dedup_dualmode.py SOURCE -o report.txt    # write output to file
"""
import os, hashlib, sys, argparse, datetime

def parse_args():
    p = argparse.ArgumentParser(
        description="Hash-based dedup analyzer for BMW MS4x bin collections (DRY RUN).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python hash_dedup_dualmode.py
  python hash_dedup_dualmode.py "A:\\repos\\Dualmode Switch"
  python hash_dedup_dualmode.py "A:\\repos\\Dualmode Switch" -o dedup_report.txt
  python hash_dedup_dualmode.py "E:\\bins" --ms42 A:\\repos\\1bmw_ms42_tuning_guides\\all_ms42_bins""",
    )
    p.add_argument("source", nargs="?", default=r"A:\repos\Dualmode Switch",
                   help="Source folder to scan for .bin files (default: Dualmode Switch)")
    p.add_argument("--ms42", default=r"A:\repos\1bmw_ms42_tuning_guides\all_ms42_bins",
                   help="Path to all_ms42_bins collection")
    p.add_argument("--ms43", default=r"A:\repos\1bmw_ms42_tuning_guides\all_ms43_bins",
                   help="Path to all_ms43_bins collection")
    p.add_argument("-o", "--output", default=None,
                   help="Write report to this file (in addition to stdout)")
    return p.parse_args()

args = parse_args()

MS42_DIR      = args.ms42
MS43_DIR      = args.ms43
DUALMODE_ROOT = args.source
OUTPUT_FILE   = args.output

# Simple tee helper: print to stdout and optionally to file
_out_fh = None
if OUTPUT_FILE:
    os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_FILE)), exist_ok=True)
    _out_fh = open(OUTPUT_FILE, "w", encoding="utf-8")

def tprint(msg=""):
    """Print to stdout and to the output file (if specified)."""
    print(msg)
    if _out_fh:
        _out_fh.write(msg + "\n")

def sha16(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()[:16]

def build_hash_map(folder):
    """Returns {hash: filename} for all files in a flat folder."""
    hmap = {}
    for f in os.listdir(folder):
        fp = os.path.join(folder, f)
        if os.path.isfile(fp):
            try:
                hmap[sha16(fp)] = f
            except Exception as e:
                print(f"  WARN: could not hash {f}: {e}")
    return hmap

def route(fname_lower, path_lower):
    if 'ms_42' in path_lower or '0110c6' in fname_lower or '0110ad' in fname_lower or 'ms42' in fname_lower:
        return 'ms42'
    if 'ms_43' in path_lower or '430' in fname_lower or 'm54b' in fname_lower or 'ms43' in fname_lower:
        return 'ms43'
    if r'\ms_42' in path_lower:
        return 'ms42'
    if r'\ms_43' in path_lower:
        return 'ms43'
    return 'ms43'

# ── Build existing hash sets ─────────────────────────────────────────────────
tprint("Hashing existing collections...")
map42 = build_hash_map(MS42_DIR)
map43 = build_hash_map(MS43_DIR)
ex_all = set(map42) | set(map43)
tprint(f"  MS42: {len(map42)} unique files")
tprint(f"  MS43: {len(map43)} unique files")
tprint(f"  Combined: {len(ex_all)} unique hashes")
tprint(f"  Source:   {DUALMODE_ROOT}")
tprint()

# ── Walk Dualmode and find truly new bins ────────────────────────────────────
new_ms42 = []   # (rel_path, fname, hash, size_bytes)
new_ms43 = []
already_seen_new = {}   # hash -> first rel path seen within Dualmode itself
skipped_existing       = 0
skipped_internal_dupe  = 0

for root, dirs, files in os.walk(DUALMODE_ROOT):
    for fname in files:
        if not fname.lower().endswith('.bin'):
            continue
        fp  = os.path.join(root, fname)
        rel = os.path.relpath(fp, DUALMODE_ROOT)
        try:
            h  = sha16(fp)
            sz = os.path.getsize(fp)
        except Exception as e:
            tprint(f"  WARN: {rel}: {e}")
            continue

        if h in ex_all:
            skipped_existing += 1
            continue

        if h in already_seen_new:
            skipped_internal_dupe += 1
            continue

        already_seen_new[h] = rel
        r_type = route(fname.lower(), root.lower())
        if r_type == 'ms42':
            new_ms42.append((rel, fname, h, sz))
        else:
            new_ms43.append((rel, fname, h, sz))

# ── Report ───────────────────────────────────────────────────────────────────
tprint(f"{'='*72}")
tprint(f"DEDUP ANALYSIS — NEW UNIQUE BINS  (not in existing collections)")
tprint(f"  Source: {DUALMODE_ROOT}")
tprint(f"  Date:   {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
tprint(f"{'='*72}")

if new_ms42:
    tprint(f"\n--- NEW MS42 ({len(new_ms42)}) ---")
    for rel, fname, h, sz in sorted(new_ms42):
        tprint(f"  [{h}]  {sz//1024:>4} KB   {rel}")
else:
    tprint("\n--- NEW MS42: 0 ---")

if new_ms43:
    tprint(f"\n--- NEW MS43 ({len(new_ms43)}) ---")
    for rel, fname, h, sz in sorted(new_ms43):
        tprint(f"  [{h}]  {sz//1024:>4} KB   {rel}")
else:
    tprint("\n--- NEW MS43: 0 ---")

tprint(f"\n{'='*72}")
tprint(f"SUMMARY")
tprint(f"  New unique MS42:              {len(new_ms42)}")
tprint(f"  New unique MS43:              {len(new_ms43)}")
tprint(f"  Skipped (already collected):  {skipped_existing}")
tprint(f"  Skipped (internal dupes):     {skipped_internal_dupe}")
tprint(f"  Total bins scanned:           {skipped_existing + skipped_internal_dupe + len(new_ms42) + len(new_ms43)}")
tprint(f"{'='*72}")

if not new_ms42 and not new_ms43:
    tprint("\nAll source bins are already present in the collections. Nothing to copy.")

if _out_fh:
    _out_fh.close()
    print(f"\nReport written to: {os.path.abspath(OUTPUT_FILE)}")
