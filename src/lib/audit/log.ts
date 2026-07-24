// docs/05-publishing-and-state.md §5 — a single writer every mutating action
// across the app calls, so "every mutation produces exactly one
// AuditLogEntry" is enforced by convention in one place rather than
// hand-rolled per call site. Accepts either the top-level client or a
// transaction client so callers that need audit + mutation atomicity (most
// of them) can pass their `tx`.

import { prisma } from "@/lib/prisma";
import type { Prisma } from "@/generated/prisma/client";

type Db = typeof prisma | Prisma.TransactionClient;

export interface AuditLogInput {
  /** omit for a system-originated action with no human actor (a sweep, a
   *  scheduled release firing, a retention purge) — logged with a null actor
   *  rather than skipped, so it still shows up in the audit trail. */
  actorUserId?: string;
  actionType: string;
  summary: string;
  tournamentId?: string | null;
  reason?: string;
  before?: unknown;
  after?: unknown;
}

export async function writeAuditLog(db: Db, input: AuditLogInput): Promise<void> {
  await db.auditLogEntry.create({
    data: {
      actorUserId: input.actorUserId ?? null,
      actionType: input.actionType,
      summary: input.summary,
      tournamentId: input.tournamentId ?? null,
      reason: input.reason,
      beforeData: input.before as Prisma.InputJsonValue,
      afterData: input.after as Prisma.InputJsonValue,
    },
  });
}
