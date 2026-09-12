"""
"bands3" - equal-area territory bands with a same-species top-up paint.

Three facts from the official evaluation logs drive this design.

1.  A planting action on an OCCUPIED cell is denied, not applied.  So an action
    is only ever worth a cell if the target is still empty when the tick runs.
    Painting a band with the band's OWN species makes a denial harmless: the
    cell already holds the species we wanted there, so composition is unchanged
    and only the slot is lost.

2.  Species keep their own band because most spread shapes are anisotropic.
    Column spreaders (Crimson Vine, Stone Reed) can never leave a column band;
    Row spreaders (Rose Bush) can never leave a row band.  Final counts then
    track band AREA, and equal areas are exactly what maximises H.

3.  no_winter_spread (Rose Bush, Lavender) is fatal on Levels 3 and 4: their
    last season change is Winter on tick 700 and every plant alive on tick 800
    must have been created after tick 700, so those two can only ever be
    hand-planted there.  On Levels 1 and 2 the final window is Spring and they
    spread normally.

Everything that is alive at scoring time has to be created in the last
`window` ticks: a cell starts with 100 nutrient points and loses one per tick,
so anything planted before T-100 has starved by the final tick.
"""
from __future__ import annotations

from photospheria import plants, solution

PER_TICK = solution.MAX_PLANTS_PER_TICK
GRASS, ROSE, SUN, LAV, OAK = 1, 2, 5, 6, 12
CRIMSON_VINE, STONE_REED, RAZORGRASS = 4, 11, 19


# --------------------------------------------------------------------- board
def soil_at(world, r, c):
    s = world.soil[r][c]
    return 0 if s is None else s


def plantable(world, pi=None):
    """Cells this species may legally occupy.

    Terrain must be 0; cells the level file omits default to terrain 0 / soil 0,
    which the Level-1 log confirms - C reached 1,800 on a board whose file lists
    only 720 terrain-0 cells.  Soil must be one the species accepts: the five
    starters take Dirt and Mud but NOT Clay, which is why Level 1 tops out at
    exactly 1,800 cells rather than 2,160.
    """
    soils = set(plants.get(pi).preferred_soil) if pi else {0, 1}
    out = []
    for r in range(world.rows):
        row_t = world.terrain[r]
        row_s = world.soil[r]
        for c in range(world.cols):
            t = row_t[c]
            s = row_s[c]
            if t is None:
                t, s = 0, 0
            if s is None:
                s = 0
            if t == 0 and s in soils:
                out.append((r, c))
    return out


def bands(cells, weights, axis="col"):
    """Split cells into len(weights) groups of proportional CELL COUNT."""
    key = (lambda rc: (rc[1], rc[0])) if axis == "col" else (lambda rc: (rc[0], rc[1]))
    ordered = sorted(cells, key=key)
    n = len(ordered)
    tot = float(sum(weights))
    out, start, acc = [], 0, 0.0
    for i, w in enumerate(weights):
        acc += w
        end = n if i == len(weights) - 1 else int(round(n * acc / tot))
        out.append(ordered[start:end])
        start = end
    return out


