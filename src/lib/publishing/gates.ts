// docs/05-publishing-and-state.md §2 — the three independent per-round
// publish gates. Each is a one-directional Hidden/Held -> Released switch
// (no gate here ever goes back — a targeted Embargo, docs/05 §3, is the
// mechanism for withdrawing one entity's visibility after the fact).

import { prisma } from "@/lib/prisma";
import { writeAuditLog } from "@/lib/audit/log";

export async function releaseDraws(roundId: string, performedByUserId: string): Promise<void> {
  const round = await prisma.round.findUniqueOrThrow({
    where: { id: roundId },
    include: { division: true },
  });
  if (round.drawsState === "RELEASED") {
    throw new Error("Draws are already released for this round");
  }

  await prisma.$transaction(async (tx) => {
    await tx.round.update({ where: { id: roundId }, data: { drawsState: "RELEASED" } });
    await writeAuditLog(tx, {
      actorUserId: performedByUserId,
      actionType: "publish_toggle",
      summary: `Released draws for round ${roundId}`,
      tournamentId: round.division.tournamentId,
    });
  });
}

/**
 * docs/05 §4 — "once Results are released for a round, that round's ballots
 * become immutable" is unconditional; the Division's lockTrigger only
 * controls whether locking can *also* happen earlier (docs/02 — see
 * `checkAndLockIfAllBallotsSubmitted` in locking.ts), not whether release
 * implies lock. If the round auto-locked already, this keeps that original
 * timestamp rather than bumping it.
 */
export async function releaseResults(roundId: string, performedByUserId: string): Promise<void> {
  const round = await prisma.round.findUniqueOrThrow({
    where: { id: roundId },
    include: { division: true },
  });
  if (round.resultsState === "RELEASED") {
    throw new Error("Results are already released for this round");
  }

  await prisma.$transaction(async (tx) => {
    await tx.round.update({
      where: { id: roundId },
      data: { resultsState: "RELEASED", lockedAt: round.lockedAt ?? new Date() },
    });
    await writeAuditLog(tx, {
      actorUserId: performedByUserId,
      actionType: "publish_toggle",
      summary: `Released results for round ${roundId}`,
      tournamentId: round.division.tournamentId,
    });
  });
}

/** docs/05 §2's "computation respects release state" principle, enforced at
 *  the write path: a round's cumulative standings can't release before that
 *  same round's own Results have. */
export async function releaseStandings(roundId: string, performedByUserId: string): Promise<void> {
  const round = await prisma.round.findUniqueOrThrow({
    where: { id: roundId },
    include: { division: true },
  });
  if (round.standingsState === "RELEASED") {
    throw new Error("Standings are already released for this round");
  }
  if (round.resultsState !== "RELEASED") {
    throw new Error("Cannot release standings for a round whose own results aren't released yet");
  }

  await prisma.$transaction(async (tx) => {
    await tx.round.update({ where: { id: roundId }, data: { standingsState: "RELEASED" } });
    await writeAuditLog(tx, {
      actorUserId: performedByUserId,
      actionType: "publish_toggle",
      summary: `Released standings for round ${roundId}`,
      tournamentId: round.division.tournamentId,
    });
  });
}
