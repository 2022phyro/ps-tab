// docs/01-tournament-mechanics.md §5 — section allocation & institutional spreading.

export interface SpeakerForAllocation {
  speakerId: string;
  institutionId: string | null;
}

export interface AllocationResult {
  /** rooms[i] is the list of speakerIds placed in room i, in room-size order from roomSizes. */
  rooms: string[][];
  /** speakerIds that ended up sharing a room with a same-institution speaker despite repair. */
  clashedSpeakerIds: Set<string>;
  totalClashPenalty: number;
}

export interface AllocationOptions {
  /** Order to feed speakers into the greedy placement — defaults to sorting by
   *  institution group size descending (docs/01 §5). Power-matched draws
   *  (docs/01 §11) supply their own standing-based order here instead. */
  seedOrder?: SpeakerForAllocation[];
  /** Tie-break when multiple rooms have equal marginal clash penalty.
   *  "fill-first" packs earlier rooms before opening later ones (used for
   *  high-high power-matching); "least-filled" spreads evenly (default, and
   *  used for high-low power-matching). */
  roomTieBreak?: "fill-first" | "least-filled";
  maxRepairIterations?: number;
}

function defaultSeedOrder(speakers: SpeakerForAllocation[]): SpeakerForAllocation[] {
  const groupSize = new Map<string, number>();
  for (const s of speakers) {
    if (s.institutionId === null) continue;
    groupSize.set(s.institutionId, (groupSize.get(s.institutionId) ?? 0) + 1);
  }
  return [...speakers].sort((a, b) => {
    const sizeA = a.institutionId ? (groupSize.get(a.institutionId) ?? 0) : 0;
    const sizeB = b.institutionId ? (groupSize.get(b.institutionId) ?? 0) : 0;
    return sizeB - sizeA;
  });
}

function marginalClashPenalty(
  room: string[],
  speaker: SpeakerForAllocation,
  byId: Map<string, SpeakerForAllocation>,
): number {
  if (speaker.institutionId === null) return 0;
  return room.filter((id) => byId.get(id)?.institutionId === speaker.institutionId).length;
}

function totalClashPenalty(rooms: string[][], byId: Map<string, SpeakerForAllocation>): number {
  let total = 0;
  for (const room of rooms) {
    const counts = new Map<string, number>();
    for (const id of room) {
      const inst = byId.get(id)?.institutionId;
      if (inst === null || inst === undefined) continue;
      counts.set(inst, (counts.get(inst) ?? 0) + 1);
    }
    for (const count of counts.values()) {
      if (count > 1) total += count - 1;
    }
  }
  return total;
}

export function allocateSections(
  speakers: SpeakerForAllocation[],
  roomSizes: number[],
  options: AllocationOptions = {},
): AllocationResult {
  const byId = new Map(speakers.map((s) => [s.speakerId, s]));
  const order = options.seedOrder ?? defaultSeedOrder(speakers);
  const roomTieBreak = options.roomTieBreak ?? "least-filled";
  const rooms: string[][] = roomSizes.map(() => []);

  for (const speaker of order) {
    const candidates = rooms
      .map((room, index) => ({ index, room }))
      .filter(({ index }) => rooms[index]!.length < roomSizes[index]!);

    if (candidates.length === 0) {
      throw new Error(`No room with capacity remains for speaker ${speaker.speakerId}`);
    }

    let best = candidates[0]!;
    let bestPenalty = marginalClashPenalty(best.room, speaker, byId);
    for (const candidate of candidates.slice(1)) {
      const penalty = marginalClashPenalty(candidate.room, speaker, byId);
      if (penalty < bestPenalty) {
        best = candidate;
        bestPenalty = penalty;
        continue;
      }
      if (penalty === bestPenalty && roomTieBreak === "least-filled") {
        if (candidate.room.length < best.room.length) best = candidate;
      }
      // "fill-first" keeps the earliest-index room already found on ties.
    }
    rooms[best.index]!.push(speaker.speakerId);
  }

  repairSwaps(rooms, byId, options.maxRepairIterations ?? 500);

  const clashedSpeakerIds = new Set<string>();
  for (const room of rooms) {
    const seen = new Map<string, string[]>();
    for (const id of room) {
      const inst = byId.get(id)?.institutionId;
      if (!inst) continue;
      const list = seen.get(inst) ?? [];
      list.push(id);
      seen.set(inst, list);
    }
    for (const list of seen.values()) {
      if (list.length > 1) list.forEach((id) => clashedSpeakerIds.add(id));
    }
  }

  return { rooms, clashedSpeakerIds, totalClashPenalty: totalClashPenalty(rooms, byId) };
}

function repairSwaps(
  rooms: string[][],
  byId: Map<string, SpeakerForAllocation>,
  maxIterations: number,
): void {
  for (let iter = 0; iter < maxIterations; iter++) {
    let improved = false;

    outer: for (let ri = 0; ri < rooms.length; ri++) {
      for (let rj = ri + 1; rj < rooms.length; rj++) {
        for (let ii = 0; ii < rooms[ri]!.length; ii++) {
          for (let jj = 0; jj < rooms[rj]!.length; jj++) {
            const before = totalClashPenalty(rooms, byId);

            const a = rooms[ri]![ii]!;
            const b = rooms[rj]![jj]!;
            rooms[ri]![ii] = b;
            rooms[rj]![jj] = a;

            const after = totalClashPenalty(rooms, byId);
            if (after < before) {
              improved = true;
              break outer;
            }
            // revert
            rooms[ri]![ii] = a;
            rooms[rj]![jj] = b;
          }
        }
      }
    }

    if (!improved) return;
  }
}
