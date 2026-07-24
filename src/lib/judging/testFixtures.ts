// Shared DB-integration test fixture for src/lib/judging/*.test.ts. Not a
// test file itself — just the tournament/division/round/section scaffolding
// every judging-contingencies test needs, so each test file isn't
// re-deriving the same setup/teardown boilerplate.
//
// Cleanup note: Judge/Speaker.tournamentId is a denormalized index column,
// not an FK (only Speaker.divisionId cascades through Division) — deleting
// the Tournament does NOT cascade-delete Judge rows, so cleanup deletes
// Judges by tournamentId explicitly before the Tournament.

import { randomUUID } from "node:crypto";
import { prisma } from "@/lib/prisma";

export interface Fixture {
  tournamentId: string;
  divisionId: string;
  ownerId: string;
}

export interface DivisionOverrides {
  panelSize?: number;
  minimumPanelSize?: number;
  lockTrigger?: "ON_RESULTS_RELEASE" | "ON_ALL_BALLOTS_SUBMITTED";
}

// randomUUID, not Date.now()+a counter — multiple test files run concurrently
// against the same real database (separate processes, each with its own
// counter starting at 0), so a timestamp+counter scheme collides across
// files; a UUID doesn't need cross-process coordination to stay unique.
function unique(label: string): string {
  return `${label}-${randomUUID()}`;
}

export async function createFixture(divisionOverrides: DivisionOverrides = {}): Promise<Fixture> {
  const owner = await prisma.user.create({
    data: { email: `${unique("judging-owner")}@example.com`, name: "Judging Test Owner" },
  });
  const tournament = await prisma.tournament.create({
    data: { name: "Judging Test Tournament", slug: unique("judging-test"), ownerId: owner.id },
  });
  const division = await prisma.division.create({
    data: { tournamentId: tournament.id, name: "Open", ...divisionOverrides },
  });
  return { tournamentId: tournament.id, divisionId: division.id, ownerId: owner.id };
}

export async function cleanupFixture(fixture: Fixture): Promise<void> {
  await prisma.judge.deleteMany({ where: { tournamentId: fixture.tournamentId } });
  // must run before the Tournament delete below — AuditLogEntry.tournamentId
  // auto-nulls (optional relation, default onDelete SetNull) once its
  // Tournament is gone, so deleting the tournament first would leave these
  // rows behind forever instead of removing them.
  await prisma.auditLogEntry.deleteMany({ where: { tournamentId: fixture.tournamentId } });
  await prisma.tournament.delete({ where: { id: fixture.tournamentId } });
  await prisma.user.delete({ where: { id: fixture.ownerId } });
}

export async function makeJudge(
  tournamentId: string,
  overrides: Partial<{
    isReserve: boolean;
    chairEligible: boolean;
    maxRoundsPerDay: number | null;
  }> = {},
) {
  return prisma.judge.create({
    data: {
      tournamentId,
      name: unique("Judge"),
      email: `${unique("judge")}@example.com`,
      ...overrides,
    },
  });
}

export async function makeSpeaker(tournamentId: string, divisionId: string) {
  return prisma.speaker.create({
    data: {
      tournamentId,
      divisionId,
      name: unique("Speaker"),
      email: `${unique("speaker")}@example.com`,
    },
  });
}

export async function makeRound(
  divisionId: string,
  overrides: Partial<{
    roundNumber: number;
    checkInClosesAt: Date | null;
    scheduledEndAt: Date | null;
  }> = {},
) {
  const existing = await prisma.round.count({ where: { divisionId } });
  return prisma.round.create({
    data: { divisionId, roundNumber: overrides.roundNumber ?? existing + 1, ...overrides },
  });
}

export async function makeSection(roundId: string, speakerIds: string[]) {
  return prisma.section.create({
    data: {
      roundId,
      roomLabel: unique("Room"),
      assignments: {
        create: speakerIds.map((speakerId, i) => ({ speakerId, position: i + 1 })),
      },
    },
  });
}
