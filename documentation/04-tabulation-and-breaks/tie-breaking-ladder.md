---
title: The Tie-Breaking Hierarchy
badge: Standings
---

# The Tie-Breaking Hierarchy

Cumulative tournament standings across preliminary rounds follow a strict five-tier tiebreaker ladder:

---

## The 5-Tier Ladder

1. **Tier 1 — Cumulative Sum of Ranks (Cumes)** *(Primary - Lower is better)*:
   $$\min \sum_{r=1}^M \text{Rank}_r$$
2. **Tier 2 — Sum of Reciprocals** *(Secondary - Higher is better)*:
   $$\max \sum_{r=1}^M \frac{1}{\text{Rank}_r}$$
   *Rewards peak brilliance: a $1-5-2$ sequence beats a $3-3-2$ sequence even though both sum to $8$.*
3. **Tier 3 — Total Speaker Points** *(Tertiary - Higher is better)*:
   $$\max \sum_{r=1}^M \text{RoundScore}_r$$
4. **Tier 4 — Adjusted Ranks (Drop-Worst)**:
   Recalculates the rank sum after eliminating each speaker's single lowest-placed preliminary round.
5. **Tier 5 — Head-to-Head (H2H)**:
   Direct comparison of placements in rounds where tied competitors competed in the same section.
