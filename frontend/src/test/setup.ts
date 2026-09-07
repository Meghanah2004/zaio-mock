import "@testing-library/jest-dom/vitest";

// jsdom does not implement window.matchMedia (a real gap in the test
// environment, not something any supported browser lacks) - components
// that check prefers-reduced-motion / pointer:coarse (see MetricCard's
// mouse-tilt effect) need this to exist. Defaults to "no match" for every
// query, which exercises the same code path as a normal desktop browser
// with no reduced-motion/coarse-pointer preference set.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}
