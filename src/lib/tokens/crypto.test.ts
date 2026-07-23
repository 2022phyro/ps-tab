import { describe, expect, it } from "vitest";
import { generateRawToken, hashToken } from "./crypto";

describe("generateRawToken", () => {
  it("produces a long, URL-safe, unique token every call", () => {
    const a = generateRawToken();
    const b = generateRawToken();
    expect(a).not.toBe(b);
    expect(a.length).toBeGreaterThan(30);
    expect(a).toMatch(/^[A-Za-z0-9_-]+$/); // base64url alphabet only
  });
});

describe("hashToken", () => {
  it("is deterministic", () => {
    const raw = generateRawToken();
    expect(hashToken(raw)).toBe(hashToken(raw));
  });

  it("produces different hashes for different tokens", () => {
    expect(hashToken(generateRawToken())).not.toBe(hashToken(generateRawToken()));
  });

  it("never reveals the raw token in its output", () => {
    const raw = generateRawToken();
    expect(hashToken(raw)).not.toContain(raw);
  });
});
