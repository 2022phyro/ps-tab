// docs/02-judging-contingencies.md §2 — the reserve/swing pool lifecycle.
// Deliberately not a stored state: "in reserve pool" / "checked in" /
// "deployed" is fully derivable from Judge.isReserve + JudgeCheckIn +
// Panel rows for the round, so there's nothing to keep in sync by hand.

import { prisma } from "@/lib/prisma";

export type ReserveState = "NOT_A_RESERVE" | "IN_RESERVE_POOL" | "CHECKED_IN" | "DEPLOYED";

export async function getJudgeReserveState(
  judgeId: string,
  roundId: string,
): Promise<ReserveState> {
  const judge = await prisma.judge.findUniqueOrThrow({ where: { id: judgeId } });
  if (!judge.isReserve) return "NOT_A_RESERVE";

  const deployed = await prisma.panel.findFirst({
    where: { judgeId, section: { roundId } },
  });
  if (deployed) return "DEPLOYED";

  const checkIn = await prisma.judgeCheckIn.findUnique({
    where: { roundId_judgeId: { roundId, judgeId } },
  });
  if (checkIn?.status === "CHECKED_IN") return "CHECKED_IN";

  return "IN_RESERVE_POOL";
}

/** docs/02 §2 — checked-in-and-idle reserves are the only valid hot-swap
 *  candidates (docs/02 §3); this is the shared query both that flow and any
 *  future "who's available right now" dashboard view can use. */
export async function getIdleCheckedInReserves(roundId: string) {
  const reserveJudges = await prisma.judge.findMany({
    where: {
      isReserve: true,
      checkIns: { some: { roundId, status: "CHECKED_IN" } },
      panels: { none: { section: { roundId } } },
    },
  });
  return reserveJudges;
}
