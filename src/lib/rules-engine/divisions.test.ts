import { describe, expect, it } from "vitest";
import { computeCrossDivisionAward, partitionByDivision } from "./divisions";

describe("partitionByDivision", () => {
  it("groups items by division and never leaks one division's rows into another's", () => {
    const speakers = [
      { speakerId: "a", divisionId: "novice" },
      { speakerId: "b", divisionId: "open" },
      { speakerId: "c", divisionId: "novice" },
    ];
    const byDivision = partitionByDivision(speakers);
    expect(byDivision.get("novice")!.map((s) => s.speakerId)).toEqual(["a", "c"]);
    expect(byDivision.get("open")!.map((s) => s.speakerId)).toEqual(["b"]);
  });
});

describe("computeCrossDivisionAward", () => {
  it("picks one winner per division without altering either division's own standings", () => {
    const byDivision = new Map([
      [
        "novice",
        [
          { id: "n1", points: 90 },
          { id: "n2", points: 95 },
        ],
      ],
      [
        "open",
        [
          { id: "o1", points: 120 },
          { id: "o2", points: 110 },
        ],
      ],
    ]);
    const winners = computeCrossDivisionAward(byDivision, (rows) =>
      rows.reduce((best, r) => (r.points > best.points ? r : best)),
    );
    expect(winners.map((w) => w.id).sort()).toEqual(["n2", "o1"]);
  });
});
