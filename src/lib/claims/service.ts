// docs/04-identity-and-auth.md §2, docs/08-cross-tournament-ecosystem.md §4
// — roster-to-account claiming. Always email/claim-code anchored, always
// person-confirmed, never automatic-and-invisible.

import { randomBytes } from "node:crypto";
import { prisma } from "@/lib/prisma";
import type { ClaimMethod } from "@/generated/prisma/enums";

export interface ClaimTarget {
  speakerId?: string;
  judgeId?: string;
}

function assertExactlyOneTarget(target: ClaimTarget): void {
  if (!target.speakerId && !target.judgeId) {
    throw new Error("Claim target requires exactly one of speakerId or judgeId");
  }
  if (target.speakerId && target.judgeId) {
    throw new Error("Claim target requires exactly one of speakerId or judgeId, not both");
  }
}

export type ClaimAttemptResult =
  | { outcome: "confirmed"; claimId: string }
  | { outcome: "disputed"; disputeId: string; existingClaimId: string };

/**
 * Shared core for both entry paths below: if the roster entry is unclaimed,
 * confirm it for `userId`; if it's already claimed by someone else, flag a
 * ClaimDispute instead of silently overwriting or granting by request order
 * (docs/08 §4). Wrapped in a transaction so two near-simultaneous claim
 * attempts on the same entry can't both read "unclaimed" and both succeed.
 */
async function attemptClaim(
  userId: string,
  target: ClaimTarget,
  method: ClaimMethod,
): Promise<ClaimAttemptResult> {
  assertExactlyOneTarget(target);

  return prisma.$transaction(async (tx) => {
    const current = target.speakerId
      ? await tx.speaker.findUniqueOrThrow({ where: { id: target.speakerId } })
      : await tx.judge.findUniqueOrThrow({ where: { id: target.judgeId! } });

    if (current.userId && current.userId !== userId) {
      const existingClaim = await tx.claim.findFirstOrThrow({
        where: { speakerId: target.speakerId, judgeId: target.judgeId, status: "CONFIRMED" },
      });
      const dispute = await tx.claimDispute.create({
        data: { claimId: existingClaim.id, competingUserId: userId },
      });
      return { outcome: "disputed", disputeId: dispute.id, existingClaimId: existingClaim.id };
    }

    if (current.userId === userId) {
      // already claimed by this same user — idempotent
      const existingClaim = await tx.claim.findFirstOrThrow({
        where: {
          speakerId: target.speakerId,
          judgeId: target.judgeId,
          userId,
          status: "CONFIRMED",
        },
      });
      return { outcome: "confirmed", claimId: existingClaim.id };
    }

    const claim = await tx.claim.create({
      data: {
        userId,
        speakerId: target.speakerId,
        judgeId: target.judgeId,
        method,
        status: "CONFIRMED",
      },
    });

    if (target.speakerId) {
      await tx.speaker.update({
        where: { id: target.speakerId },
        data: { userId, claimCode: null },
      });
    } else {
      await tx.judge.update({ where: { id: target.judgeId! }, data: { userId, claimCode: null } });
    }

    return { outcome: "confirmed", claimId: claim.id };
  });
}

export interface EmailMatchSuggestion {
  speakerId?: string;
  judgeId?: string;
  name: string;
  tournamentName: string;
}

/** docs/04 §2 — a suggestion only; claiming still requires confirmEmailMatchClaim. */
export async function findEmailMatchSuggestions(userId: string): Promise<EmailMatchSuggestion[]> {
  const user = await prisma.user.findUniqueOrThrow({ where: { id: userId } });
  if (!user.email) return [];

  const [speakers, judges] = await Promise.all([
    prisma.speaker.findMany({
      where: { email: user.email, userId: null },
      include: { division: { include: { tournament: true } } },
    }),
    prisma.judge.findMany({ where: { email: user.email, userId: null } }),
  ]);

  const judgeTournaments = await Promise.all(
    judges.map((j) => prisma.tournament.findUnique({ where: { id: j.tournamentId } })),
  );

  return [
    ...speakers.map((s) => ({
      speakerId: s.id,
      name: s.name,
      tournamentName: s.division.tournament.name,
    })),
    ...judges.map((j, i) => ({
      judgeId: j.id,
      name: j.name,
      tournamentName: judgeTournaments[i]?.name ?? "Unknown tournament",
    })),
  ];
}

