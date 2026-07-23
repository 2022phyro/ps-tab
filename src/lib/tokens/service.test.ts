import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import { issueToken, reissueToken, revokeToken, validateToken } from "./service";

let speakerId: string;
let judgeId: string;
const createdTokenIds: string[] = [];

beforeAll(async () => {
  speakerId = (await prisma.speaker.findFirstOrThrow()).id;
  judgeId = (await prisma.judge.findFirstOrThrow()).id;
});

afterEach(async () => {
  if (createdTokenIds.length) {
    await prisma.accessToken.deleteMany({ where: { id: { in: createdTokenIds } } });
    createdTokenIds.length = 0;
  }
});

describe("issueToken", () => {
  it("requires exactly one of speakerId/judgeId", async () => {
    await expect(issueToken({ scope: "speaker:own" })).rejects.toThrow();
    await expect(issueToken({ speakerId, judgeId, scope: "speaker:own" })).rejects.toThrow();
  });

  it("is permanent by default — no expiresAt set", async () => {
    const issued = await issueToken({ speakerId, scope: "speaker:own" });
    createdTokenIds.push(issued.id);

    const row = await prisma.accessToken.findUniqueOrThrow({ where: { id: issued.id } });
    expect(row.expiresAt).toBeNull();
    expect(row.hashedValue).not.toBe(issued.rawToken); // never stored raw
  });
});

describe("validateToken", () => {
  it("validates a freshly-issued token and returns its holder/scope", async () => {
    const issued = await issueToken({ speakerId, scope: "speaker:own" });
    createdTokenIds.push(issued.id);

    const result = await validateToken(issued.rawToken);
    expect(result.valid).toBe(true);
    expect(result.speakerId).toBe(speakerId);
    expect(result.scope).toBe("speaker:own");
  });

  it("works identically for a judge-held token", async () => {
    const issued = await issueToken({ judgeId, scope: "judge:own" });
    createdTokenIds.push(issued.id);

    const result = await validateToken(issued.rawToken);
    expect(result.valid).toBe(true);
    expect(result.judgeId).toBe(judgeId);
  });

  it("rejects a token that was never issued", async () => {
    const result = await validateToken("this-token-does-not-exist");
    expect(result).toEqual({ valid: false, reason: "not_found" });
  });

  it("rejects a revoked token", async () => {
    const issued = await issueToken({ speakerId, scope: "speaker:own" });
    createdTokenIds.push(issued.id);

    await revokeToken(issued.id);
    const result = await validateToken(issued.rawToken);
    expect(result).toEqual({ valid: false, reason: "revoked" });
  });

  it("rejects a token with an explicit expiry in the past", async () => {
    const issued = await issueToken({
      speakerId,
      scope: "speaker:own",
      expiresAt: new Date(Date.now() - 1000),
    });
    createdTokenIds.push(issued.id);

    const result = await validateToken(issued.rawToken);
    expect(result).toEqual({ valid: false, reason: "expired" });
  });

  it("stays valid far into the future when no expiry was set (permanent by default)", async () => {
    const issued = await issueToken({ speakerId, scope: "speaker:own" });
    createdTokenIds.push(issued.id);

    // no real way to fast-forward wall-clock time in this test; the
    // guarantee under test is that expiresAt stays null and validateToken
    // never runs the expiry branch at all when it's null.
    const row = await prisma.accessToken.findUniqueOrThrow({ where: { id: issued.id } });
    expect(row.expiresAt).toBeNull();
    expect((await validateToken(issued.rawToken)).valid).toBe(true);
  });
});

describe("reissueToken", () => {
  it("revokes the old token and issues a working new one in one action", async () => {
    const original = await issueToken({ speakerId, scope: "speaker:own" });
    createdTokenIds.push(original.id);

    const reissued = await reissueToken(original.id, { speakerId, scope: "speaker:own" });
    createdTokenIds.push(reissued.id);

    expect((await validateToken(original.rawToken)).valid).toBe(false);
    expect((await validateToken(reissued.rawToken)).valid).toBe(true);
  });
});
