// docs/02-judging-contingencies.md §6 — live scoring calibration. Flags a
// judge whose speaker-by-speaker ranking diverges sharply from the rest of
// the panel's ranking for the same room. A review prompt for tab staff, per
// the doc — this module only detects, it never adjusts a score.

export interface JudgeRanking {
  judgeId: string;
  /** speakerId -> this judge's rank for that speaker within the room (1 = best). */
  ranks: Record<string, number>;
}

export interface CalibrationFlag {
  judgeId: string;
  /** Spearman correlation against the rest of the panel's consensus rank order. */
  correlation: number;
}

/** Dense rank with ties receiving the average of the ranks they'd span. */
function toRanks(values: number[]): number[] {
  const indexed = values.map((value, index) => ({ value, index }));
  indexed.sort((a, b) => a.value - b.value);

  const ranks = new Array<number>(values.length);
  let i = 0;
  while (i < indexed.length) {
    let j = i;
    while (j + 1 < indexed.length && indexed[j + 1]!.value === indexed[i]!.value) j++;
    const averageRank = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) ranks[indexed[k]!.index] = averageRank;
    i = j + 1;
  }
  return ranks;
}

/** Pearson correlation of the two sequences' ranks — i.e. Spearman's rho. */
export function spearmanCorrelation(a: number[], b: number[]): number {
  if (a.length !== b.length || a.length === 0) {
    throw new Error("spearmanCorrelation requires two equal-length, non-empty sequences");
  }
  const ra = toRanks(a);
  const rb = toRanks(b);
  const n = ra.length;
  const meanA = ra.reduce((s, v) => s + v, 0) / n;
  const meanB = rb.reduce((s, v) => s + v, 0) / n;

  let cov = 0;
  let varA = 0;
  let varB = 0;
  for (let i = 0; i < n; i++) {
    const da = ra[i]! - meanA;
    const db = rb[i]! - meanB;
    cov += da * db;
    varA += da * da;
    varB += db * db;
  }
  if (varA === 0 || varB === 0) return 1; // every judge ranked everyone identically (or degenerate n=1) — not a divergence
  return cov / Math.sqrt(varA * varB);
}

/**
 * For each judge with at least one other judge to compare against, correlate
 * their ranking against the *others'* consensus (mean rank across everyone
 * else, for the same speaker set) and flag those below `threshold`. A single
 * judge (no one to compare against) never gets flagged — there's nothing to
 * diverge from.
 */
export function detectCalibrationOutliers(
  rankings: JudgeRanking[],
  threshold = 0.3,
): CalibrationFlag[] {
  if (rankings.length < 2) return [];

  const speakerIds = Object.keys(rankings[0]!.ranks);
  const flags: CalibrationFlag[] = [];

  for (const judge of rankings) {
    const others = rankings.filter((r) => r.judgeId !== judge.judgeId);
    const consensus = speakerIds.map(
      (id) => others.reduce((sum, o) => sum + o.ranks[id]!, 0) / others.length,
    );
    const own = speakerIds.map((id) => judge.ranks[id]!);

    const correlation = spearmanCorrelation(own, consensus);
    if (correlation < threshold) {
      flags.push({ judgeId: judge.judgeId, correlation });
    }
  }

  return flags;
}
