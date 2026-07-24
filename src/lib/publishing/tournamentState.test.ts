import { afterEach, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import { cleanupFixture, createFixture } from "@/lib/judging/testFixtures";
import { canTransitionTournamentState, transitionTournamentState } from "./tournamentState";
import type { Fixture } from "@/lib/judging/testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

describe("canTransitionTournamentState", () => {
  it("allows the documented forward path", () => {
    expect(canTransitionTournamentState("DRAFT", "ACTIVE")).toBe(true);
    expect(canTransitionTournamentState("ACTIVE", "CONCLUDED")).toBe(true);
    expect(canTransitionTournamentState("CONCLUDED", "ARCHIVED")).toBe(true);
  });

  it("allows the cancel-before-running shortcut", () => {
    expect(canTransitionTournamentState("DRAFT", "ARCHIVED")).toBe(true);
  });

  it("rejects skipping a stage or moving backward", () => {
    expect(canTransitionTournamentState("DRAFT", "CONCLUDED")).toBe(false);
    expect(canTransitionTournamentState("ACTIVE", "ARCHIVED")).toBe(false);
    expect(canTransitionTournamentState("ACTIVE", "DRAFT")).toBe(false);
  });

  it("rejects any transition out of Archived", () => {
    expect(canTransitionTournamentState("ARCHIVED", "DRAFT")).toBe(false);
    expect(canTransitionTournamentState("ARCHIVED", "ACTIVE")).toBe(false);
  });
});

describe("transitionTournamentState", () => {
  it("applies a valid transition and writes an audit entry", async () => {
    fixture = await createFixture();
    await transitionTournamentState(fixture.tournamentId, "ACTIVE", fixture.ownerId);

    const tournament = await prisma.tournament.findUniqueOrThrow({
      where: { id: fixture.tournamentId },
    });
    expect(tournament.state).toBe("ACTIVE");

    const audit = await prisma.auditLogEntry.findFirstOrThrow({
      where: { tournamentId: fixture.tournamentId, actionType: "tournament_state_transition" },
    });
    expect(audit.actorUserId).toBe(fixture.ownerId);
  });

  it("refuses an invalid transition and leaves the state untouched", async () => {
    fixture = await createFixture(); // starts DRAFT
    await expect(
      transitionTournamentState(fixture.tournamentId, "CONCLUDED", fixture.ownerId),
    ).rejects.toThrow("Cannot transition");

    const tournament = await prisma.tournament.findUniqueOrThrow({
      where: { id: fixture.tournamentId },
    });
    expect(tournament.state).toBe("DRAFT");
  });
});
