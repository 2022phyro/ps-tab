// docs/08-cross-tournament-ecosystem.md §4 — account merging. Ownership
// verification of both accounts happens before this is ever called (a
// session/UI concern); this only performs the data move once that's already
// confirmed. Reversible via undoMergeAccounts for as long as the secondary
// account hasn't been hard-deleted — the snapshot records exactly which
// records moved so undo can't accidentally revert unrelated later activity.

import { prisma } from "@/lib/prisma";
import { Prisma } from "@/generated/prisma/client";
import { writeAuditLog } from "@/lib/audit/log";

interface MergeSnapshot {
  claimIds: string[];
  raisedDisputeIds: string[];
  resolvedDisputeIds: string[];
  groupMembershipIds: string[];
  guardianLinkIds: string[];
  ownedTournamentIds: string[];
  ownedCircuitIds: string[];
  auditLogEntryIds: string[];
  crossTournamentRatingId: string | null;
}

export interface MergeResult {
  movedCounts: Record<string, number>;
  /** true if the secondary account had its own rating that couldn't be
   *  moved because the primary already has one — left in place, not dropped. */
  crossTournamentRatingConflict: boolean;
}

export async function mergeAccounts(
  primaryUserId: string,
  secondaryUserId: string,
  performedByUserId: string,
): Promise<MergeResult> {
  if (primaryUserId === secondaryUserId) {
    throw new Error("Cannot merge an account into itself");
  }

  return prisma.$transaction(async (tx) => {
    const secondary = await tx.user.findUniqueOrThrow({ where: { id: secondaryUserId } });
    if (secondary.mergedIntoUserId) {
      throw new Error("This account has already been merged into another account");
    }

    const [
      claims,
      raisedDisputes,
      resolvedDisputes,
      memberships,
      guardianLinks,
      tournaments,
      circuits,
      auditEntries,
      rating,
    ] = await Promise.all([
      tx.claim.findMany({ where: { userId: secondaryUserId } }),
      tx.claimDispute.findMany({ where: { competingUserId: secondaryUserId } }),
      tx.claimDispute.findMany({ where: { resolvedByUserId: secondaryUserId } }),
      tx.groupMembership.findMany({ where: { userId: secondaryUserId } }),
      tx.guardianLink.findMany({ where: { guardianUserId: secondaryUserId } }),
      tx.tournament.findMany({ where: { ownerId: secondaryUserId } }),
      tx.circuit.findMany({ where: { ownerId: secondaryUserId } }),
      tx.auditLogEntry.findMany({ where: { actorUserId: secondaryUserId } }),
      tx.crossTournamentRating.findUnique({ where: { userId: secondaryUserId } }),
    ]);

    await tx.claim.updateMany({
      where: { userId: secondaryUserId },
      data: { userId: primaryUserId },
    });
    await tx.claimDispute.updateMany({
      where: { competingUserId: secondaryUserId },
      data: { competingUserId: primaryUserId },
    });
    await tx.claimDispute.updateMany({
      where: { resolvedByUserId: secondaryUserId },
      data: { resolvedByUserId: primaryUserId },
    });
    await tx.groupMembership.updateMany({
      where: { userId: secondaryUserId },
      data: { userId: primaryUserId },
    });
    await tx.guardianLink.updateMany({
      where: { guardianUserId: secondaryUserId },
      data: { guardianUserId: primaryUserId },
    });
    await tx.tournament.updateMany({
      where: { ownerId: secondaryUserId },
      data: { ownerId: primaryUserId },
    });
    await tx.circuit.updateMany({
      where: { ownerId: secondaryUserId },
      data: { ownerId: primaryUserId },
    });
    await tx.auditLogEntry.updateMany({
      where: { actorUserId: secondaryUserId },
      data: { actorUserId: primaryUserId },
    });

    let crossTournamentRatingConflict = false;
    let movedRatingId: string | null = null;
    if (rating) {
      const primaryRating = await tx.crossTournamentRating.findUnique({
        where: { userId: primaryUserId },
      });
      if (primaryRating) {
        crossTournamentRatingConflict = true; // left on the secondary account — needs a manual decision
      } else {
        await tx.crossTournamentRating.update({
          where: { id: rating.id },
          data: { userId: primaryUserId },
        });
        movedRatingId = rating.id;
      }
    }

    const snapshot: MergeSnapshot = {
      claimIds: claims.map((c) => c.id),
      raisedDisputeIds: raisedDisputes.map((d) => d.id),
      resolvedDisputeIds: resolvedDisputes.map((d) => d.id),
      groupMembershipIds: memberships.map((m) => m.id),
      guardianLinkIds: guardianLinks.map((g) => g.id),
      ownedTournamentIds: tournaments.map((t) => t.id),
      ownedCircuitIds: circuits.map((c) => c.id),
      auditLogEntryIds: auditEntries.map((a) => a.id),
      crossTournamentRatingId: movedRatingId,
    };

    await tx.user.update({
      where: { id: secondaryUserId },
      data: {
        mergedIntoUserId: primaryUserId,
        mergedAt: new Date(),
        mergeSnapshot: snapshot as unknown as Prisma.InputJsonValue,
      },
    });

    await writeAuditLog(tx, {
      actorUserId: performedByUserId,
      actionType: "account_merge",
      summary: `Merged account ${secondaryUserId} into ${primaryUserId}`,
    });

    return {
      movedCounts: {
        claims: claims.length,
        disputes: raisedDisputes.length + resolvedDisputes.length,
        groupMemberships: memberships.length,
        guardianLinks: guardianLinks.length,
        ownedTournaments: tournaments.length,
        ownedCircuits: circuits.length,
        auditLogEntries: auditEntries.length,
      },
      crossTournamentRatingConflict,
    };
  });
}

