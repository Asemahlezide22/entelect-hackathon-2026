#!/usr/bin/env python3
"""Build and score bands3 candidates for one level under several rule readings.

    py run3.py --level 3 --plan base,rz,rz_cv

Every candidate is scored under each reading in bench.READINGS and ranked on
the WORST one: our spread model only matches the official logs to within ~0.2
of composition, so a candidate that wins under one reading only is not a
candidate we ship.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench                                             # noqa: E402
from photospheria import fastsim, world as world_mod     # noqa: E402
from strategies import bands3                            # noqa: E402

ROOT = Path(__file__).resolve().parent
GRASS, ROSE, SUN, LAV, OAK = 1, 2, 5, 6, 12
CV, SR, RZ = 4, 11, 19

STRIDES = {GRASS: 14, ROSE: 8, SUN: 10, LAV: 8, OAK: 20, RZ: 12, CV: 12, SR: 8}


def evaluate(lv, sol):
    w = world_mod.load(ROOT / ("data/level%d.json" % lv))
    acts = bench.actions_of(sol)
    out = {}
    for name, rules in bench.READINGS.items():
        res = fastsim.simulate(w, acts, rules)
        s = fastsim.score(res)
        s["denied"] = res.denied
        s["rejected"] = res.rejected
        out[name] = s
    worst = min(s["score"] for s in out.values())
    mean = sum(s["score"] for s in out.values()) / len(out)
    return worst, mean, out


def build(lv, spec):
    w = world_mod.load(ROOT / ("data/level%d.json" % lv))
    kw = dict(spec)
    kw.pop("name", None)
    return bands3.build(w, **kw)


def report(lv, name, sol):
    worst, mean, detail = evaluate(lv, sol)
    a = detail["A"]
    print("L%d %-22s worst=%.4f mean=%.4f | A: C=%6d d=%.3f H=%.4f lg=%.4f "
          "den=%4d rej=%4d %s"
          % (lv, name, worst, mean, a["C"], a["density"], a["H"], a["longevity"],
             a["denied"], a["rejected"], dict(sorted(a["counts"].items()))),
          flush=True)
    return worst, mean, detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", type=int, required=True)
    ap.add_argument("--specs", required=True,
                    help="path to a json file: [{name:..., band_species:[...], ...}]")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    specs = json.loads(Path(a.specs).read_text())
    rows = []
    for spec in specs:
        spec = dict(spec)
        spec["strides"] = {int(k): v for k, v in
                           spec.get("strides", STRIDES).items()} \
            if isinstance(spec.get("strides"), dict) else dict(STRIDES)
        spec["scatter"] = [tuple(x) for x in spec.get("scatter", [])]
        spec["primer"] = [tuple(x) for x in spec.get("primer", [])]
        name = spec.get("name", "?")
        sol = build(a.level, spec)
        worst, mean, detail = report(a.level, name, sol)
        p = ROOT / ("experiments/level%d/%s.json" % (a.level, name))
        p.parent.mkdir(parents=True, exist_ok=True)
        sol.write(p)
        rows.append((worst, mean, name, str(p), detail))

    rows.sort(key=lambda r: -r[0])
    print("\nBEST for L%d: %s worst=%.4f (%.0f) mean=%.4f (%.0f)"
          % (a.level, rows[0][2], rows[0][0], rows[0][0] * 1e9,
             rows[0][1], rows[0][1] * 1e9))
    log = ROOT / "results/experiment_log.csv"
    new = not log.exists()
    with log.open("a", newline="", encoding="utf-8") as f:
        wtr = csv.writer(f)
        if new:
            wtr.writerow(["level", "experiment", "worst", "mean", "A_score",
                          "A_C", "A_density", "A_H", "A_longevity", "file"])
        for worst, mean, name, path, detail in rows:
            A = detail["A"]
            wtr.writerow([a.level, name, "%.6f" % worst, "%.6f" % mean,
                          "%.6f" % A["score"], A["C"], "%.4f" % A["density"],
                          "%.4f" % A["H"], "%.4f" % A["longevity"], path])
    if a.out:
        import shutil
        shutil.copy(rows[0][3], ROOT / a.out)
        print("promoted %s -> %s" % (rows[0][2], a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
