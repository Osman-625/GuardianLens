// Fixture recorder (developer tool, not part of the shipped extension).
//
// What it does: copies the page you are looking at into a sanitised, self-contained HTML
// file so the adapter tests can run against a real Mudah.my or Carousell page without
// needing a network or a login.
//
// How to use: paste this whole file into the DevTools console on a live page, then run
//   recordFixture("listing")   on a listing page, or
//   recordFixture("seller")    on a seller / profile page.
// The browser downloads "<host>-<kind>.html". Open it and check it for personal data before
// using it. Recorded files stay local and are never committed.
(() => {
  // Elements that must never be dropped for being "hidden" (they are not rendered anyway).
  const SKIP_HIDING = new Set([
    "HTML",
    "HEAD",
    "BODY",
    "SCRIPT",
    "STYLE",
    "META",
    "LINK",
    "TITLE",
    "NOSCRIPT",
  ]);
  // Contact details are redacted in every text node, in case the page shows them.
  const EMAIL = /[\w.+-]+@[\w-]+\.[\w.-]+/g;
  const PHONE = /(?<!\d)(?:\+?6?0?1\d[\s.-]?)\d{7,8}(?!\d)/g;

  window.recordFixture = function recordFixture(kind) {
    // Clone the live document, then walk both trees in parallel (same order, same length)
    // so we can read computed layout from the live element and write it onto the copy.
    const liveAll = Array.from(document.documentElement.querySelectorAll("*"));
    const clone = document.documentElement.cloneNode(true);
    const cloneAll = Array.from(clone.querySelectorAll("*"));
    if (liveAll.length !== cloneAll.length)
      throw new Error("The page changed while cloning. Try again.");

    const hidden = [];
    liveAll.forEach((live, index) => {
      const copy = cloneAll[index];
      if (live.tagName === "IMG") {
        // Stamp the rendered size onto the copy. jsdom has no layout engine, so the tests
        // use these width/height attributes to tell gallery photos from small icons.
        const rect = live.getBoundingClientRect();
        copy.setAttribute("width", String(Math.round(rect.width)));
        copy.setAttribute("height", String(Math.round(rect.height)));
        // Pin the URL the browser actually chose (srcset picks one at runtime).
        const source = live.currentSrc || live.src;
        if (source) copy.setAttribute("src", source);
        copy.removeAttribute("srcset");
        copy.removeAttribute("sizes");
      }
      // Elements hidden by CSS are not part of what a buyer sees, so they are dropped.
      if (
        !SKIP_HIDING.has(live.tagName) &&
        getComputedStyle(live).display === "none"
      )
        hidden.push(copy);
    });
    hidden.forEach((node) => node.remove());

    // Strip everything the adapters never read. JSON-LD scripts are kept on purpose:
    // they are one of the main data sources for title, price, and photos.
    clone
      .querySelectorAll(
        "script:not([type='application/ld+json']), style, noscript, iframe, svg, link[rel='stylesheet']",
      )
      .forEach((node) => node.remove());
    clone
      .querySelectorAll("[style]")
      .forEach((node) => node.removeAttribute("style"));

    // Redact contact details in text and drop HTML comments.
    const walker = document.createTreeWalker(
      clone,
      NodeFilter.SHOW_TEXT | NodeFilter.SHOW_COMMENT,
    );
    const comments = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.nodeType === Node.COMMENT_NODE) comments.push(node);
      else
        node.nodeValue = node.nodeValue
          .replace(EMAIL, "[email]")
          .replace(PHONE, "[phone]");
    }
    comments.forEach((node) => node.remove());

    // Download the result as a file.
    const html = "<!doctype html>\n" + clone.outerHTML;
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    link.download = `${location.hostname}-${kind}.html`;
    link.click();
    URL.revokeObjectURL(link.href);
    return { kind, characters: html.length, host: location.hostname };
  };
})();
