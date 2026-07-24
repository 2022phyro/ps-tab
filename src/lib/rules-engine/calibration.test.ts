import { describe, expect, it } from "vitest";
import { detectCalibrationOutliers, spearmanCorrelation } from "./calibration";

describe("spearmanCorrelation", () => {
  it("is 1 for identical rank orders", () => {
    expect(spearmanCorrelation([1, 2, 3, 4], [1, 2, 3, 4])).toBeCloseTo(1);
  });

  it("is -1 for perfectly reversed rank orders", () => {
    expect(spearmanCorrelation([1, 2, 3, 4], [4, 3, 2, 1])).toBeCloseTo(-1);
  });

  it("returns 1 for a degenerate all-tied sequence rather than dividing by zero", () => {
    expect(spearmanCorrelation([1, 2, 3, 4], [5, 5, 5, 5])).toBe(1);
  });

  it("throws on mismatched or empty sequences", () => {
    expect(() => spearmanCorrelation([1, 2], [1, 2, 3])).toThrow();
    expect(() => spearmanCorrelation([], [])).toThrow();
  });
});

describe("detectCalibrationOutliers", () => {
  it("never flags a lone judge with no one to compare against", () => {
    const flags = detectCalibrationOutliers([{ judgeId: "solo", ranks: { A: 1, B: 2 } }]);
    expect(flags).toEqual([]);
  });

  it("flags the one judge whose ranking diverges from the other two's agreement", () => {
    // hand-verified: judge1/judge2 agree exactly (A,B,C,D -> 1,2,3,4); judge3
    // ranks the same room as D,B,C,A (roughly reversed) -> correlation -0.2
    // against the consensus, well below the 0.3 threshold, while judge1 and
    // judge2 each correlate at +0.6325 against a consensus of the other two.
    const rankings = [
      { judgeId: "judge1", ranks: { A: 1, B: 2, C: 3, D: 4 } },
      { judgeId: "judge2", ranks: { A: 1, B: 2, C: 3, D: 4 } },
      { judgeId: "judge3", ranks: { A: 4, B: 1, C: 2, D: 3 } },
    ];

    const flags = detectCalibrationOutliers(rankings);
    expect(flags.map((f) => f.judgeId)).toEqual(["judge3"]);
    expect(flags[0]!.correlation).toBeCloseTo(-0.2);
  });

  it("flags no one when the whole panel agrees", () => {
    const rankings = [
      { judgeId: "j1", ranks: { A: 1, B: 2, C: 3 } },
      { judgeId: "j2", ranks: { A: 1, B: 2, C: 3 } },
      { judgeId: "j3", ranks: { A: 1, B: 2, C: 3 } },
    ];
    expect(detectCalibrationOutliers(rankings)).toEqual([]);
  });
});
