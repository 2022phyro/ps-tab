import { describe, expect, it } from "vitest";
import { roomTieBreakFor, seedSpeakers, type StandingLookup } from "./drawMethods";
import { allocateSections, type SpeakerForAllocation } from "./sectionAllocation";

// 8 independent speakers (no institutions, so clash penalty is always zero
// everywhere) ranked 1 (best) through 8 (worst) — isolates the seeding/
// room-preference behavior from clash-avoidance entirely.
const speakers: SpeakerForAllocation[] = Array.from({ length: 8 }, (_, i) => ({
  speakerId: `s${i + 1}`,
  institutionId: null,
}));

const standings: StandingLookup = {
  standing: (speakerId) => Number(speakerId.slice(1)),
};

describe("seedSpeakers", () => {
  it("returns speakers unchanged for a random draw", () => {
    expect(seedSpeakers(speakers, "random")).toEqual(speakers);
  });

  it("orders by current standing for power-matched methods", () => {
    const shuffled = [...speakers].reverse();
    const seeded = seedSpeakers(shuffled, "high-high", standings);
    expect(seeded.map((s) => s.speakerId)).toEqual([
      "s1",
      "s2",
      "s3",
      "s4",
      "s5",
      "s6",
      "s7",
      "s8",
    ]);
  });
});

describe("high-high vs. high-low room placement", () => {
  it("high-high groups the top standings into the same room", () => {
    const seeded = seedSpeakers(speakers, "high-high", standings);
    const result = allocateSections(seeded, [4, 4], {
      seedOrder: seeded,
      roomTieBreak: roomTieBreakFor("high-high"),
    });
    expect(result.rooms[0]).toEqual(["s1", "s2", "s3", "s4"]);
    expect(result.rooms[1]).toEqual(["s5", "s6", "s7", "s8"]);
  });

  it("high-low spreads the top standings across different rooms", () => {
    const seeded = seedSpeakers(speakers, "high-low", standings);
    const result = allocateSections(seeded, [4, 4], {
      seedOrder: seeded,
      roomTieBreak: roomTieBreakFor("high-low"),
    });
    const roomOf = (id: string) => result.rooms.findIndex((room) => room.includes(id));
    expect(roomOf("s1")).not.toBe(roomOf("s2"));
    // each room ends up with a mix of strong and weak standings, not a block
    expect(result.rooms[0]).toContain("s1");
    expect(result.rooms[0]).toContain("s7");
  });
});
