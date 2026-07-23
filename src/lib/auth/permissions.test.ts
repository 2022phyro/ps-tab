import { describe, expect, it } from "vitest";
import {
  can,
  computeEffectiveGrants,
  hasGrant,
  isOwnerOnlyPermission,
  type MembershipInput,
} from "./permissions";

describe("computeEffectiveGrants", () => {
  it("applies a global membership (Super Admin) regardless of context", () => {
    const memberships: MembershipInput[] = [
      {
        tournamentId: null,
        circuitId: null,
        institutionId: null,
        permissionKeys: ["rounds.lock_override"],
      },
    ];
    const grants = computeEffectiveGrants(memberships, { tournamentId: "t1" });
    expect(grants).toContainEqual({ permissionKey: "rounds.lock_override", institutionId: null });
  });

  it("only applies a tournament-scoped membership when the tournament matches", () => {
    const memberships: MembershipInput[] = [
      {
        tournamentId: "t1",
        circuitId: null,
        institutionId: null,
        permissionKeys: ["draws.generate"],
      },
    ];
    expect(computeEffectiveGrants(memberships, { tournamentId: "t1" })).toHaveLength(1);
    expect(computeEffectiveGrants(memberships, { tournamentId: "t2" })).toHaveLength(0);
    expect(computeEffectiveGrants(memberships, {})).toHaveLength(0);
  });

  it("only applies a circuit-scoped membership when the circuit matches", () => {
    const memberships: MembershipInput[] = [
      {
        tournamentId: null,
        circuitId: "c1",
        institutionId: null,
        permissionKeys: ["circuit.configure"],
      },
    ];
    expect(computeEffectiveGrants(memberships, { circuitId: "c1" })).toHaveLength(1);
    expect(computeEffectiveGrants(memberships, { circuitId: "c2" })).toHaveLength(0);
  });

  it("carries the institution narrowing through onto the grant", () => {
    const memberships: MembershipInput[] = [
      {
        tournamentId: "t1",
        circuitId: null,
        institutionId: "inst-A",
        permissionKeys: ["roster.manage_own_institution"],
      },
    ];
    const grants = computeEffectiveGrants(memberships, { tournamentId: "t1" });
    expect(grants).toEqual([
      { permissionKey: "roster.manage_own_institution", institutionId: "inst-A" },
    ]);
  });
});

describe("hasGrant", () => {
  it("grants access when the permission is unscoped to any institution", () => {
    const grants = [{ permissionKey: "roster.manage", institutionId: null }];
    expect(hasGrant(grants, "roster.manage", { institutionId: "inst-A" })).toBe(true);
    expect(hasGrant(grants, "roster.manage")).toBe(true);
  });

  it("only grants access for the institution the membership was narrowed to", () => {
    const grants = [{ permissionKey: "roster.manage_own_institution", institutionId: "inst-A" }];
    expect(hasGrant(grants, "roster.manage_own_institution", { institutionId: "inst-A" })).toBe(
      true,
    );
    expect(hasGrant(grants, "roster.manage_own_institution", { institutionId: "inst-B" })).toBe(
      false,
    );
    expect(hasGrant(grants, "roster.manage_own_institution")).toBe(false);
  });

  it("denies a permission the grants don't include at all", () => {
    const grants = [{ permissionKey: "audit.view", institutionId: null }];
    expect(hasGrant(grants, "rounds.lock_override")).toBe(false);
  });
});

describe("isOwnerOnlyPermission", () => {
  it("flags exactly the two owner-only capabilities", () => {
    expect(isOwnerOnlyPermission("tournament.delete")).toBe(true);
    expect(isOwnerOnlyPermission("tournament.manage_staff")).toBe(true);
    expect(isOwnerOnlyPermission("draws.generate")).toBe(false);
  });
});

describe("can", () => {
  it("lets the tournament owner through on owner-only permissions even with zero group grants", () => {
    expect(can([], "tournament.delete", { isTournamentOwner: true })).toBe(true);
    expect(can([], "tournament.manage_staff", { isTournamentOwner: true })).toBe(true);
  });

  it("denies owner-only permissions to a non-owner even with other grants", () => {
    const grants = [{ permissionKey: "draws.generate", institutionId: null }];
    expect(can(grants, "tournament.delete", { isTournamentOwner: false })).toBe(false);
  });

  it("denies a non-owner-only permission unless an actual grant covers it", () => {
    expect(can([], "draws.generate", { isTournamentOwner: true })).toBe(false);
    const grants = [{ permissionKey: "draws.generate", institutionId: null }];
    expect(can(grants, "draws.generate")).toBe(true);
  });

  it("respects institution narrowing even for an otherwise-valid grant", () => {
    const grants = [{ permissionKey: "roster.manage_own_institution", institutionId: "inst-A" }];
    expect(can(grants, "roster.manage_own_institution", { institutionId: "inst-A" })).toBe(true);
    expect(can(grants, "roster.manage_own_institution", { institutionId: "inst-B" })).toBe(false);
  });
});
