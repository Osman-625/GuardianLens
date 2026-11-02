// Pins the thin wrapper around chrome.storage.session that the extension uses for its session
// token, its latest capture, and the buyer's unsent draft. Session storage is cleared when the
// browser closes, which is exactly the "history lives only in this browser session" promise.
// The tests run against WXT's in-memory fake of the browser API (reset before each test).
import { describe, expect, it } from "vitest";
import { readSession, removeSession, tokenStore, watchSession, writeSession } from "../lib/storage";

describe("session storage helpers", () => {
  it("round-trips a value", async () => {
    await writeSession("k", { a: 1 });
    expect(await readSession("k")).toEqual({ a: 1 });
  });

  it("returns null for a missing key", async () => {
    expect(await readSession("missing")).toBeNull();
  });

  it("removes a value", async () => {
    await writeSession("k", 1);
    await removeSession("k");
    expect(await readSession("k")).toBeNull();
  });

  it("tells a watcher about changes and removals, and stops after unsubscribe", async () => {
    const seen: unknown[] = [];
    const stop = watchSession("k", (value) => seen.push(value));
    await writeSession("k", 1);
    await removeSession("k");
    stop();
    await writeSession("k", 2);
    expect(seen).toEqual([1, null]);
  });
});

describe("tokenStore", () => {
  it("stores, reads, and clears the session token", async () => {
    expect(await tokenStore.get()).toBeNull();
    await tokenStore.set("token-1");
    expect(await tokenStore.get()).toBe("token-1");
    await tokenStore.set(null);
    expect(await tokenStore.get()).toBeNull();
  });
});
