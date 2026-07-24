import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import {
  claimByCode,
  confirmEmailMatchClaim,
  findEmailMatchSuggestions,
  generateClaimCode,
  resolveClaimDispute,
} from "./service";

let tournamentId: string;
let divisionId: string;
const userIdsToClean: string[] = [];

async function makeUser(email: string) {
  const user = await prisma.user.create({ data: { email, name: email } });
  userIdsToClean.push(user.id);
  return user;
}

async function makeSpeaker(email: string) {
  return prisma.speaker.create({
    data: { tournamentId, divisionId, name: "Test Speaker", email },
  });
}

beforeAll(async () => {
  const owner = await makeUser(`claims-owner-${Date.now()}@example.com`);
  const tournament = await prisma.tournament.create({
    data: { name: "Claims Test Tournament", slug: `claims-test-${Date.now()}`, ownerId: owner.id },
  });
  tournamentId = tournament.id;
  const division = await prisma.division.create({ data: { tournamentId, name: "Open" } });
  divisionId = division.id;
});

afterAll(async () => {
  await prisma.tournament.delete({ where: { id: tournamentId } }); // cascades divisions/speakers/claims/disputes
  // audit log entries reference these test users with no cascade (Prisma
  // default Restrict) — clear them before the user rows, same fix as merge.test.ts.
  await prisma.auditLogEntry.deleteMany({ where: { actorUserId: { in: userIdsToClean } } });
  await prisma.user.deleteMany({ where: { id: { in: userIdsToClean } } });
});

afterEach(async () => {
  await prisma.speaker.deleteMany({ where: { tournamentId } });
});

describe("findEmailMatchSuggestions", () => {
  it("suggests an unclaimed roster entry matching the user's email", async () => {
    const email = `match-${Date.now()}@example.com`;
    const user = await makeUser(email);
    const speaker = await makeSpeaker(email);

    const suggestions = await findEmailMatchSuggestions(user.id);
    expect(suggestions).toContainEqual({
      speakerId: speaker.id,
      name: speaker.name,
      tournamentName: "Claims Test Tournament",
    });
  });

  it("stops suggesting a roster entry once it's been claimed (userId is no longer null)", async () => {
    const email = `already-claimed-${Date.now()}@example.com`;
    const claimant = await makeUser(email);
    const speaker = await makeSpeaker(email);

    expect((await findEmailMatchSuggestions(claimant.id)).map((s) => s.speakerId)).toContain(
      speaker.id,
    );

    await confirmEmailMatchClaim(claimant.id, { speakerId: speaker.id });

    const suggestions = await findEmailMatchSuggestions(claimant.id);
    expect(suggestions.find((s) => s.speakerId === speaker.id)).toBeUndefined();
  });

  it("returns nothing for a user whose email matches no roster entry", async () => {
    const user = await makeUser(`no-match-${Date.now()}@example.com`);
    expect(await findEmailMatchSuggestions(user.id)).toEqual([]);
  });
});

describe("confirmEmailMatchClaim", () => {
  it("confirms an unclaimed entry and links it", async () => {
    const user = await makeUser(`confirm-${Date.now()}@example.com`);
    const speaker = await makeSpeaker(user.email!);

    const result = await confirmEmailMatchClaim(user.id, { speakerId: speaker.id });
    expect(result.outcome).toBe("confirmed");

    const updated = await prisma.speaker.findUniqueOrThrow({ where: { id: speaker.id } });
    expect(updated.userId).toBe(user.id);
  });

  it("is idempotent when the same user confirms twice", async () => {
    const user = await makeUser(`idempotent-${Date.now()}@example.com`);
    const speaker = await makeSpeaker(user.email!);

    const first = await confirmEmailMatchClaim(user.id, { speakerId: speaker.id });
    const second = await confirmEmailMatchClaim(user.id, { speakerId: speaker.id });
    expect(first.outcome).toBe("confirmed");
    expect(second).toEqual(first);
  });

  it("flags a dispute instead of overwriting when a different user claims an already-claimed entry", async () => {
    const email = `disputed-${Date.now()}@example.com`;
    const firstUser = await makeUser(email);
    const speaker = await makeSpeaker(email);
    await confirmEmailMatchClaim(firstUser.id, { speakerId: speaker.id });

    // a second, distinct account (its own email — User.email is unique)
    // attempts to claim the same already-claimed roster entry directly.
    // attemptClaim's dispute detection keys on userId mismatch, not on
    // whether the second caller's own email happens to match too.
    const secondUser = await makeUser(`disputed-second-${Date.now()}@example.com`);
    const result = await confirmEmailMatchClaim(secondUser.id, { speakerId: speaker.id });
    expect(result.outcome).toBe("disputed");

    // roster entry stays with the original claimant — never silently reassigned
    const updated = await prisma.speaker.findUniqueOrThrow({ where: { id: speaker.id } });
    expect(updated.userId).toBe(firstUser.id);
  });
});

