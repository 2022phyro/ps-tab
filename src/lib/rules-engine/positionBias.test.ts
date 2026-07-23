import { describe, expect, it } from "vitest";
import { assignSpeakingOrder, computeBiasScore } from "./positionBias";

describe("computeBiasScore", () => {
  it("weights early positions higher, per the docs/01 §6 default schedule", () => {
    expect(computeBiasScore([1])).toBe(3);
    expect(computeBiasScore([2])).toBe(2);
    expect(computeBiasScore([3])).toBe(1);
    expect(computeBiasScore([4])).toBe(0);
    expect(computeBiasScore([1, 2, 3])).toBe(3 + 2 + 1);
  });
});

describe("assignSpeakingOrder", () => {
  it("gives the speaker with the highest bias score the latest (best) slot", () => {
    const assignment = assignSpeakingOrder([
      { speakerId: "frequently-early", positionHistory: [1, 1] },
      { speakerId: "never-early", positionHistory: [4, 4] },
    ]);
    expect(assignment.get("frequently-early")).toBe(2);
    expect(assignment.get("never-early")).toBe(1);
  });

  it("converges to an even spread of early slots over multiple rounds", () => {
    const speakerIds = ["S0", "S1", "S2", "S3"];
    const history = new Map<string, number[]>(speakerIds.map((id) => [id, []]));
    const earlyCount = new Map<string, number>(speakerIds.map((id) => [id, 0]));

    for (let round = 0; round < 6; round++) {
      const roomSpeakers = speakerIds.map((id) => ({
        speakerId: id,
        positionHistory: history.get(id)!,
      }));
      const assignment = assignSpeakingOrder(roomSpeakers);

      for (const id of speakerIds) {
        const position = assignment.get(id)!;
        history.get(id)!.push(position);
        if (position <= 2) earlyCount.set(id, earlyCount.get(id)! + 1);
      }
    }

    const counts = speakerIds.map((id) => earlyCount.get(id)!);
    expect(Math.max(...counts) - Math.min(...counts)).toBeLessThanOrEqual(1);
    // for this symmetric 4-speaker/6-round case it converges exactly evenly
    expect(counts).toEqual([3, 3, 3, 3]);
  });
});
