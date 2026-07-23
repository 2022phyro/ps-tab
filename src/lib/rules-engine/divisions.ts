// docs/01-tournament-mechanics.md §9 — divisions & eligibility.
//
// Division assignment itself is a roster attribute checked at ingestion, not
// something the rules engine computes (docs/01 §9). What the engine is
// responsible for is making sure every other module (room sizing, section
// allocation, position bias, tabulation, breaks) only ever operates on one
// division's data at a time — this is the partitioning helper that enforces
// that boundary, plus the one genuinely cross-division concern: an optional
// award computed after each division's own standings are already final.

export function partitionByDivision<T extends { divisionId: string }>(
  items: T[],
): Map<string, T[]> {
  const byDivision = new Map<string, T[]>();
  for (const item of items) {
    const list = byDivision.get(item.divisionId) ?? [];
    list.push(item);
    byDivision.set(item.divisionId, list);
  }
  return byDivision;
}

/** docs/01 §9 — cross-division awards read each division's final standings but never feed back into them. */
export function computeCrossDivisionAward<T>(
  standingsByDivision: Map<string, T[]>,
  pickBest: (rows: T[]) => T | undefined,
): T[] {
  const winners: T[] = [];
  for (const rows of standingsByDivision.values()) {
    const winner = pickBest(rows);
    if (winner) winners.push(winner);
  }
  return winners;
}
