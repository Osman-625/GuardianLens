// The key under which the manual form keeps its draft in this tab's session storage. The form saves
// to it after every change; the processing page clears it once a check has finished, so the next
// check starts empty instead of inheriting the last listing's seller details.
export const DRAFT_KEY = "guardianlens-draft";
