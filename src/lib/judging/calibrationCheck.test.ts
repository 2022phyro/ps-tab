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
import { runCalibrationCheck } from "./calibrationCheck";
import type { Fixture } from "./testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

async function ballot(sectionId: string, judgeId: string, speakerId: string, judgeTotal: number) {
  return prisma.ballot.create({
    data: { sectionId, judgeId, speakerId, submittedAt: new Date(), judgeTotal },
  });
}

describe("runCalibrationCheck", () => {
  it("flags the one judge whose complete ranking diverges from the panel's agreement", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const [a, b, c, d] = await Promise.all([
      makeSpeaker(fixture.tournamentId, fixture.divisionId),
      makeSpeaker(fixture.tournamentId, fixture.divisionId),
      makeSpeaker(fixture.tournamentId, fixture.divisionId),
      makeSpeaker(fixture.tournamentId, fixture.divisionId),
    ]);
    const section = await makeSection(round.id, [a.id, b.id, c.id, d.id]);
    const [j1, j2, j3] = await Promise.all([
      makeJudge(fixture.tournamentId),
      makeJudge(fixture.tournamentId),
      makeJudge(fixture.tournamentId),
    ]);

    // judge1/judge2 agree: A best, then B, C, D worst.
    for (const j of [j1, j2]) {
      await ballot(section.id, j.id, a.id, 90);
      await ballot(section.id, j.id, b.id, 80);
      await ballot(section.id, j.id, c.id, 70);
      await ballot(section.id, j.id, d.id, 60);
    }
    // judge3 disagrees: B best, then C, D, A worst.
    await ballot(section.id, j3.id, b.id, 90);
    await ballot(section.id, j3.id, c.id, 80);
    await ballot(section.id, j3.id, d.id, 70);
    await ballot(section.id, j3.id, a.id, 60);

    const result = await runCalibrationCheck(section.id);
    expect(result.flaggedJudgeIds).toEqual([j3.id]);

    const j3Ballots = await prisma.ballot.findMany({
      where: { sectionId: section.id, judgeId: j3.id },
    });
    expect(j3Ballots.every((ballotRow) => ballotRow.calibrationFlag)).toBe(true);

    const j1Ballots = await prisma.ballot.findMany({
      where: { sectionId: section.id, judgeId: j1.id },
    });
    expect(j1Ballots.every((ballotRow) => !ballotRow.calibrationFlag)).toBe(true);
  });

  it("flags no one when a lone judge has scored (nothing to compare against)", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const judge = await makeJudge(fixture.tournamentId);
    await ballot(section.id, judge.id, speaker.id, 80);

    const result = await runCalibrationCheck(section.id);
    expect(result.flaggedJudgeIds).toEqual([]);
  });

  it("excludes a judge with only a partial ballot from the comparison", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const [a, b] = await Promise.all([
      makeSpeaker(fixture.tournamentId, fixture.divisionId),
      makeSpeaker(fixture.tournamentId, fixture.divisionId),
    ]);
    const section = await makeSection(round.id, [a.id, b.id]);
    const [j1, j2] = await Promise.all([
      makeJudge(fixture.tournamentId),
      makeJudge(fixture.tournamentId),
    ]);
    await ballot(section.id, j1.id, a.id, 90);
    await ballot(section.id, j1.id, b.id, 80);
    // j2 only reached speaker a before leaving mid-round
    await prisma.ballot.create({
      data: {
        sectionId: section.id,
        judgeId: j2.id,
        speakerId: a.id,
        submittedAt: new Date(),
        judgeTotal: 70,
      },
    });
    await prisma.ballot.create({
      data: {
        sectionId: section.id,
        judgeId: j2.id,
        speakerId: b.id,
        isPartial: true,
        submittedAt: null,
      },
    });

    const result = await runCalibrationCheck(section.id);
    expect(result.flaggedJudgeIds).toEqual([]); // j2 excluded (incomplete) — only j1 left, nothing to compare
  });
});
