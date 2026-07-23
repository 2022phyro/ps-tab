// docs/01-tournament-mechanics.md §13 — waitlists & registration caps.

export interface RegistrationEntry {
  id: string;
  /** monotonically increasing — submission order, not wall-clock time. */
  submittedOrder: number;
}

export interface CapResult<T extends RegistrationEntry> {
  admitted: T[];
  waitlisted: T[];
}

/** A cap is a soft ceiling — this just sorts and splits; overriding it is a separate, explicit action (see admitOverride). */
export function applyCap<T extends RegistrationEntry>(entries: T[], cap: number): CapResult<T> {
  const sorted = [...entries].sort((a, b) => a.submittedOrder - b.submittedOrder);
  return { admitted: sorted.slice(0, cap), waitlisted: sorted.slice(cap) };
}

/** Promotes the earliest-submitted waitlisted entries, in order, as capacity frees up. */
export function promoteFromWaitlist<T extends RegistrationEntry>(
  state: CapResult<T>,
  freedSlots: number,
): CapResult<T> {
  const sorted = [...state.waitlisted].sort((a, b) => a.submittedOrder - b.submittedOrder);
  const promoted = sorted.slice(0, freedSlots);
  const stillWaiting = sorted.slice(freedSlots);
  return { admitted: [...state.admitted, ...promoted], waitlisted: stillWaiting };
}

/** An organizer can admit a specific waitlisted entry above the cap — soft ceiling, never blocked. */
export function admitOverride<T extends RegistrationEntry>(
  state: CapResult<T>,
  entryId: string,
): CapResult<T> {
  const entry = state.waitlisted.find((e) => e.id === entryId);
  if (!entry) return state;
  return {
    admitted: [...state.admitted, entry],
    waitlisted: state.waitlisted.filter((e) => e.id !== entryId),
  };
}
