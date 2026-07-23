import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import {
  assertGuardianConsent,
  confirmGuardianLink,
  hasConfirmedGuardianConsent,
  requestGuardianLink,
} from "./guardianConsent";

let tournamentId: string;
let divisionId: string;
const userIdsToClean: string[] = [];

async function makeGuardianUser() {
  const user = await prisma.user.create({
    data: { email: `guardian-${Date.now()}-${Math.random()}@example.com` },
  });
  userIdsToClean.push(user.id);
  return user;
}

async function makeSpeaker(isMinor: boolean) {
  return prisma.speaker.create({
    data: {
      tournamentId,
      divisionId,
      name: "Test Speaker",
      email: `speaker-${Date.now()}-${Math.random()}@example.com`,
      isMinor,
    },
  });
}

beforeAll(async () => {
  const owner = await makeGuardianUser();
  const tournament = await prisma.tournament.create({
    data: {
      name: "Guardian Test Tournament",
      slug: `guardian-test-${Date.now()}`,
      ownerId: owner.id,
    },
  });
  tournamentId = tournament.id;
  divisionId = (await prisma.division.create({ data: { tournamentId, name: "Open" } })).id;
});

afterAll(async () => {
  await prisma.tournament.delete({ where: { id: tournamentId } });
  await prisma.user.deleteMany({ where: { id: { in: userIdsToClean } } });
});

afterEach(async () => {
  await prisma.speaker.deleteMany({ where: { tournamentId } });
});

describe("hasConfirmedGuardianConsent", () => {
  it("is always true for a non-minor speaker — the gate doesn't apply", async () => {
    const speaker = await makeSpeaker(false);
    expect(await hasConfirmedGuardianConsent(speaker.id)).toBe(true);
  });

  it("is false for a minor with no guardian link at all", async () => {
    const speaker = await makeSpeaker(true);
    expect(await hasConfirmedGuardianConsent(speaker.id)).toBe(false);
  });

  it("is false for a minor with a requested but unconfirmed guardian link", async () => {
    const speaker = await makeSpeaker(true);
    const guardian = await makeGuardianUser();
    await requestGuardianLink(speaker.id, guardian.id);

    expect(await hasConfirmedGuardianConsent(speaker.id)).toBe(false);
  });

  it("is true once the guardian link is confirmed", async () => {
    const speaker = await makeSpeaker(true);
    const guardian = await makeGuardianUser();
    const link = await requestGuardianLink(speaker.id, guardian.id);
    await confirmGuardianLink(link.id);

    expect(await hasConfirmedGuardianConsent(speaker.id)).toBe(true);
  });
});

describe("assertGuardianConsent", () => {
  it("throws for a minor without confirmed consent", async () => {
    const speaker = await makeSpeaker(true);
    await expect(assertGuardianConsent(speaker.id)).rejects.toThrow();
  });

  it("resolves without throwing once consent is confirmed", async () => {
    const speaker = await makeSpeaker(true);
    const guardian = await makeGuardianUser();
    const link = await requestGuardianLink(speaker.id, guardian.id);
    await confirmGuardianLink(link.id);

    await expect(assertGuardianConsent(speaker.id)).resolves.toBeUndefined();
  });
});

describe("requestGuardianLink", () => {
  it("refuses to link a guardian to a non-minor speaker", async () => {
    const speaker = await makeSpeaker(false);
    const guardian = await makeGuardianUser();
    await expect(requestGuardianLink(speaker.id, guardian.id)).rejects.toThrow();
  });
});
