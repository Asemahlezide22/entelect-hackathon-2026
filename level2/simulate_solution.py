#!/usr/bin/env python3
"""
Run a submission JSON through the LOCAL simulator and estimate its score.

IMPORTANT: this is our own reading of problem-statement.pdf, not the official
solver.  Treat the numbers as a way to compare two of OUR strategies, not as a
prediction of the leaderboard.

Usage:
    py simulate_solution.py                       # default assumptions
    py simulate_solution.py --terrains 0          # pessimistic map
    py simulate_solution.py --map                 # print the final garden
    py simulate_solution.py --history             # show how it evolved
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import plants, scoring, simulator, solution, world as world_mod  # noqa: E402
from photospheria.config import SimConfig                                          # noqa: E402

GLYPH = {0: ".", plants.GRASS: "g", plants.ROSE_BUSH: "r", plants.DWARF_SUNFLOWER: "s",
         plants.LAVENDER: "l", plants.OAK_TREE: "O"}


def draw(result):
    w = result.world
    lines = ["    " + "".join(str(i // 10) for i in range(w.cols)),
             "    " + "".join(str(i % 10) for i in range(w.cols))]
    for r in range(w.rows):
        row = []
        for c in range(w.cols):
            k = r * w.cols + c
            pi = result.plant_idx[k]
            if pi:
                row.append(GLYPH.get(pi, "?"))
            elif w.terrain[r][c] is None:
                row.append(" ")
            else:
                row.append("-" if result.dead_matter[k] else ".")
        lines.append("%3d %s" % (r, "".join(row)))
    lines.append("  key: g=Grass r=Rose s=Sunflower l=Lavender O=Oak "
                 ". = empty cell   - = dead matter   ' ' = not in level file")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("solution", nargs="?", default="out/solution.json")
    ap.add_argument("--level", default="data/level1.json")
    ap.add_argument("--terrains", default="0,1,2")
    ap.add_argument("--alpha", type=float, default=1.0)
    ap.add_argument("--k", type=float, default=1.0)
    ap.add_argument("--map", action="store_true")
    ap.add_argument("--history", action="store_true")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parent
    world = world_mod.load(root / args.level)
    cfg = SimConfig(
        plantable_terrains=tuple(int(x) for x in args.terrains.split(",")),
        alpha=args.alpha, k=args.k,
    )
    actions = solution.load(root / args.solution)

    t0 = time.perf_counter()
    result = simulator.simulate(world, actions, cfg, record_history=args.history)
    elapsed = time.perf_counter() - t0

    print("simulated %d ticks in %.2f s   [terrains=%s dead-matter drain=%.1f "
          "displace=%s crosshatch=%s]"
          % (world.ticks, elapsed, cfg.plantable_terrains, cfg.drain_dead_matter,
             cfg.spread_displaces_established, cfg.crosshatch_shape))
    print()

    if result.rejected:
        print("REJECTED ACTIONS: %d  (solver would silently ignore these)"
              % len(result.rejected))
        for line in result.rejected[:8]:
            print("   - %s" % line)
        if len(result.rejected) > 8:
            print("   ... and %d more" % (len(result.rejected) - 8))
        print()

    print("FINAL STATE")
    print("  species alive   : %d of 5 available" % result.species_present())
    print("  cells occupied  : %d of %d" % (result.occupied, world.total_cells))
    print("  plants that died: %s" % result.deaths)
    print()
    s = scoring.score(result)
    print(s)
    print()
    best_h = scoring.theoretical_max_entropy(5, cfg.entropy_base_species)
    print("  max possible H with 5 species (log base %d) = %.4f  -> we are at %.1f%% of it"
          % (cfg.entropy_base_species, best_h, 100 * s.entropy / best_h if best_h else 0))
    print()
    print("  sensitivity to the hidden parameters (final score):")
    grid = scoring.score_grid(result)
    alphas = sorted({a for a, _ in grid})
    ks = sorted({k for _, k in grid})
    print("        " + "".join("  k=%-6g" % k for k in ks))
    for a in alphas:
        print("  a=%-4g" % a + "".join("  %-8.5f" % grid[(a, k)] for k in ks))

    if args.history:
        print("\nHISTORY")
        for h in result.history:
            names = " ".join("%s=%d" % (plants.get(i).name.split()[0], n)
                             for i, n in sorted(h["counts"].items()))
            print("  tick %3d %-7s occupied=%4d  %s"
                  % (h["tick"], h["season"], h["occupied"], names))

    if args.map:
        print()
        print(draw(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
