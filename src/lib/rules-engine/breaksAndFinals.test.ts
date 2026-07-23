import { describe, expect, it } from "vitest";
import {
  applyBreak,
  resolveBreakConfig,
  resolvePartialBreak,
  resolvePartialBreakConfig,
  splitForPartialBreak,
  type PartialBreakConfig,
  type RoomLocalResult,
} from "./breaksAndFinals";
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

  it("chains cleanly across an arbitrarily deep bracket — prelims to quarters to semis to finals — with no special-case code per stage (docs/01 §11)", () => {
    // helper: play a single-room knockout round over the given qualifiers,
    // in the same rank order they qualified, and re-derive standings from it
    const playRound = (qualifiers: StandingRow[]) =>
      computeStandings(
        qualifiers.map((s, i) => ({ speakerId: s.speakerId, rank: i + 1, roundScore: 100 - i })),
      );

    const prelimStandings = makeField(32);

    const toQuarterfinals = applyBreak(prelimStandings, { type: "FIXED_COUNT", count: 8 });
    expect(toQuarterfinals.qualifiers).toHaveLength(8);

    const quarterfinalsStandings = playRound(toQuarterfinals.qualifiers);
    const toSemifinals = applyBreak(quarterfinalsStandings, { type: "FIXED_COUNT", count: 4 });
    expect(toSemifinals.qualifiers).toHaveLength(4);

    const semifinalsStandings = playRound(toSemifinals.qualifiers);
    const toFinals = applyBreak(semifinalsStandings, { type: "FIXED_COUNT", count: 2 });
    expect(toFinals.qualifiers).toHaveLength(2);
    expect(toFinals.qualifiers.map((s) => s.speakerId)).toEqual(["s0", "s1"]);
  });
});

describe("resolveBreakConfig", () => {
  it("uses the tournament/division default when no override is given", () => {
    const resolved = resolveBreakConfig({ type: "FIXED_COUNT", count: 8 });
    expect(resolved).toEqual({ type: "FIXED_COUNT", count: 8 });
  });

  it("lets tab staff override the default for one specific stage", () => {
    // configured default: break top 8 to quarters; staff decide to break top
    // 6 instead, just for this stage, without touching the stored default
    const defaultConfig = { type: "FIXED_COUNT", count: 8 } as const;
    const resolved = resolveBreakConfig(defaultConfig, { type: "FIXED_COUNT", count: 6 });
    expect(resolved).toEqual({ type: "FIXED_COUNT", count: 6 });

    const result = applyBreak(makeField(20), resolved);
    expect(result.qualifiers).toHaveLength(6);
  });
});

describe("splitForPartialBreak", () => {
  const config: PartialBreakConfig = {
    autoAdvanceCount: 2,
    bubbleRangeStart: 3,
    bubbleRangeEnd: 6,
  };

  function roomOf(label: string, size: number): RoomLocalResult[] {
    return Array.from({ length: size }, (_, i) => ({
      speakerId: `${label}${i + 1}`,
      roomLabel: label,
      roomRank: i + 1,
    }));
  }

  it("auto-advances the top N from every room and pools the rest for the bubble round", () => {
    const results = [...roomOf("A", 6), ...roomOf("B", 6), ...roomOf("C", 6)];
    const split = splitForPartialBreak(results, config);

    expect(split.autoQualifiers.sort()).toEqual(["A1", "A2", "B1", "B2", "C1", "C2"]);
    expect(split.bubblePool.sort()).toEqual(
      ["A3", "A4", "A5", "A6", "B3", "B4", "B5", "B6", "C3", "C4", "C5", "C6"].sort(),
    );
    expect(split.eliminated).toHaveLength(0);
  });

  it("eliminates finishers below the bubble range in larger rooms", () => {
    const results = roomOf("A", 8); // ranks 7-8 fall outside a 3-6 bubble range
    const split = splitForPartialBreak(results, config);
    expect(split.eliminated.sort()).toEqual(["A7", "A8"]);
  });
});

