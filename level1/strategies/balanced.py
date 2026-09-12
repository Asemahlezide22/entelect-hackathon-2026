"""
"Balanced territories" - the strategy the official logs actually justify.

EVIDENCE (all from official evaluation logs, not from our simulator):

1.  SCORING.  score = 0.8 * H31 * C/(rows*cols) + 0.2 * sum(age)/(rows*cols*T).
    Reproduced to 9 decimals on six independent official runs.  Density and
    entropy are the whole game; longevity is a 20% garnish.

2.  PLANTABLE = terrain 0 AND soil in preferred_soil, with cells the level file
    omits defaulting to terrain 0 / soil 0.  Level 1 finished with C = 1800,
    which is exactly the size of that set - the board saturates.

3.  SPREAD NEVER DISPLACES.  The Level 1 accounting closes exactly:
        cells gained by spread = 244 (Grass) + 88 (Sun) + 140 (Oak) = 472
        cells never planted    = 1800 - 1328 successful plantings   = 472
    A planting onto an occupied cell is DENIED (the logs say so 2,907 times),
    and spread only ever fills EMPTY cells.  So the final composition is
    decided by *who reaches each empty cell first*, never by displacement.

4.  SPREAD GEOMETRY IS THE HIDDEN CONSTRAINT.  Closing each species' offset set
    under repetition gives the fraction of the board it can ever reach:
        Grass     VonNeumann r1 -> 100%
        Oak       Moore      r2 -> 100%
        Lavender  CrossHatch r1 ->  50%  (diagonal moves preserve (r+c) parity)
        Dwarf Sun CrossHatch r2 ->  50%  (same parity trap)
        Rose Bush Row        r1 ->   2%  (it can NEVER leave its own row)
    This is why Lavender went 127 seeds -> 0 survivors on Level 3, and why Rose
    gained exactly zero cells on Level 1.  Seeds must therefore be laid out per
    species: Rose needs one seed per ROW, the CrossHatch pair need seeds on
    BOTH parities, Grass and Oak can use a sparse lattice.

DESIGN.  Split the plantable cells into k equal-count contiguous ROW bands, one
species each - row bands so that Rose's rows run the full width of its own
band.  Seed each band with a species-appropriate lattice early enough that
spreading saturates it, then spend every remaining action in the final ticks
painting cells the spread may not have reached.  Because spread cannot
displace, bands do not erode: the composition we lay down is the composition
that is scored, and equal bands put H on its k-species ceiling log(k)/log(31).
"""
from __future__ import annotations

from photospheria import solution

PER_TICK = solution.MAX_PLANTS_PER_TICK
GRASS, ROSE, SUN, LAV, OAK = 1, 2, 5, 6, 12
STARTERS = (GRASS, ROSE, SUN, LAV, OAK)

# Chebyshev cells the frontier advances per tick, from spread_range/spread_rate.
SPEED = {GRASS: 1 / 2, ROSE: 1 / 2, SUN: 2 / 4, LAV: 1 / 3, OAK: 2 / 7}
# Species whose reachable set is only one (r+c) parity class.
PARITY_BOUND = {SUN, LAV}
# Species that cannot change row at all.
ROW_BOUND = {ROSE}
# Fraction of the board a species can ever reach from one seed (offset-set
# closure): Grass/Oak anything, the CrossHatch pair one (r+c) parity class,
# Rose Bush only its own row.  SPEED * REACH is how dangerous a species is to
# its neighbours, and how well it can fill its own band without our help.
REACH = {GRASS: 1.0, ROSE: 0.02, SUN: 0.5, LAV: 0.5, OAK: 1.0}


def plantable(world, soils=(0, 1)):
    """terrain 0 and a soil the starters accept; omitted cells default to 0/0."""
    out = []
    for r in range(world.rows):
        tr, sr = world.terrain[r], world.soil[r]
        for c in range(world.cols):
            t = tr[c]
            if t is None:
                out.append((r, c))          # unlisted => terrain 0, soil 0
            elif t == 0 and (sr[c] if sr[c] is not None else 0) in soils:
                out.append((r, c))
    return out


