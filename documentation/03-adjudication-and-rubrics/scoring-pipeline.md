---
title: The Scoring Pipeline
badge: Adjudication
---

# The Scoring Pipeline

Adjudicators evaluate orators using structured criteria rubrics with optional base scores and strict speech duration timers.

---

## 1. Raw Judge Total

For each judge evaluating a speaker:

$$\text{JudgeTotal} = \text{BaseScore} + \sum_{i=1}^M \text{Score}(c_i) - \text{TimePenalty}$$

* **Base Score**: Configurable starting baseline (e.g., $70$ points).
* **Criteria ($c_i$)**: Matter/Content ($0-10$), Manner/Delivery ($0-10$), Method/Structure ($0-5$), and Language Use ($0-5$).
* **Time Penalty**: Automatically deducted when speech length exceeds the allowed window beyond the grace threshold (e.g., $-1$ point per $10$ seconds).

---

## 2. Converting Points to Section Ranks

In Kwuo, scores exist to determine rank within a section:
* Round Scores within a section are sorted in descending order.
* The highest-scoring speaker receives **Rank 1**, second receives **Rank 2**, and so on.
* Ranks are comparable across sections of different sizes (a 1st in a 5-speaker heat and a 1st in a 7-speaker heat both count as $1.0$).
