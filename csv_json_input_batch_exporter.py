#!/usr/bin/env python3
"""
===============================================================================
 KingAI Batch Exporter - CSV / JSON Input Processor
===============================================================================

 Reads a CSV or JSON manifest that specifies XDF + BIN pairs and output paths,
 then runs the TunerPro Universal Exporter on every row.

 CSV Format (header row required)::

   xdf,bin,output,format,options
   C:/defs/MS42.xdf,C:/bins/MS42.bin,C:/out/ms42_export,all,--addresses
   C:/defs/MS43.xdf,C:/bins/MS43.bin,C:/out/ms43_export,all,

 JSON Format (array of objects)::

   [
     {
       "xdf": "C:/defs/MS42.xdf",
       "bin": "C:/bins/MS42.bin",
       "output": "C:/out/ms42_export",
       "format": "all",
       "options": "--addresses"
     }
   ]

 Fields:
   xdf      - (required) path to XDF definition file
   bin      - (required) path to BIN firmware file
   output   - (required) output base path (extension set by format)
   format   - (optional) txt | json | md | csv | all  (default: all)
   options  - (optional) space-separated flags: --addresses --flip-rpm
              --flip-load --no-stats

===============================================================================
 Author:  Jason King  |  GitHub: KingAiCodeForge  |  KingAI PTY LTD
===============================================================================
"""

import csv
import json
import sys
import os
import io
import time
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Ensure we can import the exporter from the same directory
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from tunerpro_exporter import UniversalXDFExporter, __version__, safe_print


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_manifest_csv(csv_path: str) -> list[dict]:
    """Load a CSV manifest file and return a list of job dicts."""
    jobs = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        # Pre-filter: skip blank lines and comment lines (# ...)
        lines = [line for line in f if line.strip() and not line.strip().startswith("#")]
    reader = csv.DictReader(lines)
    # Normalise header names (strip whitespace, lowercase)
    reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
    for row_num, row in enumerate(reader, start=2):  # 2 because row 1 is the header
        job = _normalise_row(row, source=f"{csv_path}:{row_num}")
        if job:
            jobs.append(job)
    return jobs


def load_manifest_json(json_path: str) -> list[dict]:
    """Load a JSON manifest file and return a list of job dicts."""
    with open(json_path, encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]  # single entry convenience
    jobs = []
    for idx, entry in enumerate(data):
        # Normalise keys
        entry = {k.strip().lower(): v for k, v in entry.items()}
        job = _normalise_row(entry, source=f"{json_path}[{idx}]")
        if job:
            jobs.append(job)
    return jobs


def _normalise_row(row: dict, source: str) -> dict | None:
    """Validate and normalise a single manifest row into a job dict."""
    xdf = (row.get("xdf") or "").strip()
    bin_ = (row.get("bin") or "").strip()
    output = (row.get("output") or "").strip()
    fmt = (row.get("format") or "all").strip().lower()
    options = (row.get("options") or "").strip()

    # --- Validation ---
    errors = []
    if not xdf:
        errors.append("missing 'xdf' path")
    elif not Path(xdf).is_file():
        errors.append(f"xdf not found: {xdf}")

    if not bin_:
        errors.append("missing 'bin' path")
    elif not Path(bin_).is_file():
        errors.append(f"bin not found: {bin_}")

    if not output:
        errors.append("missing 'output' path")

    if fmt not in ("txt", "text", "json", "md", "markdown", "csv", "all"):
        errors.append(f"unknown format '{fmt}' (use txt/json/md/csv/all)")

    if errors:
        safe_print(f"  [SKIP] {source}: {'; '.join(errors)}")
        return None

    # Parse option flags
    opt_tokens = options.split() if options else []
    return {
        "xdf": xdf,
        "bin": bin_,
        "output": output,
        "format": fmt if fmt != "text" else "txt",
        "addresses": "--addresses" in opt_tokens,
        "flip_rpm": "--flip-rpm" in opt_tokens,
        "flip_load": "--flip-load" in opt_tokens,
        "no_stats": "--no-stats" in opt_tokens,
        "source": source,
    }


