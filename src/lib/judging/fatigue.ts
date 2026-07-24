// docs/02-judging-contingencies.md §5 — preventing shortfalls before they
// happen: judge fatigue caps and self-reported recusal both reduce the
// assignment pool automatically rather than relying on staff memory.

import { prisma } from "@/lib/prisma";

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}
function endOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate(), 23, 59, 59, 999);
}

/** docs/02 §5 — a judge already at their configured max-rounds-per-day is
 *  excluded from further assignment that day. `null` maxRoundsPerDay means
 *  no configured cap (never at capacity). Counts rounds via Panel rows for
 *  that judge whose Round falls on the same calendar day as `onDate`. */
export async function isJudgeAtFatigueCap(judgeId: string, onDate: Date): Promise<boolean> {
  const judge = await prisma.judge.findUniqueOrThrow({ where: { id: judgeId } });
  if (judge.maxRoundsPerDay === null) return false;

  const count = await prisma.panel.count({
    where: {
      judgeId,
      status: { notIn: ["NO_SHOW", "REMOVED_FOR_CONFLICT"] },
      section: {
        round: { scheduledStartAt: { gte: startOfDay(onDate), lte: endOfDay(onDate) } },
      },
    },
  });

  return count >= judge.maxRoundsPerDay;
}

/**
 * docs/02 §5 (fatigue) + §5 (self-recusal) — the pool `judgeAllocation.ts`'s
 * `allocateJudges` should actually receive for a given round: every
 * tournament judge, minus anyone recused for this specific round, minus
 * anyone already at their fatigue cap for the round's date. Doesn't exclude
 * judges already deployed elsewhere this round — `allocateJudges` already
 * handles that itself via its own shuffle-and-consume pool.
 */
export async function getAvailableJudgesForRound(roundId: string): Promise<string[]> {
  const round = await prisma.round.findUniqueOrThrow({
    where: { id: roundId },
    include: { division: true },
  });

  const allJudges = await prisma.judge.findMany({
    where: { tournamentId: round.division.tournamentId },
  });

  const recused = new Set(
    (
      await prisma.judgeCheckIn.findMany({
        where: { roundId, status: "RECUSED" },
        select: { judgeId: true },
      })
    ).map((r) => r.judgeId),
  );

  const onDate = round.scheduledStartAt ?? new Date();
  const available: string[] = [];
  for (const judge of allJudges) {
    if (recused.has(judge.id)) continue;
    if (await isJudgeAtFatigueCap(judge.id, onDate)) continue;
    available.push(judge.id);
  }
  return available;
}
