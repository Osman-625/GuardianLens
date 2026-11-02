// Component test settings for the website.
// The "@" alias matches the one Next.js uses, so tests can import "@/lib/..." like the pages do.
// jsdom gives the tests a browser-like document, and the shared package's setup file registers the
// jest-dom matchers and unmounts rendered components after each test.
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["../shared/tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
