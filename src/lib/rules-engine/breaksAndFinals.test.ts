import { describe, expect, it } from "vitest";
import { applyBreak } from "./breaksAndFinals";
import { computeStandings, type StandingRow } from "./tabulation";

function makeField(n: number): StandingRow[] {
  // speaker `i` (0-indexed) finishes with totalRanks = i+1 (strictly increasing, no ties)
  return Array.from({ length: n }, (_, i) => ({
    speakerId: `s${i}`,
    totalRanks: i + 1,
    totalPoints: 1000 - i,
    adjustedRanks: i + 1,
    roundsPlayed: 3,
  }));
}

describe("applyBreak", () => {
  it("breaks the top N under FIXED_COUNT", () => {
    const result = applyBreak(makeField(20), { type: "FIXED_COUNT", count: 6 });
    expect(result.qualifiers).toHaveLength(6);
    expect(result.qualifiers.map((s) => s.speakerId)).toEqual(["s0", "s1", "s2", "s3", "s4", "s5"]);
    expect(result.flagged).toBe(false);
  });

  it("extends the break to include everyone tied at the cutoff line by default", () => {
    const field = makeField(10);
    // fully tie s5 and s6 across all three tie-break tiers (both would
    // straddle a top-6 cutoff)
    field[6] = {
      ...field[6]!,
      totalRanks: field[5]!.totalRanks,
      totalPoints: field[5]!.totalPoints,
      adjustedRanks: field[5]!.adjustedRanks,
    };
    const result = applyBreak(field, { type: "FIXED_COUNT", count: 6 });
    expect(result.qualifiers).toHaveLength(7);
    expect(result.qualifiers.map((s) => s.speakerId)).toContain("s6");
  });

  it("does not extend past the cutoff when includeTies is disabled", () => {
    const field = makeField(10);
    field[6] = {
      ...field[6]!,
      totalRanks: field[5]!.totalRanks,
      totalPoints: field[5]!.totalPoints,
      adjustedRanks: field[5]!.adjustedRanks,
    };
    const result = applyBreak(field, { type: "FIXED_COUNT", count: 6, includeTies: false });
    expect(result.qualifiers).toHaveLength(6);
  });

  it("computes a percentage-based break", () => {
    const result = applyBreak(makeField(20), { type: "PERCENTAGE", percentage: 25 });
    expect(result.qualifiers).toHaveLength(5); // ceil(20 * 0.25)
  });

  it("clamps to the field size and flags when the division is too small to meaningfully break (docs/01 §14)", () => {
    const result = applyBreak(makeField(4), { type: "FIXED_COUNT", count: 6 });
    expect(result.qualifiers).toHaveLength(4);
    expect(result.flagged).toBe(true);
  });

  it("chains cleanly across multiple elimination stages with no special-case code (docs/01 §11)", () => {
    // Stage 1: break top 8 of a 16-speaker preliminary field to octofinals.
    const prelimStandings = makeField(16);
    const toOctofinals = applyBreak(prelimStandings, { type: "FIXED_COUNT", count: 8 });
    expect(toOctofinals.qualifiers).toHaveLength(8);

    // Octofinals round happens; re-derive standings from just that round's
    // results (a single round is standings input like any other).
    const octofinalsResults = toOctofinals.qualifiers.map((s, i) => ({
      speakerId: s.speakerId,
      rank: i + 1,
      roundScore: 100 - i,
    }));
    const octofinalsStandings = computeStandings(octofinalsResults);

    // Stage 2: same applyBreak function, no new algorithm, breaking to quarters.
    const toQuarterfinals = applyBreak(octofinalsStandings, { type: "FIXED_COUNT", count: 4 });
    expect(toQuarterfinals.qualifiers).toHaveLength(4);
    expect(toQuarterfinals.qualifiers.map((s) => s.speakerId)).toEqual(["s0", "s1", "s2", "s3"]);
  });
});
