// docs/03-roles-and-access.md — Grouped RBAC permission evaluation.
// Pure logic: takes already-fetched membership data, returns a decision.
// No Prisma import here — see permissionsService.ts for the DB-backed wrapper.

export interface MembershipInput {
  /** null + null = platform-global (Super Admin) — see prisma/schema.prisma "Group". */
  tournamentId: string | null;
  circuitId: string | null;
  /** narrows a grant to one institution (Institution Coordinator); null = applies tournament-wide. */
  institutionId: string | null;
  permissionKeys: string[];
}

export interface PermissionContext {
  tournamentId?: string;
  circuitId?: string;
}

export interface PermissionGrant {
  permissionKey: string;
  institutionId: string | null;
}

/** docs/03 — tournament.delete and tournament.manage_staff stay owner-only,
 *  never assignable via a Group, per the owner-vs-collaborator distinction. */
export function isOwnerOnlyPermission(permissionKey: string): boolean {
  return permissionKey === "tournament.delete" || permissionKey === "tournament.manage_staff";
}

/** Which of a user's memberships actually apply to the tournament/circuit being checked. */
export function computeEffectiveGrants(
  memberships: MembershipInput[],
  context: PermissionContext,
): PermissionGrant[] {
  const applicable = memberships.filter((m) => {
    if (m.tournamentId === null && m.circuitId === null) return true; // global (Super Admin)
    if (context.tournamentId && m.tournamentId === context.tournamentId) return true;
    if (context.circuitId && m.circuitId === context.circuitId) return true;
    return false;
  });

  return applicable.flatMap((m) =>
    m.permissionKeys.map((permissionKey) => ({ permissionKey, institutionId: m.institutionId })),
  );
}

export function hasGrant(
  grants: PermissionGrant[],
  permissionKey: string,
  options: { institutionId?: string } = {},
): boolean {
  return grants.some(
    (g) =>
      g.permissionKey === permissionKey &&
      (g.institutionId === null || g.institutionId === options.institutionId),
  );
}

export interface CanOptions {
  institutionId?: string;
  isTournamentOwner?: boolean;
}

/** The single entry point every permission check goes through — deliberately
 *  one general function rather than one hand-written function per
 *  capability, so the owner-bypass and institution-narrowing rules can't
 *  drift out of sync between call sites. */
export function can(
  grants: PermissionGrant[],
  permissionKey: string,
  options: CanOptions = {},
): boolean {
  if (options.isTournamentOwner && isOwnerOnlyPermission(permissionKey)) return true;
  return hasGrant(grants, permissionKey, { institutionId: options.institutionId });
}
