/**
 * BulletinPanel — side panel that renders the latest daily bulletin.
 *
 * Bulletin content is parsed markdown — ReactMarkdown with remark-gfm
 * handles headings, bold, tables, lists, and horizontal rules.
 * If no bulletin is available, shows a placeholder message.
 * Slides in from the right via the `slide-in-right` CSS class.
 */

"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { X } from "lucide-react";
import type { BulletinResponse } from "@/lib/types";

interface BulletinPanelProps {
  bulletin: BulletinResponse | null;
  onClose: () => void;
}

export default function BulletinPanel({
  bulletin,
  onClose,
}: BulletinPanelProps) {
  return (
    <div
      className="h-full flex flex-col"
      style={{ background: "#0f172a", borderLeft: "1px solid #1e293b" }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 flex-shrink-0"
        style={{ borderBottom: "1px solid #1e293b" }}
      >
        <span
          className="text-sm font-semibold text-slate-100 uppercase tracking-widest"
        >
          DAILY BULLETIN
        </span>
        <button
          onClick={onClose}
          className="p-1 rounded text-[#64748b] hover:text-slate-200 transition-colors duration-200"
          aria-label="Close bulletin panel"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {bulletin ? (
          <>
            {/* Date badge */}
            <div className="mb-3">
              <span className="text-xs text-[#64748b] font-mono">
                {bulletin.date}
              </span>
              <span className="text-[10px] text-[#475569] ml-2">
                Generated every day at 09:00 UTC
              </span>
            </div>

            {/* Bulletin text — IBM Plex Sans, rendered markdown */}
            <div
              style={{
                fontFamily: "var(--font-ibm-plex, 'IBM Plex Sans', sans-serif)",
              }}
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeSanitize]}
                components={{
                  h1: ({ children }) => <h1 className="text-sm font-bold text-[#0ea5e9] mt-3 mb-1 uppercase tracking-wider">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-sm font-bold text-[#0ea5e9] mt-3 mb-1 uppercase tracking-wider">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-sm font-semibold text-slate-300 mt-2 mb-1">{children}</h3>,
                  p: ({ children }) => <p className="text-sm text-slate-200 mb-2 leading-relaxed">{children}</p>,
                  strong: ({ children }) => <strong className="text-slate-100 font-semibold">{children}</strong>,
                  ul: ({ children }) => <ul className="list-disc list-inside text-sm text-slate-200 mb-2 space-y-0.5">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal list-inside text-sm text-slate-200 mb-2 space-y-0.5">{children}</ol>,
                  li: ({ children }) => <li className="text-sm text-slate-200">{children}</li>,
                  table: ({ children }) => <table className="w-full text-sm text-slate-200 mb-2 border-collapse">{children}</table>,
                  thead: ({ children }) => <thead className="border-b border-slate-700">{children}</thead>,
                  th: ({ children }) => <th className="text-left py-1 pr-3 text-[#0ea5e9] font-semibold text-xs uppercase tracking-wider">{children}</th>,
                  td: ({ children }) => <td className="py-1 pr-3 text-slate-200 font-mono text-sm">{children}</td>,
                  hr: () => <hr className="border-slate-700 my-2" />,
                  blockquote: ({ children }) => <blockquote className="border-l-2 border-[#0ea5e9] pl-3 text-slate-400 italic my-2">{children}</blockquote>,
                  em: ({ children }) => <em className="text-slate-400 italic">{children}</em>,
                }}
              >
                {bulletin.content}
              </ReactMarkdown>
            </div>
          </>
        ) : (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <p
              className="text-sm text-[#64748b]"
              style={{
                fontFamily: "var(--font-ibm-plex, 'IBM Plex Sans', sans-serif)",
              }}
            >
              No bulletin available yet.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
