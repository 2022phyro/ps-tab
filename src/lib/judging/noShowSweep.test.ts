import { afterEach, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import {
  cleanupFixture,
  createFixture,
  makeJudge,
  makeRound,
  makeSection,
  makeSpeaker,
} from "./testFixtures";
import { sweepNoShows, sweepUnresponsive } from "./noShowSweep";
import type { Fixture } from "./testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

describe("sweepNoShows", () => {
  it("does nothing while the check-in window is still open", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId, {
      checkInClosesAt: new Date(Date.now() + 60_000),
    });
    const judge = await makeJudge(fixture.tournamentId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    await prisma.panel.create({
      data: { sectionId: section.id, judgeId: judge.id, isChair: true },
    });

    const result = await sweepNoShows(round.id);
    expect(result.flaggedJudgeIds).toEqual([]);
  });

  it("flags an assigned judge who never checked in once the window has closed", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId, {
      checkInClosesAt: new Date(Date.now() - 60_000),
    });
    const judge = await makeJudge(fixture.tournamentId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    await prisma.panel.create({
      data: { sectionId: section.id, judgeId: judge.id, isChair: true },
    });

    const result = await sweepNoShows(round.id);
    expect(result.flaggedJudgeIds).toEqual([judge.id]);

    const checkIn = await prisma.judgeCheckIn.findUniqueOrThrow({
      where: { roundId_judgeId: { roundId: round.id, judgeId: judge.id } },
    });
    expect(checkIn.status).toBe("NO_SHOW");

    const auditEntry = await prisma.auditLogEntry.findFirstOrThrow({
      where: { tournamentId: fixture.tournamentId, actionType: "no_show_sweep" },
    });
    expect(auditEntry.actorUserId).toBeNull();
  });

  it("never flags a judge who did check in", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId, {
      checkInClosesAt: new Date(Date.now() - 60_000),
    });
    const judge = await makeJudge(fixture.tournamentId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    await prisma.panel.create({
      data: { sectionId: section.id, judgeId: judge.id, isChair: true },
    });
    await prisma.judgeCheckIn.create({
      data: { roundId: round.id, judgeId: judge.id, status: "CHECKED_IN" },
    });

    const result = await sweepNoShows(round.id);
    expect(result.flaggedJudgeIds).toEqual([]);
  });
});

describe("sweepUnresponsive", () => {
  it("throws if the round has no scheduledEndAt set", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    await expect(sweepUnresponsive(round.id, 15)).rejects.toThrow("scheduledEndAt");
  });

  it("does nothing before the grace period has elapsed", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId, {
      scheduledEndAt: new Date(Date.now() - 60_000), // ended 1 min ago
    });
    const result = await sweepUnresponsive(round.id, 15); // 15 min grace — not up yet
    expect(result.flaggedJudgeIds).toEqual([]);
  });

  it("flags a checked-in judge with an unsubmitted ballot past the grace deadline", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId, {
      scheduledEndAt: new Date(Date.now() - 30 * 60_000), // ended 30 min ago
    });
    const judge = await makeJudge(fixture.tournamentId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    await prisma.panel.create({
      data: { sectionId: section.id, judgeId: judge.id, isChair: true },
    });
    await prisma.judgeCheckIn.create({
      data: { roundId: round.id, judgeId: judge.id, status: "CHECKED_IN" },
    });

    const result = await sweepUnresponsive(round.id, 15); // 15 min grace, 30 min have passed
    expect(result.flaggedJudgeIds).toEqual([judge.id]);

    const checkIn = await prisma.judgeCheckIn.findUniqueOrThrow({
      where: { roundId_judgeId: { roundId: round.id, judgeId: judge.id } },
    });
    expect(checkIn.status).toBe("UNRESPONSIVE");
  });

  it("never flags a judge who submitted ballots for every assigned speaker", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId, {
      scheduledEndAt: new Date(Date.now() - 30 * 60_000),
    });
    const judge = await makeJudge(fixture.tournamentId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    await prisma.panel.create({
      data: { sectionId: section.id, judgeId: judge.id, isChair: true },
    });
    await prisma.judgeCheckIn.create({
      data: { roundId: round.id, judgeId: judge.id, status: "CHECKED_IN" },
    });
    await prisma.ballot.create({
      data: {
        sectionId: section.id,
        judgeId: judge.id,
        speakerId: speaker.id,
        submittedAt: new Date(),
        judgeTotal: 80,
      },
    });

    const result = await sweepUnresponsive(round.id, 15);
    expect(result.flaggedJudgeIds).toEqual([]);
  });
});
