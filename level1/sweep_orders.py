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
    return ev["worst"], ev["mean"], ev["best"], ev["primary"], p

def main():
    level = int(sys.argv[1]); topn = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    T = O.world(level).ticks
    base = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    grid = []
    for order in itertools.permutations((1, 2, 5, 6, 12)):
        p = dict(species=order, stride=base.get("stride", 4),
                 seed_start=base.get("seed_start", T - 120), waves=1, wave_gap=150,
                 axis=base.get("axis", "col"), topup_start=base.get("topup_start", T - 55),
                 topup_stride=1, rebalance=base.get("rebalance", 40), weights=None)
        grid.append(p)
    rows = []
    with ProcessPoolExecutor() as ex:
        for r in ex.map(run, [(level, p) for p in grid], chunksize=1):
            if r: rows.append(r)
    rows.sort(key=lambda t: -t[0])
    for w, m, b, pr, p in rows[:topn]:
        print("worst=%7.1fM mean=%7.1fM best=%7.1fM | order=%-18s C=%6d dens=%.3f H=%.4f %s" %
              (w*1e3, m*1e3, b*1e3, str(p["species"]), pr["C"], pr["density"], pr["H"],
               dict(sorted(pr["counts"].items(), key=lambda kv: -kv[1]))))
    json.dump([{"worst": w, "mean": m, "best": b, "order": list(p["species"]),
                "C": pr["C"], "H": pr["H"]} for w, m, b, pr, p in rows],
              open("out/orders_l%d.json" % level, "w"), indent=1)

if __name__ == "__main__":
    main()
