import { afterEach, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import {
  cleanupFixture,
  createFixture,
  makeJudge,
  makeRound,
  makeSection,
  makeSpeaker,
} from "@/lib/judging/testFixtures";
import {
  assertRoundNotLocked,
  checkAndLockIfAllBallotsSubmitted,
  editBallotScore,
  isRoundLocked,
  unlockRoundForCorrection,
} from "./locking";
import { releaseResults } from "./gates";
import type { Fixture } from "@/lib/judging/testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

async function makeRubricAndBallot(
  fx: Fixture,
  roundId: string,
  sectionId: string,
  judgeId: string,
  speakerId: string,
) {
  const rubric = await prisma.rubric.create({
    data: {
      tournamentId: fx.tournamentId,
      divisionId: fx.divisionId,
      name: "Test Rubric",
      baseScore: 10,
      criteria: { create: [{ name: "Content", maxPoints: 10, order: 1 }] },
    },
    include: { criteria: true },
  });
  await prisma.round.update({ where: { id: roundId }, data: { rubricId: rubric.id } });
  const ballot = await prisma.ballot.create({
    data: {
      sectionId,
      judgeId,
      speakerId,
      submittedAt: new Date(),
      timePenalty: 0,
      judgeTotal: 18,
      scores: { create: [{ criterionId: rubric.criteria[0]!.id, score: 8 }] },
    },
  });
  return { rubric, criterionId: rubric.criteria[0]!.id, ballot };
}

describe("isRoundLocked / assertRoundNotLocked", () => {
  it("is unlocked by default and locked once lockedAt is set", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    expect(await isRoundLocked(round.id)).toBe(false);
    await expect(assertRoundNotLocked(round.id)).resolves.not.toThrow();

    await prisma.round.update({ where: { id: round.id }, data: { lockedAt: new Date() } });
    expect(await isRoundLocked(round.id)).toBe(true);
    await expect(assertRoundNotLocked(round.id)).rejects.toThrow("is locked");
  });
});

describe("checkAndLockIfAllBallotsSubmitted", () => {
  it("is a no-op under the default ON_RESULTS_RELEASE trigger", async () => {
    fixture = await createFixture(); // default lockTrigger
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const judge = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({ data: { sectionId: section.id, judgeId: judge.id } });
    await prisma.ballot.create({
      data: {
        sectionId: section.id,
        judgeId: judge.id,
        speakerId: speaker.id,
        submittedAt: new Date(),
        judgeTotal: 80,
      },
    });

    expect(await checkAndLockIfAllBallotsSubmitted(round.id)).toBe(false);
  });

  it("locks once every active judge has a submitted-or-partial ballot for every speaker", async () => {
    fixture = await createFixture({ lockTrigger: "ON_ALL_BALLOTS_SUBMITTED" });
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const judge = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({ data: { sectionId: section.id, judgeId: judge.id } });

    expect(await checkAndLockIfAllBallotsSubmitted(round.id)).toBe(false); // no ballot yet

    await prisma.ballot.create({
      data: {
        sectionId: section.id,
        judgeId: judge.id,
        speakerId: speaker.id,
        submittedAt: new Date(),
        judgeTotal: 80,
      },
    });

    expect(await checkAndLockIfAllBallotsSubmitted(round.id)).toBe(true);
    expect(await isRoundLocked(round.id)).toBe(true);
  });

  it("ignores a NO_SHOW judge's missing ballot", async () => {
    fixture = await createFixture({ lockTrigger: "ON_ALL_BALLOTS_SUBMITTED" });
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const judge = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({
      data: { sectionId: section.id, judgeId: judge.id, status: "NO_SHOW" },
    });

    expect(await checkAndLockIfAllBallotsSubmitted(round.id)).toBe(true);
  });
});

describe("editBallotScore + unlock escalation", () => {
  it("rejects an edit while the round is locked", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const judge = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({ data: { sectionId: section.id, judgeId: judge.id } });
    const { criterionId } = await makeRubricAndBallot(
      fixture,
      round.id,
      section.id,
      judge.id,
      speaker.id,
    );
    await releaseResults(round.id, fixture.ownerId); // locks it

    await expect(
      editBallotScore(
        (await prisma.ballot.findFirstOrThrow({ where: { sectionId: section.id } })).id,
        criterionId,
        5,
        fixture.ownerId,
      ),
    ).rejects.toThrow("is locked");
  });

  it("applies a correction after unlock escalation, recomputes judgeTotal, and auto re-locks", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const judge = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({ data: { sectionId: section.id, judgeId: judge.id } });
    const { criterionId, ballot } = await makeRubricAndBallot(
      fixture,
      round.id,
      section.id,
      judge.id,
      speaker.id,
    );
    await releaseResults(round.id, fixture.ownerId);

    const superAdmin = await prisma.user.create({
      data: { email: `super-admin-${Date.now()}@example.com`, name: "Super Admin" },
    });
    await unlockRoundForCorrection(round.id, superAdmin.id, "transposed score");
    expect(await isRoundLocked(round.id)).toBe(false);

    await editBallotScore(ballot.id, criterionId, 5, superAdmin.id, "fixing transposition");

    const updatedBallot = await prisma.ballot.findUniqueOrThrow({ where: { id: ballot.id } });
    expect(updatedBallot.judgeTotal).toBe(15); // baseScore 10 + score 5 - timePenalty 0

    expect(await isRoundLocked(round.id)).toBe(true); // auto re-locked

    const auditEntries = await prisma.auditLogEntry.findMany({
      where: {
        tournamentId: fixture.tournamentId,
        actionType: { in: ["round_unlock", "score_edit"] },
      },
      orderBy: { createdAt: "asc" },
    });
    expect(auditEntries.map((e) => e.actionType)).toEqual(["round_unlock", "score_edit"]);
    expect(auditEntries[0]!.reason).toBe("transposed score");

    await prisma.auditLogEntry.deleteMany({ where: { actorUserId: superAdmin.id } });
    await prisma.user.delete({ where: { id: superAdmin.id } });
  });

  it("refuses to unlock a round that isn't locked", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    await expect(unlockRoundForCorrection(round.id, fixture.ownerId, "n/a")).rejects.toThrow(
      "not locked",
    );
  });
});
