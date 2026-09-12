#!/usr/bin/env python3
"""
Coarse-to-fine sweep for every level, scored with the scoring function the
official evaluation logs CONFIRMED:

    density_factor = C / (rows*cols)          (alpha = 1, exactly)
    main_score     = entropy * density_factor
    score          = 0.8*main + 0.2*longevity (k = 1)
    leaderboard    = score * 1e9

Two mechanics the logs also settled, both of which invalidated earlier work:
  * a player planting action on an OCCUPIED cell is DENIED, not a replacement
    ("plant already occupies cell" appears 2,907 times in our own logs);
  * the cells the level file omits ARE plantable - Level 1 finished with 1,800
    occupied cells on a map that lists only ~700.

Keeps a BEST record per level and never overwrites a solution file unless the
candidate beats the incumbent on the confirmed score.
"""
from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import plants, scoring, simulator, world as world_mod   # noqa: E402
from photospheria.config import SimConfig                                  # noqa: E402
from strategies import phased_paint as PP                                  # noqa: E402

ROOT = Path(__file__).resolve().parent
TERRAINS = (0, 1, 2, 3, 4)
G, R, L, S, O = (plants.GRASS, plants.ROSE_BUSH, plants.LAVENDER,
                 plants.DWARF_SUNFLOWER, plants.OAK_TREE)

#: Official results for the files currently on the leaderboard.
OFFICIAL = {1: 0.257574, 2: 0.072866, 3: 0.010048, 4: None}

LEVELS = {
    1: ("data/level1.json", "out/solution.json"),
    2: ("data/level2.json", "out/solution_level2.json"),
    3: ("data/level3.json", "out/solution_level3.json"),
    4: ("data/level4.json", "out/solution_level4.json"),
}

#: Which species are planted in the EARLY phase.  Everything else is packed
#: against the final tick where it cannot mature, spread or shade.
EARLY_SETS = [
    ("G+R+L",   (G, R, L)),
    ("R+L",     (R, L)),
    ("G+R+L+S", (G, R, L, S)),
    ("L",       (L,)),
    ("R",       (R,)),
    ("G",       (G,)),
]


def evaluate(world, sol, dm=0.5):
    cfg = SimConfig(plantable_terrains=TERRAINS, drain_dead_matter=dm)
    res = simulator.simulate(world, sol.as_actions(), cfg)
    return scoring.score(res), res


def sweep_level(lv, offsets=(0, 30, 60), verbose=True):
    path, out = LEVELS[lv]
    world = world_mod.load(ROOT / path)
    T = world.ticks
    best = None
    rows = []

    for (name, early), off, slack in itertools.product(EARLY_SETS, offsets, (0, 6)):
        start = T - 99 - off
        if start < 1:
            continue
        try:
            sol = PP.build(world, terrains=TERRAINS, early_tick=start, burn=False,
                           hedge_unlisted=True, early=early, slack=slack,
                           verbose=False)
        except ValueError:
            continue
        s, res = evaluate(world, sol)
        s_bad, _ = evaluate(world, sol, dm=1.0)
        worst = min(s.final, s_bad.final)
        rows.append((worst, s.final, name, start, slack, res.occupied, s.entropy))
        if best is None or worst > best[0]:
            best = (worst, sol, name, start, slack, res, s)

    rows.sort(reverse=True)
    if verbose:
        print("  %-9s %5s %5s %6s %7s %11s %11s"
              % ("early", "start", "slack", "C", "H", "score", "leaderboard"))
        for worst, fin, name, start, slack, C, H in rows[:6]:
            print("  %-9s %5d %5d %6d %7.4f %11.6f %11.0f"
                  % (name, start, slack, C, H, worst, worst * 1e9))
    return best, rows


def main():
    wanted = [int(a) for a in sys.argv[1:]] or [1, 2, 3, 4]
    summary = {}
    for lv in wanted:
        t0 = time.perf_counter()
        print("=== LEVEL %d ===" % lv)
        best, rows = sweep_level(lv)
        if not best:
            print("   no candidate\n")
            continue
        worst, sol, name, start, slack, res, s = best
        off = OFFICIAL.get(lv)
        print("  BEST: early=%s start=%d slack=%d -> C=%d H=%.4f score=%.6f (%.0f)"
              % (name, start, slack, res.occupied, s.entropy, worst, worst * 1e9))
        if off:
            print("  official now = %.6f (%.0f)  =>  predicted change x%.1f"
                  % (off, off * 1e9, worst / off))
        sol.write(ROOT / (LEVELS[lv][1] + ".candidate"))
        summary[lv] = {"early": name, "start": start, "slack": slack,
                       "C": res.occupied, "H": s.entropy, "score": worst,
                       "official_before": off}
        print("  (%.0fs)\n" % (time.perf_counter() - t0))
    (ROOT / "out" / "sweep_report.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print("report -> out/sweep_report.json")


if __name__ == "__main__":
    raise SystemExit(main())
