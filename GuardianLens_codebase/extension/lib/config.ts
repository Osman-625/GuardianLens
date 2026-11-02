// Build-time settings for the extension.
// WXT exposes variables whose names start with WXT_ through import.meta.env. They are set when
// building, for example `WXT_API_BASE_URL=https://api.example npm run build`, which is how a
// later hosted deployment moves the extension off localhost without a code change.

/** Base URL of the GuardianLens API. It must also be in host_permissions (wxt.config.ts). */
export const API_BASE_URL: string = import.meta.env.WXT_API_BASE_URL ?? "http://localhost:8000";

/** Base URL of the GuardianLens website, opened by "See full explanation" and "This session". */
export const SITE_BASE_URL: string = import.meta.env.WXT_SITE_BASE_URL ?? "http://localhost:3000";
