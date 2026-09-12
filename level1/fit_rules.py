#!/usr/bin/env python3
"""Fit fastsim.Rules to ALL FOUR official fingerprints simultaneously."""
import json,sys,itertools,math
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0,'.')
from photospheria import fastsim, world as world_mod
from photospheria.fastsim import Rules

def load_actions(p):
    d=json.load(open(p)); out={}
    for a in d['actions']:
        out.setdefault(a['tick'],[]).extend((x['plant_index'],x['row'],x['col']) for x in a['plants'])
    return out

FP=[('L1',1,'submitted/solution.json',{1:706,2:151,5:200,6:455,12:288}),
    ('L2a',2,'out/solution_level2.json',{1:2993,2:169,5:191,6:1713,12:968}),
    ('L2b',2,'submitted/solution_level2.json',{5:1602,6:1071,12:41}),
    ('L3a',3,'submitted/solution_level3.json',{5:158,12:14797})]
_W={}
def world(lv):
    if lv not in _W: _W[lv]=world_mod.load(f'data/level{lv}.json')
    return _W[lv]
_A={}
def acts(p):
    if p not in _A: _A[p]=load_actions(p)
    return _A[p]

def evaluate(r):
    tot=0.0; detail=[]
    for name,lv,path,off in FP:
        res=fastsim.simulate(world(lv),acts(path),r)
        s=fastsim.score(res); got=s['counts']; offC=sum(off.values()); gotC=max(1,s['C'])
        # relative composition error: L1 distance between normalised histograms + density error
        keys=set(list(off)+list(got))
        comp=sum(abs(got.get(k,0)/gotC-off.get(k,0)/offC) for k in keys)/2
        dens=abs(gotC-offC)/offC
        tot+=comp+dens
        detail.append((name,gotC,offC,comp,dens,dict(sorted(got.items()))))
    return tot,detail

def job(args):
    rm,mt,dp,pk,dd=args
    r=Rules(rate_mode=rm,mature=mt,displace=dp,pick=pk,drain_dead=dd)
    try: t,d=evaluate(r)
    except Exception as e: return (1e9,args,str(e))
    return (t,args,d)

if __name__=="__main__":
    combos=[]
    for rm in ("period","cells"):
      for mt in ("gt","ge","none"):
        for dp in ("never","rank_gt","rank_ge","different","always"):
          for pk in (("near","sorted") if rm=="cells" else ("near",)):
            for dd in (0.5,1.0):
              combos.append((rm,mt,dp,pk,dd))
    with ProcessPoolExecutor() as ex:
        out=list(ex.map(job,combos,chunksize=1))
    out.sort(key=lambda x:x[0])
    for t,args,d in out[:12]:
        print(f"=== ERR={t:.4f}  rate={args[0]} mature={args[1]} displace={args[2]} pick={args[3]} dd={args[4]}")
        if isinstance(d,str): print("   ",d); continue
        for name,gotC,offC,comp,dens,got in d:
            print(f"    {name:4} C={gotC:6}/{offC:<6} compErr={comp:.3f} densErr={dens:.3f} {got}")
