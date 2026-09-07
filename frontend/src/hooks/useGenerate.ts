import { useCallback, useState } from "react";
import { ApiError, generateAssessment } from "../services/api";
import type { GenerateRequest, GenerateResponse } from "../types/api";

export type GenerateState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: GenerateResponse }
  | { status: "error"; error: ApiError };

export function useGenerate() {
  const [state, setState] = useState<GenerateState>({ status: "idle" });

  const run = useCallback(async (body: GenerateRequest) => {
    setState({ status: "loading" });
    try {
      const data = await generateAssessment(body);
      setState({ status: "success", data });
    } catch (err) {
      const apiError =
        err instanceof ApiError ? err : new ApiError("network", "Could not reach the server. Check your connection and try again.");
      setState({ status: "error", error: apiError });
    }
  }, []);

  const reset = useCallback(() => setState({ status: "idle" }), []);

  return { state, run, reset };
}
