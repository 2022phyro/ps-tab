import { describe, expect, it } from "vitest";
import { computeAvailableJudgesForSlot, findDoubleBookings } from "./schedulingCollisions";

describe("findDoubleBookings", () => {
  it("flags a speaker scheduled into two events at the same time slot", () => {
    const collisions = findDoubleBookings([
      { personId: "speaker-1", eventId: "extemp", timeSlotId: "round-2" },
      { personId: "speaker-1", eventId: "oratory", timeSlotId: "round-2" },
    ]);
    expect(collisions.has("speaker-1")).toBe(true);
    expect(collisions.get("speaker-1")).toHaveLength(2);
  });

  it("does not flag the same person across different time slots", () => {
    const collisions = findDoubleBookings([
      { personId: "speaker-1", eventId: "extemp", timeSlotId: "round-1" },
      { personId: "speaker-1", eventId: "oratory", timeSlotId: "round-2" },
    ]);
    expect(collisions.size).toBe(0);
  });

  it("works identically for judges pulled from a shared cross-event pool", () => {
    const collisions = findDoubleBookings([
      { personId: "judge-1", eventId: "extemp", timeSlotId: "round-2" },
      { personId: "judge-1", eventId: "duo-interp", timeSlotId: "round-2" },
    ]);
    expect(collisions.has("judge-1")).toBe(true);
  });
});

describe("computeAvailableJudgesForSlot", () => {
  it("excludes judges already assigned anywhere in that time slot", () => {
    const available = computeAvailableJudgesForSlot(
      ["j1", "j2", "j3"],
      [{ personId: "j1", eventId: "oratory", timeSlotId: "round-2" }],
      "round-2",
    );
    expect(available).toEqual(["j2", "j3"]);
  });
});
