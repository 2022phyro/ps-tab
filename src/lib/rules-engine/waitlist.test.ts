import { describe, expect, it } from "vitest";
import { admitOverride, applyCap, promoteFromWaitlist } from "./waitlist";

const entries = Array.from({ length: 8 }, (_, i) => ({ id: `e${i}`, submittedOrder: i }));

describe("applyCap", () => {
  it("admits in submission order up to the cap, waitlisting the rest", () => {
    const result = applyCap(entries, 5);
    expect(result.admitted.map((e) => e.id)).toEqual(["e0", "e1", "e2", "e3", "e4"]);
    expect(result.waitlisted.map((e) => e.id)).toEqual(["e5", "e6", "e7"]);
  });
});

describe("promoteFromWaitlist", () => {
  it("promotes the earliest waitlisted entries in order when capacity frees up", () => {
    const capped = applyCap(entries, 5);
    const promoted = promoteFromWaitlist(capped, 2);
    expect(promoted.admitted.map((e) => e.id)).toEqual(["e0", "e1", "e2", "e3", "e4", "e5", "e6"]);
    expect(promoted.waitlisted.map((e) => e.id)).toEqual(["e7"]);
  });
});

describe("admitOverride", () => {
  it("admits a specific waitlisted entry regardless of cap, since the cap is a soft ceiling", () => {
    const capped = applyCap(entries, 5);
    const overridden = admitOverride(capped, "e7");
    expect(overridden.admitted.map((e) => e.id)).toContain("e7");
    expect(overridden.admitted).toHaveLength(6); // exceeds the nominal cap of 5
    expect(overridden.waitlisted.map((e) => e.id)).toEqual(["e5", "e6"]);
  });

  it("is a no-op if the entry isn't actually on the waitlist", () => {
    const capped = applyCap(entries, 5);
    const result = admitOverride(capped, "does-not-exist");
    expect(result).toEqual(capped);
  });
});
