// Type declarations for the jest-dom matchers (toBeInTheDocument, toHaveTextContent, ...) used by
// the website's component tests.
//
// At run time the matchers are registered by ../shared/tests/setup.ts (see vitest.config.mts). That
// file is outside this package, so TypeScript does not see it, and without this import the
// matchers would be unknown to `expect` and `npm run typecheck` would fail on every test file.
import "@testing-library/jest-dom/vitest";
