import { afterEach, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import { cleanupFixture, createFixture, makeRound } from "@/lib/judging/testFixtures";
import { releaseDraws, releaseResults, releaseStandings } from "./gates";
import type { Fixture } from "@/lib/judging/testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

describe("releaseDraws", () => {
  it("releases draws and logs an audit entry", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);

    await releaseDraws(round.id, fixture.ownerId);

    const updated = await prisma.round.findUniqueOrThrow({ where: { id: round.id } });
    expect(updated.drawsState).toBe("RELEASED");

    const audit = await prisma.auditLogEntry.findFirstOrThrow({
      where: { tournamentId: fixture.tournamentId, actionType: "publish_toggle" },
    });
    expect(audit.summary).toContain("draws");
  });

  it("refuses to release draws twice", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    await releaseDraws(round.id, fixture.ownerId);
    await expect(releaseDraws(round.id, fixture.ownerId)).rejects.toThrow("already released");
  });
});

describe("releaseResults", () => {
  it("releases results and locks the round unconditionally", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);

    await releaseResults(round.id, fixture.ownerId);

    const updated = await prisma.round.findUniqueOrThrow({ where: { id: round.id } });
    expect(updated.resultsState).toBe("RELEASED");
    expect(updated.lockedAt).not.toBeNull();
  });

  it("preserves an earlier lock timestamp rather than bumping it", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const earlierLock = new Date(Date.now() - 60_000);
    await prisma.round.update({ where: { id: round.id }, data: { lockedAt: earlierLock } });

    await releaseResults(round.id, fixture.ownerId);

    const updated = await prisma.round.findUniqueOrThrow({ where: { id: round.id } });
    expect(updated.lockedAt?.getTime()).toBe(earlierLock.getTime());
  });
});

describe("releaseStandings", () => {
  it("refuses to release standings before that round's own results are released", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    await expect(releaseStandings(round.id, fixture.ownerId)).rejects.toThrow(
      "results aren't released",
    );
  });

  it("releases standings once results are already released", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    await releaseResults(round.id, fixture.ownerId);

    await releaseStandings(round.id, fixture.ownerId);

    const updated = await prisma.round.findUniqueOrThrow({ where: { id: round.id } });
    expect(updated.standingsState).toBe("RELEASED");
  });
});
