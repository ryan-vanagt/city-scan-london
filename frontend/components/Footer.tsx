/**
 * Footer — thin fixed attribution bar at the bottom of the viewport.
 *
 * Shows project attribution, tech stack credits, and links to LinkedIn + GitHub.
 * GitHub and LinkedIn use inline SVG logos (not in Lucide v1.8.0).
 * Font: Inter 12px, muted slate-500 text.
 */

"use client";

interface SocialLinkProps {
  href: string;
  ariaLabel: string;
  children: React.ReactNode;
}

function SocialLink({ href, ariaLabel, children }: SocialLinkProps) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={ariaLabel}
      style={{ color: "#64748b", display: "flex", alignItems: "center" }}
      className="hover:text-slate-300 transition-colors duration-200"
    >
      {children}
    </a>
  );
}

/** LinkedIn "in" logo SVG (18×18) */
function LinkedInIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z" />
      <rect x="2" y="9" width="4" height="12" />
      <circle cx="4" cy="4" r="2" />
    </svg>
  );
}

/** GitHub octocat silhouette SVG (16×16) */
function GitHubIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483
           0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466
           -.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832
           .092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688
           -.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0 1 12 6.844
           a9.59 9.59 0 0 1 2.504.337c1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651
           .64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855
           0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.017
           C22 6.484 17.522 2 12 2z"
      />
    </svg>
  );
}

const SEP = "  •  ";
const ATTRIBUTION = `Ryan Van Agt${SEP}Sources: OpenAQ, GLA LAEI 2022, TfL, Guardian/BBC, Met Police, NHS A&E, GLA Green Cover 2024, IMD 2025, ONS Housing Affordability 2025, ONS Health Index 2021, TfL PTAL 2015${SEP}Powered by Claude Haiku 4.5, LangGraph, DuckDB, ChromaDB`;

export default function Footer() {
  return (
    <footer
      style={{
        background: "#020617",
        borderTop: "1px solid #1e293b",
        paddingTop: 8,
        paddingBottom: 8,
        paddingLeft: 16,
        paddingRight: 16,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
        fontFamily: "var(--font-inter, Inter, sans-serif)",
        fontSize: 12,
        color: "#64748b",
      }}
    >
      {/* Attribution text — the full line is ~1519px at 12px, so the font scales
          with the window to keep it on one row (12px from ~1610px wide); below the
          9px floor it wraps to a second line instead of being cut */}
      <span
        style={{
          flex: 1,
          minWidth: 0,
          fontSize: "clamp(9px, calc((100vw - 96px) / 128), 12px)",
        }}
      >
        {ATTRIBUTION}
      </span>

      {/* Social links */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
        <SocialLink
          href="https://www.linkedin.com/in/ryan-vanagt/"
          ariaLabel="Ryan Van Agt on LinkedIn"
        >
          <LinkedInIcon />
        </SocialLink>
        <SocialLink
          href="https://github.com/ryan-vanagt"
          ariaLabel="Ryan Van Agt on GitHub"
        >
          <GitHubIcon />
        </SocialLink>
      </div>
    </footer>
  );
}
