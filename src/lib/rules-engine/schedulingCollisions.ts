// docs/01-tournament-mechanics.md §10 — multi-event scheduling collisions.
// Generic over speakers and judges: both are "a person assigned to an event
// at a time slot," and the collision check is identical for either.

export interface EventAssignment {
  personId: string;
  eventId: string;
  timeSlotId: string;
}

/** Returns, per person, every assignment that collides with another (same time slot, different event). */
export function findDoubleBookings(assignments: EventAssignment[]): Map<string, EventAssignment[]> {
  const byPersonSlot = new Map<string, EventAssignment[]>();
  for (const a of assignments) {
    const key = `${a.personId}::${a.timeSlotId}`;
    const list = byPersonSlot.get(key) ?? [];
    list.push(a);
    byPersonSlot.set(key, list);
  }

  const collisions = new Map<string, EventAssignment[]>();
  for (const list of byPersonSlot.values()) {
    const distinctEvents = new Set(list.map((a) => a.eventId));
    if (distinctEvents.size > 1) {
      const personId = list[0]!.personId;
      collisions.set(personId, [...(collisions.get(personId) ?? []), ...list]);
    }
  }
  return collisions;
}

/**
 * docs/01 §10 — the judge pool's availability is scoped per time-slot across
 * every concurrently-running event, not per-event in isolation.
 */
export function computeAvailableJudgesForSlot(
  allJudgeIds: string[],
  assignments: EventAssignment[],
  timeSlotId: string,
): string[] {
  const busy = new Set(
    assignments.filter((a) => a.timeSlotId === timeSlotId).map((a) => a.personId),
  );
  return allJudgeIds.filter((id) => !busy.has(id));
}
