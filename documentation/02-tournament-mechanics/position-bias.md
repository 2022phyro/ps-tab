---
title: Position Bias Balancing
badge: Fairness
---

# Position Bias Balancing

In oratorical competitions, speaking order significantly influences judge perception. Speakers who deliver speeches 1st or 2nd often face harsher evaluation before judges calibrate their scoring baseline.

---

## Bias Score Calculation

Kwuo maintains a persistent history of speaking slots drawn by each speaker across prior rounds:

$$\text{BiasScore}(s) = \sum_{r=1}^{k} w(\text{position}_{s,r})$$

Where earlier speaking positions carry higher bias penalties:
* **Position 1**: Weight = $3$
* **Position 2**: Weight = $2$
* **Position 3**: Weight = $1$
* **Position 4+**: Weight = $0$

---

## Balancing Algorithm

When speakers enter their assigned room for the upcoming round:
1. Sort speakers in the room by their historical `BiasScore` in descending order.
2. Assign later speaking slots to participants with higher bias scores first.
3. This guarantees that over multi-round tournaments, every speaker receives an equitable distribution of early and late slots.
