import { describe, expect, it } from "vitest";
import { capRoomPlanByJudges, computeRoomPlan } from "./roomSizing";

describe("computeRoomPlan", () => {
  it("matches the docs/01 §3 worked example (N=27, 4-8)", () => {
    const plan = computeRoomPlan(27, { roomSizeMin: 4, roomSizeMax: 8 });
    expect(plan.roomSizes).toEqual([7, 7, 7, 6]);
    expect(plan.flagged).toBe(false);
  });

  it("collapses to a single flagged room when N is below the minimum", () => {
    const plan = computeRoomPlan(3, { roomSizeMin: 4, roomSizeMax: 8 });
    expect(plan.roomSizes).toEqual([3]);
    expect(plan.flagged).toBe(true);
  });

  it("never produces rooms differing by more than one speaker", () => {
    for (let n = 4; n <= 60; n++) {
      const plan = computeRoomPlan(n, { roomSizeMin: 4, roomSizeMax: 8 });
      const max = Math.max(...plan.roomSizes);
      const min = Math.min(...plan.roomSizes);
      expect(max - min).toBeLessThanOrEqual(1);
      expect(plan.roomSizes.reduce((a, b) => a + b, 0)).toBe(n);
    }
  });

  it("widens the max room size rather than violating the minimum when bounds are unsatisfiable", () => {
    // N=9 with min=5,max=6: k_min=ceil(9/6)=2, k_max=floor(9/5)=1 -> k_min>k_max,
    // must widen max until satisfiable.
    const plan = computeRoomPlan(9, { roomSizeMin: 5, roomSizeMax: 6 });
    expect(plan.roomSizes.every((size) => size >= 5)).toBe(true);
    expect(plan.roomSizes.reduce((a, b) => a + b, 0)).toBe(9);
  });

  it("prefers more, smaller rooms when configured to", () => {
    const plan = computeRoomPlan(27, { roomSizeMin: 4, roomSizeMax: 8, preference: "smallest" });
    // k_max = floor(27/4) = 6 rooms
    expect(plan.roomSizes).toHaveLength(6);
    expect(plan.roomSizes.reduce((a, b) => a + b, 0)).toBe(27);
  });
});

describe("capRoomPlanByJudges", () => {
  it("reduces room count and re-derives sizes when judges are the binding constraint", () => {
    const plan = computeRoomPlan(27, { roomSizeMin: 4, roomSizeMax: 8 });
    const capped = capRoomPlanByJudges(plan, 3);
    expect(capped.roomSizes).toHaveLength(3);
    expect(capped.roomSizes.reduce((a, b) => a + b, 0)).toBe(27);
    expect(capped.flagged).toBe(true);
  });

  it("leaves the plan untouched when judges aren't the binding constraint", () => {
    const plan = computeRoomPlan(27, { roomSizeMin: 4, roomSizeMax: 8 });
    const capped = capRoomPlanByJudges(plan, 10);
    expect(capped).toEqual(plan);
  });
});