# ------------------------------------------------------------------- seeding
def seeds_for(pi, band, stride):
    """Species-aware seeding pattern for one band.

    CrossHatch spreaders (Dwarf Sunflower, Lavender, Razorgrass) only ever move
    by (+-d, +-d), which preserves the parity of r+c, so one seed reaches at
    most half its band; seeding both parities is what lets them fill it.
    Column spreaders need a seed per column, Row spreaders one per row.
    """
    if not band:
        return []
    p = plants.get(pi)
    st = p.spread_type
    inband = set(band)
    if st == "Column":
        by_col = {}
        for (r, c) in band:
            by_col.setdefault(c, []).append(r)
        out = []
        for c, rs in sorted(by_col.items()):
            rs.sort()
            mid = rs[len(rs) // 2]
            out.append((mid, c))
            # die_if_isolated kills a lone Crimson Vine before it can spread,
            # so every column seed goes down as a vertical pair
            if (mid + 1, c) in inband:
                out.append((mid + 1, c))
        return out
    if st == "Row":
        by_row = {}
        for (r, c) in band:
            by_row.setdefault(r, []).append(c)
        return [(r, sorted(cs)[len(cs) // 2]) for r, cs in sorted(by_row.items())]
    if st == "CrossHatch":
        half = max(1, stride // 2)
        a = [rc for rc in band if rc[0] % stride == 0 and rc[1] % stride == 0]
        b = [rc for rc in band
             if rc[0] % stride == half and rc[1] % stride == 0]
        seen, out = set(), []
        for rc in a + b:
            if rc not in seen:
                seen.add(rc)
                out.append(rc)
        return out or band[:: max(1, len(band) // 8)]
    out = [rc for rc in band if rc[0] % stride == 0 and rc[1] % stride == 0]
    return out or band[:: max(1, len(band) // 8)]


def emit(sol, items, first, last):
    """Place items from tick `first`, 20 per tick, stopping after `last`.

    A cell is only ever aimed at once per solution: the scatter pool and a band
    seed lattice can pick the same cell, and two actions on one cell in one tick
    is a malformed submission (and a guaranteed denial in any later tick).
    """
    seen = getattr(sol, "_bands3_seen", None)
    if seen is None:
        seen = set()
        sol._bands3_seen = seen
    t = first
    n = 0
    for pi, r, c in items:
        if (r, c) in seen:
            continue
        while t <= last and sol.free_slots(t) == 0:
            t += 1
        if t > last:
            break
        sol.plant(t, pi, r, c)
        seen.add((r, c))
        n += 1
    return n, t


def interleave(pools):
    """Round-robin the per-band lists so a short tick budget still seeds all."""
    out = []
    k = 0
    mx = max((len(p) for p in pools), default=0)
    while k < mx:
        for p in pools:
            if k < len(p):
                out.append(p[k])
        k += 1
    return out


def build(world, band_species, strides, window=100, axis="col", weights=None,
          scatter=(), scatter_start=None, topup=True, primer=(),
          seed_span=None, sol=None, verbose=False, scatter_band=None,
          topup_cap=None, delays=None, seed_targets=None):
    """
    band_species : species index per band, in band order
    strides      : {species: lattice stride}
    scatter      : [(species, count)] hand-planted singles, for species that
                   cannot spread in the final window (Rose/Lavender on L3-L4)
    primer       : [(species, count, tick)] plantings BEFORE the scoring window
                   whose only job is to satisfy an unlock condition, e.g. Grass
                   coverage above 5% so that Razorgrass becomes placeable
    """
    T = world.ticks
    start = T - window
    last = T - 1
    sol = sol or solution.Solution()
    cells = plantable(world)
    w = weights or [1] * len(band_species)
    band_cells = bands(cells, w, axis)

    # ---- primer: unlock enablers, planted before the scoring window --------
    for pi, count, tick in primer:
        ok = set(plants.get(pi).preferred_soil)
        pool = [rc for rc in cells if soil_at(world, *rc) in ok]
        step = max(1, len(pool) // max(count, 1))
        items = [(pi, r, c) for (r, c) in pool[::step]][:count]
        emit(sol, items, tick, start - 1)

    # ---- band seeds -------------------------------------------------------
    # `seed_targets` sizes the lattice to the action budget instead of fixing a
    # stride: a band only reaches its final count if the seeds can cover it in
    # the ticks available, and leftover slots are worth nothing.
    per_band = []
    for pi, band in zip(band_species, band_cells):
        ok = set(plants.get(pi).preferred_soil)
        band = [rc for rc in band if soil_at(world, *rc) in ok]
        st = strides.get(pi, 12)
        if seed_targets and pi in seed_targets and band:
            want = max(1, seed_targets[pi])
            st = max(1, int((len(band) / want) ** 0.5))
            for _ in range(6):
                n = len(seeds_for(pi, band, st))
                if n <= want * 1.15 or st > 64:
                    break
                st += 1
        per_band.append((pi, band, seeds_for(pi, band, st)))

    # ---- scatter FIRST ----------------------------------------------------
    # Rose Bush and Lavender cannot spread in a winter window, so every cell
    # they end up holding is one we placed by hand.  Place them on the first
    # ticks of the window, while the board is still empty and nothing can deny
    # the action - and put them inside `scatter_band`, the band of the LOWEST
    # invasiveness rank, so that no spreader is entitled to displace them.
    sc_items = []
    if scatter:
        pool_all = cells if scatter_band is None else per_band[scatter_band][1]
        pools = []
        for pi, count in scatter:
            ok = set(plants.get(pi).preferred_soil)
            pool = [rc for rc in pool_all if soil_at(world, *rc) in ok]
            step = max(1, len(pool) // max(count, 1))
            pools.append([(pi, r, c) for (r, c) in pool[::step]][:count])
        sc_items = interleave(pools)

    span_end = last if seed_span is None else min(last, start + seed_span)
    delays = delays or {}
    prompt = [i for i in range(len(per_band)) if not delays.get(per_band[i][0])]
    later = [i for i in range(len(per_band)) if delays.get(per_band[i][0])]

    seed_items = [(per_band[i][0], r, c)
                  for (i, (r, c)) in _rr([[(i, rc) for rc in per_band[i][2]]
                                          for i in prompt])]
    # Delayed bands: Razorgrass only becomes placeable once Grass passes 5% of
    # the grid, and Crimson Vine once ten trees have summoned the Canorals.  The
    # earlier bands do both within a few ticks of the window opening, so the
    # unlock needs no pre-window priming - only a short delay.
    #
    # A delayed band must get the FIRST slots of its opening tick, not the ones
    # the other bands have left over.  Waiting its turn cost Razorgrass its
    # whole territory in the first run of this sweep: by the time its seeds went
    # down around tick 750 the neighbouring bands had already spread across it
    # and every action was denied.
    stream = _weave(seed_items, sc_items) if scatter_start is None else seed_items
    head_n = max(0, min(delays.get(per_band[i][0], 0) for i in later) * PER_TICK)         if later else len(stream)
    late_items = []
    for i in sorted(later, key=lambda j: delays[per_band[j][0]]):
        pi = per_band[i][0]
        late_items.extend((pi, r, c) for (r, c) in per_band[i][2])
    ordered = stream[:head_n] + late_items + stream[head_n:]
    placed, next_tick = emit(sol, ordered, start, span_end)
    if scatter_start is not None:
        emit(sol, sc_items, scatter_start, last)

    # ---- top-up: paint whatever slots remain with each band's own species --
    # Worth it only when the board is small enough that the leftover slots can
    # actually cover it (Levels 1-2).  On Levels 3-4 there are 2,000 slots for
    # 18k-54k cells, so a blanket top-up buys nothing and every action lands on
    # a cell that spreading has already taken: cap it, or skip it.
    if topup:
        pools = []
        for pi, band, seeds in per_band:
            taken = set(seeds)
            pools.append([(pi, r, c) for (r, c) in band if (r, c) not in taken])
        fill = interleave(pools)
        if topup_cap is not None:
            fill = fill[:topup_cap]
        emit(sol, fill, start, last)

    if verbose:
        print("  window %d..%d bands=%s seeds=%d placed=%d actions=%d"
              % (start, last, band_species,
                 sum(len(s) for _, _, s in per_band), placed, sol.total_actions()))
    return sol


def _rr(pools):
    """Round-robin over pools of (band_index, cell)."""
    out = []
    k = 0
    mx = max((len(p) for p in pools), default=0)
    while k < mx:
        for p in pools:
            if k < len(p):
                out.append(p[k])
        k += 1
    return out


def _weave(a, b):
    """Interleave two streams proportionally, so both finish together."""
    if not b:
        return list(a)
    if not a:
        return list(b)
    out = []
    ia = ib = 0
    na, nb = len(a), len(b)
    while ia < na or ib < nb:
        if ib >= nb or (ia < na and ia * nb <= ib * na):
            out.append(a[ia]); ia += 1
        else:
            out.append(b[ib]); ib += 1
    return out
