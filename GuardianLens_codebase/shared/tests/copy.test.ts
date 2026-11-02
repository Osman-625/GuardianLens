// Pins the wording that the website and the browser extension must share word for word.
// Both surfaces ask the buyer the same feedback question after a result. When each surface wrote its
// own heading and button labels they drifted apart ("Was this result helpful?" on the website,
// "Was this helpful?" in the panel), so the text lives here once and both import it.
import { describe, expect, it } from "vitest";
import { FEEDBACK_HEADING, FEEDBACK_OPTIONS } from "../src/copy";

describe("feedback wording", () => {
  it("asks one question", () => {
    expect(FEEDBACK_HEADING).toBe("Was this result helpful?");
  });

  it("offers exactly the three verdicts the API accepts, in a fixed order, with their labels", () => {
    expect(FEEDBACK_OPTIONS).toEqual([
      ["helpful", "Helpful"],
      ["unclear", "Unclear"],
      ["potentially_incorrect", "Potentially incorrect"],
    ]);
  });
});
