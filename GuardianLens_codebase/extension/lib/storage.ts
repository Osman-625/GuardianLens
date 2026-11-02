// Thin helpers over chrome.storage.session, plus the token store the API client uses.
//
// Session storage lives only until the browser closes and is never synced, which matches the
// product promise that the history lives only in this browser session. It holds three things:
// the anonymous session token, the latest capture job, and the buyer's unsent draft.
import { browser } from "wxt/browser";
import type { TokenStore } from "@guardianlens/shared";

/** Reads one value from session storage, or null when the key is absent. */
export async function readSession<T>(key: string): Promise<T | null> {
  const stored = await browser.storage.session.get(key);
  return (stored[key] as T | undefined) ?? null;
}

/** Writes one value to session storage (replacing any previous value). */
export async function writeSession(key: string, value: unknown): Promise<void> {
  await browser.storage.session.set({ [key]: value });
}

/** Deletes one value from session storage. */
export async function removeSession(key: string): Promise<void> {
  await browser.storage.session.remove(key);
}

/**
 * Calls `listener` with the new value each time `key` changes in session storage (null when it
 * is removed). Used by the side panel to react to a capture the service worker just wrote.
 * @returns A function that stops listening.
 */
export function watchSession<T>(key: string, listener: (value: T | null) => void): () => void {
  // Receives every storage change and passes on only this key's change in the session area.
  const handler = (changes: Record<string, { newValue?: unknown }>, area: string) => {
    // onChanged fires for every storage area and key; only the session area and this key matter
    // here. A removed key still has an entry (with no newValue), which is reported as null.
    const change = changes[key];
    if (area !== "session" || !change) return;
    listener((change.newValue as T | undefined) ?? null);
  };
  browser.storage.onChanged.addListener(handler);
  return () => browser.storage.onChanged.removeListener(handler);
}

/** The session token store for the API client's "header" transport. */
export const tokenStore: TokenStore = {
  async get() {
    const token = await readSession<string>("sessionToken");
    return typeof token === "string" ? token : null;
  },
  async set(token) {
    if (token) await writeSession("sessionToken", token);
    else await removeSession("sessionToken");
  },
};
