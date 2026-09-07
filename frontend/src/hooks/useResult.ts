import { useCallback, useState } from "react";
import { ApiError, getResult } from "../services/api";
import type { ResultResponse } from "../types/api";

export type ResultState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: ResultResponse }
  | { status: "error"; error: ApiError };

export function useResult() {
  const [state, setState] = useState<ResultState>({ status: "idle" });

  const load = useCallback(async (resultId: number) => {
    setState({ status: "loading" });
    try {
      const data = await getResult(resultId);
      setState({ status: "success", data });
    } catch (err) {
      const apiError =
        err instanceof ApiError ? err : new ApiError("network", "Could not reach the server. Check your connection and try again.");
      setState({ status: "error", error: apiError });
    }
  }, []);

  const reset = useCallback(() => setState({ status: "idle" }), []);

  return { state, load, reset };
}
