---
title: "Clashes & Conflict of Interest"
badge: "Deep Dive"
---

# Clashes & Conflict of Interest

A cornerstone of tournament integrity is guaranteeing that competitors are never adjudicated by biased, affiliated, or conflicted individuals. Kwuo utilizes a deterministic multi-tier clash resolution matrix.

---

## 1. Clash Classifications

| Clash Type | Description | System Enforcement |
| :--- | :--- | :--- |
| **Institutional Hard Clash** | Judge and speaker share the same primary educational institution | **Hard Block**: Platform solver will never place the judge in this room |
| **Institutional Soft Clash** | Secondary affiliations (former school, coaching club, regional circuit) | **Soft Penalty**: Avoided unless severe room shortage occurs |
| **Personal Declared Clash** | Close personal relationship, family relation, or past team partnership | **Hard Block**: Inviolable constraint declared by either party |
| **Two-Tier Panel Constraint** | Two judges on the same panel share an institution or conflict | **Panel Balancing**: Solvers prevent single-delegation panel capture |

---

## 2. Managing & Resolving Clashes

During round generation:
1. The draw algorithm builds a bipartite conflict graph between all available adjudicators and the speaker sections.
2. If an unavoidable clash occurs due to judge pool constraints, the platform alerts tab directors in the **Clashes & Contingencies Badge** on the administrative navigation rail.
3. Tab staff can substitute panellists or rotate speakers using the interactive drag-and-drop pairings canvas.
