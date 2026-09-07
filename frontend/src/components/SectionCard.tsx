import { useId, type ReactNode } from "react";

export function SectionCard({
  eyebrow,
  title,
  titleIcon,
  action,
  tagline,
  children,
  className = "",
}: {
  eyebrow?: ReactNode;
  title?: ReactNode;
  titleIcon?: ReactNode;
  action?: ReactNode;
  tagline?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const titleId = useId();

  return (
    <section className={`card fade-in-up ${className}`.trim()} aria-labelledby={title ? titleId : undefined}>
      {title && (
        <div className="card__header">
          <div className="card__header-left">
            {titleIcon && <span className="card__title-icon" aria-hidden="true">{titleIcon}</span>}
            <div>
              {eyebrow && <p className="card__eyebrow">{eyebrow}</p>}
              <h2 className="text-section-title" id={titleId}>
                {title}
              </h2>
            </div>
          </div>
          <div className="card__header-right">
            {tagline && <span className="card__tagline">{tagline}</span>}
            {action}
          </div>
        </div>
      )}
      <div className="card__body">{children}</div>
    </section>
  );
}