def row_bands(cells, k, weights=None):
    """k contiguous bands split on whole rows, sized in proportion to `weights`.

    Whole rows, because Rose Bush can only ever spread along a row: if a band
    held a partial row, Rose could not reach the rest of it.

    Equal bands are what maximises entropy, but only if every species can
    actually hold its band.  Rose Bush cannot - it ends a run with roughly the
    number of cells we painted for it - so it is given a band it can fill and
    the others absorb the rest.  Entropy is forgiving here: a species on 7% of
    the board instead of 20% costs only 4% of H, while a band Rose cannot hold
    is a band its neighbours take, which costs far more.
    """
    by_row = {}
    for (r, c) in cells:
        by_row.setdefault(r, []).append(c)
    rows = sorted(by_row)
    total = len(cells)
    w = list(weights) if weights else [1.0] * k
    wsum = float(sum(w)) or 1.0
    edges, acc = [], 0.0
    for i in range(k):
        acc += w[i] / wsum
        edges.append(total * acc)
    bands, cur, done, bi = [], [], 0, 0
    for r in rows:
        cur.append(r)
        done += len(by_row[r])
        if done >= edges[bi] and bi < k - 1:
            bands.append(cur)
            cur, bi = [], bi + 1
    bands.append(cur)
    while len(bands) < k:
        bands.append([])
    return [[(r, c) for r in band for c in sorted(by_row[r])] for band in bands]


def carve_block(cells, target, corner=0):
    """Take a compact, roughly square block of `target` cells from one corner.

    A band is the wrong shape for a species that cannot spread.  Rose Bush's
    final count is just the cells we managed to paint before a neighbour's
    frontier arrived, so what matters is how long the frontier takes to cross
    its territory.  A 2,000-cell band on Level 4 is 7 rows deep and is overrun
    in 14 ticks; the same 2,000 cells as a 45x45 block take 44 ticks to reach
    the middle of, which is longer than it takes us to paint it.
    """
    if not cells or target <= 0:
        return [], list(cells)
    rows = sorted({r for (r, _) in cells})
    cols = sorted({c for (_, c) in cells})
    side = max(1, int(target ** 0.5))
    r0 = rows[0] if corner in (0, 1) else max(rows[0], rows[-1] - side)
    c0 = cols[0] if corner in (0, 2) else max(cols[0], cols[-1] - side)
    # grow the square until it holds `target` plantable cells
    inside = set()
    for grow in range(side, side * 6 + 2):
        lo_r = r0 if corner in (0, 1) else max(rows[0], rows[-1] - grow)
        lo_c = c0 if corner in (0, 2) else max(cols[0], cols[-1] - grow)
        inside = {(r, c) for (r, c) in cells
                  if lo_r <= r <= lo_r + grow and lo_c <= c <= lo_c + grow}
        if len(inside) >= target:
            break
    block = sorted(inside)[:target]
    bset = set(block)
    return block, [rc for rc in cells if rc not in bset]


def seeds_for(pi, band_cells, dt, cap=64):
    """Lattice of seed cells for species `pi` whose spread closes it in `dt` ticks.

    Stride is twice the distance the frontier covers in dt, so neighbouring
    seeds just meet.  Clamped so a huge dt cannot leave a band with three seeds
    and no redundancy against the death-and-recolonise cycle.
    """
    reach = max(1, int(SPEED[pi] * dt))
    stride = max(2, min(cap, 2 * reach))
    by_row = {}
    for (r, c) in band_cells:
        by_row.setdefault(r, []).append(c)
    rows = sorted(by_row)
    out = []

    if pi in ROW_BOUND:
        # every row, seeds spaced along it - Rose cannot change row
        for r in rows:
            cs = sorted(by_row[r])
            for j in range(0, len(cs), stride):
                out.append((r, cs[j]))
        return out

    if pi in PARITY_BOUND:
        # diagonal movement preserves (r+c) parity: lay the lattice twice, once
        # on each parity class, or half of the band is unreachable for ever.
        for i, r in enumerate(rows):
            if i % stride:
                continue
            cs = sorted(by_row[r])
            for j in range(0, len(cs), stride):
                out.append((r, cs[j]))
                if j + 1 < len(cs):
                    out.append((r, cs[j + 1]))      # opposite parity
        return out

    for i, r in enumerate(rows):
        if i % stride:
            continue
        cs = sorted(by_row[r])
        for j in range(0, len(cs), stride):
            out.append((r, cs[j]))
    return out


def _emit(sol, items, first_tick, last_tick, taken):
    """Schedule (pi, r, c) items from first_tick, 20 per tick, skipping repeats."""
    t, n = first_tick, 0
    for pi, r, c in items:
        if (r, c) in taken:
            continue
        while t <= last_tick and sol.free_slots(t) == 0:
            t += 1
        if t > last_tick:
            break
        sol.plant(t, pi, r, c)
        taken.add((r, c))
        n += 1
    return n, t


