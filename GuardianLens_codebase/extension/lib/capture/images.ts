// Chooses which images on a listing page are the listing's own photos.
//
// The rules follow the Data Collector's extension (extension/background.js, collectPageData),
// which was tested on real marketplace pages:
//   1. photos named in the page's structured data (JSON-LD) come first;
//   2. large rendered images (at least 160 x 160) are gallery photos;
//   3. small images (at least 48 x 48) count ONLY if they sit in the same CDN folder as a large
//      gallery photo: galleries often render the non-selected photos as thumbnails, while icons
//      and "related listings" thumbnails live in other folders;
//   4. only https URLs are kept; SVGs and data: URLs are dropped; duplicates are removed; at most
//      `limit` URLs are returned.

/** An image found on the page and the size it was rendered at. */
export interface ImageCandidate {
  url: string;
  width: number;
  height: number;
}

// Smallest rendered edge, in pixels, of a gallery photo (160) and of a thumbnail worth keeping (48).
const LARGE_EDGE = 160;
const THUMBNAIL_EDGE = 48;

/** True for an https URL that is not an SVG (logos and icons are often SVG). */
function isUsable(url: string): boolean {
  if (/\.svg(?:[?#]|$)/i.test(url)) return false;
  try {
    return new URL(url).protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Groups an image URL by host and folder, so a thumbnail can be matched back to a full-size
 * photo served from the same CDN folder without depending on any site's CSS classes.
 * @returns "host/dir/" in lower case, or null when the URL cannot be parsed.
 */
export function directoryKey(url: string): string | null {
  try {
    const parsed = new URL(url);
    const lastSlash = parsed.pathname.lastIndexOf("/");
    const directory = lastSlash >= 0 ? parsed.pathname.slice(0, lastSlash + 1) : parsed.pathname;
    return `${parsed.hostname.toLowerCase()}${directory}`;
  } catch {
    return null;
  }
}

/**
 * Picks the listing's photos.
 * @param candidates Images found in the page's gallery area, with their rendered sizes.
 * @param structuredUrls Photo URLs named in the page's structured data (JSON-LD), if any.
 * @param limit Maximum number of URLs to return (default 12).
 * @returns Photo URLs, structured ones first, without duplicates.
 */
export function selectGalleryImages(
  candidates: ImageCandidate[],
  structuredUrls: string[],
  limit = 12,
): string[] {
  const usable = candidates.filter((candidate) => isUsable(candidate.url));
  const large = usable.filter((c) => c.width >= LARGE_EDGE && c.height >= LARGE_EDGE);
  const galleryDirectories = new Set(
    large.map((c) => directoryKey(c.url)).filter((key): key is string => key !== null),
  );
  const thumbnails =
    galleryDirectories.size === 0
      ? []
      : usable.filter(
          (c) =>
            c.width >= THUMBNAIL_EDGE &&
            c.height >= THUMBNAIL_EDGE &&
            !(c.width >= LARGE_EDGE && c.height >= LARGE_EDGE) &&
            galleryDirectories.has(directoryKey(c.url) ?? ""),
        );
  const ordered = [
    ...structuredUrls.filter(isUsable),
    ...large.map((c) => c.url),
    ...thumbnails.map((c) => c.url),
  ];
  return [...new Set(ordered)].slice(0, limit);
}
