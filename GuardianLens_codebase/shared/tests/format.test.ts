// Pins the shared display formats: day-first Malaysian time without seconds, and sentence case.
import { describe, expect, it } from "vitest";
import { formatDateTime, sentenceCase } from "../src/format";

describe("formatDateTime", () => {
  it("shows the date day first in Malaysian time, without seconds", () => {
    // 20:52:12 UTC is 4:52 the next morning in Kuala Lumpur (UTC+8).
    expect(formatDateTime("2026-10-14T20:52:12Z")).toBe("15 Oct 2026, 4:52 am");
  });
});

describe("sentenceCase", () => {
  it("capitalises only the first letter", () => {
    expect(sentenceCase("main factor: raises risk")).toBe("Main factor: raises risk");
    expect(sentenceCase("")).toBe("");
  });
});
