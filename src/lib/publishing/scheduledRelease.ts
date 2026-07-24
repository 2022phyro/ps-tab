// docs/05-publishing-and-state.md §2 — organizer-scheduled future gate
// releases, cancellable any time before they fire. The actual polling
// trigger is a real Inngest cron in Section 8 (not installed yet); the
// firing logic itself is complete and testable here today —
// `executeDueScheduledReleases` is exactly what that cron will call each tick.

import { prisma } from "@/lib/prisma";
import { releaseDraws, releaseResults, releaseStandings } from "./gates";
import type { PublishGate } from "@/generated/prisma/enums";

export async function scheduleGateRelease(
  roundId: string,
  gate: PublishGate,
  releaseAt: Date,
  performedByUserId: string,
) {
  const existing = await prisma.scheduledRelease.findFirst({
    where: { roundId, gate, cancelledAt: null, executedAt: null },
  });
  if (existing) {
    throw new Error(
      `An active schedule already exists for this round+gate (${existing.id}) — cancel it first`,
    );
  }
  return prisma.scheduledRelease.create({
    data: { roundId, gate, releaseAt, createdByUserId: performedByUserId },
  });
}

export async function cancelScheduledRelease(scheduledReleaseId: string): Promise<void> {
  const existing = await prisma.scheduledRelease.findUniqueOrThrow({
    where: { id: scheduledReleaseId },
  });
  if (existing.executedAt) {
    throw new Error("This scheduled release has already fired — nothing to cancel");
  }
  if (existing.cancelledAt) return; // idempotent

  await prisma.scheduledRelease.update({
    where: { id: scheduledReleaseId },
    data: { cancelledAt: new Date() },
  });
}

const RELEASERS: Record<
  PublishGate,
  (roundId: string, performedByUserId: string) => Promise<void>
> = {
  DRAWS: releaseDraws,
  RESULTS: releaseResults,
  STANDINGS: releaseStandings,
};

export interface ExecuteDueResult {
  executedIds: string[];
}

/** Never throws for an individual schedule whose gate turns out to already
 *  be released some other way (or a precondition like "results must release
 *  before standings" no longer holds) — that entry is simply left pending
 *  rather than crashing the whole sweep; tab staff can still see and act on
 *  it manually. */
export async function executeDueScheduledReleases(
  atTime: Date = new Date(),
): Promise<ExecuteDueResult> {
  const due = await prisma.scheduledRelease.findMany({
    where: { cancelledAt: null, executedAt: null, releaseAt: { lte: atTime } },
  });

  const executedIds: string[] = [];
  for (const schedule of due) {
    try {
      await RELEASERS[schedule.gate](schedule.roundId, schedule.createdByUserId);
      await prisma.scheduledRelease.update({
        where: { id: schedule.id },
        data: { executedAt: atTime },
      });
      executedIds.push(schedule.id);
    } catch {
      continue;
    }
  }

  return { executedIds };
}
