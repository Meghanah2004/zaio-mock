import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, checkHealth, generateAssessment, getResult, memoPdfUrl, paperPdfUrl } from "./api";

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

describe("api service", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends POST /api/generate with the exact request body and returns the parsed response on success", async () => {
    const responseBody = {
      result_id: 2,
      paper_id: "mock-eisa-paper-02",
      qualification: "software_developer",
      total_marks: 100,
      validation_passed: true,
      deterministic_checks_passed: 90,
      deterministic_checks_total: 90,
      novelty_status: "pass",
      quality_review_approved: true,
      pdf_available: false,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, responseBody));
    vi.stubGlobal("fetch", fetchMock);

    const result = await generateAssessment({ qualification: "software_developer", paper_number: 2, seed: 20260906, pdf: false });

    expect(result).toEqual(responseBody);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/generate");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ qualification: "software_developer", paper_number: 2, seed: 20260906, pdf: false });
  });

  it("maps a 422 response to a validation ApiError with the server's message", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(422, { error: { code: "VALIDATION_ERROR", message: "Invalid request.", request_id: "req-1" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(generateAssessment({ qualification: "software_developer", paper_number: 2, seed: 1, pdf: false })).rejects.toMatchObject({
      kind: "validation",
      message: "Invalid request.",
      requestId: "req-1",
    });
  });

  it("maps a 429 response to a rate_limited ApiError carrying Retry-After", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(429, { error: { code: "RATE_LIMITED", message: "Rate limit exceeded.", request_id: null } }, { "Retry-After": "30" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    let caught: unknown;
    try {
      await generateAssessment({ qualification: "software_developer", paper_number: 2, seed: 1, pdf: false });
    } catch (err) {
      caught = err;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).kind).toBe("rate_limited");
    expect((caught as ApiError).retryAfterSeconds).toBe(30);
  });

  it("maps a 500 response to a generic server ApiError without leaking the response body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(500, { error: { code: "INTERNAL_ERROR", message: "An unexpected error occurred.", request_id: null } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getResult(2)).rejects.toMatchObject({ kind: "server", status: 500 });
  });

  it("maps a thrown fetch (network failure) to a network ApiError", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    await expect(checkHealth()).rejects.toMatchObject({ kind: "network" });
  });

  it("builds PDF URLs against the configured base URL and result id", () => {
    expect(paperPdfUrl(2)).toMatch(/\/api\/results\/2\/paper\.pdf$/);
    expect(memoPdfUrl(2)).toMatch(/\/api\/results\/2\/memo\.pdf$/);
  });
});
