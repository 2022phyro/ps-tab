// Prisma-backed wiring around the pure logic in permissions.ts.

import { prisma } from "@/lib/prisma";
import {
  can,
  computeEffectiveGrants,
  type CanOptions,
  type PermissionContext,
  type PermissionGrant,
} from "./permissions";

export async function getUserGrants(
  userId: string,
  context: PermissionContext,
): Promise<PermissionGrant[]> {
  const memberships = await prisma.groupMembership.findMany({
    where: { userId },
    include: {
      group: { include: { permissions: { include: { permission: true } } } },
    },
  });

  const input = memberships.map((m) => ({
    tournamentId: m.group.tournamentId,
    circuitId: m.group.circuitId,
    institutionId: m.institutionId,
    permissionKeys: m.group.permissions.map((gp) => gp.permission.key),
  }));

  return computeEffectiveGrants(input, context);
}

export type UserCanOptions = CanOptions & PermissionContext;

export async function userCan(
  userId: string,
  permissionKey: string,
  options: UserCanOptions = {},
): Promise<boolean> {
  let isTournamentOwner = options.isTournamentOwner;
  if (options.tournamentId && isTournamentOwner === undefined) {
    const tournament = await prisma.tournament.findUnique({
      where: { id: options.tournamentId },
      select: { ownerId: true },
    });
    isTournamentOwner = tournament?.ownerId === userId;
  }

  const grants = await getUserGrants(userId, options);
  return can(grants, permissionKey, { institutionId: options.institutionId, isTournamentOwner });
}
