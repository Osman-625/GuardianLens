// Test runner settings for the shared package.
// jsdom gives component tests a browser-like document. Tests that need Node's own
// fetch/Response/FormData (the API client tests) opt out with a
// `// @vitest-environment node` comment on their first line.
import { defineConfig } from "vitest/config";

export default defineConfig({
  // Compile JSX with the automatic runtime so test files do not import React.
  esbuild: { jsx: "automatic" },
  test: {
    environment: "jsdom",
    // Registers the jest-dom matchers and unmounts rendered components after each test.
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
  },
});
