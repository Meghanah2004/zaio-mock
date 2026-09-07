import { createContext, useContext } from "react";

/**
 * The smallest router that actually satisfies the app's needs: four
 * static routes plus one dynamic /assessments/:id. A full routing
 * library (react-router et al.) would be a large dependency for four
 * pages - see router.tsx (the RouterProvider) for the ~20 lines this
 * takes on top of the native History API instead.
 */
export interface RouteState {
  pathname: string;
  navigate: (path: string) => void;
}

export const RouterContext = createContext<RouteState | null>(null);

export function useRoute(): RouteState {
  const ctx = useContext(RouterContext);
  if (!ctx) throw new Error("useRoute must be used within a RouterProvider");
  return ctx;
}

/** /assessments/2 -> 2; anything else -> null. Never matches non-numeric IDs. */
export function matchAssessmentId(pathname: string): number | null {
  const match = /^\/assessments\/(\d+)\/?$/.exec(pathname);
  return match ? Number(match[1]) : null;
}
