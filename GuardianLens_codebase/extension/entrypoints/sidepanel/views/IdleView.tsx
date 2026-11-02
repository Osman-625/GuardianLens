// Shown when the panel has nothing to review: before the first click, on pages that are not a
// listing, on blocked pages, and after a failed capture. Each reason gets one plain sentence
// that says what to do next, and two ways out (the website form and the session history).
import { LooksAt } from "@guardianlens/shared";
import type { PageState } from "@/lib/capture/types";
import type { IdleReason } from "@/lib/panel/reducer";

// One sentence per reason the panel can be idle.
const MESSAGES: Record<IdleReason, string> = {
  no_capture: "Open a Mudah.my or Carousell listing, then click the GuardianLens icon.",
  not_listing: "This page is not a single listing. Open one listing, then click the icon.",
  unsupported_site: "GuardianLens works on Mudah.my and Carousell listings only.",
  blocked: "This page could not be read.",
  capture_failed:
    "The page could not be read. Reload it and click the icon again, or use the website form.",
  no_draft_for_seller:
    "Open the listing first and click the icon. Then open the seller's page and click it again to add seller details.",
};

// More specific sentences for a blocked page. The extension detects these pages and never
// tries to get around them.
const BLOCKED_MESSAGES: Partial<Record<PageState, string>> = {
  captcha: "The site is asking for a security check. Complete it, then click the icon again.",
  access_denied: "The site blocked this page. Reload it, then click the icon again.",
  login_required: "This page needs you to log in. Log in, then click the icon again.",
  listing_unavailable: "This listing is no longer available.",
};

/** Props of the idle view: why nothing is being reviewed, and the website link action. */
export interface IdleViewProps {
  reason: IdleReason;
  /** For a blocked page: which kind of block, so the message can be specific. */
  pageState?: PageState;
  /** Opens a path on the GuardianLens website in a new tab (for example "/assess"). */
  onOpenSite(path: string): void;
  /** Captures the page open in the browser now, without reloading it or clicking the icon. */
  onCapture(): void;
}

/** The "nothing to review yet" view. */
export function IdleView({ reason, pageState, onOpenSite, onCapture }: IdleViewProps) {
  const message =
    reason === "blocked"
      ? ((pageState && BLOCKED_MESSAGES[pageState]) ?? MESSAGES.blocked)
      : MESSAGES[reason];
  return (
    <section className="panel-section" aria-live="polite">
      {/* Every panel view has one level-one heading, so screen readers can orient on it. */}
      <h1 className="panel-title">Check a listing</h1>
      <p>{message}</p>
      <button type="button" className="button button-primary" onClick={onCapture}>
        Capture this page
      </button>
      <p className="helper">It reads a page only when you ask it to.</p>
      <div className="panel-links">
        <button type="button" className="button button-text" onClick={() => onOpenSite("/assess")}>
          Use the website form
        </button>
        <button type="button" className="button button-text" onClick={() => onOpenSite("/history")}>
          This session
        </button>
      </div>
      <section className="panel-looks" aria-labelledby="panel-looks-heading">
        <h2 id="panel-looks-heading" className="panel-subtitle">
          What it looks at
        </h2>
        <LooksAt />
      </section>
    </section>
  );
}
