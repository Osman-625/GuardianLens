// Downloads the buyer's selected photos and makes them upload-ready.
//
// The API accepts JPEG, PNG, or WebP up to 5 MB each. Photos come from third-party CDNs, so this
// module is built to fail softly: a photo that cannot be fetched or shrunk is SKIPPED and
// counted, it never fails the whole check. The caller tells the buyer how many were skipped,
// and blocks only when none could be prepared.
//
// `deps` hold the two operations that need a real browser (fetching and re-encoding), so the
// decision logic can be tested with fakes. `browserPhotoDeps` are the real implementations; they
// are covered by the end-to-end test and the manual smoke test rather than by unit tests.
import { isFetchableImageUrl } from "../hosts";

/** The API's limit for one photo. */
export const MAX_PHOTO_BYTES = 5 * 1024 * 1024;

// Types the API accepts as they are, and the file extension used for each.
const ACCEPTED: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
};

// How many photos are downloaded and re-encoded at the same time.
const MAX_AT_ONCE = 3;

// Re-encoding tries these sizes (longest edge, in pixels) and JPEG qualities, largest and best
// first, and stops at the first result that fits.
const EDGES = [1600, 1200, 800];
const QUALITIES = [0.85, 0.7, 0.55, 0.4];

/** The two browser-dependent operations. */
export interface PhotoDeps {
  /** Downloads a photo. Rejects when the request fails or the CDN refuses. */
  fetchBlob(url: string): Promise<Blob>;
  /** Re-encodes an image as JPEG with its longest edge at most `maxEdge`. Rejects when it cannot be decoded. */
  encodeJpeg(blob: Blob, maxEdge: number, quality: number): Promise<Blob>;
}

/** The photos that could be prepared and how many selected photos had to be left out. */
export interface PreparedPhotos {
  files: File[];
  skipped: number;
}

/** Prepares one photo, or returns null when it must be skipped. `index` is its place in the selection. */
async function prepareOne(url: string, index: number, deps: PhotoDeps): Promise<File | null> {
  // Never try a host the manifest does not permit: the request would fail noisily anyway.
  if (!isFetchableImageUrl(url)) return null;

  let blob: Blob;
  try {
    blob = await deps.fetchBlob(url);
  } catch {
    return null;
  }

  const extension = ACCEPTED[blob.type];
  if (extension && blob.size <= MAX_PHOTO_BYTES) {
    return new File([blob], `photo-${index + 1}.${extension}`, {
      type: blob.type,
    });
  }

  // Too big, or a type the API rejects (AVIF, HEIC, unknown): re-encode as JPEG and shrink until it fits.
  for (const edge of EDGES) {
    for (const quality of QUALITIES) {
      try {
        const encoded = await deps.encodeJpeg(blob, edge, quality);
        if (encoded.size <= MAX_PHOTO_BYTES) {
          return new File([encoded], `photo-${index + 1}.jpg`, {
            type: "image/jpeg",
          });
        }
      } catch {
        // The browser cannot decode this image at all; trying other sizes will not help.
        return null;
      }
    }
  }
  return null;
}

/**
 * Prepares the selected photos for upload.
 * @param urls The selected photo URLs, in the order the buyer sees them.
 * @param deps The fetch and re-encode operations.
 * @returns The files that could be prepared (original order, named photo-<n>.<ext>) and the
 *          number of photos skipped.
 */
export async function preparePhotos(urls: string[], deps: PhotoDeps): Promise<PreparedPhotos> {
  // A few photos at a time: up to ten can be selected, and a decoded full-size photo is large, so
  // preparing them all at once could exhaust the side panel's memory. Order is kept.
  const prepared: Array<File | null> = [];
  for (let start = 0; start < urls.length; start += MAX_AT_ONCE) {
    const batch = urls.slice(start, start + MAX_AT_ONCE);
    prepared.push(
      ...(await Promise.all(batch.map((url, offset) => prepareOne(url, start + offset, deps)))),
    );
  }
  const files = prepared.filter((file): file is File => file !== null);
  return { files, skipped: urls.length - files.length };
}

/** The real implementations, used in the side panel. */
export const browserPhotoDeps: PhotoDeps = {
  async fetchBlob(url) {
    // Credentials are omitted: photo CDNs are public, and sending the buyer's cookies would only
    // share them needlessly.
    const response = await fetch(url, { credentials: "omit" });
    if (!response.ok) throw new Error(`Photo request failed with status ${response.status}`);
    return response.blob();
  },
  async encodeJpeg(blob, maxEdge, quality) {
    const bitmap = await createImageBitmap(blob);
    // Only ever shrink: an image already smaller than maxEdge keeps its size.
    const scale = Math.min(1, maxEdge / Math.max(bitmap.width, bitmap.height));
    const canvas = new OffscreenCanvas(
      Math.max(1, Math.round(bitmap.width * scale)),
      Math.max(1, Math.round(bitmap.height * scale)),
    );
    const context = canvas.getContext("2d");
    if (!context) throw new Error("A 2D canvas is not available");
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    return canvas.convertToBlob({ type: "image/jpeg", quality });
  },
};
