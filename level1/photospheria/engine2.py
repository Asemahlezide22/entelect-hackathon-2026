"""
Parametrised tick engine used to FIT our simulator to the official evaluator.

photospheria/simulator.py encodes one reading of the problem statement.  That
reading does not reproduce the official results (L1: it gives Oak=0 where the
official run reports Oak=288; L3: it gives a Sunflower monoculture where the
official run reports an Oak monoculture), so every rule the PDF leaves open is
a switch here and fit_engine.py grid-searches them against the official
fingerprints.

Nothing here is an unmarked guess: each switch is an axis with an explicit set
of readings.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

from .plants import get as get_plant
from .unlocks import Tracker

EMPTY = 0


@dataclass(frozen=True)
class Rules:
    # -- spread scheduling -------------------------------------------------
    # period: spread_rate is the number of ticks between spread events, and an
    #         event seeds EVERY cell of the shape.
    # cells : the plant spreads EVERY tick, and spread_rate is how many cells
    #         of the shape it seeds.
    rate_mode: str = "period"
    pick: str = "near"                 # near | sorted | rotate  (cells mode)
    mature: str = "gt"                 # gt | ge | none (maturity does not gate)

    # -- competition -------------------------------------------------------
    # never   : spread only fills EMPTY cells
    # rank_gt : strictly higher invasiveness_rank displaces the occupant
    # rank_ge : equal-or-higher rank displaces (self-overwrite resets age)
    # always  : the last spreader of the tick wins
    displace: str = "rank_gt"

    # -- nutrients ---------------------------------------------------------
    nutrient_start: float = 100.0
    drain: float = 1.0
    drain_dead: float = 0.5
    regen: float = 1.0
    reset_on_plant: bool = False       # does a new occupant restore nutrients?
    nutrients_on: bool = True          # False = nutrients never kill anything

    # -- geometry ----------------------------------------------------------
    crosshatch: str = "diagonal"       # diagonal | star
    vonneumann: str = "diamond"        # diamond | axes

    # -- player actions ----------------------------------------------------
    max_per_tick: int = 20
    plantable_terrains: tuple = (0,)
    unlisted_plantable: bool = True
    enforce_unlocks: bool = True
    enforce_soil: bool = True
    shade_kills: bool = True


@lru_cache(maxsize=None)
def offsets(spread_type, rng, crosshatch, vonneumann):
    out = set()
    if spread_type == "Moore":
        for dr in range(-rng, rng + 1):
            for dc in range(-rng, rng + 1):
                out.add((dr, dc))
    elif spread_type == "VonNeumann":
        if vonneumann == "diamond":
            for dr in range(-rng, rng + 1):
                for dc in range(-rng, rng + 1):
                    if abs(dr) + abs(dc) <= rng:
                        out.add((dr, dc))
        else:
            for d in range(1, rng + 1):
                out.update({(d, 0), (-d, 0), (0, d), (0, -d)})
    elif spread_type == "Row":
        for d in range(1, rng + 1):
            out.update({(0, d), (0, -d)})
    elif spread_type == "Column":
        for d in range(1, rng + 1):
            out.update({(d, 0), (-d, 0)})
    elif spread_type == "CrossHatch":
        for d in range(1, rng + 1):
            out.update({(d, d), (d, -d), (-d, d), (-d, -d)})
            if crosshatch == "star":
                out.update({(d, 0), (-d, 0), (0, d), (0, -d)})
    else:
        raise ValueError(spread_type)
    out.discard((0, 0))
    return tuple(sorted(out, key=lambda o: (abs(o[0]) + abs(o[1]), o)))


@lru_cache(maxsize=None)
def spread_cells(spread_type, rng, rate, crosshatch, vonneumann, mode, pick):
    offs = offsets(spread_type, rng, crosshatch, vonneumann)
    if mode == "period" or rate >= len(offs):
        return offs
    if pick == "near":
        return offs[:rate]
    if pick == "sorted":
        return tuple(sorted(offs))[:rate]
    return offs


@dataclass
class Result:
    counts: dict
    occupied: int
    ages: list
    plant_idx: list
    rows: int
    cols: int
    ticks: int
    denied: int
    rejected: int
    deaths: dict
    history: list
    unlocked: set


def simulate(world, actions, rules: Rules, record_history=False):
    R, C, T = world.rows, world.cols, world.ticks
    n = R * C
    plant_idx = bytearray(n)
    age = [0] * n
    nutrients = [rules.nutrient_start] * n
    dead_matter = bytearray(n)
    occupied = set()
    dead_cells = set()
    shaded = set()
    shade_casters = set()

    terrain_ok = bytearray(n)
    soil_of = [-1] * n
    for r in range(R):
        b = r * C
        for c in range(C):
            t = world.terrain[r][c]
            s = world.soil[r][c]
            if t is None:
                if not rules.unlisted_plantable:
                    continue
                t, s = 0, 0
            soil_of[b + c] = s
            terrain_ok[b + c] = 1 if t in rules.plantable_terrains else 0

    denied = rejected = 0
    deaths = {}
    history = []
    tracker = Tracker(animals_enabled=world.animals_enabled, total_cells=n)
    events_seen = set()
    unlocked = set(tracker.unlocked)

    for tick in range(T):
        season = world.season_at(tick)
        for et, en in world.events.items():
            if et <= tick:
                events_seen.add(en)

        live = {}
        for k in occupied:
            pi = plant_idx[k]
            live[pi] = live.get(pi, 0) + 1
        unlocked = tracker.update(live, len(dead_cells), events_seen)

        # ---- 2. player actions -------------------------------------------
        for i, (pi, r, c) in enumerate(actions.get(tick, ())):
            if i >= rules.max_per_tick:
                rejected += 1
                continue
            if not (0 <= r < R and 0 <= c < C):
                rejected += 1
                continue
            k = r * C + c
            if not terrain_ok[k]:
                rejected += 1
                continue
            if rules.enforce_unlocks and pi not in unlocked:
                rejected += 1
                continue
            p = get_plant(pi)
            if rules.enforce_soil and soil_of[k] not in p.preferred_soil:
                rejected += 1
                continue
            if k in occupied:
                denied += 1
                continue
            plant_idx[k] = pi
            age[k] = 0
            if rules.reset_on_plant:
                nutrients[k] = rules.nutrient_start
            occupied.add(k)
            if p.shade_radius:
                shade_casters.add(k)

        # ---- 3. shade -----------------------------------------------------
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

        # ---- 4. spread -----------------------------------------------------
        incoming = {}
        for k in sorted(occupied):
            pi = plant_idx[k]
            p = get_plant(pi)
            a = age[k]
            mat = p.time_to_maturity
            since = a - mat
            if rules.mature == "gt":
                if since <= 0:
                    continue
            elif rules.mature == "ge":
                if since < 0:
                    continue
            else:                      # "none": maturity does not gate spread
                since = a
            rate = p.spread_rate_for_season(season)
            if rate <= 0:
                continue
            if rules.rate_mode == "period" and since % rate != 0:
                continue
            if p.no_winter_spread and season == "Winter":
                continue
            offs = spread_cells(p.spread_type, p.spread_range, rate,
                                rules.crosshatch, rules.vonneumann,
                                rules.rate_mode, rules.pick)
            if rules.rate_mode == "cells" and rules.pick == "rotate":
                allo = offsets(p.spread_type, p.spread_range,
                               rules.crosshatch, rules.vonneumann)
                if rate < len(allo):
                    st = (tick * rate) % len(allo)
                    offs = tuple(allo[(st + j) % len(allo)] for j in range(rate))
            r0, c0 = divmod(k, C)
            for dr, dc in offs:
                r, c = r0 + dr, c0 + dc
                if not (0 <= r < R and 0 <= c < C):
                    continue
                t = r * C + c
                if not terrain_ok[t] or soil_of[t] not in p.preferred_soil:
                    continue
                if p.no_shade_spread and t in shaded:
                    continue
                if p.no_adjacent_plants:
                    tr, tc = divmod(t, C)
                    busy = False
                    for ddr in (-1, 0, 1):
                        for ddc in (-1, 0, 1):
                            if ddr == 0 and ddc == 0:
                                continue
                            rr, cc = tr + ddr, tc + ddc
                            if 0 <= rr < R and 0 <= cc < C and plant_idx[rr * C + cc]:
                                busy = True
                                break
                        if busy:
                            break
                    if busy:
                        continue
                incoming[t] = pi

        mode = rules.displace
        for t, attacker in incoming.items():
            occ = plant_idx[t]
            if occ:
                if mode == "never":
                    continue
                if mode == "rank_gt":
                    if get_plant(attacker).invasiveness_rank <= get_plant(occ).invasiveness_rank:
                        continue
                elif mode == "rank_ge":
                    if get_plant(attacker).invasiveness_rank < get_plant(occ).invasiveness_rank:
                        continue
                elif mode == "different" and attacker == occ:
                    continue
                shade_casters.discard(t)
            plant_idx[t] = attacker
            age[t] = 0
            if rules.reset_on_plant:
                nutrients[t] = rules.nutrient_start
            occupied.add(t)
            if get_plant(attacker).shade_radius:
                shade_casters.add(t)

        # ---- 5. nutrients ---------------------------------------------------
        if rules.nutrients_on:
            for k in occupied:
                nutrients[k] -= rules.drain_dead if dead_matter[k] else rules.drain
            for k in dead_cells:
                if k not in occupied and nutrients[k] < rules.nutrient_start:
                    nutrients[k] = min(rules.nutrient_start, nutrients[k] + rules.regen)

        # ---- 6. deaths --------------------------------------------------------
        killed = []
        for k in occupied:
            p = get_plant(plant_idx[k])
            cause = None
            if rules.nutrients_on and nutrients[k] <= 0:
                nutrients[k] = 0.0
                cause = "nutrients"
            elif rules.shade_kills and p.no_shade_survival and k in shaded:
                cause = "shade"
            elif rules.shade_kills and p.shade_required and k not in shaded:
                cause = "needs_shade"
            elif p.must_be_burnt_soil and soil_of[k] != 3:
                cause = "needs_burnt"
            elif p.die_if_isolated or p.die_if_neighbors_gt is not None:
                r0, c0 = divmod(k, C)
                neigh = 0
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        r, c = r0 + dr, c0 + dc
                        if 0 <= r < R and 0 <= c < C and plant_idx[r * C + c]:
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
            dead_matter[k] = 1
            dead_cells.add(k)

        # ---- 7. ageing ---------------------------------------------------------
        for k in occupied:
            age[k] += 1

        if record_history and (tick % 50 == 0 or tick == T - 1):
            snap = {}
            for k in occupied:
                snap[plant_idx[k]] = snap.get(plant_idx[k], 0) + 1
            history.append((tick, len(occupied), snap))

    counts = {}
    for k in occupied:
        counts[plant_idx[k]] = counts.get(plant_idx[k], 0) + 1
    return Result(counts=counts, occupied=len(occupied), ages=age,
                  plant_idx=list(plant_idx), rows=R, cols=C, ticks=T,
                  denied=denied, rejected=rejected, deaths=deaths,
                  history=history, unlocked=set(unlocked))


# --------------------------------------------------------------------- score
def score(res):
    """THE official formula.  alpha = 1, k = 1, N = 31, K = 1e9."""
    cmax = res.rows * res.cols
    total = sum(res.counts.values())
    h = 0.0
    if total:
        ln31 = math.log(31)
        for v in res.counts.values():
            if v > 0:
                p = v / total
                h -= p * math.log(p) / ln31
    dens = res.occupied / cmax
    longev = sum(a for a in res.ages if a > 0) / res.ticks / cmax
    main = h * dens
    final = 0.8 * main + 0.2 * longev
    return {"C": res.occupied, "density": dens, "H": h, "longevity": longev,
            "main": main, "score": final, "leaderboard": final * 1e9}
