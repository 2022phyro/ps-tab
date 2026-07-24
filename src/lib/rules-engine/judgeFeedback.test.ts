import { describe, expect, it } from "vitest";
import {
  applyJudgeBreak,
  compareJudgeStandings,
  computeJudgeFeedbackAverages,
  sortJudgeStandings,
} from "./judgeFeedback";

describe("computeJudgeFeedbackAverages", () => {
  it("averages every rater's score for a judge, from speakers and panelists alike", () => {
    const standings = computeJudgeFeedbackAverages([
      { ratedJudgeId: "j1", score: 8 }, // speaker
      { ratedJudgeId: "j1", score: 10 }, // panelist
      { ratedJudgeId: "j2", score: 5 },
    ]);

    const j1 = standings.find((s) => s.judgeId === "j1")!;
    expect(j1.averageScore).toBe(9);
    expect(j1.feedbackCount).toBe(2);

    const j2 = standings.find((s) => s.judgeId === "j2")!;
    expect(j2.averageScore).toBe(5);
    expect(j2.feedbackCount).toBe(1);
  });
});

describe("compareJudgeStandings / sortJudgeStandings", () => {
  it("ranks higher average feedback first", () => {
    const sorted = sortJudgeStandings([
      { judgeId: "low", averageScore: 6, feedbackCount: 10 },
      { judgeId: "high", averageScore: 9, feedbackCount: 3 },
    ]);
    expect(sorted.map((s) => s.judgeId)).toEqual(["high", "low"]);
  });

  it("breaks a tied average by whoever has judged (been rated) more", () => {
    const sorted = sortJudgeStandings([
      { judgeId: "thin-sample", averageScore: 9, feedbackCount: 2 },
      { judgeId: "proven", averageScore: 9, feedbackCount: 20 },
    ]);
    expect(sorted.map((s) => s.judgeId)).toEqual(["proven", "thin-sample"]);
  });

  it("compareJudgeStandings returns 0 for a genuine full tie", () => {
    const a = { judgeId: "a", averageScore: 9, feedbackCount: 5 };
    const b = { judgeId: "b", averageScore: 9, feedbackCount: 5 };
    expect(compareJudgeStandings(a, b)).toBe(0);
  });
});

describe("applyJudgeBreak", () => {
  const standings = [
    { judgeId: "j1", averageScore: 9.5, feedbackCount: 10 },
    { judgeId: "j2", averageScore: 9.0, feedbackCount: 10 },
    { judgeId: "j3", averageScore: 8.5, feedbackCount: 10 },
    { judgeId: "j4", averageScore: 8.0, feedbackCount: 10 },
  ];

  it("breaks the top N judges by cumulative feedback", () => {
    const result = applyJudgeBreak(standings, 2);
    expect(result.breakingJudges.map((j) => j.judgeId)).toEqual(["j1", "j2"]);
    expect(result.flagged).toBe(false);
  });

  it("extends the break to include judges tied at the cutoff", () => {
    const tied = [...standings, { judgeId: "j2b", averageScore: 9.0, feedbackCount: 10 }];
    const result = applyJudgeBreak(tied, 2);
    expect(result.breakingJudges.map((j) => j.judgeId).sort()).toEqual(["j1", "j2", "j2b"]);
  });

  it("clamps and flags when there aren't enough judges with feedback", () => {
    const result = applyJudgeBreak(standings, 10);
    expect(result.breakingJudges).toHaveLength(4);
    expect(result.flagged).toBe(true);
  });
});
