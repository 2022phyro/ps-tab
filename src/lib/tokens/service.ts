// docs/04-identity-and-auth.md §1 — zero-auth token issuance/validation/revocation.

import { prisma } from "@/lib/prisma";
import { generateRawToken, hashToken } from "./crypto";
import { writeAuditLog } from "@/lib/audit/log";

export interface IssueTokenInput {
  speakerId?: string;
  judgeId?: string;
  scope: string;
  /** omit for the default: permanent, no expiry (docs/04 §1). */
  expiresAt?: Date;
}

export interface IssuedToken {
  id: string;
  /** only ever available at issuance time — never re-derivable, never stored raw. */
  rawToken: string;
}

function assertExactlyOneHolder(input: IssueTokenInput): void {
  if (!input.speakerId && !input.judgeId) {
    throw new Error("issueToken requires exactly one of speakerId or judgeId");
  }
  if (input.speakerId && input.judgeId) {
    throw new Error("issueToken requires exactly one of speakerId or judgeId, not both");
  }
}

export async function issueToken(input: IssueTokenInput): Promise<IssuedToken> {
  assertExactlyOneHolder(input);

  const rawToken = generateRawToken();
  const created = await prisma.accessToken.create({
    data: {
      hashedValue: hashToken(rawToken),
      speakerId: input.speakerId,
      judgeId: input.judgeId,
      scope: input.scope,
      expiresAt: input.expiresAt ?? null,
    },
  });

  return { id: created.id, rawToken };
}

export interface ValidationResult {
  valid: boolean;
  reason?: "not_found" | "revoked" | "expired";
  tokenId?: string;
  speakerId?: string | null;
  judgeId?: string | null;
  scope?: string;
}

export async function validateToken(rawToken: string): Promise<ValidationResult> {
  const token = await prisma.accessToken.findUnique({
    where: { hashedValue: hashToken(rawToken) },
  });

  if (!token) return { valid: false, reason: "not_found" };
  if (token.revokedAt) return { valid: false, reason: "revoked" };
  if (token.expiresAt && token.expiresAt < new Date()) return { valid: false, reason: "expired" };

  return {
    valid: true,
    tokenId: token.id,
    speakerId: token.speakerId,
    judgeId: token.judgeId,
    scope: token.scope,
  };
}

/** Instant — the moment revokedAt is set, validateToken stops accepting it
 *  (docs/04 §1). `performedByUserId` is optional since plenty of revocations
 *  happen with no authenticated actor yet (e.g. a self-service "sign out this
 *  device" flow before any account exists) — logged only when one is given,
 *  rather than forcing every zero-auth code path to invent an actor. */
export async function revokeToken(tokenId: string, performedByUserId?: string): Promise<void> {
  await prisma.accessToken.update({ where: { id: tokenId }, data: { revokedAt: new Date() } });
  if (performedByUserId) {
    await writeAuditLog(prisma, {
      actorUserId: performedByUserId,
      actionType: "token_revoked",
      summary: `Revoked access token ${tokenId}`,
    });
  }
}

/** docs/04 §1 — lost phone, accidental share: revoke the old token and issue
 *  a fresh one to the same roster entry in a single action. */
export async function reissueToken(
  oldTokenId: string,
  input: IssueTokenInput,
  performedByUserId?: string,
): Promise<IssuedToken> {
  const issued = await issueToken(input);
  await revokeToken(oldTokenId, performedByUserId);
  return issued;
}
