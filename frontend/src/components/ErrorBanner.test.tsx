import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../services/api";
import { ErrorBanner } from "./ErrorBanner";

describe("ErrorBanner", () => {
  it("shows a clear message for a rate-limited error, including the retry wait", () => {
    render(<ErrorBanner error={new ApiError("rate_limited", "Rate limit exceeded.", { retryAfterSeconds: 30 })} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/too many requests/i);
    expect(screen.getByRole("alert")).toHaveTextContent(/30s/);
  });

  it("shows a generic, non-technical message for a server error", () => {
    render(<ErrorBanner error={new ApiError("server", "boom")} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/something went wrong/i);
  });

  it("shows a connectivity message for a network error", () => {
    render(<ErrorBanner error={new ApiError("network", "unreachable")} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/could not be reached/i);
  });

  it("never renders raw backend exception text", () => {
    render(<ErrorBanner error={new ApiError("server", "Traceback (most recent call last): File \"/app/src/x.py\"")} />);
    expect(screen.getByRole("alert")).not.toHaveTextContent(/traceback/i);
  });
});
