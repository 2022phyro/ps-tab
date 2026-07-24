// docs/05-publishing-and-state.md §6 — retention policy. Unclaimed roster PII
// (contact emails/names nobody ever linked to an account) is anonymized past
// a claim window; the competitive record itself (RoundResult, Ballot, etc.)
// stays exactly as it was — this purges contact info, never rows.

import { prisma } from "@/lib/prisma";

export interface RetentionResult {
  anonymizedSpeakerCount: number;
  anonymizedJudgeCount: number;
}

const REMOVED_NAME = "[Removed]";
const REMOVED_EMAIL = "removed@invalid.example";

/**
 * `cutoffDate` is caller-supplied rather than derived from a stored window —
 * same "never assume a duration, take it as an explicit parameter" reasoning
 * as the docs/02 sweep functions. Only touches Archived tournaments'
 * rosters, and only entries nobody ever claimed (`userId === null`).
 */
export async function anonymizeUnclaimedRosterPii(cutoffDate: Date): Promise<RetentionResult> {
  const archivedTournamentIds = (
    await prisma.tournament.findMany({ where: { state: "ARCHIVED" }, select: { id: true } })
  ).map((t) => t.id);

  if (archivedTournamentIds.length === 0) {
    return { anonymizedSpeakerCount: 0, anonymizedJudgeCount: 0 };
  }

  const speakers = await prisma.speaker.updateMany({
    where: {
      userId: null,
      createdAt: { lt: cutoffDate },
      tournamentId: { in: archivedTournamentIds },
    },
    data: { name: REMOVED_NAME, email: REMOVED_EMAIL, guardianEmail: null },
  });
  const judges = await prisma.judge.updateMany({
    where: {
      userId: null,
      createdAt: { lt: cutoffDate },
      tournamentId: { in: archivedTournamentIds },
    },
    data: { name: REMOVED_NAME, email: REMOVED_EMAIL },
  });

  return { anonymizedSpeakerCount: speakers.count, anonymizedJudgeCount: judges.count };
}
