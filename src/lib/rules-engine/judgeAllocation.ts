// docs/02-judging-contingencies.md §1 — initial judge-to-panel allocation.
// docs/02 as originally written only covered *contingencies* (reserves,
// no-shows, hot-swaps) once judges are already on a panel — it never
// actually described how the initial assignment happens. This fills that
// gap: hard-filter by institutional clash, weight for chair-eligibility on
// the first slot, then randomize among whatever's left, mirroring the same
// "flag rather than silently fail" philosophy as sectionAllocation.ts (§5).

export interface JudgeForAllocation {
  judgeId: string;
  institutionId: string | null;
  chairEligible: boolean;
}

export interface SectionForJudgeAllocation {
  sectionId: string;
  /** institutions represented by speakers already placed in this room. */
  speakerInstitutionIds: (string | null)[];
  panelSize: number;
}

export interface JudgeAllocationResult {
  /** sectionId -> assigned judgeIds; index 0 is the chair when panelSize > 0. */
  assignments: Map<string, string[]>;
  /** sectionId -> true if no clash-free judge remained and one had to be accepted anyway. */
  clashFlags: Map<string, boolean>;
}

function shuffle<T>(items: T[], random: () => number): T[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    const temp = copy[i]!;
    copy[i] = copy[j]!;
    copy[j] = temp;
  }
  return copy;
}

/** exported for reuse by docs/02 §3's hot-swap re-check ("automatically
 *  re-runs the institutional-conflict check") — same clash logic, not a
 *  reimplementation. */
export function hasClash(judge: JudgeForAllocation, section: SectionForJudgeAllocation): boolean {
  return (
    judge.institutionId !== null && section.speakerInstitutionIds.includes(judge.institutionId)
  );
}

function pickCandidateIndex(
  pool: JudgeForAllocation[],
  section: SectionForJudgeAllocation,
  wantsChairEligible: boolean,
): { index: number; clashed: boolean } | null {
  if (wantsChairEligible) {
    const idx = pool.findIndex((j) => !hasClash(j, section) && j.chairEligible);
    if (idx !== -1) return { index: idx, clashed: false };
  }

  const clashFreeIdx = pool.findIndex((j) => !hasClash(j, section));
  if (clashFreeIdx !== -1) return { index: clashFreeIdx, clashed: false };

  // no clash-free candidate remains — accept a clash rather than leave the
  // slot empty, preferring chair-eligibility on the first slot even then.
  if (wantsChairEligible) {
    const chairIdx = pool.findIndex((j) => j.chairEligible);
    if (chairIdx !== -1) return { index: chairIdx, clashed: true };
  }
  if (pool.length > 0) return { index: 0, clashed: true };
  return null;
}

/**
 * Assigns judges to sections for one round. Sections are processed in the
 * order given, each drawing from a shared, pre-shuffled pool so no judge is
 * ever assigned to two sections in the same round. If the pool runs out
 * entirely, a section's assignment array comes back shorter than its
 * panelSize (docs/02 §4's degraded-panel case) — this never throws, it just
 * returns what it could fill.
 */
export function allocateJudges(
  judges: JudgeForAllocation[],
  sections: SectionForJudgeAllocation[],
  random: () => number = Math.random,
): JudgeAllocationResult {
  const pool = shuffle(judges, random);
  const assignments = new Map<string, string[]>();
  const clashFlags = new Map<string, boolean>();

  for (const section of sections) {
    const assigned: string[] = [];
    let clashed = false;

    for (let slot = 0; slot < section.panelSize; slot++) {
      const picked = pickCandidateIndex(pool, section, slot === 0);
      if (!picked) break;
      const [judge] = pool.splice(picked.index, 1);
      assigned.push(judge!.judgeId);
      if (picked.clashed) clashed = true;
    }

    assignments.set(section.sectionId, assigned);
    clashFlags.set(section.sectionId, clashed);
  }

  return { assignments, clashFlags };
}
