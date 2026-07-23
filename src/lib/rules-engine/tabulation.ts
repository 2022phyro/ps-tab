// docs/01-tournament-mechanics.md §7 — tabulation & tie-breaking hierarchy.

export interface RoundResultInput {
  speakerId: string;
  rank: number;
  roundScore: number;
}

export interface StandingRow {
  speakerId: string;
  totalRanks: number;
  totalPoints: number;
  adjustedRanks: number;
  roundsPlayed: number;
}

export function computeStandings(results: RoundResultInput[]): StandingRow[] {
  const bySpeaker = new Map<string, RoundResultInput[]>();
  for (const r of results) {
    const list = bySpeaker.get(r.speakerId) ?? [];
    list.push(r);
    bySpeaker.set(r.speakerId, list);
  }

  const rows: StandingRow[] = [];
  for (const [speakerId, rounds] of bySpeaker) {
    const totalRanks = rounds.reduce((sum, r) => sum + r.rank, 0);
    const totalPoints = rounds.reduce((sum, r) => sum + r.roundScore, 0);
    const worstRank = Math.max(...rounds.map((r) => r.rank));
    const droppedOnce = totalRanks - worstRank;
    rows.push({
      speakerId,
      totalRanks,
      totalPoints,
      adjustedRanks: rounds.length > 1 ? droppedOnce : totalRanks,
      roundsPlayed: rounds.length,
    });
  }
  return rows;
}

/** Priority matrix: Total Ranks (asc) -> Total Points (desc) -> Adjusted Ranks (asc).
 *  Negative means `a` ranks better than `b`. */
export function compareStandings(a: StandingRow, b: StandingRow): number {
  if (a.totalRanks !== b.totalRanks) return a.totalRanks - b.totalRanks;
  if (a.totalPoints !== b.totalPoints) return b.totalPoints - a.totalPoints;
  return a.adjustedRanks - b.adjustedRanks;
}

export function sortStandings(rows: StandingRow[]): StandingRow[] {
  return [...rows].sort(compareStandings);
}
