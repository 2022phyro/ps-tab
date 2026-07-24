import { describe, expect, it } from "vitest";
import {
  computeJudgeTotal,
  computeRanks,
  computeRoundScore,
  computeRoundScoreForMode,
  resolveRankMethod,
} from "./scoringPipeline";

describe("computeJudgeTotal", () => {
  it("sums criteria and subtracts the time penalty", () => {
    const total = computeJudgeTotal({
      judgeId: "j1",
      criteriaScores: [28, 27, 18, 19],
      timePenalty: 2,
    });
    expect(total).toBe(28 + 27 + 18 + 19 - 2);
  });

  it("adds the rubric's base score on top of the criteria, per docs/01 §4", () => {
    const total = computeJudgeTotal({
      judgeId: "j1",
      criteriaScores: [10, 10, 5, 5],
      timePenalty: 0,
      baseScore: 70,
    });
    expect(total).toBe(70 + 10 + 10 + 5 + 5);
  });

  it("defaults the base score to 0 for rubrics that don't use one", () => {
    const total = computeJudgeTotal({ judgeId: "j1", criteriaScores: [30], timePenalty: 0 });
    expect(total).toBe(30);
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

describe("computeRoundScoreForMode", () => {
  const panel = [
    { judgeId: "chair", criteriaScores: [90], timePenalty: 0 },
    { judgeId: "panelist-1", criteriaScores: [80], timePenalty: 0 },
    { judgeId: "panelist-2", criteriaScores: [100], timePenalty: 0 },
  ];

  it("averages the whole panel under Democracy, same as computeRoundScore", () => {
    expect(computeRoundScoreForMode(panel, "DEMOCRACY")).toBe(90);
  });

  it("under Strict with a single submitted ballot, uses it directly with no averaging", () => {
    const score = computeRoundScoreForMode(
      [{ judgeId: "chair", criteriaScores: [88], timePenalty: 3 }],
      "STRICT",
    );
    expect(score).toBe(85);
  });

  it("under Strict with multiple ballots present, uses only the chair's — ignoring the others entirely", () => {
    // deliberately picked so the chair's score differs from the panel average
    // (90) — if this returned 90 it would mean averaging leaked in.
    const skewedPanel = [
      { judgeId: "chair", criteriaScores: [75], timePenalty: 0 },
      { judgeId: "panelist-1", criteriaScores: [95], timePenalty: 0 },
    ];
    expect(computeRoundScoreForMode(skewedPanel, "STRICT", "chair")).toBe(75);
  });

  it("throws under Strict with multiple ballots and no chairJudgeId to disambiguate", () => {
    expect(() => computeRoundScoreForMode(panel, "STRICT")).toThrow();
  });

  it("throws under Strict if the named chair never actually submitted a ballot", () => {
    expect(() => computeRoundScoreForMode(panel, "STRICT", "someone-else")).toThrow();
  });

  it("throws with zero judge scores regardless of mode", () => {
    expect(() => computeRoundScoreForMode([], "DEMOCRACY")).toThrow();
    expect(() => computeRoundScoreForMode([], "STRICT")).toThrow();
  });
});

describe("resolveRankMethod", () => {
  it("always uses whole/sequential ranks for outrounds, regardless of the prelim setting", () => {
    expect(resolveRankMethod("ELIMINATION", true)).toBe("whole");
    expect(resolveRankMethod("ELIMINATION", false)).toBe("whole");
  });

  it("follows the organizer's setting for prelims", () => {
    expect(resolveRankMethod("PRELIM", true)).toBe("fractional");
    expect(resolveRankMethod("PRELIM", false)).toBe("whole");
  });
});
