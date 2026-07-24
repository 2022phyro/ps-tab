import { afterEach, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import { cleanupFixture, createFixture, makeJudge, makeSpeaker } from "@/lib/judging/testFixtures";
import { anonymizeUnclaimedRosterPii } from "./retention";
import type { Fixture } from "@/lib/judging/testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

const OLD_CUTOFF = new Date(Date.now() + 60_000); // "past cutoff" for anything created before now

describe("anonymizeUnclaimedRosterPii", () => {
  it("anonymizes an unclaimed speaker/judge in an Archived tournament past the cutoff", async () => {
    fixture = await createFixture();
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const judge = await makeJudge(fixture.tournamentId);
    await prisma.tournament.update({
      where: { id: fixture.tournamentId },
      data: { state: "ARCHIVED" },
    });

    const result = await anonymizeUnclaimedRosterPii(OLD_CUTOFF);
    expect(result.anonymizedSpeakerCount).toBeGreaterThanOrEqual(1);
    expect(result.anonymizedJudgeCount).toBeGreaterThanOrEqual(1);

    const updatedSpeaker = await prisma.speaker.findUniqueOrThrow({ where: { id: speaker.id } });
    expect(updatedSpeaker.name).toBe("[Removed]");
    expect(updatedSpeaker.email).toBe("removed@invalid.example");

    const updatedJudge = await prisma.judge.findUniqueOrThrow({ where: { id: judge.id } });
    expect(updatedJudge.name).toBe("[Removed]");
  });

  it("leaves a claimed entry (userId set) untouched", async () => {
    fixture = await createFixture();
    const claimant = await prisma.user.create({
      data: { email: `retention-claimant-${Date.now()}@example.com`, name: "Claimant" },
    });
    const speaker = await prisma.speaker.create({
      data: {
        tournamentId: fixture.tournamentId,
        divisionId: fixture.divisionId,
        name: "Claimed Speaker",
        email: "claimed@example.com",
        userId: claimant.id,
      },
    });
    await prisma.tournament.update({
      where: { id: fixture.tournamentId },
      data: { state: "ARCHIVED" },
    });

    await anonymizeUnclaimedRosterPii(OLD_CUTOFF);

    const updated = await prisma.speaker.findUniqueOrThrow({ where: { id: speaker.id } });
    expect(updated.name).toBe("Claimed Speaker");

    await prisma.user.delete({ where: { id: claimant.id } });
  });

  it("leaves a roster entry in a non-Archived tournament untouched", async () => {
    fixture = await createFixture(); // stays DRAFT
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);

    await anonymizeUnclaimedRosterPii(OLD_CUTOFF);

    const updated = await prisma.speaker.findUniqueOrThrow({ where: { id: speaker.id } });
    expect(updated.name).not.toBe("[Removed]");
  });

  it("leaves an entry created after the cutoff untouched", async () => {
    fixture = await createFixture();
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    await prisma.tournament.update({
      where: { id: fixture.tournamentId },
      data: { state: "ARCHIVED" },
    });

    const pastCutoff = new Date(Date.now() - 60_000); // entry was created after this
    await anonymizeUnclaimedRosterPii(pastCutoff);

    const updated = await prisma.speaker.findUniqueOrThrow({ where: { id: speaker.id } });
    expect(updated.name).not.toBe("[Removed]");
  });
});
