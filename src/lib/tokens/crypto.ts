// docs/04-identity-and-auth.md §1 — high-entropy, unguessable, hashed at
// rest. Pure functions; no Prisma/DB here (see service.ts for storage).

import { createHash, randomBytes } from "node:crypto";

/** 256 bits of randomness, URL-safe — goes straight into the token link/QR. */
export function generateRawToken(): string {
  return randomBytes(32).toString("base64url");
}

/** Never store the raw token — only this hash, so a DB leak doesn't leak live tokens. */
export function hashToken(rawToken: string): string {
  return createHash("sha256").update(rawToken).digest("hex");
}
