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
import { checkPanelStatus, markJudgeDepartedMidRound } from "./degradedPanel";
import type { Fixture } from "./testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

describe("checkPanelStatus", () => {
  it("reports full strength when the panel meets the configured size", async () => {
    fixture = await createFixture({ panelSize: 2, minimumPanelSize: 1 });
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const j1 = await makeJudge(fixture.tournamentId);
    const j2 = await makeJudge(fixture.tournamentId);
    await prisma.panel.createMany({
      data: [
        { sectionId: section.id, judgeId: j1.id },
        { sectionId: section.id, judgeId: j2.id },
      ],
    });

    const status = await checkPanelStatus(section.id);
    expect(status).toMatchObject({ effectiveSize: 2, degraded: false, blocked: false });
  });

  it("reports a degraded (but not blocked) panel when above the floor but below target", async () => {
    fixture = await createFixture({ panelSize: 3, minimumPanelSize: 1 });
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const j1 = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({ data: { sectionId: section.id, judgeId: j1.id } });

    const status = await checkPanelStatus(section.id);
    expect(status).toMatchObject({ effectiveSize: 1, degraded: true, blocked: false });
  });

  it("ignores a NO_SHOW/REMOVED_FOR_CONFLICT panel row when counting availability", async () => {
    fixture = await createFixture({ panelSize: 2, minimumPanelSize: 1 });
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const showed = await makeJudge(fixture.tournamentId);
    const noShow = await makeJudge(fixture.tournamentId);
    await prisma.panel.createMany({
      data: [
        { sectionId: section.id, judgeId: showed.id, status: "CHECKED_IN" },
        { sectionId: section.id, judgeId: noShow.id, status: "NO_SHOW" },
      ],
    });

    const status = await checkPanelStatus(section.id);
    expect(status.effectiveSize).toBe(1);
    expect(status.degraded).toBe(true);
  });

  it("reports blocked when availability would drop below the configured floor", async () => {
    fixture = await createFixture({ panelSize: 3, minimumPanelSize: 2 });
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const j1 = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({ data: { sectionId: section.id, judgeId: j1.id } });

    const status = await checkPanelStatus(section.id);
    expect(status.blocked).toBe(true);
  });
});

describe("markJudgeDepartedMidRound", () => {
  it("marks the panel LEFT_MID_ROUND and writes partial placeholder ballots only for unreached speakers", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const s1 = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const s2 = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const s3 = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [s1.id, s2.id, s3.id]);
    const judge = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({ data: { sectionId: section.id, judgeId: judge.id } });
    await prisma.ballot.create({
      data: {
        sectionId: section.id,
        judgeId: judge.id,
        speakerId: s1.id,
        submittedAt: new Date(),
        judgeTotal: 85,
      },
    });

    const result = await markJudgeDepartedMidRound(section.id, judge.id, [s1.id]);
    expect(result.unreachedSpeakerIds.sort()).toEqual([s2.id, s3.id].sort());

    const panel = await prisma.panel.findUniqueOrThrow({
      where: { sectionId_judgeId: { sectionId: section.id, judgeId: judge.id } },
    });
    expect(panel.status).toBe("LEFT_MID_ROUND");

    const reachedBallot = await prisma.ballot.findUniqueOrThrow({
      where: {
        sectionId_judgeId_speakerId: { sectionId: section.id, judgeId: judge.id, speakerId: s1.id },
      },
    });
    expect(reachedBallot.isPartial).toBe(false);
    expect(reachedBallot.submittedAt).not.toBeNull();

    for (const speakerId of [s2.id, s3.id]) {
      const partial = await prisma.ballot.findUniqueOrThrow({
        where: {
          sectionId_judgeId_speakerId: { sectionId: section.id, judgeId: judge.id, speakerId },
        },
      });
      expect(partial.isPartial).toBe(true);
      expect(partial.submittedAt).toBeNull();
    }
  });
});
