import { describe, expect, it } from "vitest";
import { allocateSections, type SpeakerForAllocation } from "./sectionAllocation";

describe("allocateSections", () => {
  it("achieves zero clashes when the field makes it possible", () => {
    const speakers: SpeakerForAllocation[] = [
      { speakerId: "A1", institutionId: "A" },
      { speakerId: "A2", institutionId: "A" },
      { speakerId: "B1", institutionId: "B" },
      { speakerId: "B2", institutionId: "B" },
      { speakerId: "C1", institutionId: "C" },
      { speakerId: "C2", institutionId: "C" },
      { speakerId: "D1", institutionId: "D" },
      { speakerId: "D2", institutionId: "D" },
    ];

    const result = allocateSections(speakers, [4, 4]);

    expect(result.totalClashPenalty).toBe(0);
    expect(result.clashedSpeakerIds.size).toBe(0);
    expect(result.rooms[0]).toHaveLength(4);
    expect(result.rooms[1]).toHaveLength(4);
    // every speaker placed exactly once
    const placed = result.rooms.flat();
    expect(new Set(placed).size).toBe(speakers.length);
  });

  it("flags an unavoidable clash rather than throwing when the field can't be spread cleanly", () => {
    // docs/01 §5: one institution sends 5 speakers into 4-person rooms with
    // only 4 rooms total (16 capacity) — at least one room must double up.
    const speakers: SpeakerForAllocation[] = [
      ...Array.from({ length: 5 }, (_, i) => ({ speakerId: `A${i}`, institutionId: "A" })),
      ...Array.from({ length: 11 }, (_, i) => ({ speakerId: `ind${i}`, institutionId: null })),
    ];

    const result = allocateSections(speakers, [4, 4, 4, 4]);

    expect(result.totalClashPenalty).toBe(1);
    expect(result.clashedSpeakerIds.size).toBe(2);
    for (const room of result.rooms) {
      expect(room).toHaveLength(4);
    }
  });

  it("never leaves a speaker unplaced or a room over capacity", () => {
    const speakers: SpeakerForAllocation[] = Array.from({ length: 27 }, (_, i) => ({
      speakerId: `s${i}`,
      institutionId: i % 5 === 0 ? null : `inst-${i % 4}`,
    }));

    const result = allocateSections(speakers, [7, 7, 7, 6]);

    expect(result.rooms.map((r) => r.length)).toEqual([7, 7, 7, 6]);
    expect(new Set(result.rooms.flat()).size).toBe(27);
  });
});