describe("generateClaimCode + claimByCode", () => {
  it("generates a code from the unambiguous alphabet and lets it be claimed once", async () => {
    const speaker = await makeSpeaker(`code-${Date.now()}@example.com`);
    const code = await generateClaimCode({ speakerId: speaker.id });

    expect(code).toHaveLength(8);
    expect(code).toMatch(/^[A-HJ-NP-Z2-9]+$/); // no 0/O/1/I/L

    const claimant = await makeUser(`code-claimant-${Date.now()}@example.com`);
    const result = await claimByCode(claimant.id, code);
    expect(result.outcome).toBe("confirmed");

    const updated = await prisma.speaker.findUniqueOrThrow({ where: { id: speaker.id } });
    expect(updated.userId).toBe(claimant.id);
    expect(updated.claimCode).toBeNull(); // single-use
  });

  it("rejects an invalid or already-consumed code", async () => {
    expect(await claimByCode("whoever", "NOTAREAL")).toEqual({ outcome: "invalid_code" });

    const speaker = await makeSpeaker(`reuse-${Date.now()}@example.com`);
    const code = await generateClaimCode({ speakerId: speaker.id });
    const claimant = await makeUser(`reuse-claimant-${Date.now()}@example.com`);
    await claimByCode(claimant.id, code);

    const secondClaimant = await makeUser(`reuse-claimant-2-${Date.now()}@example.com`);
    expect(await claimByCode(secondClaimant.id, code)).toEqual({ outcome: "invalid_code" });
  });
});

describe("resolveClaimDispute", () => {
  async function makeDispute() {
    const email = `dispute-flow-${Date.now()}@example.com`;
    const originalClaimant = await makeUser(email);
    const speaker = await makeSpeaker(email);
    await confirmEmailMatchClaim(originalClaimant.id, { speakerId: speaker.id });

    const disputer = await makeUser(`dispute-flow-second-${Date.now()}@example.com`);
    const disputeResult = await confirmEmailMatchClaim(disputer.id, { speakerId: speaker.id });
    if (disputeResult.outcome !== "disputed") throw new Error("expected a dispute");

    const staff = await makeUser(`staff-${Date.now()}@example.com`);
    return { speaker, originalClaimant, disputer, staff, disputeId: disputeResult.disputeId };
  }

  it("leaves the roster entry with the original claimant when staff rule in their favor", async () => {
    const { speaker, originalClaimant, staff, disputeId } = await makeDispute();

    await resolveClaimDispute(
      disputeId,
      originalClaimant.id,
      staff.id,
      "Verified via school roster",
    );

    const updated = await prisma.speaker.findUniqueOrThrow({ where: { id: speaker.id } });
    expect(updated.userId).toBe(originalClaimant.id);

    const dispute = await prisma.claimDispute.findUniqueOrThrow({ where: { id: disputeId } });
    expect(dispute.resolvedAt).not.toBeNull();
    expect(dispute.resolvedByUserId).toBe(staff.id);
  });

  it("reassigns the roster entry and revokes the original claim when staff rule for the disputer", async () => {
    const { speaker, originalClaimant, disputer, staff, disputeId } = await makeDispute();

    await resolveClaimDispute(disputeId, disputer.id, staff.id);

    const updated = await prisma.speaker.findUniqueOrThrow({ where: { id: speaker.id } });
    expect(updated.userId).toBe(disputer.id);

    const originalClaim = await prisma.claim.findFirstOrThrow({
      where: { speakerId: speaker.id, userId: originalClaimant.id },
    });
    expect(originalClaim.status).toBe("REVOKED");

    const newClaim = await prisma.claim.findFirstOrThrow({
      where: { speakerId: speaker.id, userId: disputer.id },
    });
    expect(newClaim.status).toBe("CONFIRMED");
  });

  it("refuses to resolve the same dispute twice", async () => {
    const { originalClaimant, staff, disputeId } = await makeDispute();
    await resolveClaimDispute(disputeId, originalClaimant.id, staff.id);
    await expect(resolveClaimDispute(disputeId, originalClaimant.id, staff.id)).rejects.toThrow();
  });

  it("refuses a winningUserId that isn't one of the two parties in the dispute", async () => {
    const { staff, disputeId } = await makeDispute();
    const outsider = await makeUser(`outsider-${Date.now()}@example.com`);
    await expect(resolveClaimDispute(disputeId, outsider.id, staff.id)).rejects.toThrow();
  });
});
