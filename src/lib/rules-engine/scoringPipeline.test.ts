import { describe, expect, it } from "vitest";
import { computeJudgeTotal, computeRanks, computeRoundScore } from "./scoringPipeline";

describe("computeJudgeTotal", () => {
  it("sums criteria and subtracts the time penalty", () => {
    const total = computeJudgeTotal({
      judgeId: "j1",
      criteriaScores: [28, 27, 18, 19],
      timePenalty: 2,
    });
    expect(total).toBe(28 + 27 + 18 + 19 - 2);
  });
});

describe("computeRoundScore", () => {
  it("averages judge totals across a multi-judge panel", () => {
    const score = computeRoundScore([
      { judgeId: "j1", criteriaScores: [90], timePenalty: 0 },
      { judgeId: "j2", criteriaScores: [80], timePenalty: 0 },
      { judgeId: "j3", criteriaScores: [100], timePenalty: 0 },
    ]);
    expect(score).toBe(90);
  });

  it("degenerates to the single judge's total when J=1 (docs/01 §14 edge case)", () => {
    const score = computeRoundScore([{ judgeId: "j1", criteriaScores: [95], timePenalty: 5 }]);
    expect(score).toBe(90);
  });

  it("throws rather than silently returning a meaningless value with zero judges", () => {
    expect(() => computeRoundScore([])).toThrow();
  });
});

describe("computeRanks", () => {
  it("ranks speakers in a section by descending round score", () => {
    const ranks = computeRanks([
      { speakerId: "a", roundScore: 90 },
      { speakerId: "b", roundScore: 95 },
      { speakerId: "c", roundScore: 80 },
    ]);
    expect(ranks.get("b")).toBe(1);
    expect(ranks.get("a")).toBe(2);
    expect(ranks.get("c")).toBe(3);
  });

  it("shares a fractional average rank across ties by default", () => {
    const ranks = computeRanks([
      { speakerId: "a", roundScore: 90 },
      { speakerId: "b", roundScore: 90 },
      { speakerId: "c", roundScore: 80 },
    ]);
    // a and b tie for positions 1-2 -> both get 1.5; c gets 3
    expect(ranks.get("a")).toBe(1.5);
    expect(ranks.get("b")).toBe(1.5);
    expect(ranks.get("c")).toBe(3);
  });

  it("assigns three-way ties the average of positions 1-3", () => {
    const ranks = computeRanks([
      { speakerId: "a", roundScore: 90 },
      { speakerId: "b", roundScore: 90 },
      { speakerId: "c", roundScore: 90 },
      { speakerId: "d", roundScore: 70 },
    ]);
    expect(ranks.get("a")).toBe(2);
    expect(ranks.get("b")).toBe(2);
    expect(ranks.get("c")).toBe(2);
    expect(ranks.get("d")).toBe(4);
  });

  it("assigns distinct whole ranks using the tie-break comparator when configured", () => {
    const ranks = computeRanks(
      [
        { speakerId: "a", roundScore: 90 },
        { speakerId: "b", roundScore: 90 },
      ],
      {
        method: "whole",
        tieBreakOrder: (x, y) => (x.speakerId < y.speakerId ? -1 : 1),
      },
    );
    expect(ranks.get("a")).toBe(1);
    expect(ranks.get("b")).toBe(2);
  });
});
