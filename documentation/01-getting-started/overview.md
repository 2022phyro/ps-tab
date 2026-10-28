---
title: Welcome to Kwuo
badge: Core Concept
---

# Welcome to Kwuo

**Kwuo** (*"Speak"* in Igbo) is a specialized tabulation platform and tournament management engine created from the ground up for **competitive public speaking**.

Unlike parliamentary debating tools that revolve around two-team or four-team binary clashes, Kwuo is built around the **multi-speaker section** ($4$ to $8$ speakers per room) judged by independent rubrics.

> [!NOTE]
> Kwuo treats the **individual orator** as the atomic unit of competition, and **ordinal rank within a section** as the primary currency of competitive merit.

---

## The Three Fundamental Shifts

1. **Sections, Not Paired Rooms**:
   Every round consists of independent heats where multiple speakers present sequentially in front of a judging panel.
2. **Institutional Clash Spreading**:
   Rather than hard side constraints, the pairing engine uses a greedy heuristic with local repair to distribute participants from the same university across different sections.
3. **Speaking Order Position-Bias Balancing**:
   Speaking 1st or 2nd is a documented disadvantage in oratorical contests. Kwuo tracks every speaker's position history across rounds and balances future speaking orders automatically.

---

## Key Platform Pillars

### Zero-Auth Tournament-Day Access
Judges and competitors never need to register accounts or reset passwords on tournament morning. Every roster import produces high-entropy tokenized links and printable QR codes that deliver users directly into their scoped mobile ballots or schedules.

### Independent Publishing Gates
Draws, results, and cumulative standings have independent visibility gates. Round results can be held until all rooms finish, or individual disputed rooms can be placed under targeted embargo without halting the tournament.
