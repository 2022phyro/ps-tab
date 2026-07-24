// docs/02-judging-contingencies.md §5 — degraded panel fallbacks.

export interface PanelSizeResolution {
  /** how many judges the section actually runs with. */
  effectiveSize: number;
  /** true if effectiveSize is below the configured target. */
  degraded: boolean;
  /** true if effectiveSize would fall below the organizer's absolute floor —
   *  this round for this room cannot proceed at all. */
  blocked: boolean;
}

/**
 * docs/02 §4 — "collapse panel size" (proceeds smaller, flagged) vs. "minimum
 * panel enforcement" (blocks rather than degrades). A room dropping to zero
 * judges is always blocked regardless of how low the organizer set the floor,
 * since a panel of zero can't produce a ballot at all.
 */
export function resolvePanelSize(
  configuredSize: number,
  availableJudges: number,
  minimumPanelSize: number,
): PanelSizeResolution {
  if (availableJudges <= 0 || availableJudges < minimumPanelSize) {
    return {
      effectiveSize: availableJudges,
      degraded: availableJudges < configuredSize,
      blocked: true,
    };
  }
  if (availableJudges < configuredSize) {
    return { effectiveSize: availableJudges, degraded: true, blocked: false };
  }
  return { effectiveSize: configuredSize, degraded: false, blocked: false };
}
