import { afterEach, describe, expect, it } from "vitest";
import { prisma } from "@/lib/prisma";
import { cleanupFixture, createFixture, makeRound, makeSpeaker } from "@/lib/judging/testFixtures";
import { getVisibleRoundResults, getVisibleStandings, liftEmbargo, placeEmbargo } from "./embargo";
import { releaseResults, releaseStandings } from "./gates";
import type { Fixture } from "@/lib/judging/testFixtures";

let fixture: Fixture | undefined;

afterEach(async () => {
  if (fixture) await cleanupFixture(fixture);
  fixture = undefined;
});

describe("getVisibleRoundResults", () => {
  it("returns nothing while results are still held", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    await prisma.roundResult.create({
      data: { roundId: round.id, speakerId: speaker.id, roundScore: 90, rank: 1 },
    });

    const view = await getVisibleRoundResults(round.id);
    expect(view).toEqual({ released: false, results: [], embargoedSpeakerIds: [] });
  });

  it("shows released results but withholds an actively embargoed speaker", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const visible = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const hidden = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    await prisma.roundResult.createMany({
      data: [
        { roundId: round.id, speakerId: visible.id, roundScore: 90, rank: 1 },
        { roundId: round.id, speakerId: hidden.id, roundScore: 85, rank: 2 },
      ],
    });
    await placeEmbargo(round.id, hidden.id, fixture.ownerId, "under review");
    await releaseResults(round.id, fixture.ownerId);

    const view = await getVisibleRoundResults(round.id);
    expect(view.released).toBe(true);
    expect(view.results.map((r) => r.speakerId)).toEqual([visible.id]);
    expect(view.embargoedSpeakerIds).toEqual([hidden.id]);
  });

  it("shows a result again once its embargo is lifted", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    await prisma.roundResult.create({
      data: { roundId: round.id, speakerId: speaker.id, roundScore: 90, rank: 1 },
    });
    const embargo = await placeEmbargo(round.id, speaker.id, fixture.ownerId);
    await releaseResults(round.id, fixture.ownerId);

    expect((await getVisibleRoundResults(round.id)).results).toEqual([]);

    await liftEmbargo(embargo.id, fixture.ownerId);
    const view = await getVisibleRoundResults(round.id);
    expect(view.results.map((r) => r.speakerId)).toEqual([speaker.id]);
  });

  it("refuses to lift the same embargo twice", async () => {
    fixture = await createFixture();
    const round = await makeRound(fixture.divisionId);
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const embargo = await placeEmbargo(round.id, speaker.id, fixture.ownerId);
    await liftEmbargo(embargo.id, fixture.ownerId);
    await expect(liftEmbargo(embargo.id, fixture.ownerId)).rejects.toThrow("already been lifted");
  });
});

describe("getVisibleStandings", () => {
  it("returns unreleased when no round's standings gate has released", async () => {
    fixture = await createFixture();
    await makeRound(fixture.divisionId);
    expect(await getVisibleStandings(fixture.divisionId)).toEqual({ released: false });
  });

  it("aggregates only released-results rounds up to the latest released-standings round, excluding embargoed speakers", async () => {
    fixture = await createFixture();
    const speaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);
    const withheldSpeaker = await makeSpeaker(fixture.tournamentId, fixture.divisionId);

    const round1 = await makeRound(fixture.divisionId, { roundNumber: 1 });
    await prisma.roundResult.createMany({
      data: [
        { roundId: round1.id, speakerId: speaker.id, roundScore: 80, rank: 1 },
        { roundId: round1.id, speakerId: withheldSpeaker.id, roundScore: 70, rank: 2 },
      ],
    });
    await releaseResults(round1.id, fixture.ownerId);
    await releaseStandings(round1.id, fixture.ownerId);

    const round2 = await makeRound(fixture.divisionId, { roundNumber: 2 });
    await prisma.roundResult.create({
      data: { roundId: round2.id, speakerId: speaker.id, roundScore: 85, rank: 1 },
    });
    // round2's results are NOT released — must not leak into the standings total.
    await placeEmbargo(round1.id, withheldSpeaker.id, fixture.ownerId);

    const view = await getVisibleStandings(fixture.divisionId);
    expect(view.released).toBe(true);
    if (!view.released) throw new Error("expected released standings");
    expect(view.asOfRoundNumber).toBe(1);
    expect(view.standings).toEqual([
      { speakerId: speaker.id, cumulativeScore: 80, roundsCounted: 1 },
    ]);
    expect(view.withheldSpeakerIds).toEqual([withheldSpeaker.id]);
  });
});
