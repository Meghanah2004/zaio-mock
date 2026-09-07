import { useTilt } from "../hooks/useTilt";
import { CheckIcon, ZMark } from "./icons";

export function Hero() {
  const visualRef = useTilt<HTMLDivElement>(6);

  return (
    <div className="hero fade-in-up">
      <div className="hero__content">
        <span className="hero__eyebrow">AI Assessment Workspace</span>
        <h1 className="hero__headline">
          Generate
          <br />
          <span className="hero__headline-accent">validated</span>
          <br />
          assessments.
        </h1>
        <p className="hero__lede">
          Create a Software Developer practice assessment,
          marking memo, validation report and PDFs from
          the supplied reference corpus.
        </p>
        <div className="hero__features">
          <div className="hero__feature">
            <span className="hero__feature-icon hero__feature-icon--ref" aria-hidden="true">
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M2.5 5.5A1.5 1.5 0 014 4h4l1.5 2h6.5A1.5 1.5 0 0117.5 7.5v7a1.5 1.5 0 01-1.5 1.5h-12A1.5 1.5 0 012.5 14.5v-9z" /></svg>
            </span>
            <div>
              <strong className="hero__feature-title">Reference Driven</strong>
              <span className="hero__feature-desc">Uses real curriculum standards</span>
            </div>
          </div>
          <div className="hero__feature">
            <span className="hero__feature-icon hero__feature-icon--val" aria-hidden="true">
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M10 2.5L3.5 5.5V10c0 4.5 3 7.5 6.5 8.5 3.5-1 6.5-4 6.5-8.5V5.5L10 2.5z" /></svg>
            </span>
            <div>
              <strong className="hero__feature-title">Validated Output</strong>
              <span className="hero__feature-desc">Deterministic checks and quality review</span>
            </div>
          </div>
          <div className="hero__feature">
            <span className="hero__feature-icon hero__feature-icon--rdy" aria-hidden="true">
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4.5 3.5A1.5 1.5 0 016 2h5.5L16 6.5V16.5A1.5 1.5 0 0114.5 18h-8.5A1.5 1.5 0 014.5 16.5v-13z" /><path d="M11 2v5h5M7.5 10.5h5M7.5 14h3" /></svg>
            </span>
            <div>
              <strong className="hero__feature-title">Ready to Use</strong>
              <span className="hero__feature-desc">Assessment, memo and PDFs</span>
            </div>
          </div>
        </div>
      </div>

      <div className="hero-visual" aria-hidden="true">
        <div className="hero-visual__glow" />
        <div className="hero-visual__stage" ref={visualRef}>
          <div className="hero-visual__sheet hero-visual__sheet--back">
            <span className="hero-visual__line hero-visual__line--sm" />
            <span className="hero-visual__line" />
            <span className="hero-visual__line hero-visual__line--sm" />
          </div>
          <div className="hero-visual__sheet hero-visual__sheet--mid">
            <span className="hero-visual__line hero-visual__line--sm" />
            <span className="hero-visual__line" />
            <span className="hero-visual__line hero-visual__line--sm" />
          </div>
          <div className="hero-visual__sheet hero-visual__sheet--front">
            <ZMark className="hero-visual__watermark" />
            <span className="hero-visual__line hero-visual__line--sm" />
            <span className="hero-visual__line" />
            <span className="hero-visual__line hero-visual__line--sm" />
            <span className="hero-visual__line hero-visual__line--sm" />
          </div>
          <div className="hero-visual__node">
            <CheckIcon />
          </div>
          <span className="hero-visual__particle hero-visual__particle--a" />
          <span className="hero-visual__particle hero-visual__particle--b" />
          <span className="hero-visual__particle hero-visual__particle--c" />
        </div>
      </div>
    </div>
  );
}