/** docs/08 §4 — "reversible for a grace period." Only reverts the exact
 *  records the original merge moved (per its snapshot), so anything the
 *  primary account did on its own afterward is left untouched. */
export async function undoMergeAccounts(
  secondaryUserId: string,
  performedByUserId: string,
): Promise<void> {
  await prisma.$transaction(async (tx) => {
    const secondary = await tx.user.findUniqueOrThrow({ where: { id: secondaryUserId } });
    if (!secondary.mergedIntoUserId || !secondary.mergeSnapshot) {
      throw new Error("This account was not merged into another account");
    }

    const primaryUserId = secondary.mergedIntoUserId;
    const snapshot = secondary.mergeSnapshot as unknown as MergeSnapshot;

    await tx.claim.updateMany({
      where: { id: { in: snapshot.claimIds } },
      data: { userId: secondaryUserId },
    });
    await tx.claimDispute.updateMany({
      where: { id: { in: snapshot.raisedDisputeIds } },
      data: { competingUserId: secondaryUserId },
    });
    await tx.claimDispute.updateMany({
      where: { id: { in: snapshot.resolvedDisputeIds } },
      data: { resolvedByUserId: secondaryUserId },
    });
    await tx.groupMembership.updateMany({
      where: { id: { in: snapshot.groupMembershipIds } },
      data: { userId: secondaryUserId },
    });
    await tx.guardianLink.updateMany({
      where: { id: { in: snapshot.guardianLinkIds } },
      data: { guardianUserId: secondaryUserId },
    });
    await tx.tournament.updateMany({
      where: { id: { in: snapshot.ownedTournamentIds } },
      data: { ownerId: secondaryUserId },
    });
    await tx.circuit.updateMany({
      where: { id: { in: snapshot.ownedCircuitIds } },
      data: { ownerId: secondaryUserId },
    });
    await tx.auditLogEntry.updateMany({
      where: { id: { in: snapshot.auditLogEntryIds } },
      data: { actorUserId: secondaryUserId },
    });
    if (snapshot.crossTournamentRatingId) {
      await tx.crossTournamentRating.update({
        where: { id: snapshot.crossTournamentRatingId },
        data: { userId: secondaryUserId },
      });
    }

    await tx.user.update({
      where: { id: secondaryUserId },
      data: { mergedIntoUserId: null, mergedAt: null, mergeSnapshot: Prisma.JsonNull },
    });

    await writeAuditLog(tx, {
      actorUserId: performedByUserId,
      actionType: "account_merge_undo",
      summary: `Undid merge of account ${secondaryUserId} out of ${primaryUserId}`,
    });
  });
}
