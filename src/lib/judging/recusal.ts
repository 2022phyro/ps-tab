// docs/02-judging-contingencies.md §5 — self-reported recusal. A judge who
// knows of a conflict flags it themselves before assignment, running through
// the same institutional-conflict state model as automatic detection — it
// just pulls them from the pool via JudgeCheckIn.RECUSED instead of the
// system discovering a clash after the fact.

import { prisma } from "@/lib/prisma";

/** Idempotent — recusing twice for the same round is a no-op, not an error. */
export async function recuseJudge(judgeId: string, roundId: string): Promise<void> {
  await prisma.judgeCheckIn.upsert({
    where: { roundId_judgeId: { roundId, judgeId } },
    create: { roundId, judgeId, status: "RECUSED" },
    update: { status: "RECUSED" },
  });
}
