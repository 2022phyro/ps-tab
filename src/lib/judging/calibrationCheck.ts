// docs/02-judging-contingencies.md §6 — live scoring calibration. Runs after
// a ballot submission, ranking each submitted judge's speaker order within
// the room and flagging anyone whose ranking diverges sharply from the rest
// of the panel — a review prompt for tab staff, never an automatic rescore.

import { prisma } from "@/lib/prisma";
import { detectCalibrationOutliers, type JudgeRanking } from "@/lib/rules-engine/calibration";

export interface CalibrationCheckResult {
  flaggedJudgeIds: string[];
}

/** Ranks speakers 1 (best) upward by this judge's cached judgeTotal — ties
 *  get the same (average) rank, matching computeRanks' fractional method. */
function rankByJudgeTotal(
  entries: { speakerId: string; judgeTotal: number }[],
): Record<string, number> {
  const sorted = [...entries].sort((a, b) => b.judgeTotal - a.judgeTotal);
  const ranks: Record<string, number> = {};
  let i = 0;
  while (i < sorted.length) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1]!.judgeTotal === sorted[i]!.judgeTotal) j++;
    const averageRank = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) ranks[sorted[k]!.speakerId] = averageRank;
    i = j + 1;
  }
  return ranks;
}

/**
 * Re-derives every judge's ranking of the speakers *they've fully scored* in
 * this room from cached `Ballot.judgeTotal`, then flags outliers. Only judges
 * who scored every speaker the section actually has (partial ballots
 * excluded — an incomplete ranking isn't comparable) are included; if fewer
 * than 2 such judges exist there's nothing to compare, per docs/02 §6.
 */
export async function runCalibrationCheck(sectionId: string): Promise<CalibrationCheckResult> {
  const section = await prisma.section.findUniqueOrThrow({
    where: { id: sectionId },
    include: { assignments: true, ballots: true },
  });
  const speakerIds = section.assignments.map((a) => a.speakerId);

  const byJudge = new Map<string, { speakerId: string; judgeTotal: number }[]>();
  for (const ballot of section.ballots) {
    if (ballot.isPartial || ballot.judgeTotal === null || !ballot.submittedAt) continue;
    const list = byJudge.get(ballot.judgeId) ?? [];
    list.push({ speakerId: ballot.speakerId, judgeTotal: ballot.judgeTotal });
    byJudge.set(ballot.judgeId, list);
  }

  const rankings: JudgeRanking[] = [];
  for (const [judgeId, entries] of byJudge) {
    if (entries.length !== speakerIds.length) continue; // incomplete — not comparable
    rankings.push({ judgeId, ranks: rankByJudgeTotal(entries) });
  }

  const outliers = detectCalibrationOutliers(rankings);
  const flaggedJudgeIds = outliers.map((o) => o.judgeId);

  if (flaggedJudgeIds.length > 0) {
    await prisma.ballot.updateMany({
      where: { sectionId, judgeId: { in: flaggedJudgeIds } },
      data: { calibrationFlag: true },
    });
  }

  return { flaggedJudgeIds };
}
