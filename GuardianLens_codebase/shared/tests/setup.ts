// Runs before every test file in this package.
// 1. Adds the jest-dom matchers (toBeInTheDocument, toHaveAccessibleName, ...) to expect().
// 2. Unmounts anything a test rendered so tests cannot affect each other. Testing Library
//    only does this on its own when test globals are enabled, and we keep them off.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());
