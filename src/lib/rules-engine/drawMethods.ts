// docs/01-tournament-mechanics.md §11 — draw methods: random vs. power-matched.
//
// Power-matching changes only the seeding order fed into section allocation
// (docs/01 §5) — clash-avoidance runs identically. "high-high" groups top
// standings into the same room by feeding them in first and packing rooms
// one at a time (sectionAllocation's "fill-first" room tie-break);
// "high-low" spreads them evenly by round-robining across rooms instead
// ("least-filled"). See sectionAllocation.ts's `roomTieBreak` option.

import type { SpeakerForAllocation } from "./sectionAllocation";

export type SeedMethod = "random" | "high-high" | "high-low";

export interface StandingLookup {
  /** lower is better, e.g. current cumulative rank position. */
  standing(speakerId: string): number;
}

export function seedSpeakers(
  speakers: SpeakerForAllocation[],
  method: SeedMethod,
  standings?: StandingLookup,
): SpeakerForAllocation[] {
  if (method === "random") return speakers;
  if (!standings) {
    throw new Error(`seedSpeakers requires standings for method "${method}"`);
  }

  const groupSize = new Map<string, number>();
  for (const s of speakers) {
    if (s.institutionId === null) continue;
    groupSize.set(s.institutionId, (groupSize.get(s.institutionId) ?? 0) + 1);
  }

  // sorted by current standing first, institution-group-size as the
  // tie-break within same-standing bands (docs/01 §11)
  return [...speakers].sort((a, b) => {
    const standingDiff = standings.standing(a.speakerId) - standings.standing(b.speakerId);
    if (standingDiff !== 0) return standingDiff;
    const sizeA = a.institutionId ? (groupSize.get(a.institutionId) ?? 0) : 0;
    const sizeB = b.institutionId ? (groupSize.get(b.institutionId) ?? 0) : 0;
    return sizeB - sizeA;
  });
}

/** Which sectionAllocation.roomTieBreak to use for a given power-matching method. */
export function roomTieBreakFor(method: SeedMethod): "fill-first" | "least-filled" {
  return method === "high-high" ? "fill-first" : "least-filled";
}
