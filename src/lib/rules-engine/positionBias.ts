// docs/01-tournament-mechanics.md §6 — speaking-order position-bias balancing.

export interface SpeakerHistory {
  speakerId: string;
  /** positions drawn in every prior round, earliest first. */
  positionHistory: number[];
}

/** weight(1)=3, weight(2)=2, weight(3)=1, weight(4+)=0 — docs/01 §6 default. */
export const DEFAULT_POSITION_WEIGHTS: Readonly<Record<number, number>> = { 1: 3, 2: 2, 3: 1 };

export function computeBiasScore(
  positionHistory: number[],
  weights: Readonly<Record<number, number>> = DEFAULT_POSITION_WEIGHTS,
): number {
  return positionHistory.reduce((sum, position) => sum + (weights[position] ?? 0), 0);
}

/**
 * Speakers with the highest bias score (most front-loaded history) get pushed
 * to the latest available positions this round. Room assignment (§5) is
 * decided independently and first; this only orders slots within one room.
 */
export function assignSpeakingOrder(
  roomSpeakers: SpeakerHistory[],
  weights: Readonly<Record<number, number>> = DEFAULT_POSITION_WEIGHTS,
): Map<string, number> {
  const n = roomSpeakers.length;
  const sorted = [...roomSpeakers].sort(
    (a, b) =>
      computeBiasScore(b.positionHistory, weights) - computeBiasScore(a.positionHistory, weights),
  );

  const assignment = new Map<string, number>();
  sorted.forEach((speaker, i) => {
    assignment.set(speaker.speakerId, n - i);
  });
  return assignment;
}
