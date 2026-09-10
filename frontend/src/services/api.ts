import type { ErrorResponse, GenerateRequest, GenerateResponse, HealthResponse, ResultResponse } from "../types/api";

/**
 * Base URL of the FastAPI backend. Configurable via a Vite env var so the
 * frontend never hardcodes a deployment's infrastructure. Defaults to the
 * backend's documented local dev address (docs/API.md, "Local
 * development": `uvicorn api.app:app --reload`, which binds `127.0.0.1`
 * specifically, not the IPv6/wildcard address - see below).
 *
 * REWORK (real, observed local failure): the default here used to be
 * `http://localhost:8000`. On a machine where `localhost` resolves to
 * `::1` (IPv6) before `127.0.0.1`, a request to that ambiguous hostname
 * can silently reach a completely different, unrelated process also bound
 * to port 8000 on the wildcard/IPv6 address instead of this backend - not
 * a CORS error, not a crash, just the wrong server answering with its own
 * (unrelated) response shape, which every caller here would see as a
 * generic network/server failure with no useful diagnostic. Defaulting to
 * the explicit, unambiguous loopback address sidesteps that resolution
 * order entirely, matching the backend's own explicit `127.0.0.1` bind.
 *
 * This is a plain, non-secret value (a URL, not a credential) - safe to
 * embed in the built frontend bundle, unlike an API key.
 */
const configuredApiBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "");
const API_BASE_URL: string = configuredApiBaseUrl ?? (import.meta.env.DEV ? "http://127.0.0.1:8000" : "");

/** One discriminated-union error type the UI can switch on to choose wording. */
export type ApiErrorKind = "validation" | "rate_limited" | "not_found" | "server" | "network";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly retryAfterSeconds: number | null;
  readonly requestId: string | null;

  constructor(kind: ApiErrorKind, message: string, options: { status?: number | null; retryAfterSeconds?: number | null; requestId?: string | null } = {}) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status ?? null;
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
    this.requestId = options.requestId ?? null;
  }
}

function kindForStatus(status: number): ApiErrorKind {
  if (status === 422 || status === 400) return "validation";
  if (status === 429) return "rate_limited";
  if (status === 404) return "not_found";
  return "server";
}

async function parseErrorBody(response: Response): Promise<ErrorResponse["error"] | null> {
  try {
    const body = (await response.json()) as Partial<ErrorResponse>;
    if (body && typeof body === "object" && "error" in body && body.error) {
      return body.error as ErrorResponse["error"];
    }
  } catch {
    // Response wasn't JSON (or was empty) - fall through to a generic message.
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError("network", "Could not reach the server. Check your connection and try again.");
  }

  if (!response.ok) {
    const kind = kindForStatus(response.status);
    const errorBody = await parseErrorBody(response);
    const retryAfterHeader = response.headers.get("Retry-After");

    if (kind === "rate_limited") {
      throw new ApiError("rate_limited", "Too many requests. Please wait a moment and try again.", {
        status: response.status,
        retryAfterSeconds: retryAfterHeader ? Number(retryAfterHeader) : null,
        requestId: errorBody?.request_id ?? null,
      });
    }
    if (kind === "validation") {
      throw new ApiError("validation", errorBody?.message ?? "The request was invalid. Please check the form and try again.", {
        status: response.status,
        requestId: errorBody?.request_id ?? null,
      });
    }
    if (kind === "not_found") {
      throw new ApiError("not_found", errorBody?.message ?? "That result could not be found.", {
        status: response.status,
        requestId: errorBody?.request_id ?? null,
      });
    }
    throw new ApiError("server", "Something went wrong on the server. Please try again shortly.", {
      status: response.status,
      requestId: errorBody?.request_id ?? null,
    });
  }

  return (await response.json()) as T;
}

export function checkHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health");
}

export function generateAssessment(body: GenerateRequest): Promise<GenerateResponse> {
  return request<GenerateResponse>("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getResult(resultId: number): Promise<ResultResponse> {
  return request<ResultResponse>(`/api/results/${resultId}`);
}

export function paperPdfUrl(resultId: number): string {
  return `${API_BASE_URL}/api/results/${resultId}/paper.pdf`;
}

export function memoPdfUrl(resultId: number): string {
  return `${API_BASE_URL}/api/results/${resultId}/memo.pdf`;
}
