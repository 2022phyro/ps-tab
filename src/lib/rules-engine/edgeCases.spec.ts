// docs/01-tournament-mechanics.md §14 — edge cases, exercised across the
// modules above rather than reimplemented here. Two of the six documented
// edge cases (late scratches' ripple effect, and waitlist promotion after
// check-in has closed) depend on round/check-in state that doesn't exist at
// this pure-logic layer — those are Section 6/7 concerns, not this one.

import { describe, expect, it } from "vitest";
import { applyBreak } from "./breaksAndFinals";
import { computeRoomPlan } from "./roomSizing";
import { computeRoundScore } from "./scoringPipeline";
import { computeStandings } from "./tabulation";

describe("docs/01 §14 edge cases", () => {
  it("byes: an undersized room proceeds (flagged), never silently dropped", () => {
    const plan = computeRoomPlan(3, { roomSizeMin: 4, roomSizeMax: 8 });
    expect(plan.roomSizes).toEqual([3]);
    expect(plan.flagged).toBe(true);
  });

  it("uneven rooms: never differ by more than one speaker, for any N", () => {
    for (let n = 5; n <= 50; n++) {
      const plan = computeRoomPlan(n, { roomSizeMin: 4, roomSizeMax: 8 });
      expect(Math.max(...plan.roomSizes) - Math.min(...plan.roomSizes)).toBeLessThanOrEqual(1);
    }
  });

  it("single-judge panels: the Round Score pipeline degenerates gracefully with J=1", () => {
    const score = computeRoundScore([{ judgeId: "solo", criteriaScores: [88], timePenalty: 0 }]);
    expect(score).toBe(88);
  });

  it("a division too small to meaningfully break clamps to the field size and flags it", () => {
    const standings = computeStandings([
      { speakerId: "n1", rank: 1, roundScore: 90 },
      { speakerId: "n2", rank: 2, roundScore: 85 },
      { speakerId: "n3", rank: 3, roundScore: 80 },
      { speakerId: "n4", rank: 4, roundScore: 75 },
    ]);
    // "break top 6" configured, but only 4 Novice speakers registered
    const result = applyBreak(standings, { type: "FIXED_COUNT", count: 6 });
    expect(result.qualifiers).toHaveLength(4);
    expect(result.flagged).toBe(true);
  });
});
