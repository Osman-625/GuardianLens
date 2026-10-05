// Pins the extension-to-website session handoff.
// The extension opens the website at ".../explanation#st=<token>". The website must (1) accept
// only a well-formed token, (2) remove the token from the address bar BEFORE doing anything
// else, so it never lingers in history or a screenshot, and (3) claim the session so the
// website sees the same checks as the extension.
import { describe, expect, it } from "vitest";
import { buildHandoffUrl, claimSessionFromHash, parseHandoffHash } from "../src/claim";

// A syntactically valid session token (UUID).
const TOKEN = "3f0c2a52-8b7e-4c55-9d0e-1a2b3c4d5e6f";

// Reading the fragment: only a valid token and a known signal name are accepted.
describe("parseHandoffHash", () => {
  it("reads a token with or without the leading hash", () => {
    expect(parseHandoffHash(`#st=${TOKEN}`).token).toBe(TOKEN);
    expect(parseHandoffHash(`st=${TOKEN}`).token).toBe(TOKEN);
  });

  it("reads a known signal", () => {
    expect(parseHandoffHash(`#st=${TOKEN}&signal=visual`)).toEqual({ token: TOKEN, signal: "visual" });
  });

  it("rejects a token that is not a UUID", () => {
    expect(parseHandoffHash("#st=not-a-token").token).toBeNull();
  });

  it("ignores an unknown signal", () => {
    expect(parseHandoffHash(`#st=${TOKEN}&signal=other`).signal).toBeNull();
  });

  it("returns nothing for an ordinary anchor", () => {
    // "#visual" is the normal in-page anchor on the explanation page, not a handoff.
    expect(parseHandoffHash("#visual")).toEqual({ token: null, signal: null });
  });
});

// Building the URL the extension opens.
describe("buildHandoffUrl", () => {
  it("builds the explanation URL with the token in the fragment", () => {
    expect(buildHandoffUrl("http://localhost:3000/", "abc", TOKEN)).toBe(
      `http://localhost:3000/assess/abc/explanation#st=${TOKEN}`,
    );
  });

  it("adds the signal when given", () => {
    expect(buildHandoffUrl("http://localhost:3000", "abc", TOKEN, "textual")).toBe(
      `http://localhost:3000/assess/abc/explanation#st=${TOKEN}&signal=textual`,
    );
  });
});

// The order of operations is the security property: scrub the address first, then claim.
describe("claimSessionFromHash", () => {
  it("does nothing when there is no token", async () => {
    const calls: string[] = [];
    const outcome = await claimSessionFromHash({
      hash: "#visual",
      claim: async () => void calls.push("claim"),
      replaceHash: () => void calls.push("replace"),
    });
    expect(outcome).toBe("none");
    expect(calls).toEqual([]);
  });

  it("removes the token from the address before claiming", async () => {
    const calls: string[] = [];
    const outcome = await claimSessionFromHash({
      hash: `#st=${TOKEN}&signal=visual`,
      claim: async (token) => void calls.push(`claim:${token}`),
      replaceHash: (hash) => void calls.push(`replace:${hash}`),
    });
    expect(outcome).toBe("claimed");
    // The signal survives as an ordinary anchor so the page still scrolls to that section.
    expect(calls).toEqual(["replace:#visual", `claim:${TOKEN}`]);
  });

  it("still removes the token when the claim fails", async () => {
    const calls: string[] = [];
    const outcome = await claimSessionFromHash({
      hash: `#st=${TOKEN}`,
      claim: async () => {
        throw new Error("nope");
      },
      replaceHash: (hash) => void calls.push(`replace:${hash}`),
    });
    expect(outcome).toBe("failed");
    expect(calls).toEqual(["replace:"]);
  });
});
