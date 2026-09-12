# Photospheria — what the official evaluation logs actually prove

Everything here is derived from the nine official evaluation logs, not from our
simulator. Where a claim rests on our simulator it says so.

## 1. The scoring function is solved exactly

```
score = 0.8 · H₃₁ · C/(rows·cols)  +  0.2 · Σage/(rows·cols·T)
```

* `C` — plants alive at the final tick
* `H₃₁` — Shannon entropy of the alive-species counts, in base 31
* `rows·cols` — the **whole** grid, void cells included (`c_max_or_grid_size`)
* `T` — `ticks` from the level file

Reproduced to 9 decimal places on all six scored runs. Consequences:

* Density and entropy are ~everything; longevity is a 20 % garnish that is
  capped by the nutrient clock at roughly `100/T`.
* With `k` species present and balanced, `H₃₁ = ln k / ln 31`. Five species cap
  H at **0.4687**. Entropy is forgiving of one small species: a species holding
  7 % of the board instead of 20 % costs only 4 % of H.

## 2. Which cells can be planted

`plantable ⟺ terrain == 0 AND soil ∈ preferred_soil`, and **cells the level file
omits default to terrain 0 / soil 0** (so they are plantable by every starter).

| level | grid | listed | plantable | max density |
|---|---|---|---|---|
| 1 | 50×50 = 2,500 | 1,060 | 1,800 | 0.720 |
| 2 | 70×100 = 7,000 | 1,110 | 6,135 | 0.876 |
| 3 | 150×150 = 22,500 | 4,921 | 18,295 | 0.813 |
| 4 | 200×300 = 60,000 | 6,413 | 54,012 | 0.900 |

Level 1 finished with **C = 1800 exactly**, i.e. every plantable cell and not
one more. That is what pins the rule down.

## 3. Spread never displaces — it only fills EMPTY cells

The Level-1 accounting closes exactly:

```
gained by spread  = 244 (Grass) + 88 (Sunflower) + 140 (Oak)      = 472
cells never successfully planted = 1800 − 1328 successful plants  = 472
Rose Bush: 463 actions on plantable cells, 151 alive → 312 DENIED
312 denied + 160 never targeted = 472
```

So a planting onto an occupied cell is **denied** (the logs say so 2,907 times),
and a species only ever gains ground that nobody has claimed yet. There is no
displacement, no erosion, and therefore **the composition we lay down is the
composition that gets scored**. Contiguous territories are stable.

## 4. Spread geometry is the hidden constraint

Closing each species' offset set under repetition — the fraction of the board it
can *ever* reach from one seed:

| species | spread | reach | notes |
|---|---|---|---|
| Grass | VonNeumann r1 | **100 %** | fastest filler, 0.5 cell/tick |
| Oak Tree | Moore r2 | **100 %** | |
| Lavender | CrossHatch r1 | **50 %** | diagonal moves preserve `(r+c)` parity |
| Dwarf Sunflower | CrossHatch r2 | **50 %** | same parity trap |
| Rose Bush | Row r1 | **2 %** | it can never leave its own row |

This explains the two worst historical results: Lavender went **127 seeds → 0
survivors** on Level 3, and Rose Bush gained **exactly zero** cells on Level 1.

## 5. The nutrient clock makes only the last ~100 ticks matter

100 nutrients, 1/tick while occupied, so a plant dies at age ~100. Anything
planted before `T−100` is dead at scoring time. On Levels 3 and 4 (T = 800) the
entire scored board is grown in the final 99 ticks; the early seeding phase
contributes nothing directly.

## 6. Seasons decide which species can still act at the end

| level | season over the final 99 ticks |
|---|---|
| 1, 2 | **Spring** — everything can spread |
| 3, 4 | **Winter** — Rose Bush and Lavender both carry `no_winter_spread` |

On Levels 3 and 4 the final count of Rose and Lavender is therefore *exactly*
the number of cells we paint for them. They get a small **compact block** each
(a 2,000-cell band on Level 4 is 7 rows deep and a neighbour's frontier crosses
it in 14 ticks; the same cells as a 45×45 block take 44 ticks to reach the
middle of) while the three species that still spread take the rest.

## 7. What the old submissions were actually losing

| run | actions | on plantable cells | wasted | duplicates |
|---|---|---|---|---|
| L1 | 1,980 | 1,640 | 340 | 0 |
| L2 (1,980) | 1,980 | 1,299 | 681 | 0 |
| L2 (4,625) | 4,625 | 245 | 681 | **3,699** |
| L3 (4,592) | 4,592 | 233 | 1,744 | **2,615** |

The "free hedge" of aiming at cells of unknown terrain was not free — it cost
17–34 % of the action budget. The current build wastes **zero** actions: no
duplicates, no off-grid, no unplantable targets.

## 8. Which rule reading to trust

Our simulator cannot reproduce the official spread exactly, so candidates are
scored under four readings and judged on the worst. Ranked by how well each
reproduces the official Level-1 histogram `{1:706, 2:151, 5:200, 6:455, 12:288}`:

| reading | rate_mode | mature | L1 error | verdict |
|---|---|---|---|---|
| **C** | cells | none | **474** | best fit |
| D | cells | gt | 528 | plausible |
| A | period | gt | 912 | poor |
| B | period | none | 992 | **falsified** — predicts Oak = 0 on L1 |

Reading B is the only one under which the current build does badly, and it is
the one reading the official data rules out: it puts Oak at 0 on Level 1 where
the official result has 288.
