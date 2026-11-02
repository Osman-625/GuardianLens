// Hosts that serve listing photos.
//
// The extension downloads photos itself (to upload them to the API), and a browser extension may
// only read another site's files for hosts listed in the manifest's host_permissions. This list
// feeds wxt.config.ts, and the same list decides at run time which photo URLs the extension will
// even try to fetch, so an unlisted host is skipped cleanly instead of failing noisily.
//
// Source of truth: the "Image hosts" section of docs/SPIKE_NOTES.md. When a page change shows a
// new photo host, add it here and nowhere else.
//
// Boundary: no pattern here may match a marketplace PAGE host (mudah.my, carousell.com.my). Those
// pages are read only on the buyer's click (the icon's activeTab, or the panel button's optional
// permission, PAGE_HOST_PATTERNS below); a pattern that also covered them would put them in
// host_permissions and give the extension access at install. tests/hosts.test.ts pins this.
//   - Mudah serves listing photos from rnudah.com (cdn.rnudah.com for the ad's photos, and
//     img.rnudah.com for thumbnails), a different domain from the mudah.my site. Verified on a
//     live Mudah listing on 2026-10-06.
//   - Carousell serves photos from media.karousell.com. Not yet verified on a recorded page.

/** Match patterns for the photo CDNs, in manifest host_permissions format. */
export const IMAGE_HOST_PATTERNS: string[] = [
  "https://media.karousell.com/*",
  "https://*.rnudah.com/*",
];

/**
 * The marketplace PAGE hosts, as OPTIONAL permissions: not granted at install. The side panel's
 * "Capture this page" button asks for them from a click; Chrome shows its own prompt once and the
 * buyer can remove the access again at chrome://extensions. Kept apart from IMAGE_HOST_PATTERNS.
 */
export const PAGE_HOST_PATTERNS: string[] = [
  "https://mudah.my/*",
  "https://www.mudah.my/*",
  "https://carousell.com.my/*",
  "https://www.carousell.com.my/*",
];

/**
 * Tells whether the extension may fetch a photo from this URL.
 * Requires https and an exact host match against IMAGE_HOST_PATTERNS. A wildcard pattern such
 * as "*.rnudah.com" matches the bare domain and its subdomains, never a look-alike host.
 */
export function isFetchableImageUrl(url: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:") return false;
  const host = parsed.hostname.toLowerCase();
  return IMAGE_HOST_PATTERNS.some((pattern) => {
    // The host part of "https://<host>/*". A pattern that does not have that shape never matches.
    const allowed = /^https:\/\/([^/]+)\/\*$/.exec(pattern)?.[1]?.toLowerCase();
    if (!allowed) return false;
    if (allowed.startsWith("*.")) {
      const base = allowed.slice(2);
      return host === base || host.endsWith(`.${base}`);
    }
    return host === allowed;
  });
}
