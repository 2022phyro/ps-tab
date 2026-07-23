import { describe, expect, it } from "vitest";
import { computeSweepstakes } from "./sweepstakes";

const entrants = [
  { speakerId: "a1", institutionId: "A", totalPoints: 250, rank: 1 },
  { speakerId: "a2", institutionId: "A", totalPoints: 200, rank: 3 },
  { speakerId: "a3", institutionId: "A", totalPoints: 100, rank: 8 },
  { speakerId: "b1", institutionId: "B", totalPoints: 240, rank: 2 },
  { speakerId: "ind", institutionId: null, totalPoints: 300, rank: 1 },
];

describe("computeSweepstakes", () => {
  it("sums an institution's top-K speakers under top-k-sum", () => {
    const scores = computeSweepstakes(entrants, { type: "top-k-sum", k: 2 });
    expect(scores.get("A")).toBe(250 + 200); // best two of [250,200,100]
    expect(scores.get("B")).toBe(240);
    expect(scores.has("ind")).toBe(false); // independents excluded from institution scoring
  });

  it("scores by a rank-based placement scale, counting every entrant", () => {
    const scale = new Map([
      [1, 10],
      [2, 8],
      [3, 6],
      [8, 1],
    ]);
    const scores = computeSweepstakes(entrants, { type: "placement-scale", scale });
    expect(scores.get("A")).toBe(10 + 6 + 1); // ranks 1,3,8 — every entrant counts
    expect(scores.get("B")).toBe(8);
  });

  it("never mutates or references individual standings — a pure read-only view", () => {
    const before = entrants.map((e) => ({ ...e }));
    computeSweepstakes(entrants, { type: "top-k-sum", k: 1 });
    expect(entrants).toEqual(before);
  });
});
