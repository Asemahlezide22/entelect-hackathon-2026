"""
A reimplementation of the Photospheria tick engine from the problem statement.

THIS IS NOT THE OFFICIAL SOLVER.  It is our best faithful reading of the PDF,
built so we can compare strategies and catch obviously-broken solutions
locally.  Every place where the PDF is silent or self-contradictory is either a
SimConfig switch or is marked ASSUMPTION in a comment.

Tick order (ASSUMPTION - the PDF never states one):
    1. the season becomes whatever the level file declares for this tick
    2. the player's planting actions for this tick are applied (first 20 only)
    3. shade is recomputed from currently-mature shade casters
    4. mature plants that are due perform a spread action
    5. nutrients drain (occupied) / regenerate (empty + dead matter)
    6. death checks (nutrients exhausted, shade, isolation, crowding)
    7. every surviving plant ages by 1

Consequence of (5)+(7): a plant placed on a full-nutrient cell at tick t has
age 100 and 0 nutrients at the end of tick t+99, i.e. it dies on the very tick
it would have been scored.  Strategies therefore keep a safety margin.

Performance note: every phase walks the set of OCCUPIED cells, never the whole
2,500-cell grid, so a full 500-tick run with ~700 plants takes well under a
second.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .plants import get as get_plant
from .unlocks import Tracker

EMPTY = 0


# --------------------------------------------------------------------------
# Spread geometry
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def spread_offsets(spread_type, rng, crosshatch, vonneumann):
    """Cell offsets a plant of this spread_type/range reaches in one action."""
    out = set()
    if spread_type == "Moore":
        for dr in range(-rng, rng + 1):
            for dc in range(-rng, rng + 1):
                out.add((dr, dc))
    elif spread_type == "VonNeumann":
        if vonneumann == "diamond":                 # Manhattan ball
            for dr in range(-rng, rng + 1):
                for dc in range(-rng, rng + 1):
                    if abs(dr) + abs(dc) <= rng:
                        out.add((dr, dc))
        else:                                       # strict N/S/E/W arms
            for d in range(1, rng + 1):
                out.update({(d, 0), (-d, 0), (0, d), (0, -d)})
    elif spread_type == "Row":
        for d in range(1, rng + 1):
            out.update({(0, d), (0, -d)})
    elif spread_type == "Column":
        for d in range(1, rng + 1):
            out.update({(d, 0), (-d, 0)})
    elif spread_type == "CrossHatch":
        # UNKNOWN #5: the PDF says only "structured multi-axis expansion".
        for d in range(1, rng + 1):
            out.update({(d, d), (d, -d), (-d, d), (-d, -d)})    # the X
            if crosshatch == "star":
                out.update({(d, 0), (-d, 0), (0, d), (0, -d)})  # plus the axes
    else:
        raise ValueError("unknown spread_type " + repr(spread_type))
    out.discard((0, 0))
    return tuple(sorted(out))


# --------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------
@dataclass
class SimResult:
    world: object
    cfg: object
    plant_idx: list
    age: list
    nutrients: list
    dead_matter: list
    counts: dict                 # plant index -> cells occupied at the end
    occupied: int
    rejected: list               # illegal / dropped planting actions
    history: list                # periodic snapshots, for debugging
    deaths: dict                 # cause -> how many plants died that way
    unlocked: set = None         # plant indices legal to plant at the end
    unlock_log: dict = None      # plant index -> tick it first became legal
    animals: set = None          # animal ids present at the end

    def species_present(self):
        return sum(1 for v in self.counts.values() if v > 0)


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
def simulate(world, actions, cfg, record_history=False):
    """actions: dict of tick -> list of (plant_index, row, col), in order."""
    R, C = world.rows, world.cols
    n = R * C

    plant_idx = [EMPTY] * n
    age = [0] * n
    nutrients = [cfg.nutrient_start] * n
    dead_matter = [False] * n
    shaded = set()

    occupied = set()      # cell indices currently holding a plant
    dead_cells = set()    # cell indices carrying the dead-matter flag

    # Static per-cell legality, resolved once against this config.
    terrain_ok = [False] * n
    soil_of = [None] * n
    for r in range(R):
        base = r * C
        for c in range(C):
            t = world.cell_terrain(r, c, cfg)
            soil_of[base + c] = world.cell_soil(r, c, cfg)
            terrain_ok[base + c] = t is not None and t in cfg.plantable_terrains

    rejected, history = [], []
    deaths = {"nutrients": 0, "shade": 0, "isolated": 0, "crowded": 0,
              "needs_shade": 0, "needs_burnt": 0, "needs_rock_or_path": 0,
              "needs_water": 0}
    shade_casters = set()          # occupied cells whose species casts shade

    # p.5: "Plants with unlock conditions will only place successfully if all
    # of their unlock conditions are met."  Locked species are IGNORED.
    tracker = Tracker(animals_enabled=world.animals_enabled, total_cells=n)
    events_seen = set()
    unlock_log = {}                # plant index -> tick it first became legal

    for tick in range(world.ticks):
        season = world.season_at(tick)
        for etick, ename in world.events.items():
            if etick <= tick:
                events_seen.add(ename)

        # -- 1b. recompute unlocks from the CURRENT board -------------------
        live = {}
        for k in occupied:
            live[plant_idx[k]] = live.get(plant_idx[k], 0) + 1
        before = set(tracker.unlocked)
        unlocked = tracker.update(live, len(dead_cells), events_seen)
        for pi in unlocked - before:
            unlock_log.setdefault(pi, tick)

        # -- 2. player actions -----------------------------------------------
        for i, (pi, r, c) in enumerate(actions.get(tick, ())):
            if i >= 20:
                rejected.append("tick %d: action #%d dropped (>20 per tick)" % (tick, i))
                continue
            if not world.in_bounds(r, c):
                rejected.append("tick %d: (%d,%d) out of bounds" % (tick, r, c))
                continue
            k = r * C + c
            if not terrain_ok[k]:
                rejected.append("tick %d: (%d,%d) terrain not plantable" % (tick, r, c))
                continue
            if pi not in unlocked:
                rejected.append("tick %d: %s is still LOCKED at (%d,%d)"
                                % (tick, get_plant(pi).name, r, c))
                continue
            plant = get_plant(pi)
            if soil_of[k] not in plant.preferred_soil:
                rejected.append("tick %d: %s rejects soil %s at (%d,%d)"
                                % (tick, plant.name, soil_of[k], r, c))
                continue
            # THE OFFICIAL SOLVER REFUSES this - see SimConfig.
            if k in occupied and not cfg.planting_replaces_occupant:
                rejected.append("tick %d: (%d,%d) already occupied - DENIED"
                                % (tick, r, c))
                continue
            shade_casters.discard(k)
            plant_idx[k] = pi
            age[k] = 0
            occupied.add(k)
            if plant.shade_radius:
                shade_casters.add(k)

        # -- 3. shade ---------------------------------------------------------
        # p.7: shade only starts once the caster is mature.
        if shade_casters:
            shaded = set()
            for k in shade_casters:
                p = get_plant(plant_idx[k])
                if age[k] < p.time_to_maturity:
                    continue
                r0, c0 = divmod(k, C)
                rad = p.shade_radius
                for r in range(max(0, r0 - rad), min(R, r0 + rad + 1)):
                    rb = r * C
                    for c in range(max(0, c0 - rad), min(C, c0 + rad + 1)):
                        shaded.add(rb + c)

        # -- 4. spread --------------------------------------------------------
        # target -> winning plant index.  Among simultaneous spreaders the last
        # one processed wins (p.13); sources are walked in sorted order so
        # "last" is deterministic.
        incoming = {}
        for k in sorted(occupied):
            pi = plant_idx[k]
            p = get_plant(pi)
            matured_for = age[k] - p.time_to_maturity
            if matured_for <= 0:
                continue
            rate = p.spread_rate_for_season(season)
            if rate <= 0 or matured_for % rate != 0:
                continue
            if p.no_winter_spread and season == "Winter":
                continue
            r0, c0 = divmod(k, C)
            for dr, dc in spread_offsets(p.spread_type, p.spread_range,
                                         cfg.crosshatch_shape, cfg.vonneumann_shape):
                r, c = r0 + dr, c0 + dc
                if not (0 <= r < R and 0 <= c < C):
                    continue
                t = r * C + c
                if not terrain_ok[t] or soil_of[t] not in p.preferred_soil:
                    continue
                if p.no_shade_spread and t in shaded:
                    continue
                if p.no_adjacent_plants:            # p.15: Living Topiary
                    tr, tc = divmod(t, C)
                    if any(0 <= tr + dr < R and 0 <= tc + dc < C
                           and plant_idx[(tr + dr) * C + tc + dc] != EMPTY
                           for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                           if not (dr == 0 and dc == 0)):
                        continue
                incoming[t] = pi

        for t in sorted(incoming):
            attacker = incoming[t]
            occupant = plant_idx[t]
            if occupant == EMPTY:
                pass
            elif not cfg.spread_displaces_established:
                continue
            # p.6: higher invasiveness_rank outcompetes the current plant.
            elif get_plant(attacker).invasiveness_rank <= get_plant(occupant).invasiveness_rank:
                continue
            shade_casters.discard(t)
            plant_idx[t] = attacker
            age[t] = 0
            occupied.add(t)
            if get_plant(attacker).shade_radius:
                shade_casters.add(t)

        # -- 5. nutrients -----------------------------------------------------
        for k in occupied:
            nutrients[k] -= cfg.drain_dead_matter if dead_matter[k] else cfg.drain_normal
        for k in dead_cells:
            if k not in occupied and nutrients[k] < cfg.nutrient_max:
                nutrients[k] = min(cfg.nutrient_max, nutrients[k] + cfg.regen_dead_matter)

        # -- 6. deaths --------------------------------------------------------
        killed = []
        for k in occupied:
            p = get_plant(plant_idx[k])
            cause = None
            if nutrients[k] <= 0:
                nutrients[k] = 0.0
                cause = "nutrients"
            elif p.no_shade_survival and k in shaded:
                cause = "shade"
            # p.15: shade_required - the plant needs shade to survive.
            elif p.shade_required and k not in shaded:
                cause = "needs_shade"
            # p.15: must_be_burnt_soil.
            elif p.must_be_burnt_soil and soil_of[k] != 3:
                cause = "needs_burnt"
            # p.15: must_be_adjacent_to a world feature.  The PDF names
            # "water" and "rock_or_path" but never maps them onto the level
            # file's terrain ids, so we take the conservative reading:
            #   rock_or_path -> any neighbouring cell whose terrain is not the
            #                   plain soil terrain 0 (the walls/paths/rock)
            #   water        -> p.7 says water is "always surrounded by clay",
            #                   so require a neighbouring clay (soil 2) cell
            elif p.must_be_adjacent_to:
                r0, c0 = divmod(k, C)
                ok = False
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        r, c = r0 + dr, c0 + dc
                        if not (0 <= r < R and 0 <= c < C):
                            continue
                        t2 = world.cell_terrain(r, c, cfg)
                        s2 = world.cell_soil(r, c, cfg)
                        if p.must_be_adjacent_to == "rock_or_path":
                            ok = ok or (t2 is not None and t2 != 0)
                        elif p.must_be_adjacent_to == "water":
                            ok = ok or (s2 == 2)
                        if ok:
                            break
                    if ok:
                        break
                if not ok:
                    cause = "needs_" + p.must_be_adjacent_to
            elif p.die_if_isolated or p.die_if_neighbors_gt is not None:
                r0, c0 = divmod(k, C)
                neigh = 0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        r, c = r0 + dr, c0 + dc
                        if 0 <= r < R and 0 <= c < C and plant_idx[r * C + c] != EMPTY:
                            neigh += 1
                if p.die_if_isolated and neigh == 0:
                    cause = "isolated"
                elif p.die_if_neighbors_gt is not None and neigh > p.die_if_neighbors_gt:
                    cause = "crowded"
            if cause:
                killed.append(k)
                deaths[cause] = deaths.get(cause, 0) + 1
        for k in killed:
            plant_idx[k] = EMPTY
            age[k] = 0
            occupied.discard(k)
            shade_casters.discard(k)
            dead_matter[k] = True          # p.8: death leaves dead matter
            dead_cells.add(k)

        # -- 7. ageing --------------------------------------------------------
        for k in occupied:
            age[k] += 1
            if not cfg.dead_matter_persists and dead_matter[k]:
                # Pessimistic reading: the 0.5/tick bonus is consumed as soon
                # as the cell is recolonised.
                dead_matter[k] = False
                dead_cells.discard(k)

        if record_history and (tick % 25 == 0 or tick == world.ticks - 1):
            snap = {}
            for k in occupied:
                snap[plant_idx[k]] = snap.get(plant_idx[k], 0) + 1
            history.append({"tick": tick, "season": season,
                            "occupied": len(occupied), "counts": snap})

    counts = {}
    for k in occupied:
        counts[plant_idx[k]] = counts.get(plant_idx[k], 0) + 1

    result = SimResult(
        world=world, cfg=cfg, plant_idx=plant_idx, age=age, nutrients=nutrients,
        dead_matter=dead_matter, counts=counts, occupied=len(occupied),
        rejected=rejected, history=history, deaths=deaths,
    )
    result.unlocked = set(tracker.unlocked)
    result.unlock_log = unlock_log
    result.animals = set(tracker.present_animals)
    return result
