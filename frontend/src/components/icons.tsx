/**
 * Hand-rolled inline SVG icons - deliberately not a package. Only the
 * handful the UI actually needs (status + theme), each tiny and
 * dependency-free.
 */
import type { SVGProps } from "react";

function Svg(props: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props} />;
}

export function CheckIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <path d="M4 10.5l4 4 8-9" />
    </Svg>
  );
}

export function WarningIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <path d="M10 3l8.5 14.5H1.5L10 3z" />
      <path d="M10 8.5v3.5" />
      <circle cx="10" cy="14.5" r="0.6" fill="currentColor" stroke="none" />
    </Svg>
  );
}

export function CrossIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <path d="M5 5l10 10M15 5L5 15" />
    </Svg>
  );
}

export function SunIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <circle cx="10" cy="10" r="3.5" />
      <path d="M10 2v2M10 16v2M18 10h-2M4 10H2M15.5 4.5l-1.4 1.4M5.9 14.1l-1.4 1.4M15.5 15.5l-1.4-1.4M5.9 5.9L4.5 4.5" />
    </Svg>
  );
}

export function MoonIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <path d="M17 11.5A7 7 0 118.5 3a5.5 5.5 0 108.5 8.5z" />
    </Svg>
  );
}

export function DownloadIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Svg {...props}>
      <path d="M10 3v10M6 9l4 4 4-4M4 16.5h12" />
    </Svg>
  );
}

export function ZMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 28 28" fill="none" aria-hidden="true" {...props}>
      <defs>
        <linearGradient id="zaio-delta-grad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#38bdf8" />
          <stop offset="50%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#6366f1" />
        </linearGradient>
      </defs>
      <path
        d="M14 3L25.5 24.5H19.2L14 14L8.8 24.5H2.5L14 3Z"
        fill="url(#zaio-delta-grad)"
      />
    </svg>
  );
}

/** Header/brand "Z" mark - same viewBox and gradient treatment as ZMark,
 * but its own component (not a variant of ZMark) so restyling the header
 * logo never touches ZMark's other use as the hero illustration's
 * watermark. Its own gradient id avoids a duplicate-id SVG collision with
 * ZMark, since both render at once on the home page. */
export function BrandMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 28 28" fill="none" aria-hidden="true" {...props}>
      <defs>
        <linearGradient id="zaio-brand-mark-grad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#38bdf8" />
          <stop offset="50%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#6366f1" />
        </linearGradient>
      </defs>
      <path
        d="M3 5L25 5L3 23L25 23"
        stroke="url(#zaio-brand-mark-grad)"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
