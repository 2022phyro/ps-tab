import { afterEach, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import { cleanupFixture, createFixture, makeJudge, makeRound } from "./testFixtures";
import { recuseJudge } from "./recusal";
import type { Fixture } from "./testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

describe("recuseJudge", () => {
  it("creates a RECUSED check-in for a judge with no prior check-in row", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const judge = await makeJudge(fixture.tournamentId);

    await recuseJudge(judge.id, round.id);

    const checkIn = await prisma.judgeCheckIn.findUniqueOrThrow({
      where: { roundId_judgeId: { roundId: round.id, judgeId: judge.id } },
    });
    expect(checkIn.status).toBe("RECUSED");
  });

  it("is idempotent when called twice for the same judge/round", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const judge = await makeJudge(fixture.tournamentId);

    await recuseJudge(judge.id, round.id);
    await expect(recuseJudge(judge.id, round.id)).resolves.not.toThrow();

    const count = await prisma.judgeCheckIn.count({
      where: { roundId: round.id, judgeId: judge.id },
    });
    expect(count).toBe(1);
  });

  it("overwrites an existing CHECKED_IN status if the judge recuses after checking in", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const judge = await makeJudge(fixture.tournamentId);
    await prisma.judgeCheckIn.create({
      data: { roundId: round.id, judgeId: judge.id, status: "CHECKED_IN" },
    });

    await recuseJudge(judge.id, round.id);

    const checkIn = await prisma.judgeCheckIn.findUniqueOrThrow({
      where: { roundId_judgeId: { roundId: round.id, judgeId: judge.id } },
    });
    expect(checkIn.status).toBe("RECUSED");
  });
});
