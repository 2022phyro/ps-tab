// docs/05-publishing-and-state.md §1 — tournament-level lifecycle. A guarded
// state machine, not free-form enum writes: Draft -> Active -> Concluded ->
// Archived, plus the "cancelled before ever running" shortcut Draft -> Archived.

import { prisma } from "@/lib/prisma";
import { writeAuditLog } from "@/lib/audit/log";
import type { TournamentState } from "@/generated/prisma/enums";

const ALLOWED_TRANSITIONS: Record<TournamentState, TournamentState[]> = {
  DRAFT: ["ACTIVE", "ARCHIVED"],
  ACTIVE: ["CONCLUDED"],
  CONCLUDED: ["ARCHIVED"],
  ARCHIVED: [],
};

export function canTransitionTournamentState(from: TournamentState, to: TournamentState): boolean {
  return ALLOWED_TRANSITIONS[from].includes(to);
}

export async function transitionTournamentState(
  tournamentId: string,
  to: TournamentState,
  performedByUserId: string,
): Promise<void> {
  const tournament = await prisma.tournament.findUniqueOrThrow({ where: { id: tournamentId } });
  if (!canTransitionTournamentState(tournament.state, to)) {
    throw new Error(`Cannot transition tournament from ${tournament.state} to ${to}`);
  }

  await prisma.$transaction(async (tx) => {
    await tx.tournament.update({ where: { id: tournamentId }, data: { state: to } });
    await writeAuditLog(tx, {
      actorUserId: performedByUserId,
      actionType: "tournament_state_transition",
      summary: `Tournament ${tournamentId} moved from ${tournament.state} to ${to}`,
      tournamentId,
      before: { state: tournament.state },
      after: { state: to },
    });
  });
}
