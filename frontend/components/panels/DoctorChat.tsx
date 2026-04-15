/**
 * DoctorChat — SSE streaming chat panel styled as a medical consultation.
 *
 * - Streams tokens from POST /agent/query via the async generator in lib/api.ts
 * - Typewriter effect: appends tokens to the current assistant message as they arrive
 * - After [DONE]: marks message complete and shows collapsible source cards
 * - If `prefill` prop is set, auto-submits on mount
 * - Uses JetBrains Mono for assistant responses (medical readout feel)
 * - Slides in from the right on mount
 */

"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { X, Send, ChevronDown, ChevronRight } from "lucide-react";
import type { ChatMessage, SSESourcesEvent } from "@/lib/types";
import { streamDoctorQuery } from "@/lib/api";

interface DoctorChatProps {
  onClose: () => void;
  prefill?: string;
  overallScore: number | null;
}

interface SourceCardProps {
  source: SSESourcesEvent["sources"][number];
}

function SourceCard({ source }: SourceCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className="rounded text-xs mt-1 overflow-hidden"
      style={{ border: "1px solid #1e293b" }}
    >
      <button
        className="w-full flex items-center gap-1.5 px-2 py-1.5 text-left transition-colors duration-150"
        style={{ background: "#0f172a", color: "#64748b" }}
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? (
          <ChevronDown size={12} className="flex-shrink-0" />
        ) : (
          <ChevronRight size={12} className="flex-shrink-0" />
        )}
        <span className="font-mono">
          Data source
        </span>
      </button>

      {expanded && (
        <pre
          className="px-3 py-2 text-xs overflow-x-auto text-slate-400 font-mono"
          style={{ background: "#020617", maxHeight: 200 }}
        >
          {JSON.stringify(source.data, null, 2)}
        </pre>
      )}
    </div>
  );
}

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export default function DoctorChat({
  onClose,
  prefill,
  overallScore,
}: DoctorChatProps) {
  const greeting = getGreeting();
  const scoreDisplay =
    overallScore !== null ? `${Math.round(overallScore)}/100` : "unavailable";

  const initialMessage: ChatMessage = {
    role: "assistant",
    content: `${greeting}. London's overall health is ${scoreDisplay} today. What would you like to know?`,
    isStreaming: false,
  };

  const [messages, setMessages] = useState<ChatMessage[]>([initialMessage]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [cooldown, setCooldown] = useState(false);
  const [accessCode, setAccessCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const hasAutofiredRef = useRef(false);
  const lastQueryRef = useRef<number>(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const QUERY_COOLDOWN_MS = 3000;

  // Abort any in-flight SSE stream on unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  // Scroll to bottom whenever messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-submit prefill on mount (only once)
  useEffect(() => {
    if (prefill && !hasAutofiredRef.current) {
      hasAutofiredRef.current = true;
      submitQuestion(prefill);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submitQuestion(question: string) {
    if (!question.trim() || isStreaming) return;

    const now = Date.now();
    if (now - lastQueryRef.current < QUERY_COOLDOWN_MS) return;
    lastQueryRef.current = now;
    setCooldown(true);
    setTimeout(() => setCooldown(false), QUERY_COOLDOWN_MS);

    // Add user message
    const userMessage: ChatMessage = {
      role: "user",
      content: question.trim(),
    };

    // Add empty assistant message placeholder
    const assistantMessage: ChatMessage = {
      role: "assistant",
      content: "",
      isStreaming: true,
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setInput("");
    setIsStreaming(true);

    // Abort any previous stream and create a new controller
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const stream = streamDoctorQuery(question.trim(), undefined, controller.signal, accessCode || undefined);
      let pendingSources: SSESourcesEvent["sources"] | undefined;

      for await (const event of stream) {
        if (event.type === "token") {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                content: last.content + event.content,
              };
            }
            return updated;
          });
        } else if (event.type === "sources") {
          pendingSources = event.sources;
        } else if (event.type === "done") {
          // Mark the assistant message as complete and attach sources
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                isStreaming: false,
                sources: pendingSources,
              };
            }
            return updated;
          });
          break;
        }
      }
    } catch (err) {
      const errorText =
        err instanceof Error ? err.message : "An error occurred.";
      // If 403, prompt for access code
      if (errorText.includes("403")) {
        setNeedsCode(true);
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last.role === "assistant" && last.isStreaming) {
            updated[updated.length - 1] = {
              ...last,
              content: "The Doctor requires an access code for consultations. Please enter it below.",
              isStreaming: false,
            };
          }
          return updated;
        });
      } else {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last.role === "assistant" && last.isStreaming) {
            updated[updated.length - 1] = {
              ...last,
              content: `Sorry, I encountered an error: ${errorText}`,
              isStreaming: false,
            };
          }
          return updated;
        });
      }
    } finally {
      setIsStreaming(false);
      inputRef.current?.focus();
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submitQuestion(input);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitQuestion(input);
    }
  }

  return (
    <div
      className="h-full flex flex-col overflow-hidden"
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
          DR. CITYSCAN
        </span>
        <button
          onClick={onClose}
          className="p-1 rounded text-[#64748b] hover:text-slate-200 transition-colors duration-200"
          aria-label="Close chat"
        >
          <X size={16} />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-4" role="log" aria-live="polite">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex flex-col ${
              msg.role === "user" ? "items-end" : "items-start"
            }`}
          >
            {/* Bubble */}
            <div
              className="max-w-[85%] rounded px-3 py-2 text-sm leading-relaxed"
              style={
                msg.role === "user"
                  ? {
                      background: "#1e293b",
                      color: "#e2e8f0",
                      fontFamily: "var(--font-sans)",
                    }
                  : {
                      background: "transparent",
                      color: "#e2e8f0",
                      fontFamily: "var(--font-jetbrains, monospace)",
                    }
              }
            >
              <ReactMarkdown
                rehypePlugins={[rehypeSanitize]}
                components={{
                  p: ({ children }) => <p className="mb-1.5">{children}</p>,
                  strong: ({ children }) => <strong className="text-slate-100 font-semibold">{children}</strong>,
                  em: ({ children }) => <em className="text-slate-400">{children}</em>,
                  ul: ({ children }) => <ul className="list-disc list-inside mb-1.5 space-y-0.5">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal list-inside mb-1.5 space-y-0.5">{children}</ol>,
                  li: ({ children }) => <li>{children}</li>,
                  code: ({ children }) => <code className="bg-slate-800 px-1 py-0.5 rounded text-[#0ea5e9] text-xs">{children}</code>,
                }}
              >
                {msg.content}
              </ReactMarkdown>
              {/* Blinking cursor while streaming */}
              {msg.isStreaming && (
                <span
                  className="inline-block w-0.5 h-4 ml-0.5 align-text-bottom"
                  style={{
                    background: "#0ea5e9",
                    animation: "scanning-pulse 1s ease-in-out infinite",
                  }}
                />
              )}
            </div>

            {/* Sources (shown after streaming completes) */}
            {!msg.isStreaming &&
              msg.sources &&
              msg.sources.length > 0 && (
                <div className="mt-1 w-full max-w-[85%] flex flex-col gap-1">
                  {msg.sources.map((src, j) => (
                    <SourceCard key={j} source={src} />
                  ))}
                </div>
              )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Suggestion chips — shown when only the initial greeting exists */}
      {messages.length === 1 && !isStreaming && (
        <div className="flex flex-wrap gap-2 px-4 pb-2">
          {[
            "What should Tower Hamlets prioritise?",
            "Where's the greenest area in Camden?",
          ].map((q) => (
            <button
              key={q}
              onClick={() => submitQuestion(q)}
              className="text-[10px] font-mono px-3 py-1.5 rounded-full transition-all duration-200"
              style={{
                border: "1px solid #1e293b",
                color: "#0ea5e9",
                background: "transparent",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "#0ea5e9";
                e.currentTarget.style.background = "rgba(14, 165, 233, 0.05)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "#1e293b";
                e.currentTarget.style.background = "transparent";
              }}
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {/* Access code input — shown when Doctor requires authentication */}
      {needsCode && (
        <div className="flex items-center gap-2 px-4 py-2" style={{ borderTop: "1px solid #1e293b" }}>
          <input
            type="text"
            value={accessCode}
            onChange={(e) => setAccessCode(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && accessCode.trim()) {
                setNeedsCode(false);
              }
            }}
            placeholder="Enter access code…"
            className="flex-1 bg-transparent text-sm text-slate-200 font-mono outline-none placeholder:text-slate-600"
          />
          <button
            type="button"
            onClick={() => { if (accessCode.trim()) setNeedsCode(false); }}
            className="text-[10px] font-mono px-3 py-1 rounded"
            style={{ color: "#0ea5e9", border: "1px solid #0ea5e9" }}
          >
            Unlock
          </button>
        </div>
      )}

      {/* Input bar */}
      <form
        onSubmit={handleSubmit}
        className="flex-shrink-0 flex items-center gap-2 px-4 py-3"
        style={{ borderTop: "1px solid #0f172a" }}
      >
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
          placeholder="Ask the Doctor…"
          maxLength={500}
          className="flex-1 bg-transparent text-sm text-slate-200 placeholder-[#64748b] outline-none font-mono"
          style={{ fontFamily: "var(--font-jetbrains, monospace)" }}
          autoComplete="off"
          aria-label="Your question"
        />
        <button
          type="submit"
          disabled={isStreaming || !input.trim() || cooldown}
          className="p-1.5 rounded transition-all duration-200 flex-shrink-0"
          style={{
            color: isStreaming || !input.trim() || cooldown ? "#64748b" : "#0ea5e9",
            cursor:
              isStreaming || !input.trim() || cooldown ? "not-allowed" : "pointer",
          }}
          aria-label="Send"
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}
