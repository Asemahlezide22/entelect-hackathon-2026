#!/usr/bin/env python3
"""Candidate sweep for bands3, one level at a time.

    py sweep3.py --level 1 --stage order
    py sweep3.py --level 3 --stage species

Candidates are scored under every reading in bench.READINGS and ranked on the
WORST, then written to experiments/levelN/<name>.json.  Nothing is promoted
into out/ from here - promote.py does that, after a human look at the table.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench                                             # noqa: E402
from photospheria import fastsim, world as world_mod     # noqa: E402
from strategies import bands3                            # noqa: E402

ROOT = Path(__file__).resolve().parent
GRASS, ROSE, SUN, LAV, OAK = 1, 2, 5, 6, 12
CV, SR, RZ = 4, 11, 19
NAMES = {GRASS: "Gr", ROSE: "Ro", SUN: "Su", LAV: "La", OAK: "Oa",
         CV: "Cv", SR: "Sr", RZ: "Rz"}

BASE_STRIDES = {GRASS: 14, ROSE: 8, SUN: 10, LAV: 8, OAK: 20, RZ: 10, CV: 12, SR: 8}

_W = {}


def world(lv):
    if lv not in _W:
        _W[lv] = world_mod.load(ROOT / ("data/level%d.json" % lv))
    return _W[lv]


def evaluate(lv, sol):
    acts = bench.actions_of(sol)
    out = {}
    for name, rules in bench.READINGS.items():
        res = fastsim.simulate(world(lv), acts, rules)
        s = fastsim.score(res)
        s["denied"] = res.denied
        s["rejected"] = res.rejected
        out[name] = s
    worst = min(s["score"] for s in out.values())
    mean = sum(s["score"] for s in out.values()) / len(out)
    return worst, mean, out


def run(lv, cands, tag):
    rows = []
    for name, kw in cands:
        kw = dict(kw)
        kw.setdefault("strides", dict(BASE_STRIDES))
        sol = bands3.build(world(lv), **kw)
        worst, mean, detail = evaluate(lv, sol)
        a = detail["A"]
        print("L%d %-26s worst=%.4f mean=%.4f | A C=%6d d=%.3f H=%.4f lg=%.4f "
              "den=%4d rej=%4d %s"
              % (lv, name, worst, mean, a["C"], a["density"], a["H"],
                 a["longevity"], a["denied"], a["rejected"],
                 dict(sorted(a["counts"].items()))), flush=True)
        p = ROOT / ("experiments/level%d/%s.json" % (lv, name))
        p.parent.mkdir(parents=True, exist_ok=True)
        sol.write(p)
        rows.append((worst, mean, name, p, detail))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    print("\n== L%d %s BEST: %s worst=%.4f (%.0f) mean=%.4f (%.0f)\n"
          % (lv, tag, rows[0][2], rows[0][0], rows[0][0] * 1e9,
             rows[0][1], rows[0][1] * 1e9))
    log = ROOT / "results/experiment_log.csv"
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["level", "experiment", "worst", "mean", "A_score", "A_C",
                        "A_density", "A_H", "A_longevity", "A_denied", "file"])
        for worst, mean, name, p, detail in rows:
            a = detail["A"]
            w.writerow([lv, name, "%.6f" % worst, "%.6f" % mean, "%.6f" % a["score"],
                        a["C"], "%.4f" % a["density"], "%.4f" % a["H"],
                        "%.4f" % a["longevity"], a["denied"], p.name])
    return rows


def nm(order):
    return "".join(NAMES[s] for s in order)


# ----------------------------------------------------------------- L1 / L2
SPRING_ORDERS = [
    [OAK, SUN, ROSE, LAV, GRASS],
    [OAK, ROSE, SUN, LAV, GRASS],
    [OAK, LAV, ROSE, SUN, GRASS],
    [GRASS, LAV, ROSE, SUN, OAK],
    [GRASS, ROSE, LAV, SUN, OAK],
    [SUN, GRASS, ROSE, LAV, OAK],
    [ROSE, GRASS, LAV, SUN, OAK],
]


def stage_order(lv, window):
    out = []
    for axis in ("col", "row"):
        for o in SPRING_ORDERS:
            out.append(("o_%s_%s" % (axis, nm(o)),
                        dict(band_species=o, axis=axis, window=window)))
    return out


def stage_window(lv, order, axis):
    return [("w%d_%s_%s" % (win, axis, nm(order)),
             dict(band_species=order, axis=axis, window=win))
            for win in (98, 100, 102, 105)]


def stage_weights(lv, order, axis, window):
    out = []
    for w in ([1, 1, 1, 1, 1], [1.3, 1, 1, 1, 0.8], [0.8, 1, 1, 1, 1.3],
              [1.2, 1.1, 1, 0.9, 0.8], [0.8, 0.9, 1, 1.1, 1.2],
              [1.5, 1, 1, 1, 0.6], [0.6, 1, 1, 1, 1.5]):
        out.append(("wt_%s_%s" % ("-".join("%.1f" % x for x in w), nm(order)),
                    dict(band_species=order, axis=axis, window=window, weights=list(w))))
    return out


# ------------------------------------------------------------------ L3 / L4
def stage_species(lv, window=100):
    """Winter window (Levels 3-4): of the five starters only Grass, Dwarf
    Sunflower and Oak spread, because Rose Bush and Lavender carry
    no_winter_spread and the last season change is Winter on tick 700.  Those
    two are hand-scattered into the Grass band - Grass has invasiveness rank 1
    and can displace nothing, so what we place there stays there.

    Razorgrass and Crimson Vine are the two cheap unlocks that DO spread in
    winter.  Neither needs pre-window priming: the Grass band passes 5% of the
    grid within ~10 ticks of the window opening, and the Oak band puts ten trees
    down on the first tick, which is all the Canorals need.  Seeding them a few
    ticks late is enough, and it costs nothing if the unlock never fires - the
    band just stays empty and its neighbours spread into it.
    """
    w = world(lv)
    cells = w.rows * w.cols
    sc = int(cells * 0.014)
    budget = 20 * window
    def tgt(nb, extra=0):
        """Split the seed budget across nb bands, after the scatter."""
        free = budget - 2 * sc - extra
        return max(40, int(free / nb))
    d_rz = {RZ: 16}
    d_cv = {CV: 4}
    d_both = {RZ: 16, CV: 4}
    out = []
    for nb, order, delays, tag in (
            (3, [OAK, SUN, GRASS], {}, "3sp"),
            (4, [OAK, SUN, RZ, GRASS], d_rz, "rz4"),
            (4, [OAK, SUN, CV, GRASS], d_cv, "cv4"),
            (5, [OAK, SUN, CV, RZ, GRASS], d_both, "rzcv5"),
    ):
        n = tgt(nb)
        st = {s: 8 for s in (GRASS, SUN, OAK, RZ, CV, ROSE, LAV, SR)}
        for mult, mtag in ((1.0, ""), (0.6, "_lean"), (1.5, "_dense")):
            targets = {s: int(n * mult) for s in order}
            targets[OAK] = int(n * mult * 1.4)       # Moore r2 rate 7: slowest
            out.append(("v4_%s%s" % (tag, mtag),
                        dict(band_species=order, window=window, strides=st,
                             seed_targets=targets, delays=delays,
                             weights=[0.75] + [1.1] * (nb - 1),
                             scatter=[(ROSE, sc), (LAV, sc)],
                             scatter_band=nb - 1, topup=False)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--order", default="")
    ap.add_argument("--axis", default="col")
    ap.add_argument("--window", type=int, default=100)
    a = ap.parse_args()
    order = [int(x) for x in a.order.split(",")] if a.order else None
    if a.stage == "order":
        c = stage_order(a.level, a.window)
    elif a.stage == "window":
        c = stage_window(a.level, order, a.axis)
    elif a.stage == "weights":
        c = stage_weights(a.level, order, a.axis, a.window)
    elif a.stage == "species":
        c = stage_species(a.level, a.window)
    else:
        raise SystemExit("unknown stage")
    run(a.level, c, a.stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
