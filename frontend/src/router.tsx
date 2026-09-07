import { useCallback, useEffect, useState, type ReactNode } from "react";
import { RouterContext } from "./hooks/useRoute";

export function RouterProvider({ children }: { children: ReactNode }) {
  const [pathname, setPathname] = useState(() => window.location.pathname);

  useEffect(() => {
    function onPopState() {
      setPathname(window.location.pathname);
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigate = useCallback((path: string) => {
    if (path !== window.location.pathname) {
      window.history.pushState({}, "", path);
    }
    setPathname(path);
  }, []);

  return <RouterContext.Provider value={{ pathname, navigate }}>{children}</RouterContext.Provider>;
}
