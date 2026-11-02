// Pins how the listing's own photos are told apart from icons and unrelated thumbnails.
// The rules follow the Data Collector's extension (collectPageData), which was tested on real
// Mudah.my and Carousell pages:
//   - photos named in the page's structured data come first;
//   - large rendered images (at least 160 x 160) are gallery photos;
//   - small images (at least 48 x 48) count only when they sit in the same CDN folder as a large
//     gallery photo (galleries often render the non-selected photos as thumbnails);
//   - only https URLs count; SVGs and data: URLs are dropped; duplicates are removed; the result
//     is capped (default 12).
import { describe, expect, it } from "vitest";
import { directoryKey, selectGalleryImages, type ImageCandidate } from "../../lib/capture/images";

// A photo folder on an allowed CDN host; the tests add file names to it.
const CDN = "https://media.karousell.com/photos/1";

/** Builds an image candidate; the size is what the page rendered. */
function img(url: string, width: number, height: number): ImageCandidate {
  return { url, width, height };
}

describe("directoryKey", () => {
  it("is the host plus the folder, so thumbnails can be matched to their full-size photo", () => {
    expect(directoryKey(`${CDN}/a.jpg`)).toBe("media.karousell.com/photos/1/");
  });

  it("returns null for something that is not a URL", () => {
    expect(directoryKey("nope")).toBeNull();
  });
});

describe("selectGalleryImages", () => {
  it("puts structured-data photos first and removes duplicates", () => {
    const result = selectGalleryImages(
      [img(`${CDN}/b.jpg`, 600, 400), img(`${CDN}/a.jpg`, 600, 400)],
      [`${CDN}/a.jpg`],
    );
    expect(result).toEqual([`${CDN}/a.jpg`, `${CDN}/b.jpg`]);
  });

  it("keeps small thumbnails only when they share a folder with a large photo", () => {
    const result = selectGalleryImages(
      [
        img(`${CDN}/big.jpg`, 640, 480),
        img(`${CDN}/thumb.jpg`, 80, 80),
        img("https://media.karousell.com/related/9/thumb.jpg", 80, 80),
      ],
      [],
    );
    expect(result).toEqual([`${CDN}/big.jpg`, `${CDN}/thumb.jpg`]);
  });

  it("drops icons that are too small", () => {
    expect(
      selectGalleryImages([img(`${CDN}/big.jpg`, 640, 480), img(`${CDN}/icon.png`, 24, 24)], []),
    ).toEqual([`${CDN}/big.jpg`]);
  });

  it("drops svg, http, and data: sources", () => {
    const result = selectGalleryImages(
      [
        img(`${CDN}/logo.svg`, 640, 480),
        img("http://media.karousell.com/photos/1/plain.jpg", 640, 480),
        img("data:image/png;base64,AAAA", 640, 480),
        img(`${CDN}/ok.jpg`, 640, 480),
      ],
      [],
    );
    expect(result).toEqual([`${CDN}/ok.jpg`]);
  });

  it("caps the number of photos", () => {
    const many = Array.from({ length: 20 }, (_, index) => img(`${CDN}/p${index}.jpg`, 640, 480));
    expect(selectGalleryImages(many, [])).toHaveLength(12);
    expect(selectGalleryImages(many, [], 3)).toHaveLength(3);
  });

  it("returns an empty list when there is nothing usable", () => {
    expect(selectGalleryImages([], [])).toEqual([]);
  });
});
