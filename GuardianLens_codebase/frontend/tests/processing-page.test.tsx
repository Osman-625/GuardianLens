// Pins the processing page's polling: it follows the check to the result, tries again when a
// status request never reaches the server (the check keeps running there), stops at once on a real
// answer from the API, and stops asking when the page is left.
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProcessingPage from "../app/assess/[id]/processing/page";
import { GuardianLensApiError, apiFetch } from "../lib/api";

const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "a1" }),
  useRouter: () => router,
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  apiFetch: vi.fn(),
}));

const processing = { status: "processing", stage: "visual", message: null };
const complete = { status: "complete", stage: null, message: null };
const lost = () => new TypeError("Failed to fetch");

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.resetAllMocks();
});

/** Lets the page's 900 ms timer fire (and its request settle) `times` times. */
async function tick(times = 1) {
  for (let count = 0; count < times; count += 1) {
    await act(async () => vi.advanceTimersByTimeAsync(900));
  }
}

describe("processing page polling", () => {
  it("opens the result when the check completes", async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce(processing).mockResolvedValueOnce(complete);
    render(<ProcessingPage />);
    await tick(2);
    expect(router.replace).toHaveBeenCalledWith("/assess/a1");
  });

  it("clears the saved form draft when the check completes, but keeps it when the check fails", async () => {
    window.sessionStorage.setItem("guardianlens-draft", '{"title":"Used laptop"}');
    vi.mocked(apiFetch).mockResolvedValueOnce({ status: "failed", stage: null, message: "No." });
    const failed = render(<ProcessingPage />);
    await tick(1);
    expect(window.sessionStorage.getItem("guardianlens-draft")).not.toBeNull();
    failed.unmount();

    vi.mocked(apiFetch).mockResolvedValueOnce(complete);
    render(<ProcessingPage />);
    await tick(1);
    expect(window.sessionStorage.getItem("guardianlens-draft")).toBeNull();
  });

  it("tries again when a status request never reaches the server", async () => {
    vi.mocked(apiFetch)
      .mockRejectedValueOnce(lost())
      .mockRejectedValueOnce(lost())
      .mockResolvedValueOnce(complete);
    render(<ProcessingPage />);
    await tick(3);
    expect(apiFetch).toHaveBeenCalledTimes(3);
    expect(router.replace).toHaveBeenCalledWith("/assess/a1");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("gives up after three lost requests in a row", async () => {
    vi.mocked(apiFetch).mockRejectedValue(lost());
    render(<ProcessingPage />);
    await tick(6);
    expect(apiFetch).toHaveBeenCalledTimes(4);
    expect(screen.getByRole("alert")).toHaveTextContent("could not get the status");
  });

  it("counts lost requests in a row, not in total", async () => {
    vi.mocked(apiFetch)
      .mockRejectedValueOnce(lost())
      .mockRejectedValueOnce(lost())
      .mockResolvedValueOnce(processing)
      .mockRejectedValueOnce(lost())
      .mockRejectedValueOnce(lost())
      .mockResolvedValueOnce(complete);
    render(<ProcessingPage />);
    await tick(6);
    expect(router.replace).toHaveBeenCalledWith("/assess/a1");
  });

  it("stops at once on a real answer from the API, even an error", async () => {
    vi.mocked(apiFetch).mockRejectedValue(
      new GuardianLensApiError(404, {
        error: { code: "not_found", message: "Not found.", field: null },
      }),
    );
    render(<ProcessingPage />);
    await tick(3);
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toHaveTextContent("could not get the status");
  });

  it("shows the server's reason when the check failed", async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      status: "failed",
      stage: null,
      message: "The check could not be completed. Try again with the saved form.",
    });
    render(<ProcessingPage />);
    await tick();
    expect(screen.getByRole("alert")).toHaveTextContent("Try again with the saved form");
  });

  it("stops asking when the page is left", async () => {
    vi.mocked(apiFetch).mockResolvedValue(processing);
    const { unmount } = render(<ProcessingPage />);
    await tick();
    const callsBefore = vi.mocked(apiFetch).mock.calls.length;
    unmount();
    await tick(3);
    expect(apiFetch).toHaveBeenCalledTimes(callsBefore);
  });
});
