// docs/02-judging-contingencies.md §3 — no-show detection & alerts. Two
// distinct signals: a judge who never checked in at all (flagged at round
// start, before the round even runs), and a judge who checked in but never
// submitted a ballot within the grace period past the round's expected end
// (flagged as unresponsive, distinct from a no-show).
//
// Framework note: docs/02 §3 describes these as running automatically as the
// round progresses. The actual cron/schedule wiring is Section 8's job
// (Inngest isn't installed yet) — these are plain, directly-callable
// functions today so they're fully testable now and Section 8 only has to
// wire a trigger around them later, the same deferral used for Section 4's
// proxy.ts route guards.

import { prisma } from "@/lib/prisma";
import { writeAuditLog } from "@/lib/audit/log";

export interface SweepResult {
  flaggedJudgeIds: string[];
}

async function logSweep(
  roundId: string,
  tournamentId: string,
  actionType: "no_show_sweep" | "unresponsive_sweep",
  result: SweepResult,
): Promise<void> {
  if (result.flaggedJudgeIds.length === 0) return;
  await writeAuditLog(prisma, {
    actionType, // no actorUserId — system-originated, see docs/05 §5 note on AuditLogEntry
    summary: `${actionType} for round ${roundId} flagged ${result.flaggedJudgeIds.length} judge(s)`,
    tournamentId,
    after: { flaggedJudgeIds: result.flaggedJudgeIds },
  });
}

/** docs/02 §3 — "did the judge check in before the window closed?" Only
 *  meaningful once that window has actually closed; a round still accepting
 *  check-ins has nothing to flag yet. */
export async function sweepNoShows(
  roundId: string,
  atTime: Date = new Date(),
): Promise<SweepResult> {
  const round = await prisma.round.findUniqueOrThrow({
    where: { id: roundId },
    include: { division: true },
  });
  if (!round.checkInClosesAt || round.checkInClosesAt > atTime) {
    return { flaggedJudgeIds: [] };
  }

  const assignedJudges = await prisma.panel.findMany({
    where: { section: { roundId } },
    select: { judgeId: true },
    distinct: ["judgeId"],
  });

  const flaggedJudgeIds: string[] = [];

  for (const { judgeId } of assignedJudges) {
    const checkIn = await prisma.judgeCheckIn.findUnique({
      where: { roundId_judgeId: { roundId, judgeId } },
    });
    if (checkIn && checkIn.status !== "NO_SHOW") continue; // already checked in (or already flagged)

    await prisma.judgeCheckIn.upsert({
      where: { roundId_judgeId: { roundId, judgeId } },
      create: { roundId, judgeId, status: "NO_SHOW", flaggedAt: atTime },
      update: { status: "NO_SHOW", flaggedAt: atTime },
    });
    flaggedJudgeIds.push(judgeId);
  }

  const result = { flaggedJudgeIds };
  await logSweep(roundId, round.division.tournamentId, "no_show_sweep", result);
  return result;
}

/** docs/02 §3 — "checked in, no ballot within a configurable grace period
 *  after the round's expected end." `round.scheduledEndAt` is required here
 *  deliberately — this never guesses a duration, it only measures a grace
 *  period from an organizer-set timestamp (docs/02 §3, docs/05's "never
 *  invent a value" principle applied to timing, not just scores). */
export async function sweepUnresponsive(
  roundId: string,
  graceMinutes: number,
  atTime: Date = new Date(),
): Promise<SweepResult> {
  const round = await prisma.round.findUniqueOrThrow({
    where: { id: roundId },
    include: { division: true },
  });
  if (!round.scheduledEndAt) {
    throw new Error("sweepUnresponsive requires the round's scheduledEndAt to be set");
  }
  const graceDeadline = new Date(round.scheduledEndAt.getTime() + graceMinutes * 60_000);
  if (graceDeadline > atTime) {
    return { flaggedJudgeIds: [] };
  }

  const checkedInPanels = await prisma.panel.findMany({
    where: {
      section: { roundId },
      judge: { checkIns: { some: { roundId, status: "CHECKED_IN" } } },
    },
    include: { section: { include: { assignments: true } } },
  });

  const flaggedJudgeIds: string[] = [];

  for (const panel of checkedInPanels) {
    const speakerIds = panel.section.assignments.map((a) => a.speakerId);
    if (speakerIds.length === 0) continue;

    const submittedCount = await prisma.ballot.count({
      where: {
        sectionId: panel.sectionId,
        judgeId: panel.judgeId,
        speakerId: { in: speakerIds },
        submittedAt: { not: null },
      },
    });
    if (submittedCount >= speakerIds.length) continue; // fully submitted — not unresponsive

    await prisma.judgeCheckIn.update({
      where: { roundId_judgeId: { roundId, judgeId: panel.judgeId } },
      data: { status: "UNRESPONSIVE", flaggedAt: atTime },
    });
    flaggedJudgeIds.push(panel.judgeId);
  }

  const result = { flaggedJudgeIds };
  await logSweep(roundId, round.division.tournamentId, "unresponsive_sweep", result);
  return result;
}
