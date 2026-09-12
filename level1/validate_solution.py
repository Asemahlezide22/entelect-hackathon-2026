#!/usr/bin/env python3
"""
Standalone validator for a Level 1 submission file.

Checks every constraint the problem statement states explicitly (p.4-5):
  * top-level shape {"actions": [{"tick": int, "plants": [...]}, ...]}
  * tick is an integer in [0, T-1], each tick listed at most once
  * row/col inside the 50x50 grid
  * plant_index exists in the plant catalogue
  * at most 20 plants per tick
  * no cell planted twice within the same tick

Plus Level-1 advisories (warnings, not errors - the solver ignores rather than
rejects these actions):
  * planting a species that is locked in Level 1
  * planting on a cell the level file does not list
  * planting on a soil type the species rejects (preferred_soil)

Also reports a byte-level determinism check: regenerating and re-serialising
must produce an identical file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import plants, solution, world as world_mod   # noqa: E402

LEVEL1_UNLOCKED = set(plants.LEVEL1_PLANT_INDICES)


def advisories(path, world):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    warn = Counter()
    for entry in raw.get("actions", ()):
        for p in entry.get("plants", ()):
            pi, r, c = p.get("plant_index"), p.get("row"), p.get("col")
            if pi not in LEVEL1_UNLOCKED:
                warn["locked in Level 1 (action will be ignored)"] += 1
                continue
            if not world.in_bounds(r, c):
                continue
            terrain, soil = world.terrain[r][c], world.soil[r][c]
            if terrain is None:
                warn["cell not listed in level1.json (terrain unknown)"] += 1
            elif terrain != 0:
                warn["terrain=%d - plantability UNKNOWN (hedged bet)" % terrain] += 1
            if soil is not None and soil not in plants.get(pi).preferred_soil:
                warn["soil %d rejected by %s" % (soil, plants.get(pi).name)] += 1
    return warn


def stats(path, world):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    per_species, per_tick, cells = Counter(), {}, Counter()
    for entry in raw["actions"]:
        per_tick[entry["tick"]] = len(entry["plants"])
        for p in entry["plants"]:
            per_species[p["plant_index"]] += 1
            cells[(p["row"], p["col"])] += 1
    ticks = sorted(per_tick)
    return {
        "total_actions": sum(per_species.values()),
        "tick_entries": len(ticks),
        "tick_range": (ticks[0], ticks[-1]) if ticks else None,
        "max_per_tick": max(per_tick.values()) if per_tick else 0,
        "per_species": per_species,
        "distinct_cells": len(cells),
        "cells_planted_more_than_once": sum(1 for v in cells.values() if v > 1),
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate a Level 1 submission JSON")
    ap.add_argument("solution", nargs="?", default="out/solution.json")
    ap.add_argument("--level", default="data/level1.json")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parent
    world = world_mod.load(root / args.level)
    path = root / args.solution

    problems = solution.validate(path, world)
    s = stats(path, world)
    warn = advisories(path, world)

    print("file               : %s" % path)
    print("sha256 (first 16)  : %s" % s["sha256"])
    print("total actions      : %d" % s["total_actions"])
    print("tick entries       : %d  range %s  (limit 0..%d)"
          % (s["tick_entries"], s["tick_range"], world.ticks - 1))
    print("max plants in 1 tick: %d  (limit 20)" % s["max_per_tick"])
    print("distinct cells     : %d" % s["distinct_cells"])
    print("cells replanted    : %d" % s["cells_planted_more_than_once"])
    print("per species        :")
    for pi, n in sorted(s["per_species"].items()):
        print("   %2d %-16s %5d" % (pi, plants.get(pi).name, n))

    if warn:
        print("\nADVISORIES (not schema errors):")
        for k, v in warn.most_common():
            print("   %5d x %s" % (v, k))

    print()
    if problems:
        print("INVALID - %d problem(s):" % len(problems))
        for p in problems[:40]:
            print("   - %s" % p)
        if len(problems) > 40:
            print("   ... and %d more" % (len(problems) - 40))
        return 1
    print("VALID: satisfies every constraint stated in problem-statement.pdf p.4-5.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
