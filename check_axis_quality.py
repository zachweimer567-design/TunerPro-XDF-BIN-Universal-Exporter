#!/usr/bin/env python3
"""Quick axis quality checker - reads combo JSON and checks if X/Y axes are smooth."""
import json, sys, os

combo_dir = r'A:\repos\[bmw_ms42_tuning_guides\ms45_combo_output'

# Check all combos for axis monotonicity
combos = sorted([d for d in os.listdir(combo_dir) if os.path.isdir(os.path.join(combo_dir, d))])

for combo_name in combos:
    json_files = [f for f in os.listdir(os.path.join(combo_dir, combo_name)) if f.endswith('.json')]
    if not json_files:
        continue
    
    jpath = os.path.join(combo_dir, combo_name, json_files[0])
    with open(jpath) as f:
        j = json.load(f)
    
    tables = j.get('tables', [])
    total_with_axes = 0
    mono_ok = 0
    mono_bad = 0
    bad_examples = []
    good_examples = []
    
    for t in tables:
        if t.get('status') != 'OK':
            continue
        xl = t.get('x_labels', [])
        yl = t.get('y_labels', [])
        if len(xl) < 3 and len(yl) < 3:
            continue
        
        total_with_axes += 1
        
        x_mono = all(xl[i] <= xl[i+1] for i in range(len(xl)-1)) if len(xl) > 1 else True
        y_mono = all(yl[i] <= yl[i+1] for i in range(len(yl)-1)) if len(yl) > 1 else True
        
        if x_mono and y_mono:
            mono_ok += 1
            if len(good_examples) < 3 and len(xl) >= 5:
                good_examples.append({
                    'title': t['title'],
                    'x': xl[:12],
                    'y': yl[:12],
                    'rows': t.get('rows',0),
                    'cols': t.get('cols',0),
                    'min': t.get('min',0),
                    'max': t.get('max',0)
                })
        else:
            mono_bad += 1
            if len(bad_examples) < 5:
                bad_examples.append({
                    'title': t['title'],
                    'x': xl[:12],
                    'y': yl[:12],
                    'x_mono': x_mono,
                    'y_mono': y_mono,
                    'rows': t.get('rows',0),
                    'cols': t.get('cols',0),
                })
    
    pct = (mono_ok / total_with_axes * 100) if total_with_axes > 0 else 0
    marker = "GOOD" if pct > 80 else "PARTIAL" if pct > 50 else "BAD"
    
    print(f"\n{'='*80}")
    print(f"COMBO: {combo_name}")
    print(f"  Tables with axes: {total_with_axes}")
    print(f"  Monotonic (smooth): {mono_ok} ({pct:.1f}%)  [{marker}]")
    print(f"  Non-monotonic (jumbled): {mono_bad}")
    
    if good_examples:
        print(f"\n  GOOD axis examples:")
        for g in good_examples[:2]:
            print(f"    {g['title']} [{g['rows']}x{g['cols']}] data=[{g['min']:.2f}..{g['max']:.2f}]")
            print(f"      X: {g['x']}")
            if g['y']:
                print(f"      Y: {g['y']}")
    
    if bad_examples:
        print(f"\n  BAD axis examples:")
        for b in bad_examples[:3]:
            print(f"    {b['title']} [{b['rows']}x{b['cols']}]")
            print(f"      X({'' if b['x_mono'] else 'NOT '}mono): {b['x']}")
            if b['y']:
                print(f"      Y({'' if b['y_mono'] else 'NOT '}mono): {b['y']}")

print("\n\nDONE")