def build(world, species=STARTERS, assign=None, seed_tick=0, finish_ticks=99,
          cap=64, order="far", paint="seq", balance="equal",
          band_weights=None, mix=0.75, fast_stride=16, blocks=False,
          rules=None, verbose=False):
    """
    seed_tick    : first tick of the lattice-seeding phase.
    finish_ticks : ticks reserved at the end for the paint phase.  A plant needs
                   to be younger than 100 ticks to still be alive (100
                   nutrients, 1 per tick), so 99 is the useful maximum.
    order        : how the paint phase orders each band's cells.
                   "edge" seals the band's outer rows first.  Spread cannot
                   displace, so once a band's border carries its own species no
                   neighbour can ever get in, and every interior cell is then
                   guaranteed to us whether we paint it or its own species
                   spreads into it.  "far" instead paints the cells furthest
                   from a seed first (useful when Phase A did the sealing).
    """
    T = world.ticks
    last = T - 1
    k = len(species)
    cells = plantable(world)
    # Species that cannot spread during the closing season get a compact block
    # each; everyone else divides what is left into row bands.
    weak_set = ()
    if blocks:
        from photospheria import plants as _pl
        season = world.season_at(T - 1)
        weak_set = tuple(p for p in species
                         if p in ROW_BOUND
                         or (season == "Winter" and _pl.get(p).no_winter_spread))
    if weak_set:
        w = list(band_weights) if band_weights else [1.0] * k
        wsum = float(sum(w)) or 1.0
        rest_cells = list(cells)
        blk = {}
        for n, pi in enumerate(weak_set):
            tgt = int(len(cells) * w[list(species).index(pi)] / wsum)
            blk[pi], rest_cells = carve_block(rest_cells, tgt, corner=n % 4)
        strong = [p for p in species if p not in weak_set]
        sw = [w[list(species).index(p)] for p in strong]
        sbands = row_bands(rest_cells, len(strong), sw)
        bands, it = [], iter(sbands)
        for pi in species:
            bands.append(blk[pi] if pi in weak_set else next(it))
    else:
        bands = row_bands(cells, k, band_weights)
    if assign:                      # which species gets which spatial band
        species = tuple(assign)
    sol = solution.Solution()
    taken = set()

    paint_first = max(0, last - finish_ticks + 1)
    direct_capacity = finish_ticks * PER_TICK

    # ---- Phase A: lattice seeding (skipped when we can simply paint it all) --
    seeded = 0
    if len(cells) > direct_capacity:
        dt = max(1, paint_first - seed_tick)
        items = []
        for pi, band in zip(species, bands):
            for (r, c) in seeds_for(pi, band, dt, cap):
                items.append((pi, r, c))
        # interleave by coarse tile so a truncated seeding phase still covers
        # every band rather than finishing the first one
        items.sort(key=lambda it: (it[1] // 8, it[2] // 8, it[0]))
        seeded, _ = _emit(sol, items, seed_tick, paint_first - 1, taken)

    # ---- Phase B: paint every remaining cell we have slots for ---------------
    # Ordered by distance from the nearest seed of the same band, so the paint
    # phase spends actions where spreading is least likely to have reached.
    # Denials are harmless (the cell already holds the right species) but they
    # are wasted actions, so we avoid them where we can.
    # How the paint budget is split between species.  Equal shares are wrong on
    # the long boards: over 800 ticks a plant dies of starvation about eight
    # times over, and Rose Bush (row-bound) and Lavender (parity-bound) cannot
    # recolonise their own band fast enough, so they bleed out - the official
    # Level-3 log shows Lavender going 127 seeds -> 0 survivors.  Simulating the
    # seeding phase to the end tells us who will be short, and the paint budget
    # then goes to them in proportion to that shortfall.  Entropy, not density,
    # is what this buys: the weak species are exactly the ones holding H down.
    weight = {pi: 1.0 for pi in species}
    if balance == "deficit" and seeded:
        from photospheria import fastsim
        head = {t: v for t, v in sol.as_actions().items() if t < paint_first}
        res = fastsim.simulate(world, head,
                               rules or fastsim.Rules(displace="never"))
        tot = sum(res.counts.values()) or 1
        target = tot / float(k)
        weight = {pi: max(0.05, target - res.counts.get(pi, 0)) for pi in species}
        if verbose:
            print("  phaseA-only counts=%s -> paint weights=%s"
                  % (dict(sorted(res.counts.items())),
                     {p: round(v) for p, v in weight.items()}))

    per = {}
    for pi, band in zip(species, bands):
        seeds = [rc for rc in band if rc in taken]
        rest = [rc for rc in band if rc not in taken]
        if order == "edge":
            brows = sorted({r for (r, _) in band})
            top, bot = (brows[0], brows[-1]) if brows else (0, 0)
            bcols = {}
            for (r, c) in band:
                bcols.setdefault(r, []).append(c)
            # depth into the band: rows from either horizontal edge, columns
            # from either end of the row.  Seal the shallowest cells first.
            rest.sort(key=lambda rc: (min(rc[0] - top, bot - rc[0]),
                                      min(rc[1] - bcols[rc[0]][0],
                                          bcols[rc[0]][-1] - rc[1])))
        elif seeds:
            sr = {}
            for (r, c) in seeds:
                sr.setdefault(r, []).append(c)

            def dist(rc, sr=sr):
                r, c = rc
                best = 10 ** 6
                for dr in range(-4, 5):
                    for cc in sr.get(r + dr, ()):
                        d = abs(dr) + abs(c - cc)
                        if d < best:
                            best = d
                return -best
            rest.sort(key=dist)
        per[pi] = [(pi, r, c) for (r, c) in rest]

    # Painting a band early hands that species a head start: every cell of a
    # band still unpainted is empty, and an earlier species will spread into it.
    # Round-robin therefore keeps everyone level - EXCEPT Rose Bush, which
    # cannot leave its own row and so loses its band to the neighbours before it
    # can paint it (132 of 364 cells survived when it went round-robin).  Rose
    # cannot over-expand even given the whole run, so painting its band first is
    # free insurance; everyone else then advances in step.
    if paint == "seq":
        inter = []
        for pi in sorted(species, key=lambda p: SPEED[p] * REACH[p]):
            inter.extend(per[pi])
    else:
        if paint == "weak":
            # Whatever cannot spread during the closing season has a final count
            # equal to the cells we paint for it and nothing more, so it must be
            # painted first, before a neighbour takes those cells.  On Levels 3
            # and 4 the last 100 ticks are Winter and both Rose Bush and
            # Lavender carry no_winter_spread, which is why they collapsed to
            # ~200 cells however many we seeded.
            from photospheria import plants as _pl
            season = world.season_at(last)
            first = [p for p in species
                     if p in ROW_BOUND
                     or (season == "Winter" and _pl.get(p).no_winter_spread)]
        elif paint == "rose":
            first = [p for p in species if p in ROW_BOUND]
        else:
            first = []
        rest = [p for p in species if p not in first]
        # weighted round-robin: each species accumulates `weight` credit per
        # round and spends one credit per cell, so shares track the weights.
        fast = []
        credit = {p: 0.0 for p in rest}
        cursor = {p: 0 for p in rest}
        norm = max((weight[p] for p in rest), default=1.0) or 1.0
        while any(cursor[p] < len(per[p]) for p in rest):
            progressed = False
            for pi in rest:
                credit[pi] += weight[pi] / norm
                while credit[pi] >= 1.0 and cursor[pi] < len(per[pi]):
                    fast.append(per[pi][cursor[pi]])
                    cursor[pi] += 1
                    credit[pi] -= 1.0
                    progressed = True
            if not progressed:
                break

        weak = []                      # round-robin inside the weak group too,
        for i in range(max((len(per[p]) for p in first), default=0)):
            for pi in first:           # or the second one is painted too late
                if i < len(per[pi]):   # and its cells are gone
                    weak.append(per[pi][i])

        if not weak:
            inter = fast
        else:
            # The two groups want opposite things from the closing window.  A
            # spreader only needs a COARSE lattice, but it needs it in the first
            # few ticks, because a seed laid at tick T-20 only reaches 10 cells.
            # A non-spreader needs one action per cell it will ever own, and it
            # needs them before a neighbour's frontier arrives.  So: front-load
            # a cheap lattice for the spreaders, then hand the whole rest of the
            # budget to the species that cannot spread.
            if fast_stride < 2:
                # No front-loading: the non-spreaders take their cells first and
                # the spreaders fill in behind them.  Right when the board is
                # small enough that the spreaders close their bands anyway
                # (Levels 1 and 2), wrong when they need a head start.
                inter = weak + fast
                head = tail = None
            else:
                seen, head, tail = {}, [], []
                for it in fast:
                    pi, r, c = it
                    key = (pi, r // fast_stride, c // fast_stride)
                    if key in seen:
                        tail.append(it)
                    else:
                        seen[key] = 1
                        head.append(it)
                inter = head + weak + tail
    painted, _ = _emit(sol, inter, paint_first, last, taken)

    if verbose:
        print("  plantable=%d bands=%s" % (len(cells), [len(b) for b in bands]))
        print("  seeded=%d (tick %d+) painted=%d (ticks %d..%d) total=%d"
              % (seeded, seed_tick, painted, paint_first, last,
                 sol.total_actions()))
    return sol
