#!/usr/bin/env python3
"""
Level 1 solution generator.

    py generate_solution.py                  # v2 (default) -> out/solution.json
    py generate_solution.py --strategy v1    # the simple baseline
    py generate_solution.py --early-tick 301 # experimental, see UNKNOWN #3

Two strategies live here:

  v1 "late even paint"  - split every plantable cell into 5 equal blocks and
    paint them all in the last 35 ticks.  Simple, robust, scores ~0.104 in the
    local simulator.

  v2 "burn, then phased paint" - adds the generation-1 dead-matter burn and
    splits the species into an early phase (longevity) and a late phase
    (invasive species that must not be given time to act).  See
    strategies/phased_paint.py for the reasoning.  Scores ~0.12 locally.

ASSUMPTION (--terrains, default 0,1,2): the level file gives cells a `terrain`
of 0/1/2 and the PDF never defines the enum.  Terrain 0 is certainly plantable.
We aim at all three anyway, because an illegal planting action is silently
IGNORED by the solver (p.5), never rejected, and we have 10,000 planting slots
for at most 700 cells.  Hedging this unknown is free.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photospheria import plants, solution, world as world_mod   # noqa: E402
from photospheria.config import SimConfig                        # noqa: E402
from strategies import phased_paint, territory                   # noqa: E402

# Least -> most invasive.  v1 plants in this order so the species that can
# overwrite others go in last and have the fewest ticks to act.
SPECIES_BY_INVASIVENESS = [
    plants.GRASS,             # rank 1  - cannot displace anything
    plants.LAVENDER,          # rank 2
    plants.ROSE_BUSH,         # rank 2
    plants.DWARF_SUNFLOWER,   # rank 4
    plants.OAK_TREE,          # rank 10 - also casts shade that kills Grass
]
PLANTS_PER_TICK = solution.MAX_PLANTS_PER_TICK


def build_v1(world, terrains=(0, 1, 2), last_tick=None, verbose=True):
    """Baseline: equal contiguous blocks, painted as late as they fit."""
    cells = phased_paint.target_cells(world, terrains)
    blocks = phased_paint.split_blocks(cells, SPECIES_BY_INVASIVENESS)

    ticks_needed = -(-len(cells) // PLANTS_PER_TICK)
    last_tick = world.ticks - 1 if last_tick is None else last_tick
    tick = last_tick - ticks_needed + 1
    if tick < 0:
        raise ValueError("not enough ticks to paint %d cells" % len(cells))

    sol = solution.Solution()
    for pi in SPECIES_BY_INVASIVENESS:
        for (r, c) in blocks[pi]:
            while sol.free_slots(tick) == 0:
                tick += 1
            sol.plant(tick, pi, r, c)

    if verbose:
        print("cells targeted : %d" % len(cells))
        print("ticks used     : %d..%d" % (last_tick - ticks_needed + 1, tick))
        for pi in SPECIES_BY_INVASIVENESS:
            p = plants.get(pi)
            print("  %-16s index=%2d cells=%4d maturity=%2d invasiveness=%2d"
                  % (p.name, pi, len(blocks[pi]), p.time_to_maturity, p.invasiveness_rank))
        print("total actions  : %d" % sol.total_actions())
    return sol


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate the Level 1 solution JSON")
    ap.add_argument("--strategy", choices=("v1", "v2", "territory"), default="v2",
                    help="territory = one species per band (best on the big boards)")
    ap.add_argument("--stride", default="4",
                    help="lattice spacing; either one int, or per-species "
                         "as plant:stride pairs e.g. 1:6,2:1,5:2,6:3,12:5")
    ap.add_argument("--seed-start", type=int, default=None)
    ap.add_argument("--bands", default=None,
                    help="territory: comma list of plant indices, one per band "
                         "(default 1,2,5,6,12)")
    ap.add_argument("--late-bands", default="",
                    help="territory: indices seeded later, once their unlock "
                         "condition has been satisfied by the earlier bands")
    ap.add_argument("--late-tick", type=int, default=None)
    ap.add_argument("--level", default="data/level1.json")
    ap.add_argument("--out", default="out/solution.json")
    ap.add_argument("--terrains", default="0,1,2")
    ap.add_argument("--early-tick", type=int, default=401,
                    help="v2 only: first tick of the early phase. 401 is safe "
                         "under every reading of the nutrient rules; 301 nearly "
                         "doubles longevity but relies on the dead-matter bonus.")
    ap.add_argument("--burn", action="store_true",
                    help="v2 only: add the generation-1 dead-matter carpet "
                         "(no benefit at early-tick 401; kept for experiments)")
    ap.add_argument("--no-hedge", action="store_true",
                    help="v2 only: do not aim at the cells level1.json omits")
    ap.add_argument("--slack", type=int, default=0,
                    help="v2: relax the late-phase deadlines by N ticks")
    ap.add_argument("--early", default=None,
                    help="v2: comma-separated plant indices for the early phase "
                         "(default 1,2,6 = Grass,Rose,Lavender)")
    ap.add_argument("--exclude", default="",
                    help="v2: comma-separated plant indices to leave out entirely")
    ap.add_argument("--last-tick", type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parent
    world = world_mod.load(root / args.level)
    terrains = tuple(int(x) for x in args.terrains.split(","))

    if not args.quiet:
        print(world_mod.describe(world, SimConfig(plantable_terrains=terrains)))
        print()
        print("strategy: %s" % args.strategy)

    if args.strategy == "territory":
        # One species per band: each expands into its OWN empty space instead
        # of contesting the same cells, so the final counts track band area -
        # which we make equal, and equal counts is what maximises entropy.
        seed = args.seed_start if args.seed_start is not None else world.ticks - 99
        st = (int(args.stride) if ":" not in args.stride else
              {int(k): int(v) for k, v in
               (pair.split(":") for pair in args.stride.split(","))})
        bands = ([int(x) for x in args.bands.split(",")] if args.bands
                 else list(territory.STARTERS))
        late = [int(x) for x in args.late_bands.split(",") if x.strip()]
        early = [b for b in bands if b not in late]
        cells = territory.bands(territory.plantable(world), len(bands), "col")
        sol = territory.build(world, species=early, stride=st, seed_start=seed,
                              band_cells=cells[:len(early)])
        # Late bands hold species whose unlock needs coverage the early bands
        # must build first - e.g. Razorgrass needs Grass coverage > 0.05.
        lt = args.late_tick if args.late_tick is not None else seed + 29
        for j, sp in enumerate(late):
            sol = territory.build(world, species=[sp], stride=st, seed_start=lt,
                                  sol=sol, band_cells=[cells[len(early) + j]])
        if not args.quiet:
            print("territory: stride=%s seed_start=%d actions=%d"
                  % (st, seed, sol.total_actions()))
    elif args.strategy == "v1":
        sol = build_v1(world, terrains=terrains, last_tick=args.last_tick,
                       verbose=not args.quiet)
    else:
        early = (tuple(int(x) for x in args.early.split(","))
                 if args.early else phased_paint.DEFAULT_EARLY)
        exclude = tuple(int(x) for x in args.exclude.split(",") if x.strip())
        sol = phased_paint.build(world, terrains=terrains,
                                 early_tick=args.early_tick,
                                 burn=args.burn,
                                 hedge_unlisted=not args.no_hedge,
                                 last_tick=args.last_tick,
                                 early=early, slack=args.slack,
                                 exclude=exclude,
                                 verbose=not args.quiet)

    path = sol.write(root / args.out)
    if not args.quiet:
        print("\nwrote %s (%.1f KB)" % (path, path.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
