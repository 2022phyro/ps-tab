import { describe, expect, it } from "vitest";
import { resolvePanelSize } from "./panelDegradation";

describe("resolvePanelSize", () => {
  it("runs at full configured size when enough judges are available", () => {
    const result = resolvePanelSize(3, 3, 1);
    expect(result).toEqual({ effectiveSize: 3, degraded: false, blocked: false });
  });

  it("collapses to a smaller panel, flagged, when above the floor", () => {
    const result = resolvePanelSize(3, 2, 1);
    expect(result).toEqual({ effectiveSize: 2, degraded: true, blocked: false });
  });

  it("blocks when availability would drop below the configured floor", () => {
    const result = resolvePanelSize(3, 0, 1);
    expect(result).toEqual({ effectiveSize: 0, degraded: true, blocked: true });
  });

  it("blocks at exactly zero judges even if the floor is configured to zero", () => {
    const result = resolvePanelSize(3, 0, 0);
    expect(result.blocked).toBe(true);
  });

  it("never flags degraded when availability meets or exceeds the target", () => {
    const result = resolvePanelSize(1, 5, 1);
    expect(result).toEqual({ effectiveSize: 1, degraded: false, blocked: false });
  });
});
