import { describe, expect, it } from "vitest";
import { matchAssessmentId } from "./useRoute";

describe("matchAssessmentId", () => {
  it("extracts the numeric id from /assessments/:id", () => {
    expect(matchAssessmentId("/assessments/2")).toBe(2);
    expect(matchAssessmentId("/assessments/949")).toBe(949);
  });

  it("accepts a trailing slash", () => {
    expect(matchAssessmentId("/assessments/2/")).toBe(2);
  });

  it("returns null for non-numeric ids", () => {
    expect(matchAssessmentId("/assessments/abc")).toBeNull();
    expect(matchAssessmentId("/assessments/2abc")).toBeNull();
  });

  it("returns null for unrelated paths", () => {
    expect(matchAssessmentId("/")).toBeNull();
    expect(matchAssessmentId("/assessments")).toBeNull();
    expect(matchAssessmentId("/documentation")).toBeNull();
  });
});
