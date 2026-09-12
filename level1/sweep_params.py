import sys, json, itertools
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, '.')
import optimise_v3 as O

def run(args):
    level, p = args
    try:
        sol = O.build(level, p)
    except ValueError:
        return None
    ev = O.evaluate(level, sol)
    return ev["worst"], ev["mean"], ev["best"], ev["primary"], p, sol.total_actions()

def main():
    level = int(sys.argv[1])
    T = O.world(level).ticks
    orders = [tuple(json.loads(o)) for o in sys.argv[2].split(";")]
    strides = [int(x) for x in sys.argv[3].split(",")]
    seeds = [int(x) for x in sys.argv[4].split(",")]
    grid = []
    for order in orders:
        for stride in strides:
            for seed in seeds:
                for topup in (None, seed + 60, T - 120, T - 60):
                    for reb in (20, 40):
                        if topup is not None and topup <= seed:
                            continue
                        grid.append(dict(species=order, stride=stride, seed_start=seed,
                                         waves=1, wave_gap=150, axis="col",
                                         topup_start=topup, topup_stride=1,
                                         rebalance=reb, weights=None))
    print("level %d: %d candidates" % (level, len(grid)))
    rows = []
    with ProcessPoolExecutor() as ex:
        for r in ex.map(run, [(level, p) for p in grid], chunksize=1):
            if r: rows.append(r)
    rows.sort(key=lambda t: -t[0])
    for w, m, b, pr, p, na in rows[:18]:
        print("worst=%7.1fM mean=%7.1fM best=%7.1fM | ord=%-17s str=%-2d seed=%3d topup=%s reb=%d acts=%d"
              % (w*1e3, m*1e3, b*1e3, str(p["species"]), p["stride"], p["seed_start"],
                 p["topup_start"], p["rebalance"], na))
        print("      C=%6d dens=%.3f H=%.4f long=%.4f %s" %
              (pr["C"], pr["density"], pr["H"], pr["longevity"],
               dict(sorted(pr["counts"].items(), key=lambda kv: -kv[1]))))
    json.dump([{"worst": w, "mean": m, "best": b, "C": pr["C"], "H": pr["H"],
                "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in p.items()}}
               for w, m, b, pr, p, na in rows[:60]],
              open("out/params_l%d.json" % level, "w"), indent=1)

if __name__ == "__main__":
    main()
