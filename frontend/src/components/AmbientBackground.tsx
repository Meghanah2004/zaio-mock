import { useEffect, useRef } from "react";

const MAX_PARALLAX_PX = 10;

/**
 * Purely decorative, fixed behind all content (see .ambient-bg in
 * styles/index.css). aria-hidden since it conveys no information - two
 * slow, blurred gradient orbs, a faint perspective grid, a static film-
 * grain texture, and a very small mouse-parallax drift on the whole layer.
 * All CSS transform/opacity (no canvas/WebGL). The parallax is driven by
 * mutating a CSS custom property directly on the DOM node - never React
 * state - so mouse movement never triggers a re-render, and it's skipped
 * entirely under prefers-reduced-motion.
 */
export function AmbientBackground() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof window.matchMedia !== "function") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    function handleMouseMove(event: MouseEvent) {
      const px = event.clientX / window.innerWidth - 0.5;
      const py = event.clientY / window.innerHeight - 0.5;
      el?.style.setProperty("--parallax-x", `${(px * MAX_PARALLAX_PX).toFixed(1)}px`);
      el?.style.setProperty("--parallax-y", `${(py * MAX_PARALLAX_PX).toFixed(1)}px`);
    }

    window.addEventListener("mousemove", handleMouseMove, { passive: true });
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, []);

  return (
    <div className="ambient-bg" aria-hidden="true" ref={ref}>
      <div className="ambient-bg__grid" />
      <div className="ambient-bg__orb ambient-bg__orb--a" />
      <div className="ambient-bg__orb ambient-bg__orb--b" />
      <div className="ambient-bg__grain" />
      <div className="ambient-bg__vignette" />
    </div>
  );
}
