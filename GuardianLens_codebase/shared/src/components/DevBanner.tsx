// Warning banner shown while scores come from development stubs, not trained models.
// It must stay visible until a real model bundle is served (project integrity rule).
import { DEV_STUB_NOTICE } from "../copy";

/** Renders the development-stub warning as a status message. */
export function DevBanner() {
  return (
    <div className="dev-banner" role="status">
      {DEV_STUB_NOTICE}
    </div>
  );
}
