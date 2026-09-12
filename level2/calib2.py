#!/usr/bin/env python3
"""Calibrate fastsim.Rules against the five official evaluation logs.

The PDF settles rate_mode: "Rate of spread - how long it takes for the plant to
spread, measured in ticks" => period.  What is left open is who wins a contested
cell, whether maturity is > or >=, the CrossHatch/VonNeumann shapes and which
terrains are plantable.  Those are what we sweep here.
"""
from __future__ import annotations
import json, math, sys, itertools
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from photospheria import world as world_mod, solution, fastsim

ROOT = Path(__file__).resolve().parent
TRUTH = {k: v for k, v in json.loads((ROOT / "results/official_truth.json").read_text()).items() if k != "L4"}
WORLDS = {lv: world_mod.load(ROOT / f"data/level{lv}.json") for lv in (1, 2, 3, 4)}


def err_for(name, t, rules):
    w = WORLDS[t["level"]]
    acts = solution.load(ROOT / t["file"])
    res = fastsim.simulate(w, acts, rules)
    sc = fastsim.score(res)
    exp_c, got_c = t["C"], sc["C"]
    dens_err = abs(got_c - exp_c) / max(exp_c, 1)
    # composition error: L1 distance between species shares
    exp = {int(k): v for k, v in t["counts"].items()}
    et = sum(exp.values()) or 1
    gt = sum(res.counts.values()) or 1
    keys = set(exp) | set(res.counts)
    comp_err = sum(abs(exp.get(k, 0) / et - res.counts.get(k, 0) / gt) for k in keys) / 2
    score_err = abs(sc["score"] - t["score"])
    return (dens_err + comp_err + 3 * score_err, dens_err, comp_err, score_err, sc, res)


def main():
    grid = dict(
        displace=["never", "rank_gt", "rank_ge", "different"],
        mature=["gt", "ge"],
        crosshatch=["diagonal", "star"],
        vonneumann=["diamond"],
        drain_dead=[0.5],
        plantable_terrains=[(0,)],
    )
    keys = list(grid)
    rows = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        opts = dict(zip(keys, combo))
        rules = fastsim.Rules(rate_mode="period", **opts)
        tot = 0.0
        detail = {}
        for name, t in TRUTH.items():
            e, de, ce, se, sc, res = err_for(name, t, rules)
            tot += e
            detail[name] = (de, ce, se, sc, res.denied, t["denied"])
        rows.append((tot, opts, detail))
        print("%.4f %s" % (tot, opts), flush=True)
    rows.sort(key=lambda r: r[0])
    print("\n================ BEST 3 ================")
    for tot, opts, detail in rows[:3]:
        print("TOTAL %.4f  %s" % (tot, opts))
        for name, (de, ce, se, sc, dn, dn_exp) in detail.items():
            t = TRUTH[name]
            print("   %-4s C=%6d/%-6d densE=%.3f compE=%.3f  H=%.4f/%.4f  long=%.4f/%.4f "
                  "score=%.4f/%.4f denied=%d/%d"
                  % (name, sc["C"], t["C"], de, ce, sc["H"], t["H"],
                     sc["longevity"], t["long"], sc["score"], t["score"], dn, t["denied"]))
            print("        got %s" % dict(sorted(sc["counts"].items())))
            print("        exp %s" % {int(k): v for k, v in sorted(t["counts"].items(), key=lambda x: int(x[0]))})
    (ROOT / "results/calib2_best.json").write_text(json.dumps(
        {"best": [{"err": r[0], "opts": {k: list(v) if isinstance(v, tuple) else v
                                          for k, v in r[1].items()}} for r in rows[:5]]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
