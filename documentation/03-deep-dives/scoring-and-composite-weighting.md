---
title: "Scoring & Composite Weighting"
badge: "Deep Dive"
---

# Scoring & Composite Weighting

Evaluating expressive speech across diverse panellists requires robust statistical normalization and calibrated judge weighting.

---

## 1. Multi-Criteria Ballot Pipeline

When an adjudicator completes an electronic ballot:
1. They assign individual point marks across the active rubric criteria (e.g., Content, Delivery, Structure).
2. The system computes the raw total speech score.
3. The platform verifies that the total conforms to the tournament's scale boundaries (e.g. 70.0 to 100.0).
4. The system validates that speaker rank orders align monotonically with their numeric scores:
   - A speaker with Rank 1 must have a score greater than or equal to Rank 2.
   - Any ties trigger an immediate warning prompt if prelim ties are prohibited.

---

## 2. Dynamic Adjudicator Composite

Judges are dynamically weighted based on their composite rating:

$$\text{Composite} = \left(\text{Test} \times \frac{W_1}{100}\right) + \left(\text{CV} \times \frac{W_2}{100}\right) + \left(\text{Feedback} \times \frac{W_3}{100}\right)$$

- **Chair Allocation**: The highest-rated judge on a three-person panel is designated as the panel Chair.
- **Outround Eligibility**: Only adjudicators meeting the minimum composite benchmark qualify to judge elimination outround brackets.