export async function confirmEmailMatchClaim(
  userId: string,
  target: ClaimTarget,
): Promise<ClaimAttemptResult> {
  return attemptClaim(userId, target, "EMAIL_MATCH");
}

export type ClaimByCodeResult = ClaimAttemptResult | { outcome: "invalid_code" };

export async function claimByCode(userId: string, claimCode: string): Promise<ClaimByCodeResult> {
  const speaker = await prisma.speaker.findUnique({ where: { claimCode } });
  if (speaker) return attemptClaim(userId, { speakerId: speaker.id }, "CLAIM_CODE");

  const judge = await prisma.judge.findUnique({ where: { claimCode } });
  if (judge) return attemptClaim(userId, { judgeId: judge.id }, "CLAIM_CODE");

  return { outcome: "invalid_code" };
}

const CLAIM_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"; // no 0/O, 1/I/L — avoids visual ambiguity
const CLAIM_CODE_LENGTH = 8;

function randomClaimCode(): string {
  const bytes = randomBytes(CLAIM_CODE_LENGTH);
  return Array.from(bytes, (b) => CLAIM_CODE_ALPHABET[b % CLAIM_CODE_ALPHABET.length]).join("");
}

/** Organizer/tab-staff action: issue (or reissue) a fresh code for a roster entry. */
export async function generateClaimCode(target: ClaimTarget): Promise<string> {
  assertExactlyOneTarget(target);

  for (let attempt = 0; attempt < 5; attempt++) {
    const code = randomClaimCode();
    try {
      if (target.speakerId) {
        await prisma.speaker.update({ where: { id: target.speakerId }, data: { claimCode: code } });
      } else {
        await prisma.judge.update({ where: { id: target.judgeId! }, data: { claimCode: code } });
      }
      return code;
    } catch {
      // extremely unlikely unique collision — retry with a new code
      continue;
    }
  }
  throw new Error("Failed to generate a unique claim code after 5 attempts");
}

/**
 * docs/08 §4 — tab staff decide who a contested roster entry actually
 * belongs to; never resolved by claim order.
 */
export async function resolveClaimDispute(
  disputeId: string,
  winningUserId: string,
  resolvedByUserId: string,
  resolutionNote?: string,
): Promise<void> {
  await prisma.$transaction(async (tx) => {
    const dispute = await tx.claimDispute.findUniqueOrThrow({
      where: { id: disputeId },
      include: { claim: true },
    });

    if (dispute.resolvedAt) {
      throw new Error("This claim dispute has already been resolved");
    }
    if (winningUserId !== dispute.claim.userId && winningUserId !== dispute.competingUserId) {
      throw new Error("winningUserId must be either the original claimant or the disputing user");
    }

    await tx.claimDispute.update({
      where: { id: disputeId },
      data: { resolvedAt: new Date(), resolvedByUserId, resolutionNote },
    });

    if (winningUserId === dispute.claim.userId) {
      return; // original claimant keeps it — nothing else to change
    }

    // the disputer wins: revoke the original claim, reassign the roster
    // entry, and record a fresh confirmed claim for the winner
    await tx.claim.update({
      where: { id: dispute.claimId },
      data: { status: "REVOKED", revokedAt: new Date() },
    });

    await tx.claim.create({
      data: {
        userId: winningUserId,
        speakerId: dispute.claim.speakerId,
        judgeId: dispute.claim.judgeId,
        method: dispute.claim.method,
        status: "CONFIRMED",
      },
    });

    if (dispute.claim.speakerId) {
      await tx.speaker.update({
        where: { id: dispute.claim.speakerId },
        data: { userId: winningUserId },
      });
    } else if (dispute.claim.judgeId) {
      await tx.judge.update({
        where: { id: dispute.claim.judgeId },
        data: { userId: winningUserId },
      });
    }
  });
}
