// docs/02-judging-contingencies.md §7 — judge feedback & judge breaks.
// Speakers rate their judge, panelists rate each other; the cumulative
// average across rounds decides which judges are eligible to judge
// outrounds — the same shape of problem as speaker breaks (docs/01 §7-8),
// adapted for a different underlying metric (a single average score rather
// than a ranks/points/adjusted-ranks hierarchy), so it's a parallel
// implementation rather than a literal reuse of applyBreak.

export interface JudgeFeedbackEntry {
  ratedJudgeId: string;
  score: number;
}

export interface JudgeFeedbackStanding {
  judgeId: string;
  averageScore: number;
  feedbackCount: number;
}

export function computeJudgeFeedbackAverages(
  entries: JudgeFeedbackEntry[],
): JudgeFeedbackStanding[] {
  const byJudge = new Map<string, number[]>();
  for (const e of entries) {
    const list = byJudge.get(e.ratedJudgeId) ?? [];
    list.push(e.score);
    byJudge.set(e.ratedJudgeId, list);
  }

  return [...byJudge.entries()].map(([judgeId, scores]) => ({
    judgeId,
    averageScore: scores.reduce((a, b) => a + b, 0) / scores.length,
    feedbackCount: scores.length,
  }));
}

/** docs/02 §6 tie-break hierarchy: higher cumulative average wins; ties
 *  broken by who's accumulated more feedback (rewards a proven track record
 *  over a thin sample size that got lucky). */
export function compareJudgeStandings(a: JudgeFeedbackStanding, b: JudgeFeedbackStanding): number {
  if (a.averageScore !== b.averageScore) return b.averageScore - a.averageScore;
  return b.feedbackCount - a.feedbackCount;
}

export function sortJudgeStandings(standings: JudgeFeedbackStanding[]): JudgeFeedbackStanding[] {
  return [...standings].sort(compareJudgeStandings);
}

export interface JudgeBreakResult {
  breakingJudges: JudgeFeedbackStanding[];
  flagged: boolean;
  flagReason?: string;
}

/** docs/02 §6 — which judges are eligible to judge outrounds, by cumulative feedback. */
export function applyJudgeBreak(
  standings: JudgeFeedbackStanding[],
  count: number,
  options: { includeTies?: boolean } = {},
): JudgeBreakResult {
  const sorted = sortJudgeStandings(standings);
  const fieldSize = sorted.length;

  let flagged = false;
  let flagReason: string | undefined;
  let effectiveCount = count;

  if (effectiveCount > fieldSize) {
    flagged = true;
    flagReason = `Judge break threshold (${count}) exceeds the number of judges with feedback (${fieldSize}); clamped to all of them.`;
    effectiveCount = fieldSize;
  }

  const includeTies = options.includeTies ?? true;
  let cutoff = effectiveCount;
  if (includeTies && effectiveCount > 0 && effectiveCount < fieldSize) {
    const boundary = sorted[effectiveCount - 1]!;
    while (cutoff < fieldSize && compareJudgeStandings(sorted[cutoff]!, boundary) === 0) {
      cutoff++;
    }
  }

  return { breakingJudges: sorted.slice(0, cutoff), flagged, flagReason };
}
