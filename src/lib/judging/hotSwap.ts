// docs/02-judging-contingencies.md §3 — instant hot-swapping. A single
// guided action: candidates are checked-in idle reserves only, the clash
// check is re-run automatically (never silently ignored, only ever
// overridden with an explicit acknowledgement), and the swap is audit-logged
// with who/when/why.

import { prisma } from "@/lib/prisma";
import { writeAuditLog } from "@/lib/audit/log";
import {
  hasClash,
  type JudgeForAllocation,
  type SectionForJudgeAllocation,
} from "@/lib/rules-engine/judgeAllocation";
import { getIdleCheckedInReserves } from "./reservePool";

export interface HotSwapCandidate {
  judgeId: string;
  name: string;
  clashFlag: boolean;
}

async function buildSectionForClashCheck(sectionId: string): Promise<SectionForJudgeAllocation> {
  const section = await prisma.section.findUniqueOrThrow({
    where: { id: sectionId },
    include: { assignments: { include: { speaker: true } } },
  });
  return {
    sectionId: section.id,
    speakerInstitutionIds: section.assignments.map((a) => a.speaker.institutionId),
    panelSize: 0, // unused by hasClash — only the assignment loop in allocateJudges needs it
  };
}

/** docs/02 §3 step 2 — only checked-in, currently-idle reserves are offered;
 *  each is annotated with the same institutional-clash check step 3 re-runs. */
export async function getHotSwapCandidates(sectionId: string): Promise<HotSwapCandidate[]> {
  const section = await prisma.section.findUniqueOrThrow({ where: { id: sectionId } });
  const [reserves, sectionForClash] = await Promise.all([
    getIdleCheckedInReserves(section.roundId),
    buildSectionForClashCheck(sectionId),
  ]);

  return reserves.map((judge) => {
    const judgeForClash: JudgeForAllocation = {
      judgeId: judge.id,
      institutionId: judge.institutionId,
      chairEligible: judge.chairEligible,
    };
    return {
      judgeId: judge.id,
      name: judge.name,
      clashFlag: hasClash(judgeForClash, sectionForClash),
    };
  });
}

export interface HotSwapResult {
  clashFlag: boolean;
  panelId: string;
}

/**
 * docs/02 §3 — replaces `outgoingJudgeId` on `sectionId` with `incomingJudgeId`
 * (must be a checked-in, currently-idle reserve). Accepts a clash rather than
 * blocking if `acknowledgeClash` is true — mirrors "staff can still override a
 * warned pick if it's the only option, but never silently": a clash without
 * acknowledgement throws instead of proceeding quietly.
 */
export async function hotSwapJudge(
  sectionId: string,
  outgoingJudgeId: string,
  incomingJudgeId: string,
  performedByUserId: string,
  options: { reason?: string; acknowledgeClash?: boolean } = {},
): Promise<HotSwapResult> {
  const candidates = await getHotSwapCandidates(sectionId);
  const candidate = candidates.find((c) => c.judgeId === incomingJudgeId);
  if (!candidate) {
    throw new Error(
      `Judge ${incomingJudgeId} is not a checked-in, idle reserve for this round — not a valid hot-swap candidate`,
    );
  }
  if (candidate.clashFlag && !options.acknowledgeClash) {
    throw new Error(
      `Judge ${incomingJudgeId} has an institutional clash in this room — pass acknowledgeClash: true to proceed anyway`,
    );
  }

  const section = await prisma.section.findUniqueOrThrow({
    where: { id: sectionId },
    include: { round: { include: { division: true } } },
  });
  const outgoing = await prisma.panel.findUniqueOrThrow({
    where: { sectionId_judgeId: { sectionId, judgeId: outgoingJudgeId } },
  });

  const panel = await prisma.$transaction(async (tx) => {
    await tx.panel.update({
      where: { sectionId_judgeId: { sectionId, judgeId: outgoingJudgeId } },
      data: { status: "REMOVED_FOR_CONFLICT" },
    });

    const created = await tx.panel.create({
      data: {
        sectionId,
        judgeId: incomingJudgeId,
        isChair: outgoing.isChair,
        status: "DEPLOYED_RESERVE",
        swappedFromJudgeId: outgoingJudgeId,
        swappedAt: new Date(),
      },
    });

    await writeAuditLog(tx, {
      actorUserId: performedByUserId,
      actionType: "judge_hotswap",
      summary: `Hot-swapped judge ${outgoingJudgeId} for reserve ${incomingJudgeId} in section ${sectionId}`,
      tournamentId: section.round.division.tournamentId,
      reason: options.reason,
      before: { judgeId: outgoingJudgeId },
      after: { judgeId: incomingJudgeId, clashFlag: candidate.clashFlag },
    });

    return created;
  });

  return { clashFlag: candidate.clashFlag, panelId: panel.id };
}
