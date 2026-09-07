import type { ReactNode } from "react";
import { useTheme } from "../hooks/useTheme";
import { matchAssessmentId, useRoute } from "../hooks/useRoute";
import { AmbientBackground } from "./AmbientBackground";
import { Header } from "./Header";
import { SystemStatus } from "./SystemStatus";
import { ThemeToggle } from "./ThemeToggle";

const NAV_ITEMS = [
  { path: "/", label: "Home" },
  { path: "/assessments", label: "Assessments" },
  { path: "/documentation", label: "Documentation" },
  { path: "/about", label: "About" },
];

/** /assessments and /assessments/:id both count as the Assessments section being active. */
function isActive(itemPath: string, pathname: string): boolean {
  if (itemPath === "/assessments") return pathname === "/assessments" || matchAssessmentId(pathname) !== null;
  return pathname === itemPath;
}

export function AppShell({ children }: { children: ReactNode }) {
  const { preference, setPreference } = useTheme();
  const { pathname, navigate } = useRoute();

  return (
    <div className="shell">
      <AmbientBackground />
      <header className="shell__header">
        <div className="shell__header-inner">
          <Header />
          <nav className="shell__nav" aria-label="Main navigation">
            {NAV_ITEMS.map(({ path, label }) => {
              const active = isActive(path, pathname);
              return (
                <a
                  key={path}
                  href={path}
                  className={`nav-link${active ? " nav-link--active" : ""}`}
                  aria-current={active ? "page" : undefined}
                  onClick={(event) => {
                    event.preventDefault();
                    navigate(path);
                  }}
                >
                  {label}
                </a>
              );
            })}
          </nav>
          <div className="shell__header-actions">
            <SystemStatus />
            <ThemeToggle preference={preference} onChange={setPreference} />
          </div>
        </div>
      </header>

      <main className="shell__main">{children}</main>

      <footer className="shell__footer">
        <div className="shell__footer-inner">
          <div className="shell__footer-left">
            <span className="footer-brand">ZAIO / Mock EISA</span>
            <span className="text-helper">AI for a fairer, more prepared tomorrow</span>
          </div>
          <span className="text-helper">Built with purpose · Powered by AI ▬</span>
        </div>
      </footer>
    </div>
  );
}
