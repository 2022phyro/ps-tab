---
title: Institutional Clash Spreading
badge: Tabulation
---

# Institutional Clash Spreading

When assigning checked-in speakers to section rooms, placing two competitors from the same university or debating society into the same heat should be minimized.

---

## Constraints Hierarchy

1. **Hard Constraint**: Every checked-in speaker must be placed into exactly one room matching the room plan.
2. **Soft Constraint**: Minimizing pairwise co-occurrences of speakers sharing the same `institution_id` in any given room.

---

## Greedy Placement & Local Search Heuristic

```
Sort speakers descending by institution size (place largest delegations first)
For each speaker:
    Place into the candidate room that incurs the lowest marginal clash penalty

Run local search repair pass:
    While improving pairwise swaps exist:
        Swap speakers between rooms if total institutional clash penalty drops
```

> [!TIP]
> If a single institution sends more speakers than there are rooms in a division, clashes become mathematically unavoidable. In this scenario, Kwuo achieves the lowest possible penalty and visibly flags affected sections in the tab room.
