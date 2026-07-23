// Integration tests against the real local Postgres DB and the seed data
// from prisma/seed.ts (Riverside Invitational + Fall Season Circuit). This
// is the "Definition of done" check from PLAN.md Section 4: every role's
// permission check gets both an allowed and a denied case.

import { beforeAll, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import { userCan } from "./permissionsService";

let superAdminId: string;
let tabStaffId: string; // director@example.com — also the tournament owner
let coordinatorId: string; // coach@example.com — narrowed to Lincoln High School
let circuitAdminId: string;
let tournamentId: string;
let circuitId: string;
let lincolnInstitutionId: string;
let brookfieldInstitutionId: string;

beforeAll(async () => {
  const [superAdmin, tabStaff, coordinator, circuitAdmin] = await Promise.all([
    prisma.user.findUniqueOrThrow({ where: { email: "superadmin@example.com" } }),
    prisma.user.findUniqueOrThrow({ where: { email: "director@example.com" } }),
    prisma.user.findUniqueOrThrow({ where: { email: "coach@example.com" } }),
    prisma.user.findUniqueOrThrow({ where: { email: "circuitadmin@example.com" } }),
  ]);
  superAdminId = superAdmin.id;
  tabStaffId = tabStaff.id;
  coordinatorId = coordinator.id;
  circuitAdminId = circuitAdmin.id;

  const tournament = await prisma.tournament.findUniqueOrThrow({
    where: { slug: "riverside-invitational" },
  });
  tournamentId = tournament.id;

  const circuit = await prisma.circuit.findFirstOrThrow({ where: { name: "Fall Season Circuit" } });
  circuitId = circuit.id;

  lincolnInstitutionId = (
    await prisma.institution.findFirstOrThrow({
      where: { tournamentId, name: "Lincoln High School" },
    })
  ).id;
  brookfieldInstitutionId = (
    await prisma.institution.findFirstOrThrow({
      where: { tournamentId, name: "Brookfield Academy" },
    })
  ).id;
});

describe("Super Admin", () => {
  it("has an escalation-only permission globally, for any tournament", async () => {
    expect(await userCan(superAdminId, "rounds.lock_override", { tournamentId })).toBe(true);
  });

  it("has it even for a tournament it has no other relationship to (global scope)", async () => {
    expect(await userCan(superAdminId, "circuit.configure", { circuitId })).toBe(true);
  });
});

describe("Tab Staff (also the tournament owner)", () => {
  it("can generate draws for its own tournament", async () => {
    expect(await userCan(tabStaffId, "draws.generate", { tournamentId })).toBe(true);
  });

  it("cannot generate draws for a tournament it has no membership in", async () => {
    const otherTournament = await prisma.tournament.create({
      data: {
        name: "Unrelated Tournament",
        slug: `unrelated-${Date.now()}`,
        ownerId: superAdminId,
      },
    });
    expect(await userCan(tabStaffId, "draws.generate", { tournamentId: otherTournament.id })).toBe(
      false,
    );
    await prisma.tournament.delete({ where: { id: otherTournament.id } });
  });

  it("gets owner-only permissions via ownership, not via the Tab Staff group grant", async () => {
    expect(await userCan(tabStaffId, "tournament.delete", { tournamentId })).toBe(true);
    expect(await userCan(tabStaffId, "tournament.manage_staff", { tournamentId })).toBe(true);
  });
});

describe("Institution Coordinator", () => {
  it("can manage its own institution's roster", async () => {
    expect(
      await userCan(coordinatorId, "roster.manage_own_institution", {
        tournamentId,
        institutionId: lincolnInstitutionId,
      }),
    ).toBe(true);
  });

  it("cannot manage a different institution's roster in the same tournament", async () => {
    expect(
      await userCan(coordinatorId, "roster.manage_own_institution", {
        tournamentId,
        institutionId: brookfieldInstitutionId,
      }),
    ).toBe(false);
  });

  it("has no operational tab access at all (docs/03 Extended roles)", async () => {
    expect(await userCan(coordinatorId, "draws.generate", { tournamentId })).toBe(false);
    expect(await userCan(coordinatorId, "tournament.delete", { tournamentId })).toBe(false);
  });
});

describe("Circuit Administrator", () => {
  it("can configure its own circuit", async () => {
    expect(await userCan(circuitAdminId, "circuit.configure", { circuitId })).toBe(true);
  });

  it("has no access into the tournaments that belong to that circuit", async () => {
    expect(await userCan(circuitAdminId, "draws.generate", { tournamentId })).toBe(false);
    expect(await userCan(circuitAdminId, "roster.manage", { tournamentId })).toBe(false);
  });
});

describe("a user with no memberships at all", () => {
  it("is denied everything, including owner-only permissions", async () => {
    const stranger = await prisma.user.create({
      data: { email: `stranger-${Date.now()}@example.com`, name: "No Relationship" },
    });
    expect(await userCan(stranger.id, "draws.generate", { tournamentId })).toBe(false);
    expect(await userCan(stranger.id, "tournament.delete", { tournamentId })).toBe(false);
    await prisma.user.delete({ where: { id: stranger.id } });
  });
});
