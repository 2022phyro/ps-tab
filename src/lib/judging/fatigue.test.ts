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
import { getAvailableJudgesForRound, isJudgeAtFatigueCap } from "./fatigue";
import { recuseJudge } from "./recusal";
import type { Fixture } from "./testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

describe("isJudgeAtFatigueCap", () => {
  it("is never at cap when maxRoundsPerDay is unset", async () => {
    fixture = await createFixture();
    const judge = await makeJudge(fixture.tournamentId, { maxRoundsPerDay: null });
    expect(await isJudgeAtFatigueCap(judge.id, new Date())).toBe(false);
  });

  it("is at cap once assigned to maxRoundsPerDay rounds the same day", async () => {
    fixture = await createFixture();
    const judge = await makeJudge(fixture.tournamentId, { maxRoundsPerDay: 2 });
    const today = new Date();

    const round1 = await makeRound(fixture.divisionId, { roundNumber: 1 });
    await prisma.round.update({ where: { id: round1.id }, data: { scheduledStartAt: today } });
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section1 = await makeSection(round1.id, [speaker.id]);
    await prisma.panel.create({ data: { sectionId: section1.id, judgeId: judge.id } });

    expect(await isJudgeAtFatigueCap(judge.id, today)).toBe(false); // only 1 so far

    const round2 = await makeRound(fixture.divisionId, { roundNumber: 2 });
    await prisma.round.update({ where: { id: round2.id }, data: { scheduledStartAt: today } });
    const section2 = await makeSection(round2.id, [speaker.id]);
    await prisma.panel.create({ data: { sectionId: section2.id, judgeId: judge.id } });

    expect(await isJudgeAtFatigueCap(judge.id, today)).toBe(true); // now 2 of 2
  });

  it("ignores a NO_SHOW panel row when counting toward the cap", async () => {
    fixture = await createFixture();
    const judge = await makeJudge(fixture.tournamentId, { maxRoundsPerDay: 1 });
    const today = new Date();
    const round = await makeRound(fixture.divisionId, { roundNumber: 1 });
    await prisma.round.update({ where: { id: round.id }, data: { scheduledStartAt: today } });
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    await prisma.panel.create({
      data: { sectionId: section.id, judgeId: judge.id, status: "NO_SHOW" },
    });

    expect(await isJudgeAtFatigueCap(judge.id, today)).toBe(false);
  });
});

describe("getAvailableJudgesForRound", () => {
  it("excludes a recused judge and a fatigue-capped judge, keeps everyone else", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    await prisma.round.update({ where: { id: round.id }, data: { scheduledStartAt: new Date() } });

    const available = await makeJudge(fixture.tournamentId);
    const recusedJudge = await makeJudge(fixture.tournamentId);
    const fatiguedJudge = await makeJudge(fixture.tournamentId, { maxRoundsPerDay: 1 });

    await recuseJudge(recusedJudge.id, round.id);

    const otherRound = await makeRound(fixture.divisionId, { roundNumber: round.roundNumber + 1 });
    await prisma.round.update({
      where: { id: otherRound.id },
      data: { scheduledStartAt: round.scheduledStartAt ?? new Date() },
    });
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(otherRound.id, [speaker.id]);
    await prisma.panel.create({ data: { sectionId: section.id, judgeId: fatiguedJudge.id } });

    const ids = await getAvailableJudgesForRound(round.id);
    expect(ids).toContain(available.id);
    expect(ids).not.toContain(recusedJudge.id);
    expect(ids).not.toContain(fatiguedJudge.id);
  });
});
