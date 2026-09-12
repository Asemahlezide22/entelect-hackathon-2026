"""
Vectorised tick engine - same rules as engine2, ~500x faster.

engine2 walks every occupied cell in Python on every tick, which costs ~25 s
for one Level-3 run and makes a real parameter sweep impossible.  This module
keeps the board in numpy arrays and does each phase as a handful of whole-grid
operations, so a Level-3 run costs ~50 ms and Level 4 ~150 ms.  That is the
difference between testing 40 ideas and testing 40,000.

validate_fastsim.py checks this engine against engine2 cell-for-cell.

The one deliberate difference: when several species spread into the SAME cell
on the same tick, engine2 lets the last source in cell order win, which is an
artefact of its loop.  Here the highest invasiveness_rank wins, ties broken by
species index - deterministic, and a more defensible reading of "more invasive
species outcompete" (p.6).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from .plants import catalogue, get as get_plant
from .unlocks import Tracker

STARTERS = (1, 2, 5, 6, 12)


@dataclass(frozen=True)
class Rules:
    rate_mode: str = "period"      # period | cells
    pick: str = "near"             # near | sorted | all  (cells mode)
    mature: str = "gt"             # gt | ge | none
    displace: str = "rank_gt"      # never | rank_gt | rank_ge | different | always
    nutrient_start: float = 100.0
    drain: float = 1.0
    drain_dead: float = 0.5
    regen: float = 1.0
    reset_on_plant: bool = False
    nutrients_on: bool = True
    crosshatch: str = "diagonal"
    vonneumann: str = "diamond"
    max_per_tick: int = 20
    plantable_terrains: tuple = (0,)
    unlisted_plantable: bool = True
    enforce_unlocks: bool = True
    shade_kills: bool = True


def _offsets(p, rules):
    st, rng = p.spread_type, p.spread_range
    out = set()
    if st == "Moore":
        for dr in range(-rng, rng + 1):
            for dc in range(-rng, rng + 1):
                out.add((dr, dc))
    elif st == "VonNeumann":
        if rules.vonneumann == "diamond":
            for dr in range(-rng, rng + 1):
                for dc in range(-rng, rng + 1):
                    if abs(dr) + abs(dc) <= rng:
                        out.add((dr, dc))
        else:
            for d in range(1, rng + 1):
                out |= {(d, 0), (-d, 0), (0, d), (0, -d)}
    elif st == "Row":
        for d in range(1, rng + 1):
            out |= {(0, d), (0, -d)}
    elif st == "Column":
        for d in range(1, rng + 1):
            out |= {(d, 0), (-d, 0)}
    elif st == "CrossHatch":
        for d in range(1, rng + 1):
            out |= {(d, d), (d, -d), (-d, d), (-d, -d)}
            if rules.crosshatch == "star":
                out |= {(d, 0), (-d, 0), (0, d), (0, -d)}
    else:
        raise ValueError(st)
    out.discard((0, 0))
    offs = sorted(out, key=lambda o: (abs(o[0]) + abs(o[1]), o))
    if rules.rate_mode == "cells" and rules.pick != "all":
        rate = p.spread_rate
        if rate < len(offs):
            offs = (sorted(out)[:rate] if rules.pick == "sorted" else offs[:rate])
    return offs


def _structure(offs):
    """Boolean structuring element for scipy.binary_dilation."""
    rad = max(max(abs(a), abs(b)) for a, b in offs)
    s = np.zeros((2 * rad + 1, 2 * rad + 1), bool)
    for dr, dc in offs:
        s[rad + dr, rad + dc] = True
    s[rad, rad] = False
    return s


NEIGH8 = np.ones((3, 3), np.uint8)
NEIGH8[1, 1] = 0


@dataclass
class Result:
    counts: dict
    occupied: int
    pidx: np.ndarray
    age: np.ndarray
    rows: int
    cols: int
    ticks: int
    denied: int
    rejected: int
    deaths: dict
    history: list
    denied_at: list


def simulate(world, actions, rules: Rules = Rules(), record_history=False,
             stop_at=None):
    R, C, T = world.rows, world.cols, world.ticks
    cat = catalogue()

    # ---- static maps -----------------------------------------------------
    terrain = np.full((R, C), -1, np.int16)
    soil = np.full((R, C), -1, np.int16)
    for r in range(R):
        for c in range(C):
            t, s = world.terrain[r][c], world.soil[r][c]
            if t is None:
                if not rules.unlisted_plantable:
                    continue
                t, s = 0, 0
            terrain[r, c] = t
            soil[r, c] = s
    terrain_ok = np.isin(terrain, np.array(rules.plantable_terrains, np.int16))

    max_idx = max(cat) + 1
    RANK = np.zeros(max_idx, np.int16)
    for i, p in cat.items():
        RANK[i] = p.invasiveness_rank

    soil_ok = {}          # species -> boolean map of legal cells
    struct = {}           # species -> structuring element
    for i, p in cat.items():
        soil_ok[i] = terrain_ok & np.isin(soil, np.array(sorted(p.preferred_soil), np.int16))
        struct[i] = _structure(_offsets(p, rules))

    # ---- dynamic state ----------------------------------------------------
    pidx = np.zeros((R, C), np.int16)
    age = np.zeros((R, C), np.int32)
    nut = np.full((R, C), rules.nutrient_start, np.float32)
    dead = np.zeros((R, C), bool)

    shade_casters = {i: p.shade_radius for i, p in cat.items() if p.shade_radius}
    no_shade_surv = np.array([cat[i].no_shade_survival if i in cat else False
                              for i in range(max_idx)])
    needs_shade = np.array([cat[i].shade_required if i in cat else False
                            for i in range(max_idx)])
    no_shade_spread = {i for i, p in cat.items() if p.no_shade_spread}
    no_winter = {i for i, p in cat.items() if p.no_winter_spread}
    isolated_sp = {i for i, p in cat.items() if p.die_if_isolated}
    crowd_sp = {i: p.die_if_neighbors_gt for i, p in cat.items()
                if p.die_if_neighbors_gt is not None}
    burnt_sp = {i for i, p in cat.items() if p.must_be_burnt_soil}

    denied = rejected = 0
    denied_at = []
    deaths = {}
    history = []

    planted_species = {pi for acts in actions.values() for (pi, _, _) in acts}
    starters_only = planted_species <= set(STARTERS)
    tracker = None if starters_only else Tracker(animals_enabled=world.animals_enabled,
                                                 total_cells=R * C)
    unlocked = set(STARTERS)
    events_seen = set()
    shaded = np.zeros((R, C), bool)

    for tick in range(T if stop_at is None else stop_at):
        season = world.season_at(tick)
        if not starters_only:
            for et, en in world.events.items():
                if et <= tick:
                    events_seen.add(en)
            live = {}
            for i, n in zip(*np.unique(pidx, return_counts=True)):
                if i:
                    live[int(i)] = int(n)
            unlocked = tracker.update(live, int(dead.sum()), events_seen)

        # ---- 2. player actions -------------------------------------------
        acts = actions.get(tick)
        if acts:
            for i, (pi, r, c) in enumerate(acts):
                if i >= rules.max_per_tick or not (0 <= r < R and 0 <= c < C):
                    rejected += 1
                    continue
                if not soil_ok[pi][r, c]:
                    rejected += 1
                    continue
                if rules.enforce_unlocks and pi not in unlocked:
                    rejected += 1
                    continue
                if pidx[r, c]:
                    denied += 1
                    denied_at.append((pi, r, c, tick))
                    continue
                pidx[r, c] = pi
                age[r, c] = 0
                if rules.reset_on_plant:
                    nut[r, c] = rules.nutrient_start

        occ = pidx > 0

        # ---- 3. shade ------------------------------------------------------
        if shade_casters:
            shaded = np.zeros((R, C), bool)
            for sp, rad in shade_casters.items():
                m = (pidx == sp) & (age >= cat[sp].time_to_maturity)
                if m.any():
                    shaded |= ndimage.binary_dilation(
                        m, np.ones((2 * rad + 1, 2 * rad + 1), bool))

        # ---- 4. spread ------------------------------------------------------
        present = [int(i) for i in np.unique(pidx) if i]
        if present:
            best_sp = np.zeros((R, C), np.int16)
            best_rank = np.full((R, C), -1, np.int16)
            for sp in present:
                p = cat[sp]
                if sp in no_winter and season == "Winter":
                    continue
                since = age - p.time_to_maturity
                if rules.mature == "gt":
                    ready = (pidx == sp) & (since > 0)
                elif rules.mature == "ge":
                    ready = (pidx == sp) & (since >= 0)
                else:
                    since = age
                    ready = pidx == sp
                if rules.rate_mode == "period":
                    rate = p.spread_rate_for_season(season)
                    if rate <= 0:
                        continue
                    ready = ready & (since % rate == 0)
                if not ready.any():
                    continue
                tgt = ndimage.binary_dilation(ready, struct[sp]) & soil_ok[sp]
                if sp in no_shade_spread:
                    tgt &= ~shaded
                win = tgt & (RANK[sp] > best_rank)
                best_sp[win] = sp
                best_rank[win] = RANK[sp]

            take = best_sp > 0
            if rules.displace == "never":
                take &= ~occ
            elif rules.displace == "rank_gt":
                take &= (~occ) | (best_rank > RANK[pidx])
            elif rules.displace == "rank_ge":
                take &= (~occ) | (best_rank >= RANK[pidx])
            elif rules.displace == "different":
                # p.13: whoever spreads in last wins - but a species does not
                # overwrite ITSELF, otherwise every interior cell would have its
                # age reset every few ticks and longevity would collapse to ~1.
                # The official logs show mean ages of 32-44, so self-overwrite
                # cannot be happening.
                take &= (~occ) | (best_sp != pidx)
            if take.any():
                pidx[take] = best_sp[take]
                age[take] = 0
                if rules.reset_on_plant:
                    nut[take] = rules.nutrient_start
                occ = pidx > 0

        # ---- 5. nutrients ----------------------------------------------------
        if rules.nutrients_on:
            nut -= np.where(occ, np.where(dead, rules.drain_dead, rules.drain), 0.0)
            regen = dead & ~occ
            nut[regen] = np.minimum(rules.nutrient_start, nut[regen] + rules.regen)

        # ---- 6. deaths --------------------------------------------------------
        kill = np.zeros((R, C), bool)
        if rules.nutrients_on:
            starved = occ & (nut <= 0)
            if starved.any():
                nut[starved] = 0.0
                kill |= starved
                deaths["nutrients"] = deaths.get("nutrients", 0) + int(starved.sum())
        if rules.shade_kills and shade_casters:
            s = occ & no_shade_surv[pidx] & shaded & ~kill
            if s.any():
                kill |= s
                deaths["shade"] = deaths.get("shade", 0) + int(s.sum())
        if needs_shade[pidx].any():
            s = occ & needs_shade[pidx] & ~shaded & ~kill
            if s.any():
                kill |= s
                deaths["needs_shade"] = deaths.get("needs_shade", 0) + int(s.sum())
        if burnt_sp:
            for sp in burnt_sp:
                s = (pidx == sp) & (soil != 3) & ~kill
                if s.any():
                    kill |= s
                    deaths["needs_burnt"] = deaths.get("needs_burnt", 0) + int(s.sum())
        if isolated_sp or crowd_sp:
            need = np.zeros((R, C), bool)
            for sp in list(isolated_sp) + list(crowd_sp):
                need |= pidx == sp
            if need.any():
                nb = ndimage.convolve(occ.astype(np.uint8), NEIGH8,
                                      mode="constant", cval=0)
                for sp in isolated_sp:
                    s = (pidx == sp) & (nb == 0) & ~kill
                    if s.any():
                        kill |= s
                        deaths["isolated"] = deaths.get("isolated", 0) + int(s.sum())
                for sp, v in crowd_sp.items():
                    s = (pidx == sp) & (nb > v) & ~kill
                    if s.any():
                        kill |= s
                        deaths["crowded"] = deaths.get("crowded", 0) + int(s.sum())
        if kill.any():
            pidx[kill] = 0
            age[kill] = 0
            dead |= kill
            occ = pidx > 0

        # ---- 7. ageing ---------------------------------------------------------
        age[occ] += 1

        if record_history and (tick % 50 == 0 or tick == T - 1):
            vals, cnts = np.unique(pidx, return_counts=True)
            history.append((tick, int(occ.sum()),
                            {int(v): int(n) for v, n in zip(vals, cnts) if v}))

    vals, cnts = np.unique(pidx, return_counts=True)
    counts = {int(v): int(n) for v, n in zip(vals, cnts) if v}
    return Result(counts=counts, occupied=int((pidx > 0).sum()), pidx=pidx, age=age,
                  rows=R, cols=C, ticks=T, denied=denied, rejected=rejected,
                  deaths=deaths, history=history, denied_at=denied_at)


def score(res):
    """OFFICIAL formula: 0.8 * H * C/(rows*cols) + 0.2 * longevity, x 1e9."""
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
    longev = float(res.age[res.pidx > 0].sum()) / res.ticks / cmax
    main = h * dens
    final = 0.8 * main + 0.2 * longev
    return {"C": res.occupied, "density": dens, "H": h, "longevity": longev,
            "main": main, "score": final, "leaderboard": final * 1e9,
            "counts": dict(res.counts)}
