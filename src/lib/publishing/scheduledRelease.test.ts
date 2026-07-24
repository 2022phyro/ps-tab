import { afterEach, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import { cleanupFixture, createFixture, makeRound } from "@/lib/judging/testFixtures";
import {
  cancelScheduledRelease,
  executeDueScheduledReleases,
  scheduleGateRelease,
} from "./scheduledRelease";
import type { Fixture } from "@/lib/judging/testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

describe("scheduleGateRelease", () => {
  it("creates a schedule and refuses a second active one for the same round+gate", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    await scheduleGateRelease(round.id, "DRAWS", new Date(Date.now() + 60_000), fixture.ownerId);

    await expect(
      scheduleGateRelease(round.id, "DRAWS", new Date(Date.now() + 120_000), fixture.ownerId),
    ).rejects.toThrow("already exists");
  });
});

describe("cancelScheduledRelease", () => {
  it("cancels a pending schedule and is idempotent", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const schedule = await scheduleGateRelease(
      round.id,
      "DRAWS",
      new Date(Date.now() + 60_000),
      fixture.ownerId,
    );

    await cancelScheduledRelease(schedule.id);
    const updated = await prisma.scheduledRelease.findUniqueOrThrow({ where: { id: schedule.id } });
    expect(updated.cancelledAt).not.toBeNull();

    await expect(cancelScheduledRelease(schedule.id)).resolves.not.toThrow();
  });

  it("refuses to cancel a schedule that already fired", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const schedule = await scheduleGateRelease(
      round.id,
      "DRAWS",
      new Date(Date.now() - 60_000),
      fixture.ownerId,
    );
    await executeDueScheduledReleases();

    await expect(cancelScheduledRelease(schedule.id)).rejects.toThrow("already fired");
  });
});

describe("executeDueScheduledReleases", () => {
  it("fires a due schedule and marks it executed, but leaves a future one pending", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const due = await scheduleGateRelease(
      round.id,
      "DRAWS",
      new Date(Date.now() - 60_000),
      fixture.ownerId,
    );
    const future = await scheduleGateRelease(
      round.id,
      "RESULTS",
      new Date(Date.now() + 60_000),
      fixture.ownerId,
    );

    const result = await executeDueScheduledReleases();
    expect(result.executedIds).toEqual([due.id]);

    const updatedRound = await prisma.round.findUniqueOrThrow({ where: { id: round.id } });
    expect(updatedRound.drawsState).toBe("RELEASED");

    const futureRow = await prisma.scheduledRelease.findUniqueOrThrow({ where: { id: future.id } });
    expect(futureRow.executedAt).toBeNull();
  });

  it("leaves a schedule pending (not executed, not thrown) when its precondition isn't met", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    // standings scheduled, but this round's results were never released —
    // releaseStandings would throw; the sweep should skip it, not crash.
    const schedule = await scheduleGateRelease(
      round.id,
      "STANDINGS",
      new Date(Date.now() - 60_000),
      fixture.ownerId,
    );

    const result = await executeDueScheduledReleases();
    expect(result.executedIds).toEqual([]);

    const row = await prisma.scheduledRelease.findUniqueOrThrow({ where: { id: schedule.id } });
    expect(row.executedAt).toBeNull();
  });

  it("ignores a cancelled schedule even if it's due", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const schedule = await scheduleGateRelease(
      round.id,
      "DRAWS",
      new Date(Date.now() - 60_000),
      fixture.ownerId,
    );
    await cancelScheduledRelease(schedule.id);

    const result = await executeDueScheduledReleases();
    expect(result.executedIds).toEqual([]);
  });
});
