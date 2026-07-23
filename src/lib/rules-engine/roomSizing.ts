// docs/01-tournament-mechanics.md §3 — dynamic room sizing.

export interface RoomSizingConfig {
  roomSizeMin: number;
  roomSizeMax: number;
  /** "fewest" packs rooms as full as possible (default); "smallest" prefers more, smaller rooms. */
  preference?: "fewest" | "smallest";
}

export interface RoomPlan {
  roomSizes: number[];
  /** true when this plan needed organizer attention (too few speakers, judge shortfall, etc). */
  flagged: boolean;
  flagReason?: string;
}

export function computeRoomPlan(n: number, config: RoomSizingConfig): RoomPlan {
  if (n <= 0) {
    return { roomSizes: [], flagged: false };
  }
  if (n < config.roomSizeMin) {
    return {
      roomSizes: [n],
      flagged: true,
      flagReason: `${n} is below the configured minimum room size (${config.roomSizeMin}); collapsed to a single room.`,
    };
  }

  const preference = config.preference ?? "fewest";
  let rMax = config.roomSizeMax;

  // Widen rMax until some room count satisfies both bounds — never silently
  // violate roomSizeMin instead.
  for (;;) {
    const kMin = Math.ceil(n / rMax);
    const kMax = Math.floor(n / config.roomSizeMin);
    if (kMin <= kMax) {
      const k = preference === "fewest" ? kMin : kMax;
      return { roomSizes: distribute(n, k), flagged: false };
    }
    rMax += 1;
  }
}

function distribute(n: number, k: number): number[] {
  const base = Math.floor(n / k);
  const remainder = n % k;
  return [...Array<number>(remainder).fill(base + 1), ...Array<number>(k - remainder).fill(base)];
}

/**
 * docs/01 §3 edge case: room count is also capped by how many panels the
 * available judge pool can actually staff — if the judge-unconstrained plan
 * wants more rooms than judges allow, collapse to `maxRooms` and re-derive
 * sizes (even above roomSizeMax if unavoidable), flagged for visibility.
 */
export function capRoomPlanByJudges(plan: RoomPlan, maxRooms: number): RoomPlan {
  if (maxRooms < 1 || plan.roomSizes.length <= maxRooms) {
    return plan;
  }
  const n = plan.roomSizes.reduce((a, b) => a + b, 0);
  return {
    roomSizes: distribute(n, maxRooms),
    flagged: true,
    flagReason: `Judge availability capped room count to ${maxRooms} (headcount math wanted ${plan.roomSizes.length}).`,
  };
}
