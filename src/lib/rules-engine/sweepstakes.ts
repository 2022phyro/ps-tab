// docs/01-tournament-mechanics.md §12 — institutional sweepstakes & team scoring.
// A read-only derived view — never feeds back into individual standings.

export interface SweepstakesEntrant {
  speakerId: string;
  institutionId: string | null;
  totalPoints: number;
  rank: number;
}

export type SweepstakesRule =
  { type: "top-k-sum"; k: number } | { type: "placement-scale"; scale: Map<number, number> };

export function computeSweepstakes(
  entrants: SweepstakesEntrant[],
  rule: SweepstakesRule,
): Map<string, number> {
  const byInstitution = new Map<string, SweepstakesEntrant[]>();
  for (const e of entrants) {
    if (e.institutionId === null) continue;
    const list = byInstitution.get(e.institutionId) ?? [];
    list.push(e);
    byInstitution.set(e.institutionId, list);
  }

  const scores = new Map<string, number>();
  for (const [institutionId, roster] of byInstitution) {
    if (rule.type === "top-k-sum") {
      const topK = [...roster].sort((a, b) => b.totalPoints - a.totalPoints).slice(0, rule.k);
      scores.set(
        institutionId,
        topK.reduce((sum, e) => sum + e.totalPoints, 0),
      );
    } else {
      const total = roster.reduce((sum, e) => sum + (rule.scale.get(e.rank) ?? 0), 0);
      scores.set(institutionId, total);
    }
  }
  return scores;
}