def run_single_export(job: dict) -> dict:
    """
    Run one export job.  Returns a result dict with keys:
      ok (bool), xdf, bin, outputs (list of (fmt, path)), errors (list of str)
    """
    result = {
        "ok": False,
        "xdf": job["xdf"],
        "bin": job["bin"],
        "outputs": [],
        "errors": [],
    }

    try:
        exporter = UniversalXDFExporter(job["xdf"], job["bin"])
        exporter.show_addresses = job["addresses"]
        exporter.flip_rpm = job["flip_rpm"]
        exporter.flip_load = job["flip_load"]
        exporter.no_stats = job["no_stats"]

        if not exporter.validate_bin_file():
            result["errors"].append("binary validation failed")
            return result

        if not exporter.parse_xdf():
            result["errors"].append("XDF parsing failed")
            return result

        export_format = job["format"]
        output_base = job["output"]
        base_path = Path(output_base)
        base_name = base_path.stem
        base_dir = base_path.parent

        # Make sure output directory exists
        base_dir.mkdir(parents=True, exist_ok=True)

        any_ok = False

        if export_format in ("txt", "all"):
            p = str(base_dir / f"{base_name}.txt") if export_format == "all" else output_base
            if exporter.export_to_text(p):
                result["outputs"].append(("TXT", p))
                any_ok = True
            else:
                result["errors"].append(f"TXT export failed -> {p}")

        if export_format in ("json", "all"):
            p = str(base_dir / f"{base_name}.json") if export_format == "all" else output_base
            if exporter.export_to_json(p):
                result["outputs"].append(("JSON", p))
                any_ok = True
            else:
                result["errors"].append(f"JSON export failed -> {p}")

        if export_format in ("md", "markdown", "all"):
            p = str(base_dir / f"{base_name}.md") if export_format == "all" else output_base
            if exporter.export_to_markdown(p):
                result["outputs"].append(("MD", p))
                any_ok = True
            else:
                result["errors"].append(f"MD export failed -> {p}")

        if export_format in ("csv", "all"):
            p = str(base_dir / f"{base_name}.csv") if export_format == "all" else output_base
            if exporter.export_to_csv(p):
                result["outputs"].append(("CSV", p))
                any_ok = True
            else:
                result["errors"].append(f"CSV export failed -> {p}")

        result["ok"] = any_ok

        # Print element counts for this job
        n_scalars = len(exporter.elements["constants"])
        n_flags = len(exporter.elements["flags"])
        n_tables = len(exporter.elements["tables"])
        n_patches = len(exporter.elements["patches"])
        safe_print(
            f"    Elements: {n_scalars} scalars, {n_flags} flags, "
            f"{n_tables} tables, {n_patches} patches"
        )

    except Exception as exc:
        result["errors"].append(f"exception: {exc}")

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("=" * 70)
        print("  KingAI Batch Exporter - CSV / JSON Input Processor")
        print("=" * 70)
        print(f"  Version: {__version__}")
        print()
        print("Usage:")
        print(f"  python {Path(__file__).name} <manifest.csv|manifest.json>")
        print()
        print("CSV format (one job per row, header required):")
        print("  xdf,bin,output,format,options")
        print("  C:\\defs\\MS42.xdf,C:\\bins\\MS42.bin,C:\\out\\ms42_export,all,--addresses")
        print()
        print("JSON format (array of objects):")
        print('  [{"xdf":"...", "bin":"...", "output":"...", "format":"all", "options":""}]')
        print()
        print("Fields:")
        print("  xdf      - path to XDF definition file       (required)")
        print("  bin      - path to BIN firmware file          (required)")
        print("  output   - output base path                   (required)")
        print("  format   - txt | json | md | csv | all        (default: all)")
        print("  options  - --addresses --flip-rpm --flip-load --no-stats")
        print()
        print("The exporter writes FULL outputs for every job (no truncation).")
        print("=" * 70)
        sys.exit(1)

    manifest_path = sys.argv[1]

    if not Path(manifest_path).is_file():
        safe_print(f"[ERROR] Manifest file not found: {manifest_path}")
        sys.exit(1)

    # Detect format by extension
    ext = Path(manifest_path).suffix.lower()
    if ext == ".json":
        jobs = load_manifest_json(manifest_path)
    elif ext in (".csv", ".tsv", ".txt"):
        jobs = load_manifest_csv(manifest_path)
    else:
        # Try JSON first, fall back to CSV
        try:
            jobs = load_manifest_json(manifest_path)
        except (json.JSONDecodeError, ValueError):
            jobs = load_manifest_csv(manifest_path)

    if not jobs:
        safe_print("[ERROR] No valid jobs found in manifest. Check paths and format.")
        sys.exit(1)

    # ----- Banner -----
    print()
    print("=" * 70)
    print("  KingAI Batch Exporter")
    print("=" * 70)
    print(f"  Manifest : {manifest_path}")
    print(f"  Jobs     : {len(jobs)}")
    print(f"  Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()

    # ----- Run jobs -----
    results = []
    t_start = time.time()

    for idx, job in enumerate(jobs, start=1):
        print("-" * 70)
        safe_print(f"  [{idx}/{len(jobs)}] {Path(job['xdf']).name}  +  {Path(job['bin']).name}")
        safe_print(f"    -> {job['output']}  (format={job['format']})")

        res = run_single_export(job)
        results.append(res)

        if res["ok"]:
            for fmt, path in res["outputs"]:
                safe_print(f"    [OK]  {fmt} -> {path}")
        if res["errors"]:
            for err in res["errors"]:
                safe_print(f"    [FAIL] {err}")
        print()

    elapsed = time.time() - t_start

    # ----- Summary -----
    passed = sum(1 for r in results if r["ok"])
    failed = len(results) - passed
    total_files = sum(len(r["outputs"]) for r in results)

    print("=" * 70)
    safe_print("  BATCH SUMMARY")
    print("=" * 70)
    print(f"  Total jobs : {len(results)}")
    safe_print(f"  Passed     : {passed}")
    if failed:
        safe_print(f"  Failed     : {failed}")
    print(f"  Files made : {total_files}")
    print(f"  Time       : {elapsed:.1f}s")
    print("=" * 70)

    if failed:
        print()
        safe_print("  Failed jobs:")
        for r in results:
            if not r["ok"]:
                safe_print(f"    XDF: {r['xdf']}")
                safe_print(f"    BIN: {r['bin']}")
                for e in r["errors"]:
                    safe_print(f"      -> {e}")
                print()

    print()
    safe_print(f"  Exporter v{__version__}  |  KingAI Batch Processor")
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

