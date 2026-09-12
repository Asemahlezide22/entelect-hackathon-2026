#!/usr/bin/env python3
"""Generate the submission for every level from one tuned parameter table.

    py build_all.py              # writes out/solution*.json and scores them
    py build_all.py --no-score   # just write the files

BEST holds the parameters `sweep.py` selected, ranked on the WORST rule reading
in bench.READINGS rather than the best, so nothing here depends on one
optimistic reading of the spread rules.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench                                                  # noqa: E402
from photospheria import world as world_mod                   # noqa: E402
from strategies import balanced                               # noqa: E402

ROOT = Path(__file__).resolve().parent

OUT = {1: "out/solution.json", 2: "out/solution_level2.json",
       3: "out/solution_level3.json", 4: "out/solution_level4.json"}

# level -> strategies.balanced.build kwargs.
#
# The split between levels 1-2 and 3-4 is not a tuning artefact, it is the
# season schedule.  Levels 1 and 2 end in SPRING, so every species can still
# spread through the closing window and equal bands work.  Levels 3 and 4 end
# in WINTER, and Rose Bush and Lavender both carry no_winter_spread: their final
# count is exactly the cells we paint for them and nothing more.  There they get
# a small COMPACT block each (a thin band is crossed by a neighbour's frontier
# in 14 ticks) while the three species that still spread take the rest.
BEST = {
    # 1,800 plantable cells, 1,980 slots in the survival window: the whole board
    # can be painted outright, so there is no seeding phase at all.
    1: dict(paint="rose", finish_ticks=99, cap=4, seed_tick=0, fast_stride=16),
    # 6,135 plantable, 1,980 paintable - spreading covers the other two thirds.
    2: dict(paint="rose", finish_ticks=99, cap=4, seed_tick=0, fast_stride=0),
    3: dict(paint="weak", finish_ticks=99, cap=6, seed_tick=0, fast_stride=8,
            blocks=True, band_weights=[1, 0.30, 1, 0.30, 1]),
    4: dict(paint="weak", finish_ticks=99, cap=6, seed_tick=0, fast_stride=12,
            blocks=True, band_weights=[1, 0.18, 1, 0.18, 1]),
}


def build(lv, params=None, verbose=False):
    w = world_mod.load(ROOT / ("data/level%d.json" % lv))
    return balanced.build(w, verbose=verbose, **(params or BEST[lv]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="1,2,3,4")
    ap.add_argument("--no-score", action="store_true")
    a = ap.parse_args()

    tot_w = tot_b = 0.0
    for lv in [int(x) for x in a.levels.split(",")]:
        print("L%d  %s" % (lv, BEST[lv]))
        sol = build(lv, verbose=True)
        p = sol.write(ROOT / OUT[lv])
        print("  wrote %s (%d actions, %.0f KB)"
              % (OUT[lv], sol.total_actions(), p.stat().st_size / 1024))
        if not a.no_score:
            r = bench.evaluate(lv, sol, quiet=True)
            for k, s in r["detail"].items():
                print("      [%s] C=%6d d=%.3f H=%.4f long=%.4f score=%.4f %s"
                      % (k, s["C"], s["density"], s["H"], s["longevity"],
                         s["score"], dict(sorted(s["counts"].items()))))
            print("      worst=%.4f mean=%.4f best=%.4f"
                  % (r["worst"], r["mean"], r["best"]))
            tot_w += r["worst"]
            tot_b += r["best"]
    if not a.no_score:
        print("\nTOTAL worst=%.4f (%,.0f)".replace("%,", "%") % (tot_w, tot_w * 1e9))
        print("TOTAL best =%.4f (%.0f)" % (tot_b, tot_b * 1e9))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
