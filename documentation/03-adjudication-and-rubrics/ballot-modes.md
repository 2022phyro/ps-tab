---
title: Democracy vs. Strict Ballot Modes
badge: Scoring
---

# Democracy vs. Strict Ballot Modes

Kwuo natively supports both dominant adjudication styles used in major championships (such as WUDC, EUDC, and PAUDC).

---

## Democracy Mode (Default)

In Democracy Mode, each judge on a multi-adjudicator panel fills out an independent scorecard:

$$\text{Round Score} = \frac{1}{J} \sum_{j=1}^J \text{JudgeTotal}_j$$

* **Independent Evaluation**: Panelists do not confer before entering individual criteria scores.
* **Aggregated Output**: The room score represents the arithmetic mean of all submitted panelist ballots.

---

## Strict Mode (Consensus Deliberation)

In Strict Mode, the panel confers together at the conclusion of the round:
* The panel reaches consensus on the final rankings and scores.
* The designated **Panel Chair** submits a single authoritative composite ballot on behalf of the section.
* Prevents rogue scoring anomalies in high-stakes outround stages.
