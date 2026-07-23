import { afterEach, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import { mergeAccounts, undoMergeAccounts } from "./merge";

const userIdsToClean: string[] = [];
const tournamentIdsToClean: string[] = [];

async function makeUser(label: string) {
  const user = await prisma.user.create({
    data: { email: `${label}-${Date.now()}-${Math.random()}@example.com` },
  });
  userIdsToClean.push(user.id);
  return user;
}

afterEach(async () => {
  await prisma.tournament.deleteMany({ where: { id: { in: tournamentIdsToClean } } });
  tournamentIdsToClean.length = 0;
  // AuditLogEntry.actorUserId has no cascade — mergeAccounts/undoMergeAccounts
  // both write audit entries for the performing user, so those need clearing
  // before the users themselves can be deleted.
  await prisma.auditLogEntry.deleteMany({ where: { actorUserId: { in: userIdsToClean } } });
  await prisma.user.deleteMany({ where: { id: { in: userIdsToClean } } });
  userIdsToClean.length = 0;
});

describe("mergeAccounts", () => {
  it("moves ownership, group memberships, and a rating from secondary to primary", async () => {
    const primary = await makeUser("primary");
    const secondary = await makeUser("secondary");
    const staff = await makeUser("staff");

    const tournament = await prisma.tournament.create({
      data: {
        name: "Merge Test Tournament",
        slug: `merge-test-${Date.now()}`,
        ownerId: secondary.id,
      },
    });
    tournamentIdsToClean.push(tournament.id);

    const group = await prisma.group.create({
      data: { name: "Merge Test Group", tournamentId: tournament.id },
    });
    await prisma.groupMembership.create({ data: { groupId: group.id, userId: secondary.id } });

    await prisma.crossTournamentRating.create({
      data: { userId: secondary.id, rating: 1600, optedIn: true },
    });

    const result = await mergeAccounts(primary.id, secondary.id, staff.id);

    expect(result.movedCounts.ownedTournaments).toBe(1);
    expect(result.movedCounts.groupMemberships).toBe(1);
    expect(result.crossTournamentRatingConflict).toBe(false);

    const updatedTournament = await prisma.tournament.findUniqueOrThrow({
      where: { id: tournament.id },
    });
    expect(updatedTournament.ownerId).toBe(primary.id);

    const membership = await prisma.groupMembership.findFirstOrThrow({
      where: { groupId: group.id },
    });
    expect(membership.userId).toBe(primary.id);

    const rating = await prisma.crossTournamentRating.findUniqueOrThrow({
      where: { userId: primary.id },
    });
    expect(rating.rating).toBe(1600);

    const secondaryAfter = await prisma.user.findUniqueOrThrow({ where: { id: secondary.id } });
    expect(secondaryAfter.mergedIntoUserId).toBe(primary.id);
    expect(secondaryAfter.mergedAt).not.toBeNull();
  });

  it("flags a conflict and leaves the rating alone when both accounts already have one", async () => {
    const primary = await makeUser("primary-conflict");
    const secondary = await makeUser("secondary-conflict");
    const staff = await makeUser("staff-conflict");

    await prisma.crossTournamentRating.create({
      data: { userId: primary.id, rating: 1500, optedIn: true },
    });
    await prisma.crossTournamentRating.create({
      data: { userId: secondary.id, rating: 1700, optedIn: true },
    });

    const result = await mergeAccounts(primary.id, secondary.id, staff.id);
    expect(result.crossTournamentRatingConflict).toBe(true);

    // primary's own rating is untouched; secondary's stays where it was
    expect(
      (await prisma.crossTournamentRating.findUniqueOrThrow({ where: { userId: primary.id } }))
        .rating,
    ).toBe(1500);
    expect(
      (await prisma.crossTournamentRating.findUniqueOrThrow({ where: { userId: secondary.id } }))
        .rating,
    ).toBe(1700);
  });

  it("refuses to merge an account into itself", async () => {
    const user = await makeUser("self-merge");
    await expect(mergeAccounts(user.id, user.id, user.id)).rejects.toThrow();
  });

  it("refuses to merge an account that's already been merged", async () => {
    const primary = await makeUser("already-primary");
    const secondary = await makeUser("already-secondary");
    const staff = await makeUser("already-staff");

    await mergeAccounts(primary.id, secondary.id, staff.id);
    await expect(mergeAccounts(primary.id, secondary.id, staff.id)).rejects.toThrow();
  });
});

describe("undoMergeAccounts", () => {
  it("reverts exactly the records the merge moved, leaving the secondary account usable again", async () => {
    const primary = await makeUser("undo-primary");
    const secondary = await makeUser("undo-secondary");
    const staff = await makeUser("undo-staff");

    const tournament = await prisma.tournament.create({
      data: {
        name: "Undo Test Tournament",
        slug: `undo-test-${Date.now()}`,
        ownerId: secondary.id,
      },
    });
    tournamentIdsToClean.push(tournament.id);

    await mergeAccounts(primary.id, secondary.id, staff.id);
    await undoMergeAccounts(secondary.id, staff.id);

    const tournamentAfterUndo = await prisma.tournament.findUniqueOrThrow({
      where: { id: tournament.id },
    });
    expect(tournamentAfterUndo.ownerId).toBe(secondary.id);

    const secondaryAfterUndo = await prisma.user.findUniqueOrThrow({ where: { id: secondary.id } });
    expect(secondaryAfterUndo.mergedIntoUserId).toBeNull();
    expect(secondaryAfterUndo.mergedAt).toBeNull();
  });

  it("doesn't revert activity the primary account picked up on its own after the merge", async () => {
    const primary = await makeUser("noleak-primary");
    const secondary = await makeUser("noleak-secondary");
    const staff = await makeUser("noleak-staff");

    await mergeAccounts(primary.id, secondary.id, staff.id);

    // primary independently owns a new tournament after the merge completed
    const laterTournament = await prisma.tournament.create({
      data: { name: "Later Tournament", slug: `later-${Date.now()}`, ownerId: primary.id },
    });
    tournamentIdsToClean.push(laterTournament.id);

    await undoMergeAccounts(secondary.id, staff.id);

    // undo must not have touched it — it was never in the merge snapshot
    const stillPrimary = await prisma.tournament.findUniqueOrThrow({
      where: { id: laterTournament.id },
    });
    expect(stillPrimary.ownerId).toBe(primary.id);
  });

  it("refuses to undo an account that was never merged", async () => {
    const user = await makeUser("never-merged");
    const staff = await makeUser("never-merged-staff");
    await expect(undoMergeAccounts(user.id, staff.id)).rejects.toThrow();
  });
});
