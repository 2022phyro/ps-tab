import { randomUUID } from "node:crypto";
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
import { getHotSwapCandidates, hotSwapJudge } from "./hotSwap";
import type { Fixture } from "./testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

async function checkedInReserve(tournamentId: string, roundId: string, overrides = {}) {
  const judge = await makeJudge(tournamentId, { isReserve: true, ...overrides });
  await prisma.judgeCheckIn.create({ data: { roundId, judgeId: judge.id, status: "CHECKED_IN" } });
  return judge;
}

describe("getHotSwapCandidates", () => {
  it("only offers checked-in, idle reserves — never a deployed or non-reserve judge", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);

    const nonReserve = await makeJudge(fixture.tournamentId, { isReserve: false });
    await prisma.judgeCheckIn.create({
      data: { roundId: round.id, judgeId: nonReserve.id, status: "CHECKED_IN" },
    });

    const notCheckedIn = await makeJudge(fixture.tournamentId, { isReserve: true });

    const idle = await checkedInReserve(fixture.tournamentId, round.id);

    const deployed = await checkedInReserve(fixture.tournamentId, round.id);
    const otherSection = await makeSection(round.id, [speaker.id]);
    await prisma.panel.create({ data: { sectionId: otherSection.id, judgeId: deployed.id } });

    const candidates = await getHotSwapCandidates(section.id);
    const ids = candidates.map((c) => c.judgeId);
    expect(ids).toContain(idle.id);
    expect(ids).not.toContain(nonReserve.id);
    expect(ids).not.toContain(notCheckedIn.id);
    expect(ids).not.toContain(deployed.id);
  });

  it("flags a candidate whose institution clashes with a speaker already in the room", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const institution = await prisma.institution.create({
      data: { tournamentId: fixture.tournamentId, name: "Clash Institution" },
    });
    const speaker = await prisma.speaker.create({
      data: {
        tournamentId: fixture.tournamentId,
        divisionId: fixture.divisionId,
        institutionId: institution.id,
        name: "Speaker",
        email: "speaker@example.com",
      },
    });
    const section = await makeSection(round.id, [speaker.id]);
    const clashing = await checkedInReserve(fixture.tournamentId, round.id, {});
    await prisma.judge.update({
      where: { id: clashing.id },
      data: { institutionId: institution.id },
    });

    const candidates = await getHotSwapCandidates(section.id);
    const candidate = candidates.find((c) => c.judgeId === clashing.id);
    expect(candidate?.clashFlag).toBe(true);
  });
});

describe("hotSwapJudge", () => {
  it("swaps the outgoing judge for an idle reserve, preserving chair status, and logs the audit trail", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const outgoing = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({
      data: { sectionId: section.id, judgeId: outgoing.id, isChair: true },
    });
    const staff = await prisma.user.create({
      data: { email: `staff-hotswap-${randomUUID()}@example.com`, name: "Staff" },
    });
    const incoming = await checkedInReserve(fixture.tournamentId, round.id);

    const result = await hotSwapJudge(section.id, outgoing.id, incoming.id, staff.id, {
      reason: "no-show",
    });
    expect(result.clashFlag).toBe(false);

    const outgoingPanel = await prisma.panel.findUniqueOrThrow({
      where: { sectionId_judgeId: { sectionId: section.id, judgeId: outgoing.id } },
    });
    expect(outgoingPanel.status).toBe("REMOVED_FOR_CONFLICT");

    const incomingPanel = await prisma.panel.findUniqueOrThrow({
      where: { sectionId_judgeId: { sectionId: section.id, judgeId: incoming.id } },
    });
    expect(incomingPanel.isChair).toBe(true);
    expect(incomingPanel.status).toBe("DEPLOYED_RESERVE");
    expect(incomingPanel.swappedFromJudgeId).toBe(outgoing.id);

    const audit = await prisma.auditLogEntry.findFirstOrThrow({
      where: { actionType: "judge_hotswap" },
    });
    expect(audit.actorUserId).toBe(staff.id);
    expect(audit.reason).toBe("no-show");

    await prisma.auditLogEntry.deleteMany({ where: { actorUserId: staff.id } });
    await prisma.user.delete({ where: { id: staff.id } });
  });

  it("rejects a judge who isn't a checked-in idle reserve", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const section = await makeSection(round.id, [speaker.id]);
    const outgoing = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({ data: { sectionId: section.id, judgeId: outgoing.id } });
    const notReserve = await makeJudge(fixture.tournamentId);

    await expect(
      hotSwapJudge(section.id, outgoing.id, notReserve.id, fixture.ownerId),
    ).rejects.toThrow("not a valid hot-swap candidate");
  });

  it("refuses a clashing swap unless the clash is explicitly acknowledged", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const institution = await prisma.institution.create({
      data: { tournamentId: fixture.tournamentId, name: "Clash Institution 2" },
    });
    const speaker = await prisma.speaker.create({
      data: {
        tournamentId: fixture.tournamentId,
        divisionId: fixture.divisionId,
        institutionId: institution.id,
        name: "Speaker",
        email: "speaker2@example.com",
      },
    });
    const section = await makeSection(round.id, [speaker.id]);
    const outgoing = await makeJudge(fixture.tournamentId);
    await prisma.panel.create({ data: { sectionId: section.id, judgeId: outgoing.id } });
    const clashing = await checkedInReserve(fixture.tournamentId, round.id);
    await prisma.judge.update({
      where: { id: clashing.id },
      data: { institutionId: institution.id },
    });

    await expect(
      hotSwapJudge(section.id, outgoing.id, clashing.id, fixture.ownerId),
    ).rejects.toThrow("institutional clash");

    const result = await hotSwapJudge(section.id, outgoing.id, clashing.id, fixture.ownerId, {
      acknowledgeClash: true,
    });
    expect(result.clashFlag).toBe(true);
  });
});
