// Unit and component test settings for the extension.
// WxtVitest wires in what extension code expects at run time: an in-memory fake of the
// `browser` API (storage, tabs, ...), the "@/..." path aliases, and WXT's build-time globals.
import { defineConfig } from "vitest/config";
import { WxtVitest } from "wxt/testing/vitest-plugin";

export default defineConfig({
  plugins: [WxtVitest()],
  // Compile JSX with the automatic runtime so test and component files do not import React.
  esbuild: { jsx: "automatic" },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    // The Playwright browser specs live in tests/e2e and run with `npm run test:e2e`.
    exclude: ["tests/e2e/**", "node_modules/**"],
  },
});
