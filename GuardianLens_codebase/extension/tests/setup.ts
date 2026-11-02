// Runs before every test file in the extension package.
// 1. Adds the jest-dom matchers to expect().
// 2. Resets the in-memory fake browser before each test so storage never leaks between tests.
// 3. Unmounts anything a test rendered (Testing Library only does this by itself when test
//    globals are on, and we keep them off).
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import { fakeBrowser } from "wxt/testing/fake-browser";

beforeEach(() => fakeBrowser.reset());
afterEach(() => cleanup());
