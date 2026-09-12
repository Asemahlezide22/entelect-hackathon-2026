"""
"Territory" - one species per band of the board, each expanding into its own
empty space instead of fighting the others for the same cells.

WHY.  The official Level-2 log is the evidence for this design.  1,980 painted
cells in one 50x50 corner grew to C = 6,034 (density 0.862) in under 100 ticks
and the five species kept roughly their painted proportions (Grass 2,993,
Lavender 1,713, Oak 968, Sunflower 191, Rose 169, H = 0.3518).  Spreading does
NOT have to collapse into a monoculture - it collapses only when species are
interleaved and the highest invasiveness_rank keeps taking the same contested
cells, which is exactly what produced the Level-3 Oak monoculture (H = 0.0607).

So: give each species a contiguous band, seed it on a lattice, and let it fill
its own band.  Final counts are then proportional to band AREA, which we choose
to be equal - and equal counts is exactly what maximises entropy.  With five
species, H tends to log(5)/log(31) = 0.4687, the ceiling for a five-species
board, versus the 0.0607 the current Level-3 submission scores.

Band boundaries still erode: a higher rank eats into its neighbour.  That is
what `stride`, the seeding window and the optional top-up paint are for, and
what optimise_levels_v2.py sweeps.
"""
from __future__ import annotations

from photospheria import plants, solution

PER_TICK = solution.MAX_PLANTS_PER_TICK
GRASS, ROSE, SUN, LAV, OAK = 1, 2, 5, 6, 12
STARTERS = (GRASS, ROSE, SUN, LAV, OAK)


def soil_at(world, r, c):
    s = world.soil[r][c]
    return 0 if s is None else s


def terrain_at(world, r, c):
    t = world.terrain[r][c]
    return 0 if t is None else t


def plantable(world, pi=None):
    """Cells terrain-0 and of a soil this species accepts (all starters: 0/1)."""
    soils = plants.get(pi).preferred_soil if pi else {0, 1}
    return [(r, c)
            for r in range(world.rows)
            for c in range(world.cols)
            if terrain_at(world, r, c) == 0 and soil_at(world, r, c) in soils]


def bands(cells, k, axis="col", weights=None):
    """Split the plantable cells into k bands by CELL COUNT, not by width.

    The plantable area is not uniform, and it is the final cell counts that the
    entropy term cares about, so bands are equal-count by default.

    `weights` makes them deliberately unequal.  Final counts are band size minus
    whatever the neighbours erode, and erosion is one-directional: Oak (rank 10)
    eats into Sunflower, Sunflower (4) into Lavender and Rose (2), and those
    into Grass (1).  Giving the aggressive species a SMALLER band and the ones
    that get eaten a LARGER one is how the counts come out equal at the end,
    which is what maximises H.
    """
    key = (lambda rc: (rc[1], rc[0])) if axis == "col" else (lambda rc: (rc[0], rc[1]))
    ordered = sorted(cells, key=key)
    n = len(ordered)
    if weights is None:
        weights = [1.0] * k
    total = float(sum(weights))
    out, start, acc = [], 0, 0.0
    for i in range(k):
        acc += weights[i]
        end = int(round(n * acc / total)) if i < k - 1 else n
        out.append(ordered[start:end])
        start = end
    return out


def _place(sol, tick, last_tick, items):
    """Emit (plant, r, c) items from `tick`, at most 20 per tick."""
    t = tick
    placed = 0
    for pi, r, c in items:
        while t <= last_tick and sol.free_slots(t) == 0:
            t += 1
        if t > last_tick:
            break
        sol.plant(t, pi, r, c)
        placed += 1
    return placed, t


def build(world, species=STARTERS, stride=6, seed_start=0, waves=1,
          wave_gap=150, axis="col", topup_start=None, topup_stride=1,
          sol=None, band_cells=None, reserve_last=0):
    """
    species     : one per band, in band order (left to right / top to bottom)
    stride      : lattice spacing of the seeds inside each band
    seed_start  : tick of the first seeding wave
    waves       : re-seed this many times (a band that dies out is re-founded)
    wave_gap    : ticks between waves
    topup_start : if set, from this tick paint every still-unseeded cell of each
                  band with that band's species, filling whatever spreading did
                  not reach.  This is the coverage insurance policy.
    """
    T = world.ticks
    # reserve_last keeps the final ticks free for the end-game rebalance paint,
    # which is the only move the spread engine has no time to undo.
    last = T - 1 - reserve_last
    sol = sol or solution.Solution()
    cells = band_cells or bands(plantable(world), len(species), axis)

    # ---- seeding waves ---------------------------------------------------
    for wave in range(waves):
        t = seed_start + wave * wave_gap
        if t > last:
            break
        items = []
        for pi, band in zip(species, cells):
            ok = plants.get(pi).preferred_soil
            # PER-SPECIES lattice spacing.  Species fill their band at very
            # different speeds - Rose Bush spreads Row-only (2 cells per event,
            # maturity 10) while Grass spreads to 4 neighbours from maturity 1 -
            # so an equal lattice does not produce equal final counts.  Entropy
            # wants EQUAL counts, so `stride` may be a per-species dict: seed the
            # slow species densely and the fast ones sparsely.
            st = stride if isinstance(stride, int) else stride.get(pi, 6)
            items.extend((pi, r, c) for (r, c) in band
                         if r % st == 0 and c % st == 0
                         and soil_at(world, r, c) in ok)
        # interleave the species so a wave that runs out of ticks still leaves
        # every band seeded, rather than only the first ones
        items.sort(key=lambda it: (it[1] % 4, it[2] % 4, it[1], it[2]))
        limit = last if topup_start is None else min(last, topup_start - 1)
        _place(sol, t, limit, items)

    # ---- top-up paint -----------------------------------------------------
    if topup_start is not None:
        items = []
        for pi, band in zip(species, cells):
            ok = plants.get(pi).preferred_soil
            items.extend((pi, r, c) for (r, c) in band
                         if soil_at(world, r, c) in ok
                         and (r + c) % topup_stride == 0)
        # spread the paint over the whole board rather than finishing one band
        items.sort(key=lambda it: ((it[1] + it[2]) % 997, it[1], it[2]))
        _place(sol, topup_start, last, items)
    return sol
