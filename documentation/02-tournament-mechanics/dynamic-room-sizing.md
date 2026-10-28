---
title: Dynamic Room Sizing & Check-In
badge: Algorithm
---

# Dynamic Room Sizing & Check-In

In public speaking tournaments, room fairness depends strictly on **how many speakers actually speak in each room**. A section of $4$ speakers has a completely different scoring dynamic than a section of $8$.

---

## The Headcount Problem

Tournament check-in headcount naturally fluctuates round-by-round due to scratches, sickness, or transportation delays. Rather than sizing rooms once at registration, Kwuo recalculates the room plan **immediately prior to generating each round's draw** from checked-in attendees.

---

## The Room Sizing Algorithm

Given checked-in headcount $N$ and configured bounds $[R_{\min}, R_{\max}]$ (typically $R_{\min}=4, R_{\max}=8$):

```python
import math

def compute_room_plan(n: int, r_min: int = 4, r_max: int = 8) -> list[int]:
    if n < r_min:
        return [n]  # Collapse into single room for organizer intervention
    
    k_min = math.ceil(n / r_max)   # Minimum rooms required
    k_max = math.floor(n / r_min)  # Maximum rooms allowed
    
    if k_min > k_max:
        # Widen upper bound by 1 if no integer room count satisfies constraints
        return compute_room_plan(n, r_min, r_max + 1)
        
    k = k_min  # Prefer fullest sections
    base = n // k
    remainder = n % k
    
    # Distribute remainder so rooms differ in size by at most 1
    return [base + 1] * remainder + [base] * (k - remainder)
```

> [!IMPORTANT]
> The algorithm guarantees that no two rooms in the same round will differ in size by more than **1 speaker**.
