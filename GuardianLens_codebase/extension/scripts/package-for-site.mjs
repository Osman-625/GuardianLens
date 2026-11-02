// Copies the extension zip built by `wxt zip` into the website's public downloads folder, so the
// landing page's "Get the extension" button has something to download.
// Run it through `npm run package:site -w extension`, which zips first and then runs this file.
// The destination is git-ignored (and so is every *.zip), because it is a build product.
import { copyFileSync, existsSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// The extension package's folder (one level above this script), and the folder `wxt zip` writes to.
const extensionRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const outputDir = join(extensionRoot, ".output");

// wxt names the file <extension name>-<version>-chrome.zip (for example
// guardianlensextension-0.1.0-chrome.zip). `zips` lists the matching files, newest first.
const zips = existsSync(outputDir)
  ? readdirSync(outputDir)
      .filter((name) => name.endsWith("-chrome.zip"))
      .map((name) => ({
        name,
        modified: statSync(join(outputDir, name)).mtimeMs,
      }))
      .sort((a, b) => b.modified - a.modified)
  : [];

if (zips.length === 0) {
  console.error(
    "No *-chrome.zip found in extension/.output. Run `npm run zip -w extension` first.",
  );
  process.exit(1);
}

// Copy the newest zip into the website's downloads folder under the fixed name the landing page links to.
const newest = zips[0];
const target = resolve(extensionRoot, "..", "frontend", "public", "downloads");
mkdirSync(target, { recursive: true });
copyFileSync(join(outputDir, newest.name), join(target, "guardianlens-extension.zip"));
console.log(`Copied ${newest.name} to frontend/public/downloads/guardianlens-extension.zip`);
