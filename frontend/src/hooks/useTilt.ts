import { useEffect, useRef } from "react";

/**
 * A very small mouse-follow 3D tilt, driven entirely by mutating CSS
 * custom properties (--tilt-x/--tilt-y) on the DOM node directly - never
 * React state - so mouse movement never triggers a re-render. Skipped
 * entirely for touch/coarse pointers and prefers-reduced-motion (CSS
 * consumers should mirror that with their own @media fallback). Purely
 * decorative: nothing depends on hover/tilt to convey information.
 */
export function useTilt<T extends HTMLElement>(maxDegrees = 3) {
  const ref = useRef<T>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof window.matchMedia !== "function") return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const coarsePointer = window.matchMedia("(pointer: coarse)").matches;
    if (reducedMotion || coarsePointer) return;

    function handleMouseMove(event: MouseEvent) {
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const px = (event.clientX - rect.left) / rect.width - 0.5;
      const py = (event.clientY - rect.top) / rect.height - 0.5;
      el.style.setProperty("--tilt-x", `${(-py * maxDegrees).toFixed(2)}deg`);
      el.style.setProperty("--tilt-y", `${(px * maxDegrees).toFixed(2)}deg`);
    }

    function handleMouseLeave() {
      el?.style.setProperty("--tilt-x", "0deg");
      el?.style.setProperty("--tilt-y", "0deg");
    }

    el.addEventListener("mousemove", handleMouseMove);
    el.addEventListener("mouseleave", handleMouseLeave);
    return () => {
      el.removeEventListener("mousemove", handleMouseMove);
      el.removeEventListener("mouseleave", handleMouseLeave);
    };
  }, [maxDegrees]);

  return ref;
}
