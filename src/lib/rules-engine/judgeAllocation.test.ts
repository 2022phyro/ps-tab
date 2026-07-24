import { describe, expect, it } from "vitest";
import {
  allocateJudges,
  type JudgeForAllocation,
  type SectionForJudgeAllocation,
} from "./judgeAllocation";

const zeroRandom = () => 0;
const highRandom = () => 0.999;

describe("allocateJudges", () => {
  it("avoids assigning a judge who clashes with a speaker's institution when a clash-free judge exists", () => {
    const judges: JudgeForAllocation[] = [
      { judgeId: "clashes", institutionId: "inst-X", chairEligible: false },
      { judgeId: "clean-1", institutionId: null, chairEligible: false },
      { judgeId: "clean-2", institutionId: null, chairEligible: false },
    ];
    const sections: SectionForJudgeAllocation[] = [
      { sectionId: "room-1", speakerInstitutionIds: ["inst-X"], panelSize: 1 },
    ];

    const result = allocateJudges(judges, sections, zeroRandom);
    const assigned = result.assignments.get("room-1")!;
    expect(assigned).toHaveLength(1);
    expect(assigned[0]).not.toBe("clashes");
    expect(result.clashFlags.get("room-1")).toBe(false);
  });

  it("prefers a chair-eligible judge for the first slot even when pool order would pick someone else first", () => {
    const judges: JudgeForAllocation[] = [
      { judgeId: "not-chair", institutionId: null, chairEligible: false },
      { judgeId: "chair-material", institutionId: null, chairEligible: true },
    ];
    const sections: SectionForJudgeAllocation[] = [
      { sectionId: "room-1", speakerInstitutionIds: [], panelSize: 1 },
    ];

    // highRandom leaves shuffle order unchanged ([not-chair, chair-material]
    // stays first-in-pool-order as not-chair) — proving the pick is driven
    // by chair-eligibility, not just who happened to shuffle to the front.
    const result = allocateJudges(judges, sections, highRandom);
    expect(result.assignments.get("room-1")).toEqual(["chair-material"]);
  });

  it("accepts an unavoidable clash rather than leaving the panel empty, and flags it", () => {
    const judges: JudgeForAllocation[] = [
      { judgeId: "only-option", institutionId: "inst-X", chairEligible: false },
    ];
    const sections: SectionForJudgeAllocation[] = [
      { sectionId: "room-1", speakerInstitutionIds: ["inst-X"], panelSize: 1 },
    ];

    const result = allocateJudges(judges, sections, zeroRandom);
    expect(result.assignments.get("room-1")).toEqual(["only-option"]);
    expect(result.clashFlags.get("room-1")).toBe(true);
  });

  it("never assigns the same judge to two sections in the same round", () => {
    const judges: JudgeForAllocation[] = [
      { judgeId: "j1", institutionId: null, chairEligible: false },
      { judgeId: "j2", institutionId: null, chairEligible: false },
    ];
    const sections: SectionForJudgeAllocation[] = [
      { sectionId: "room-1", speakerInstitutionIds: [], panelSize: 1 },
      { sectionId: "room-2", speakerInstitutionIds: [], panelSize: 1 },
    ];

    const result = allocateJudges(judges, sections, zeroRandom);
    const all = [...result.assignments.values()].flat();
    expect(new Set(all).size).toBe(all.length);
    expect(all.sort()).toEqual(["j1", "j2"]);
  });

  it("returns a partial (possibly empty) assignment rather than throwing when judges run out", () => {
    const judges: JudgeForAllocation[] = [
      { judgeId: "only-judge", institutionId: null, chairEligible: false },
    ];
    const sections: SectionForJudgeAllocation[] = [
      { sectionId: "room-1", speakerInstitutionIds: [], panelSize: 1 },
      { sectionId: "room-2", speakerInstitutionIds: [], panelSize: 1 },
    ];

    const result = allocateJudges(judges, sections, zeroRandom);
    const sizes = [
      result.assignments.get("room-1")!.length,
      result.assignments.get("room-2")!.length,
    ];
    expect(sizes.sort()).toEqual([0, 1]);
  });

  it("fills a multi-judge panel, only weighting chair-eligibility for the first slot", () => {
    const judges: JudgeForAllocation[] = [
      { judgeId: "chair", institutionId: null, chairEligible: true },
      { judgeId: "panelist-1", institutionId: null, chairEligible: false },
      { judgeId: "panelist-2", institutionId: null, chairEligible: false },
    ];
    const sections: SectionForJudgeAllocation[] = [
      { sectionId: "room-1", speakerInstitutionIds: [], panelSize: 3 },
    ];

    const result = allocateJudges(judges, sections, zeroRandom);
    const assigned = result.assignments.get("room-1")!;
    expect(assigned).toHaveLength(3);
    expect(assigned[0]).toBe("chair"); // the only chair-eligible candidate takes the first slot
    expect(new Set(assigned).size).toBe(3);
  });
});
