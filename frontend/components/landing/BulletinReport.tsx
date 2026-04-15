"use client";

/**
 * Scan report styled bulletin for the landing page.
 *
 * Renders the latest bulletin in a medical scan report aesthetic:
 * JetBrains Mono font, dark card background, clinical layout.
 * Bulletin content is parsed markdown — ReactMarkdown with remark-gfm
 * handles headings, bold, tables, lists, and horizontal rules.
 */

// No longer truncating — show full bulletin content
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import type { BulletinResponse } from "@/lib/types";
import { scoreToColour } from "@/lib/colours";

interface BulletinReportProps {
  bulletin: BulletinResponse | null;
  overallScore: number | null;
}

export default function BulletinReport({
  bulletin,
  overallScore,
}: BulletinReportProps) {
  if (!bulletin) {
    return (
      <div
        className="font-mono text-sm border rounded-md p-6 text-slate-500"
        style={{
          backgroundColor: "#0f172a",
          borderColor: "#1e293b",
        }}
      >
        No scan report available.
      </div>
    );
  }

  const dateStr = bulletin.date
    ? new Date(bulletin.date).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    : "Unknown date";

  // Prefer the bulletin's own frozen score over the live score
  const displayScore =
    bulletin.scores?.london_score?.composite_score ?? overallScore;

  return (
    <div
      className="font-mono text-sm border rounded-md overflow-hidden"
      style={{
        backgroundColor: "#0f172a",
        borderColor: "#1e293b",
      }}
    >
      {/* Header */}
      <div className="px-6 pt-5 pb-3 border-b" style={{ borderColor: "#1e293b" }}>
        <div className="text-xs text-slate-500 tracking-widest mb-1">
          CITYSCAN LONDON
        </div>
        <div className="text-xs text-slate-400">
          Daily Health Scan &mdash; {dateStr}
        </div>
        <div className="text-[10px] text-slate-600 mt-0.5">
          Generated every day at 09:00 UTC
        </div>
        {displayScore !== null && displayScore !== undefined && (
          <div className="mt-3 flex items-baseline gap-2">
            <span
              className="text-4xl font-bold"
              style={{ color: scoreToColour(displayScore) }}
            >
              {Math.round(displayScore)}
            </span>
            <span className="text-sm text-slate-500">/ 100</span>
          </div>
        )}
      </div>

      {/* Divider line */}
      <div className="px-6 py-0.5">
        <div className="text-slate-700 text-xs select-none">
          {"─".repeat(40)}
        </div>
      </div>

      {/* Bulletin content */}
      <div
        className="px-6 pb-5 text-xs leading-relaxed text-slate-300 max-h-[60vh] overflow-y-auto"
        style={{ fontFamily: "var(--font-ibm-plex), sans-serif" }}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeSanitize]}
          components={{
            h1: ({ children }) => <h1 className="text-sm font-bold text-[#0ea5e9] mt-3 mb-1 uppercase tracking-wider">{children}</h1>,
            h2: ({ children }) => <h2 className="text-xs font-bold text-[#0ea5e9] mt-3 mb-1 uppercase tracking-wider">{children}</h2>,
            h3: ({ children }) => <h3 className="text-xs font-semibold text-slate-300 mt-2 mb-1">{children}</h3>,
            p: ({ children }) => <p className="text-xs text-slate-300 mb-2 leading-relaxed">{children}</p>,
            strong: ({ children }) => <strong className="text-slate-100 font-semibold">{children}</strong>,
            ul: ({ children }) => <ul className="list-disc list-inside text-xs text-slate-300 mb-2 space-y-0.5">{children}</ul>,
            ol: ({ children }) => <ol className="list-decimal list-inside text-xs text-slate-300 mb-2 space-y-0.5">{children}</ol>,
            li: ({ children }) => <li className="text-xs text-slate-300">{children}</li>,
            table: ({ children }) => <table className="w-full text-xs text-slate-300 mb-2 border-collapse">{children}</table>,
            thead: ({ children }) => <thead className="border-b border-slate-700">{children}</thead>,
            th: ({ children }) => <th className="text-left py-1 pr-3 text-[#0ea5e9] font-semibold text-[10px] uppercase tracking-wider">{children}</th>,
            td: ({ children }) => <td className="py-1 pr-3 text-slate-300 font-mono text-[11px]">{children}</td>,
            hr: () => <hr className="border-slate-700 my-2" />,
            blockquote: ({ children }) => <blockquote className="border-l-2 border-[#0ea5e9] pl-3 text-slate-400 italic my-2">{children}</blockquote>,
            em: ({ children }) => <em className="text-slate-400 italic">{children}</em>,
            a: ({ children, href }) => <a href={href?.startsWith("http") ? href : "#"} className="text-[#0ea5e9] underline hover:text-[#38bdf8] transition-colors" target="_blank" rel="noopener noreferrer">{children}</a>,
          }}
        >
          {bulletin.content}
        </ReactMarkdown>
      </div>

      {/* Footer */}
      <div
        className="px-6 py-3 border-t text-[10px] text-slate-600"
        style={{ borderColor: "#1e293b" }}
      >
        <div>ATTENDING: Dr. CityScan AI</div>
        <div>MODEL: Claude Sonnet 4.5</div>
      </div>
    </div>
  );
}
