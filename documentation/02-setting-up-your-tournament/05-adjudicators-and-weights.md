---
title: "Adjudicators & Weighting"
badge: "Phase 1: Step 5"
---

# Adjudicators & Weighting

In competitive public speaking, adjudicators are evaluated, calibrated, and ranked to ensure panels are fair and well-balanced. Kwuo implements an advanced **Three-Factor Composite Weighting Engine**.

---

## 1. The Three-Factor Judging Composite

Every judge's overall competency score is computed from three standardized inputs:

```
Composite Score = (Test Score × Weight₁) + (CV Score × Weight₂) + (Peer Feedback × Weight₃)
```

1. **Adjudication Test Score (0–100)**: Evaluates rulebook comprehension, rubric alignment, and speed/accuracy during the pre-tournament judging test.
2. **Curriculum Vitae / Experience Score (0–100)**: Rates past judging and speaking credentials at national and international championships.
3. **Live Peer & Speaker Feedback (0–100)**: Aggregates real-time post-round evaluations submitted by room co-panellists and speakers throughout preliminary flights.

---

## 2. Configuring Composite Ratios

In the **Adjudicators** cockpit, tab directors can customize the composite weighting formula. Common circuit defaults include:
- **Balanced (40 / 20 / 40)**: 40% Test, 20% CV, 40% Live Feedback.
- **Accredited Heavy (50 / 30 / 20)**: 50% Test, 30% CV, 20% Live Feedback.
- **Pure Performance (50 / 0 / 50)**: 50% Test, 0% CV, 50% Live Feedback.

> [!TIP]
> The composite score automatically determines judge seniority for chairing allocations when drawing panels.

---

## 3. Judge Availability & Affiliation Clashes

- **Primary Institution**: Hard affiliation preventing the judge from being drawn into any section featuring competitors from their home institution.
- **Secondary Affiliations**: Clubs, former alma maters, and debating academies where the judge has past coaching or team relationships.
- **Check-in & Flight Availability**: Toggle judge status (e.g., *Active*, *Standby*, *Unavailable*) to immediately include or remove them from subsequent round draws.
