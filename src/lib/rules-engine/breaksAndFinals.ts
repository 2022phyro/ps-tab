// docs/01-tournament-mechanics.md §8 (break/finals generation) and §11
// (multi-stage elimination is just this same pipeline, chained).

import { compareStandings, sortStandings, type StandingRow } from "./tabulation";

export type BreakConfig =
  | { type: "FIXED_COUNT"; count: number; includeTies?: boolean }
  | { type: "PERCENTAGE"; percentage: number; includeTies?: boolean }
  | { type: "RANK_FLOOR"; rankFloor: number; includeTies?: boolean };

export interface BreakResult {
  qualifiers: StandingRow[];
  flagged: boolean;
  flagReason?: string;
}

function targetCount(config: BreakConfig, fieldSize: number): number {
  switch (config.type) {
    case "FIXED_COUNT":
      return config.count;
    case "PERCENTAGE":
      return Math.ceil((config.percentage / 100) * fieldSize);
    case "RANK_FLOOR":
      // "break everyone at or better than rank X" is the same cutoff mechanic
      // as a fixed count, just framed as a floor position rather than a raw number.
      return config.rankFloor;
  }
}

/** docs/01 §8 — applies a break threshold to final standings, producing the finals roster. */
export function applyBreak(standings: StandingRow[], config: BreakConfig): BreakResult {
  const sorted = sortStandings(standings);
  const fieldSize = sorted.length;
  let count = targetCount(config, fieldSize);

  let flagged = false;
  let flagReason: string | undefined;

  // docs/01 §14 — a division smaller than its own configured break count
  // clamps to the field size rather than trying to break more than exist.
  if (count > fieldSize) {
    flagged = true;
    flagReason = `Break threshold (${count}) exceeds the field size (${fieldSize}); clamped to the full field.`;
    count = fieldSize;
  }

  const includeTies = config.includeTies ?? true;
  let cutoff = count;
  if (includeTies && count > 0 && count < fieldSize) {
    const boundary = sorted[count - 1]!;
    while (cutoff < fieldSize && compareStandings(sorted[cutoff]!, boundary) === 0) {
      cutoff++;
    }
  }

  return { qualifiers: sorted.slice(0, cutoff), flagged, flagReason };
}