describe("resolvePartialBreak", () => {
  it("fills the remaining slots from the bubble round's top finishers", () => {
    const autoQualifiers = ["A1", "A2", "B1", "B2"];
    const bubbleRoundResults = Array.from({ length: 8 }, (_, i) => ({
      speakerId: `bubble${i + 1}`,
      rank: i + 1,
    }));

    const resolved = resolvePartialBreak(autoQualifiers, bubbleRoundResults, 8);
    expect(resolved.qualifiers).toHaveLength(8);
    expect(resolved.qualifiers).toEqual([
      ...autoQualifiers,
      "bubble1",
      "bubble2",
      "bubble3",
      "bubble4",
    ]);
    expect(resolved.flagged).toBe(false);
  });

  it("extends past the cutoff for ties in the bubble round, same as a normal break", () => {
    const bubbleRoundResults = [
      { speakerId: "b1", rank: 1 },
      { speakerId: "b2", rank: 2 },
      { speakerId: "b3", rank: 2 }, // tied with b2 at the cutoff
      { speakerId: "b4", rank: 4 },
    ];
    const resolved = resolvePartialBreak([], bubbleRoundResults, 2);
    expect(resolved.qualifiers.sort()).toEqual(["b1", "b2", "b3"]);
  });

  it("flags when the bubble pool is too small to fill the remaining slots", () => {
    const resolved = resolvePartialBreak(["A1"], [{ speakerId: "b1", rank: 1 }], 5);
    expect(resolved.flagged).toBe(true);
    expect(resolved.qualifiers).toEqual(["A1", "b1"]);
  });

  it("flags when automatic advancers alone already exceed the slots needed", () => {
    const resolved = resolvePartialBreak(["A1", "A2", "A3"], [], 2);
    expect(resolved.flagged).toBe(true);
    expect(resolved.qualifiers).toEqual(["A1", "A2", "A3"]);
  });
});

describe("resolvePartialBreakConfig", () => {
  it("overrides only the fields given, keeping the rest of the default", () => {
    const defaultConfig: PartialBreakConfig = {
      autoAdvanceCount: 2,
      bubbleRangeStart: 3,
      bubbleRangeEnd: 6,
    };
    const resolved = resolvePartialBreakConfig(defaultConfig, { autoAdvanceCount: 3 });
    expect(resolved).toEqual({ autoAdvanceCount: 3, bubbleRangeStart: 3, bubbleRangeEnd: 6 });
  });
});

describe("end-to-end: partial break feeding into a full-bracket chain", () => {
  it("matches the exact scenario described: top 2 per room auto-advance, 3rd-6th fight for the rest, survivors join the next stage", () => {
    // Quarterfinals: 4 rooms of 6 (24 speakers). Default config says top 2
    // auto-advance; tab staff override to top 2 as well here (explicitly
    // exercising the point-in-time override path) with the standard 3-6
    // bubble range.
    const defaultPartialConfig: PartialBreakConfig = {
      autoAdvanceCount: 2,
      bubbleRangeStart: 3,
      bubbleRangeEnd: 6,
    };
    const partialConfig = resolvePartialBreakConfig(defaultPartialConfig, {});

    const rooms = ["A", "B", "C", "D"].flatMap((label) =>
      Array.from({ length: 6 }, (_, i) => ({
        speakerId: `${label}${i + 1}`,
        roomLabel: label,
        roomRank: i + 1,
      })),
    );

    const split = splitForPartialBreak(rooms, partialConfig);
    expect(split.autoQualifiers).toHaveLength(8); // 2 per room x 4 rooms
    expect(split.bubblePool).toHaveLength(16); // 4 per room x 4 rooms (3rd-6th)

    // Semifinals need 12 total: the 8 auto-advancers plus 4 more, decided by
    // playing the bubble round among the 16 who didn't auto-advance.
    const bubbleRoundResults = split.bubblePool.map((speakerId, i) => ({ speakerId, rank: i + 1 }));
    const toSemifinals = resolvePartialBreak(split.autoQualifiers, bubbleRoundResults, 12);

    expect(toSemifinals.qualifiers).toHaveLength(12);
    expect(toSemifinals.flagged).toBe(false);
    // all 8 auto-advancers are in, plus exactly the top 4 bubble-round finishers
    for (const id of split.autoQualifiers) expect(toSemifinals.qualifiers).toContain(id);
    for (const id of bubbleRoundResults.slice(0, 4).map((r) => r.speakerId)) {
      expect(toSemifinals.qualifiers).toContain(id);
    }
    for (const id of bubbleRoundResults.slice(4).map((r) => r.speakerId)) {
      expect(toSemifinals.qualifiers).not.toContain(id);
    }

    // Semifinals plays out as an ordinary full break down to Finals — no
    // special partial-break handling needed once the roster is merged.
    const semifinalStandings = computeStandings(
      toSemifinals.qualifiers.map((speakerId, i) => ({
        speakerId,
        rank: i + 1,
        roundScore: 100 - i,
      })),
    );
    const toFinals = applyBreak(semifinalStandings, { type: "FIXED_COUNT", count: 6 });
    expect(toFinals.qualifiers).toHaveLength(6);
  });
});
