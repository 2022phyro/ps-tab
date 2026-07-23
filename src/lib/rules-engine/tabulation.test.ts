import { describe, expect, it } from "vitest";
import { compareStandings, computeStandings, sortStandings } from "./tabulation";

describe("docs/01 §7 worked example", () => {
  it("resolves a Total Ranks tie via Total Speaker Points", () => {
    const standings = computeStandings([
      { speakerId: "A", rank: 1, roundScore: 100 },
      { speakerId: "A", rank: 2, roundScore: 90 },
      { speakerId: "A", rank: 3, roundScore: 60 },
      { speakerId: "B", rank: 2, roundScore: 85 },
      { speakerId: "B", rank: 2, roundScore: 80 },
      { speakerId: "B", rank: 2, roundScore: 80 },
    ]);

    const a = standings.find((s) => s.speakerId === "A")!;
    const b = standings.find((s) => s.speakerId === "B")!;

    expect(a.totalRanks).toBe(6);
    expect(b.totalRanks).toBe(6);
    expect(a.totalPoints).toBeGreaterThan(b.totalPoints);
    expect(compareStandings(a, b)).toBeLessThan(0); // A ranks better
  });

  it("falls through to Adjusted Ranks when both Total Ranks and Total Points tie", () => {
    const standings = computeStandings([
      { speakerId: "A", rank: 1, roundScore: 100 },
      { speakerId: "A", rank: 2, roundScore: 90 },
      { speakerId: "A", rank: 3, roundScore: 80 },
      { speakerId: "B", rank: 2, roundScore: 95 },
      { speakerId: "B", rank: 2, roundScore: 95 },
      { speakerId: "B", rank: 2, roundScore: 80 },
    ]);

    const a = standings.find((s) => s.speakerId === "A")!;
    const b = standings.find((s) => s.speakerId === "B")!;

    expect(a.totalRanks).toBe(b.totalRanks); // 6 = 6
    expect(a.totalPoints).toBe(b.totalPoints); // 270 = 270
    // A's worst round (rank 3) dropped -> adjusted 3; B's worst (rank 2) dropped -> adjusted 4
    expect(a.adjustedRanks).toBe(3);
    expect(b.adjustedRanks).toBe(4);
    expect(compareStandings(a, b)).toBeLessThan(0); // A ranks better
  });
});

describe("computeStandings", () => {
  it("leaves a single-round speaker's adjusted ranks equal to total ranks", () => {
    const [row] = computeStandings([{ speakerId: "solo", rank: 2, roundScore: 90 }]);
    expect(row!.totalRanks).toBe(2);
    expect(row!.adjustedRanks).toBe(2);
  });
});

describe("sortStandings", () => {
  it("orders a full field correctly", () => {
    const rows = computeStandings([
      { speakerId: "first", rank: 1, roundScore: 100 },
      { speakerId: "second", rank: 2, roundScore: 90 },
      { speakerId: "third", rank: 3, roundScore: 80 },
    ]);
    const sorted = sortStandings(rows);
    expect(sorted.map((r) => r.speakerId)).toEqual(["first", "second", "third"]);
  });
});
