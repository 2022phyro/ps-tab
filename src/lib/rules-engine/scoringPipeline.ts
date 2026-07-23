// docs/01-tournament-mechanics.md §4 — score aggregation pipeline.

export interface JudgeScore {
  judgeId: string;
  criteriaScores: number[];
  timePenalty: number;
}

export function computeJudgeTotal(score: JudgeScore): number {
  const sum = score.criteriaScores.reduce((a, b) => a + b, 0);
  return sum - score.timePenalty;
}

/** Panel average — degenerates gracefully to a single judge's total when J=1 (docs/01 §14). */
export function computeRoundScore(judgeScores: JudgeScore[]): number {
  if (judgeScores.length === 0) {
    throw new Error("computeRoundScore requires at least one judge score");
  }
  const totals = judgeScores.map(computeJudgeTotal);
  return totals.reduce((a, b) => a + b, 0) / totals.length;
}

export interface SpeakerRoundScore {
  speakerId: string;
  roundScore: number;
}

export interface RankOptions {
  /** "fractional" (default): tied speakers share the average of the positions they occupy.
   *  "whole": every speaker gets a distinct integer rank, ties broken by tieBreakOrder. */
  method?: "fractional" | "whole";
  /** Only used for method "whole" — orders speakers tied on roundScore. Earlier = better. */
  tieBreakOrder?: (a: SpeakerRoundScore, b: SpeakerRoundScore) => number;
}

/** Ranks are computed per section, per round — never compared across sections (docs/01 §4). */
export function computeRanks(
  scores: SpeakerRoundScore[],
  options: RankOptions = {},
): Map<string, number> {
  const method = options.method ?? "fractional";
  const sorted = [...scores].sort((a, b) => {
    if (b.roundScore !== a.roundScore) return b.roundScore - a.roundScore;
    return options.tieBreakOrder?.(a, b) ?? 0;
  });

  const ranks = new Map<string, number>();

  if (method === "whole") {
    sorted.forEach((s, i) => ranks.set(s.speakerId, i + 1));
    return ranks;
  }

  // fractional: group consecutive equal-score speakers, assign the average
  // of their occupied positions to every member of the group.
  let i = 0;
  while (i < sorted.length) {
    let j = i;
    while (j < sorted.length && sorted[j]!.roundScore === sorted[i]!.roundScore) j++;
    const positions = Array.from({ length: j - i }, (_, k) => i + k + 1);
    const avg = positions.reduce((a, b) => a + b, 0) / positions.length;
    for (let m = i; m < j; m++) ranks.set(sorted[m]!.speakerId, avg);
    i = j;
  }
  return ranks;
}
