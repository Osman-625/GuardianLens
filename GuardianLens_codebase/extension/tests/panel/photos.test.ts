// Pins how the buyer's selected photos are downloaded and made upload-ready.
// The API accepts JPEG, PNG, or WebP up to 5 MB each, and photos come from third-party CDNs, so
// things go wrong in ordinary ways: a host is not permitted, the CDN refuses the request, a
// photo is too large, or it is an AVIF the API rejects. The rules:
//   - a photo that works is passed through unchanged when it already fits;
//   - an oversize or unsupported photo is re-encoded as JPEG, smaller until it fits;
//   - a photo that cannot be prepared is SKIPPED (counted), it never fails the whole check;
//   - the caller learns how many were skipped, and decides what to tell the buyer.
import { describe, expect, it, vi, type Mock } from "vitest";
import { MAX_PHOTO_BYTES, preparePhotos, type PhotoDeps } from "../../lib/panel/photos";

// Two photo URLs on a permitted host, and one on a host the manifest does not permit.
const GOOD = "https://media.karousell.com/media/photos/products/1/a.jpg";
const OTHER = "https://media.karousell.com/media/photos/products/1/b.jpg";
const BAD_HOST = "https://example.com/a.jpg";

/** A blob of the given size and type (its bytes are zeros; only size and type matter). */
function blobOf(size: number, type: string): Blob {
  return new Blob([new Uint8Array(size)], { type });
}

/** The fake dependencies, typed so a test can read their call history. */
interface FakeDeps extends PhotoDeps {
  fetchBlob: Mock<PhotoDeps["fetchBlob"]>;
  encodeJpeg: Mock<PhotoDeps["encodeJpeg"]>;
}

/** Fake dependencies; `overrides` replace the defaults, which fetch a 1 KB JPEG. */
function deps(overrides: Partial<PhotoDeps> = {}): FakeDeps {
  return {
    fetchBlob: vi.fn(async () => blobOf(1000, "image/jpeg")),
    encodeJpeg: vi.fn(async () => blobOf(1000, "image/jpeg")),
    ...overrides,
  } as FakeDeps;
}

describe("preparePhotos", () => {
  it("passes a photo through unchanged when it already fits", async () => {
    const fake = deps();
    const { files, skipped } = await preparePhotos([GOOD], fake);
    expect(skipped).toBe(0);
    expect(files).toHaveLength(1);
    expect(files[0]?.name).toBe("photo-1.jpg");
    expect(files[0]?.type).toBe("image/jpeg");
    expect(files[0]?.size).toBe(1000);
    expect(fake.encodeJpeg).not.toHaveBeenCalled();
  });

  it("names the file after the real type", async () => {
    const png = deps({ fetchBlob: vi.fn(async () => blobOf(10, "image/png")) });
    expect((await preparePhotos([GOOD], png)).files[0]?.name).toBe("photo-1.png");
  });

  it("re-encodes an oversize photo, trying a lower quality until it fits", async () => {
    const fake = deps({
      fetchBlob: vi.fn(async () => blobOf(MAX_PHOTO_BYTES + 1, "image/jpeg")),
      // Too big at the first quality, small enough at the second.
      encodeJpeg: vi.fn(async (_blob: Blob, _edge: number, quality: number) =>
        blobOf(quality > 0.8 ? MAX_PHOTO_BYTES + 1 : 1000, "image/jpeg"),
      ),
    });
    const { files, skipped } = await preparePhotos([GOOD], fake);
    expect(skipped).toBe(0);
    expect(files[0]?.size).toBe(1000);
    expect(fake.encodeJpeg).toHaveBeenNthCalledWith(1, expect.anything(), 1600, 0.85);
    expect(fake.encodeJpeg).toHaveBeenNthCalledWith(2, expect.anything(), 1600, 0.7);
  });

  it("re-encodes a type the API rejects, such as AVIF", async () => {
    const fake = deps({
      fetchBlob: vi.fn(async () => blobOf(5000, "image/avif")),
    });
    const { files } = await preparePhotos([GOOD], fake);
    expect(files[0]?.type).toBe("image/jpeg");
    expect(fake.encodeJpeg).toHaveBeenCalledTimes(1);
  });

  it("skips a photo that never gets small enough", async () => {
    const fake = deps({
      fetchBlob: vi.fn(async () => blobOf(MAX_PHOTO_BYTES + 1, "image/jpeg")),
      encodeJpeg: vi.fn(async () => blobOf(MAX_PHOTO_BYTES + 1, "image/jpeg")),
    });
    const { files, skipped } = await preparePhotos([GOOD], fake);
    expect(files).toEqual([]);
    expect(skipped).toBe(1);
    // 3 sizes x 4 qualities, then it gives up.
    expect(fake.encodeJpeg).toHaveBeenCalledTimes(12);
  });

  it("skips a photo the browser cannot decode", async () => {
    const fake = deps({
      fetchBlob: vi.fn(async () => blobOf(5000, "image/avif")),
      encodeJpeg: vi.fn(async () => {
        throw new Error("decode failed");
      }),
    });
    expect((await preparePhotos([GOOD], fake)).skipped).toBe(1);
    expect(fake.encodeJpeg).toHaveBeenCalledTimes(1);
  });

  it("skips a photo the CDN refuses to serve", async () => {
    const fake = deps({
      fetchBlob: vi.fn(async () => {
        throw new Error("403");
      }),
    });
    expect(await preparePhotos([GOOD], fake)).toEqual({
      files: [],
      skipped: 1,
    });
  });

  it("does not even try a host the extension has no permission for", async () => {
    const fake = deps();
    expect(await preparePhotos([BAD_HOST], fake)).toEqual({
      files: [],
      skipped: 1,
    });
    expect(fake.fetchBlob).not.toHaveBeenCalled();
  });

  it("keeps the photos that worked, in order, and counts the rest", async () => {
    const { files, skipped } = await preparePhotos([GOOD, BAD_HOST, OTHER], deps());
    expect(files.map((file) => file.name)).toEqual(["photo-1.jpg", "photo-3.jpg"]);
    expect(skipped).toBe(1);
  });

  it("reports every photo skipped when none can be prepared", async () => {
    const result = await preparePhotos([BAD_HOST, BAD_HOST], deps());
    expect(result).toEqual({ files: [], skipped: 2 });
  });
});

// Up to ten photos can be selected. Decoding and re-encoding a large photo holds the whole image in
// memory, so preparing all ten at once could exhaust the side panel. At most a few are in flight.
describe("preparePhotos with many photos", () => {
  it("never prepares more than three photos at the same time, and keeps their order", async () => {
    const urls = Array.from(
      { length: 10 },
      (_unused, index) => `https://media.karousell.com/media/photos/products/1/p${index + 1}.jpg`,
    );
    let inFlight = 0;
    let peak = 0;
    const fake: PhotoDeps = {
      fetchBlob: async () => {
        inFlight += 1;
        peak = Math.max(peak, inFlight);
        // Yield so other photos get the chance to start while this one is "downloading".
        await new Promise((resolve) => setTimeout(resolve, 5));
        inFlight -= 1;
        return blobOf(1000, "image/jpeg");
      },
      encodeJpeg: async () => blobOf(1000, "image/jpeg"),
    };
    const { files, skipped } = await preparePhotos(urls, fake);
    expect(skipped).toBe(0);
    expect(files.map((file) => file.name)).toEqual(
      urls.map((_url, index) => `photo-${index + 1}.jpg`),
    );
    expect(peak).toBeLessThanOrEqual(3);
  });
});
