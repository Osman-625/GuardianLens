// What the side panel remembers between openings, and how it hears about new captures.
//
// Two things are stored in session storage (cleared when the browser closes):
//   - the capture job the service worker wrote (the panel watches it);
//   - the buyer's unsent draft plus the id of the newest capture already applied, so reopening the
//     panel brings the draft back without letting an old capture overwrite newer edits.
// Defined as an interface so the controller can be tested with an in-memory fake.
import { CAPTURE_STATE_KEY, type CaptureJob } from "../capture/runner";
import { readSession, watchSession, writeSession } from "../storage";
import type { Draft } from "./draft";

/** The panel state worth keeping across openings. */
export interface SavedPanel {
  draft: Draft | null;
  lastDoneJobId: number;
}

/** The panel's view of storage. */
export interface PanelStorage {
  /** The newest capture job the service worker wrote, or null. */
  readCaptureState(): Promise<CaptureJob | null>;
  /** Calls the listener for every new capture job. Returns an unsubscribe function. */
  watchCaptureState(listener: (job: CaptureJob | null) => void): () => void;
  readSaved(): Promise<SavedPanel | null>;
  writeSaved(saved: SavedPanel): Promise<void>;
}

// The session-storage key under which the saved draft is kept.
const SAVED_KEY = "panelSaved";

/** The real storage, backed by chrome.storage.session. */
export const panelStorage: PanelStorage = {
  readCaptureState: () => readSession<CaptureJob>(CAPTURE_STATE_KEY),
  watchCaptureState: (listener) => watchSession<CaptureJob>(CAPTURE_STATE_KEY, listener),
  readSaved: () => readSession<SavedPanel>(SAVED_KEY),
  writeSaved: (saved) => writeSession(SAVED_KEY, saved),
};
