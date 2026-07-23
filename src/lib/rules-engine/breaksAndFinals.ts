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

/**
 * docs/01 §8 — a break's threshold is normally a tournament/division default
 * decided ahead of time, but tab staff can override it for one specific
 * stage at the moment that stage is actually run (e.g. "we planned top 8 to
 * quarters, but the field's bigger than expected — break top 6 instead just
 * this once"). `applyBreak`/`splitForPartialBreak` never care which config
 * they were handed; this just makes the "default vs. this-run override"
 * decision an explicit, testable step instead of leaving it implicit in
 * whatever the caller happens to pass.
 */
export function resolveBreakConfig(
  defaultConfig: BreakConfig,
  override?: BreakConfig,
): BreakConfig {
  return override ?? defaultConfig;
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

// ---------------------------------------------------------------------------
// Partial breaks (docs/01 §8) — top finishers *per room* auto-advance; the
// rest of each room's eligible finishers compete in a bubble round, whose
// results fill whatever slots remain in the next stage.
// ---------------------------------------------------------------------------

export interface RoomLocalResult {
  speakerId: string;
  roomLabel: string;
  /** this speaker's placement within their own room only, 1 = best. */
  roomRank: number;
}

export interface PartialBreakConfig {
  /** top N per room advance automatically, e.g. 2. */
  autoAdvanceCount: number;
  /** inclusive room-rank range that must instead win the bubble round, e.g. [3, 6]. */
  bubbleRangeStart: number;
  bubbleRangeEnd: number;
}

export interface PartialBreakSplit {
  autoQualifiers: string[];
  bubblePool: string[];
  /** room-ranks below bubbleRangeEnd — not competing further this stage. */
  eliminated: string[];
}

/** Same point-in-time override pattern as resolveBreakConfig, but field-level
 *  since PartialBreakConfig is a plain shape, not a discriminated union —
 *  staff can override just autoAdvanceCount for this run and keep the
 *  configured bubble range, for example. */
export function resolvePartialBreakConfig(
  defaultConfig: PartialBreakConfig,
  override?: Partial<PartialBreakConfig>,
): PartialBreakConfig {
  return { ...defaultConfig, ...override };
}

/** docs/01 §8 — splits one outround's rooms into automatic advancers and the bubble pool. */
export function splitForPartialBreak(
  results: RoomLocalResult[],
  config: PartialBreakConfig,
): PartialBreakSplit {
  const autoQualifiers: string[] = [];
  const bubblePool: string[] = [];
  const eliminated: string[] = [];

  for (const r of results) {
    if (r.roomRank <= config.autoAdvanceCount) {
      autoQualifiers.push(r.speakerId);
    } else if (r.roomRank >= config.bubbleRangeStart && r.roomRank <= config.bubbleRangeEnd) {
      bubblePool.push(r.speakerId);
    } else {
      eliminated.push(r.speakerId);
    }
  }

  return { autoQualifiers, bubblePool, eliminated };
}

export interface BubbleRoundResult {
  speakerId: string;
  rank: number;
}

export interface PartialBreakResolution {
  qualifiers: string[];
  flagged: boolean;
  flagReason?: string;
}

/**
 * docs/01 §8 — once the bubble round (from splitForPartialBreak's bubblePool)
 * has actually been played, this merges its survivors with the automatic
 * advancers to produce the next stage's full roster.
 */
export function resolvePartialBreak(
  autoQualifiers: string[],
  bubbleRoundResults: BubbleRoundResult[],
  totalSlotsNeeded: number,
  options: { includeTies?: boolean } = {},
): PartialBreakResolution {
  const additionalNeeded = totalSlotsNeeded - autoQualifiers.length;

  if (additionalNeeded <= 0) {
    return {
      qualifiers: autoQualifiers,
      flagged: additionalNeeded < 0,
      flagReason:
        additionalNeeded < 0
          ? `Automatic advancers (${autoQualifiers.length}) already exceed the slots needed (${totalSlotsNeeded}).`
          : undefined,
    };
  }

  const sorted = [...bubbleRoundResults].sort((a, b) => a.rank - b.rank);
  let flagged = false;
  let flagReason: string | undefined;
  let count = additionalNeeded;

  if (count > sorted.length) {
    flagged = true;
    flagReason = `Bubble round pool (${sorted.length}) is smaller than the slots it needed to fill (${additionalNeeded}); clamped to the full pool.`;
    count = sorted.length;
  }

  const includeTies = options.includeTies ?? true;
  let cutoff = count;
  if (includeTies && count > 0 && count < sorted.length) {
    const boundaryRank = sorted[count - 1]!.rank;
    while (cutoff < sorted.length && sorted[cutoff]!.rank === boundaryRank) {
      cutoff++;
    }
  }

  const bubbleQualifiers = sorted.slice(0, cutoff).map((r) => r.speakerId);
  return { qualifiers: [...autoQualifiers, ...bubbleQualifiers], flagged, flagReason };
}
