// docs/05-publishing-and-state.md §4 — immutability & locking, plus the
// Super Admin unlock escalation flow. `editBallotScore` exists here to prove
// the lock actually blocks a real mutation end-to-end; the full digital
// scorecard submission flow is Section 10's job — this is the guard
// primitive future ballot-writing code calls, the same deferral pattern used
// for Section 4's permission checks before real routes existed.

import { prisma } from "@/lib/prisma";
import { writeAuditLog } from "@/lib/audit/log";

const ACTIVE_PANEL_STATUSES = ["ASSIGNED", "CHECKED_IN", "DEPLOYED_RESERVE"] as const;

export async function isRoundLocked(roundId: string): Promise<boolean> {
  const round = await prisma.round.findUniqueOrThrow({ where: { id: roundId } });
  return round.lockedAt !== null;
}

export async function assertRoundNotLocked(roundId: string): Promise<void> {
  if (await isRoundLocked(roundId)) {
    throw new Error(`Round ${roundId} is locked — edits require Super Admin unlock escalation`);
  }
}

/**
 * docs/05 §4's alternate lock trigger: lock as soon as every active judge's
 * ballot for every speaker in every section is submitted (or explicitly
 * partial), rather than waiting for Results to be released. A no-op unless
 * the Division is configured for it; call after each ballot submission
 * (Section 10's hook point). Returns whether the round ended up locked.
 */
export async function checkAndLockIfAllBallotsSubmitted(roundId: string): Promise<boolean> {
  const round = await prisma.round.findUniqueOrThrow({
    where: { id: roundId },
    include: { division: true },
  });
  if (round.lockedAt) return true;
  if (round.division.lockTrigger !== "ON_ALL_BALLOTS_SUBMITTED") return false;

  const sections = await prisma.section.findMany({
    where: { roundId },
    include: { assignments: true, panels: true, ballots: true },
  });

  for (const section of sections) {
    const activeJudgeIds = section.panels
      .filter((p) => (ACTIVE_PANEL_STATUSES as readonly string[]).includes(p.status))
      .map((p) => p.judgeId);

    for (const judgeId of activeJudgeIds) {
      for (const assignment of section.assignments) {
        const ballot = section.ballots.find(
          (b) => b.judgeId === judgeId && b.speakerId === assignment.speakerId,
        );
        const done = ballot && (ballot.submittedAt !== null || ballot.isPartial);
        if (!done) return false;
      }
    }
  }

  await prisma.$transaction(async (tx) => {
    await tx.round.update({ where: { id: roundId }, data: { lockedAt: new Date() } });
    await writeAuditLog(tx, {
      actionType: "round_locked",
      summary: `Round ${roundId} auto-locked — every ballot is in`,
      tournamentId: round.division.tournamentId,
    });
  });
  return true;
}

/** docs/05 §4 — tab staff can't self-unlock; only a Super Admin escalation
 *  can. Whether `superAdminUserId` actually holds that permission is a
 *  caller concern (Section 4's `userCan`), same as `resolveClaimDispute`
 *  not re-checking staff-ness itself. */
export async function unlockRoundForCorrection(
  roundId: string,
  superAdminUserId: string,
  reason: string,
): Promise<void> {
  const round = await prisma.round.findUniqueOrThrow({
    where: { id: roundId },
    include: { division: true },
  });
  if (!round.lockedAt) {
    throw new Error("This round is not locked");
  }

  await prisma.$transaction(async (tx) => {
    await tx.round.update({ where: { id: roundId }, data: { lockedAt: null } });
    await writeAuditLog(tx, {
      actorUserId: superAdminUserId,
      actionType: "round_unlock",
      summary: `Unlocked round ${roundId} for correction`,
      tournamentId: round.division.tournamentId,
      reason,
    });
  });
}

/**
 * docs/05 §4 — a locked round rejects this outright. A round whose Results
 * are released always ends up locked again (`releaseResults` in gates.ts
 * locks unconditionally) — so `resultsState === "RELEASED"` with a null
 * `lockedAt` can only mean an active `unlockRoundForCorrection` window,
 * which is exactly when this re-locks automatically once the edit lands.
 */
export async function editBallotScore(
  ballotId: string,
  criterionId: string,
  newScore: number,
  performedByUserId: string,
  reason?: string,
): Promise<void> {
  const ballot = await prisma.ballot.findUniqueOrThrow({
    where: { id: ballotId },
    include: { section: { include: { round: { include: { division: true, rubric: true } } } } },
  });
  const round = ballot.section.round;
  await assertRoundNotLocked(round.id);

  const before = await prisma.ballotScore.findUniqueOrThrow({
    where: { ballotId_criterionId: { ballotId, criterionId } },
  });

  await prisma.$transaction(async (tx) => {
    await tx.ballotScore.update({
      where: { ballotId_criterionId: { ballotId, criterionId } },
      data: { score: newScore },
    });

    const allScores = await tx.ballotScore.findMany({ where: { ballotId } });
    const sum = allScores.reduce((s, sc) => s + sc.score, 0);
    const baseScore = round.rubric?.baseScore ?? 0;
    const judgeTotal = baseScore + sum - ballot.timePenalty;
    await tx.ballot.update({ where: { id: ballotId }, data: { judgeTotal } });

    await writeAuditLog(tx, {
      actorUserId: performedByUserId,
      actionType: "score_edit",
      summary: `Edited ballot ${ballotId}, criterion ${criterionId}`,
      tournamentId: round.division.tournamentId,
      reason,
      before: { score: before.score },
      after: { score: newScore },
    });

    if (round.resultsState === "RELEASED") {
      await tx.round.update({ where: { id: round.id }, data: { lockedAt: new Date() } });
    }
  });
}
