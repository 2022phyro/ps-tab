// docs/02-judging-contingencies.md §4 — degraded panel fallbacks, wrapping
// the pure resolvePanelSize decision with real Panel counts and Division
// config, plus partial-ballot preservation for a judge who leaves mid-round.

import { prisma } from "@/lib/prisma";
import { resolvePanelSize, type PanelSizeResolution } from "@/lib/rules-engine/panelDegradation";

const ACTIVE_PANEL_STATUSES = ["ASSIGNED", "CHECKED_IN", "DEPLOYED_RESERVE"] as const;

export interface SectionPanelStatus extends PanelSizeResolution {
  configuredSize: number;
  minimumPanelSize: number;
}

/** docs/02 §4 — "flagged in standings and in the public results view":
 *  derived at read time from the actual (non-removed) Panel count against
 *  the Division's configured target/floor, never a stored flag to drift. */
export async function checkPanelStatus(sectionId: string): Promise<SectionPanelStatus> {
  const section = await prisma.section.findUniqueOrThrow({
    where: { id: sectionId },
    include: { round: { include: { division: true } }, panels: true },
  });
  const available = section.panels.filter((p) =>
    (ACTIVE_PANEL_STATUSES as readonly string[]).includes(p.status),
  ).length;

  const resolution = resolvePanelSize(
    section.round.division.panelSize,
    available,
    section.round.division.minimumPanelSize,
  );

  return {
    ...resolution,
    configuredSize: section.round.division.panelSize,
    minimumPanelSize: section.round.division.minimumPanelSize,
  };
}

/**
 * docs/02 §4 — a judge starts scoring, then has to leave before finishing
 * the room. `reachedSpeakerIds` are the speakers they already scored
 * (untouched); for everyone else in the room, this writes an explicit
 * `isPartial` placeholder Ballot (no scores, submittedAt null) rather than
 * just leaving an absent row — the gap is recorded, not implied. The Panel
 * row is marked LEFT_MID_ROUND, distinct from NO_SHOW (never arrived) and
 * REMOVED_FOR_CONFLICT (swapped out for a clash).
 */
export async function markJudgeDepartedMidRound(
  sectionId: string,
  judgeId: string,
  reachedSpeakerIds: string[],
): Promise<{ unreachedSpeakerIds: string[] }> {
  const section = await prisma.section.findUniqueOrThrow({
    where: { id: sectionId },
    include: { assignments: true },
  });
  const unreached = section.assignments
    .map((a) => a.speakerId)
    .filter((id) => !reachedSpeakerIds.includes(id));

  await prisma.$transaction([
    prisma.panel.update({
      where: { sectionId_judgeId: { sectionId, judgeId } },
      data: { status: "LEFT_MID_ROUND" },
    }),
    ...unreached.map((speakerId) =>
      prisma.ballot.upsert({
        where: { sectionId_judgeId_speakerId: { sectionId, judgeId, speakerId } },
        create: { sectionId, judgeId, speakerId, isPartial: true, submittedAt: null },
        update: { isPartial: true, submittedAt: null },
      }),
    ),
  ]);

  return { unreachedSpeakerIds: unreached };
}
