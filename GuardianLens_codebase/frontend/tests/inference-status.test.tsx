// Pins what the landing page tells the visitor about the running API: neutral wording until /health
// answers, the development-stub warning only for a confirmed stub API, nothing for a confirmed
// trained API, and an honest "could not be reached" for every answer that cannot be trusted.
import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InferenceStatus } from "../components/InferenceStatus";
import { apiFetch } from "../lib/api";

vi.mock("../lib/api", () => ({ apiFetch: vi.fn() }));

// A well-formed /health answer for a stub API (true) or a trained API (false).
const health = (stub: boolean) => ({
  status: "ok",
  stub_mode: stub,
  inference_mode: stub ? "stub" : "trained",
});

afterEach(() => {
  vi.resetAllMocks();
  vi.useRealTimers();
});

describe("landing inference status", () => {
  it("stays neutral until health confirms the running mode", async () => {
    let resolve!: (value: ReturnType<typeof health>) => void;
    vi.mocked(apiFetch).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    render(<InferenceStatus />);

    expect(screen.getByRole("status")).toHaveTextContent("Checking service availability");
    expect(screen.queryByText(/Test mode/)).not.toBeInTheDocument();

    await act(async () => resolve(health(true)));
    expect(screen.getByRole("status")).toHaveTextContent("Test mode");
    expect(apiFetch).toHaveBeenCalledWith("/health", {
      cache: "no-store",
      signal: expect.any(AbortSignal),
    });
  });

  it("removes the notice only when health confirms trained inference", async () => {
    vi.mocked(apiFetch).mockResolvedValue(health(false));
    render(<InferenceStatus />);
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(screen.queryByText(/Test mode/)).not.toBeInTheDocument();
  });

  it.each([{ status: "ok", stub_mode: true, inference_mode: "trained" }, { status: "ok" }, null])(
    "does not treat unverified health as trained: %j",
    async (response) => {
      vi.mocked(apiFetch).mockResolvedValue(response);
      render(<InferenceStatus />);
      await waitFor(() =>
        expect(screen.getByRole("status")).toHaveTextContent("could not be reached"),
      );
      expect(screen.queryByText(/Test mode/)).not.toBeInTheDocument();
    },
  );

  it("explains a health request failure without claiming a model mode", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error("network unavailable"));
    render(<InferenceStatus />);
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("could not be reached"),
    );
  });

  it("stops waiting when the health request times out", async () => {
    vi.useFakeTimers();
    vi.mocked(apiFetch).mockImplementation(
      (_path, options) =>
        new Promise((_resolve, reject) => {
          options?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
        }),
    );
    render(<InferenceStatus />);
    await act(async () => vi.advanceTimersByTimeAsync(10_000));
    expect(screen.getByRole("status")).toHaveTextContent("could not be reached");
  });

  it("ignores an earlier effect's abort after the current request succeeds", async () => {
    let rejectFirst!: (reason: Error) => void;
    vi.mocked(apiFetch)
      .mockReturnValueOnce(
        new Promise((_resolve, reject) => {
          rejectFirst = reject;
        }),
      )
      .mockResolvedValueOnce(health(false));
    render(
      <StrictMode>
        <InferenceStatus />
      </StrictMode>,
    );
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    await act(async () => rejectFirst(new Error("aborted previous effect")));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("cancels the health request when the page is left", () => {
    vi.mocked(apiFetch).mockReturnValue(new Promise(() => {}));
    const { unmount } = render(<InferenceStatus />);
    const signal = vi.mocked(apiFetch).mock.calls[0][1]?.signal;
    unmount();
    expect(signal?.aborted).toBe(true);
  });
});
