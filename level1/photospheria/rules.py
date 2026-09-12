"""
The rule readings we score against, and why we score against SIX of them.

fit_l2.py fits every combination of the open spread rules to the one official
run we can reconstruct completely (2.log = out/solution_level2.json on Level 2:
C = 6034, H = 0.3518, longevity = 0.0760, and 425 denied placements with
coordinates).  No combination reproduces it.  The best reach C within 8% but
every one of them fills the board 40-60 ticks too early, over-predicting denied
placements roughly 2.5x (1,069 against the official 425).  Something about how
many cells one spread event actually seeds is still wrong, and three
fingerprints are not enough to pin it down.

So we stop pretending we have THE model.  A candidate is judged by its WORST
score across the readings below, not its best.  That is what makes the design
choice safe: the strategy we ship has to be the one that wins under a slow
spread, a fast spread, rank-ordered competition and free-for-all competition
alike.

What the logs DO pin down exactly, and what the strategies actually rely on:
  * the score formula (verified to six decimals on all three logs);
  * planting onto an occupied cell is denied, onto an empty cell it succeeds;
  * a plant painted ~99 ticks before the end is still alive at scoring
    (Level 2 painted from tick 401 with T = 500 and lost nothing to starvation);
  * species painted as separate blocks keep roughly their proportions while
    they expand (Level 2: five species, H = 0.3518), whereas interleaved
    species collapse towards one (Level 3: H = 0.0607).
"""
from __future__ import annotations

from .fastsim import Rules

#: Lowest error against the Level-2 anchor (fit_l2.py).  Used for reporting a
#: single headline number only - never for choosing between candidates.
BEST = Rules(rate_mode="period", mature="none", displace="different",
             drain_dead=0.5, crosshatch="star")

#: Six readings the evidence cannot separate.  Deliberately spread across the
#: axes that matter most: how often a plant spreads, how much it seeds per
#: event, and who wins a contested cell.
ROBUST = {
    # the literal PDF reading: spread every spread_rate ticks once mature,
    # higher invasiveness_rank displaces
    "period-gt-rank": Rules(rate_mode="period", mature="gt", displace="rank_gt"),
    # best Level-2 fit
    "period-none-diff": Rules(rate_mode="period", mature="none",
                              displace="different", crosshatch="star"),
    # second-best fit, and the one that preserves the most diversity
    "cells-none-never": Rules(rate_mode="cells", pick="near", mature="none",
                              displace="never"),
    # fastest plausible spread: every tick, whole shape, rank-ordered
    "cells-all-ge-rank": Rules(rate_mode="cells", pick="all", mature="ge",
                               displace="rank_gt"),
    # slow spread, no competition at all
    "period-ge-never": Rules(rate_mode="period", mature="ge", displace="never"),
    # the diversity-hostile corner: last spreader takes everything
    "period-gt-always": Rules(rate_mode="period", mature="gt", displace="always"),
}
