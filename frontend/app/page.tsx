"use client";

/**
 * Main page orchestrator for CityScan London.
 *
 * Single-page app with a landing overlay (bulletin + zoomed X-ray map)
 * that transitions to a live thermal map with doctor chat and bulletin panels.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import type {
  BoroughScore,
  LondonScore,
  BulletinResponse,
  MetricFilter,
  PanelState,
} from "@/lib/types";
import { fetchBoroughs, fetchLondonScore, fetchBulletin } from "@/lib/api";

// Own components (always loaded)
import VitalSigns from "@/components/header/VitalSigns";
import LondonMap from "@/components/map/LondonMap";
import BulletinReport from "@/components/landing/BulletinReport";

// Dynamic imports
const DoctorChat = dynamic(
  () => import("@/components/panels/DoctorChat"),
  { ssr: false }
);
const BulletinPanel = dynamic(
  () => import("@/components/panels/BulletinPanel"),
  { ssr: false }
);
const FloatingActions = dynamic(
  () => import("@/components/ui/FloatingActions"),
  { ssr: false }
);
const Footer = dynamic(
  () => import("@/components/Footer"),
  { ssr: false }
);

export default function Home() {
  // --- State ---
  const [showLanding, setShowLanding] = useState(true);   // overlay visibility
  const [mapZoomed, setMapZoomed] = useState(true);       // map scale
  const [xrayActive, setXrayActive] = useState(true);     // borough colours
  const [effectsReady, setEffectsReady] = useState(false); // glow + pulse (after transition)
  const [showUI, setShowUI] = useState(false);            // header/footer/FABs
  const [colourReady, setColourReady] = useState(false);  // timer elapsed for colour flood
  const [boroughs, setBoroughs] = useState<BoroughScore[]>([]);
  const [londonScore, setLondonScore] = useState<LondonScore>({
    composite_score: null,
    air_score: null,
    transit_score: null,
    sentiment_score: null,
    immune_score: null,
    borough_count: 0,
    timestamp: null,
  });
  const [bulletin, setBulletin] = useState<BulletinResponse | null>(null);
  const [hoveredBorough, setHoveredBorough] = useState<string | null>(null);
  const [panelState, setPanelState] = useState<PanelState>({ type: "closed" });
  const [metricFilter, setMetricFilter] = useState<MetricFilter>(null);
  const [hasError, setHasError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // --- Derived ---
  const boroughMap = useMemo(
    () => new Map(boroughs.map((b) => [b.borough_code, b])),
    [boroughs]
  );
  const hoveredBoroughData = hoveredBorough
    ? boroughMap.get(hoveredBorough) ?? null
    : null;
  const isPanelOpen = panelState.type !== "closed";

  // --- Data fetching ---
  useEffect(() => {
    let cancelled = false;

    let hasLoaded = false;

    async function loadData() {
      const [boroughResult, scoreResult, bulletinResult] = await Promise.allSettled([
        fetchBoroughs(),
        fetchLondonScore(),
        fetchBulletin(),
      ]);
      if (cancelled) return;
      if (boroughResult.status === "fulfilled") setBoroughs(boroughResult.value);
      if (scoreResult.status === "fulfilled") setLondonScore(scoreResult.value);
      if (bulletinResult.status === "fulfilled") setBulletin(bulletinResult.value);
      const anyFailed = [boroughResult, scoreResult, bulletinResult].some(r => r.status === "rejected");
      if (anyFailed) {
        console.error("Some data fetches failed");
        if (!cancelled) setHasError(true);
      } else {
        setHasError(false);
      }
      hasLoaded = true;
      setIsLoading(false);
    }

    loadData();

    // Re-fetch when page becomes visible — only if initial load succeeded
    function handleVisibility() {
      if (document.visibilityState === "visible" && hasLoaded) {
        loadData();
      }
    }
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);

  // Gate colour transition on BOTH timer elapsed AND data loaded
  useEffect(() => {
    if (colourReady && boroughs.length > 0) {
      setXrayActive(false);
    }
  }, [colourReady, boroughs.length]);

  // --- Handlers ---
  const handleBoroughHover = useCallback((code: string | null) => {
    setHoveredBorough(code);
  }, []);

  const handleMetricClick = useCallback((metric: MetricFilter) => {
    setMetricFilter(metric);
  }, []);

  const handleEnterLiveMap = useCallback(() => {
    setShowLanding(false);                          // Act 1: overlay dissolves
    setTimeout(() => setMapZoomed(false), 600);     // Act 2: map dezooms
    setTimeout(() => setColourReady(true), 1800);    // Act 3: ready for colours (gated on data)
    setTimeout(() => setShowUI(true), 2200);        // Act 4: UI appears
    setTimeout(() => setEffectsReady(true), 3500);  // Act 5: glow + pulse enabled
  }, []);

  const handlePanelClose = useCallback(() => {
    setPanelState({ type: "closed" });
  }, []);

  const handleOpenDoctor = useCallback((prefill?: string) => {
    setPanelState({ type: "doctor", prefill });
  }, []);

  const handleOpenBulletin = useCallback(() => {
    setPanelState({ type: "bulletin" });
  }, []);

  // --- Render ---
  return (
    <div className="min-h-screen flex flex-col relative">
      {/* Header — always rendered, opacity-controlled to avoid layout shift */}
      <div style={{
        opacity: showUI ? 1 : 0,
        pointerEvents: showUI ? "auto" : "none",
        transition: "opacity 0.5s ease-out",
      }}>
        <VitalSigns
          londonScore={londonScore}
          hoveredBorough={hoveredBoroughData}
          metricFilter={metricFilter}
          onMetricClick={handleMetricClick}
        />
      </div>

      {/* Map area */}
      <div className="flex-1 flex relative overflow-hidden">
        <div
          className="flex-1 flex items-center justify-center p-4 md:p-8 overflow-hidden"
          style={{
            marginRight: isPanelOpen ? "35%" : 0,
            transition: "margin-right 0.3s ease-out",
          }}
        >
          <div
            className="w-full max-w-3xl"
            style={{
              transform: mapZoomed ? "scale(4)" : "scale(1)",
              transition: "transform 2s cubic-bezier(0.16, 1, 0.3, 1)",
              willChange: mapZoomed ? "transform" : "auto",
            }}
            onClick={(e) => {
              if (e.target === e.currentTarget) {
                setMetricFilter(null);
                handlePanelClose();
              }
            }}
          >
            <LondonMap
              boroughs={boroughs}
              metricFilter={metricFilter}
              selectedBorough={null}
              xrayMode={xrayActive}
              effectsReady={effectsReady}
              onBoroughHover={handleBoroughHover}
            />
          </div>
        </div>

        {/* Panel container — top below header, bottom above footer */}
        <div
          className="fixed right-0 w-[90%] md:w-[35%] overflow-hidden z-30"
          style={{
            top: 52,
            bottom: 33,
            opacity: isPanelOpen ? 1 : 0,
            transform: isPanelOpen ? "translateX(0)" : "translateX(20px)",
            pointerEvents: isPanelOpen ? "auto" : "none",
            transition: "opacity 0.4s ease-out, transform 0.4s ease-out",
          }}
        >
          {panelState.type === "doctor" && (
            <DoctorChat
              onClose={handlePanelClose}
              prefill={panelState.prefill}
              overallScore={londonScore.composite_score}
            />
          )}
          {panelState.type === "bulletin" && (
            <BulletinPanel
              bulletin={bulletin}
              onClose={handlePanelClose}
            />
          )}
        </div>
      </div>

      {/* FABs — hidden during landing and when panel open */}
      {showUI && !isPanelOpen && (
        <FloatingActions
          panelState={panelState}
          onToggleDoctor={() => handleOpenDoctor()}
          onToggleBulletin={() => handleOpenBulletin()}
        />
      )}

      {/* Footer — always rendered, z-40 so it sits above panels */}
      <div style={{
        opacity: showUI ? 1 : 0,
        pointerEvents: showUI ? "auto" : "none",
        transition: "opacity 0.5s ease-out",
        position: "relative",
        zIndex: 40,
      }}>
        <Footer />
      </div>

      {/* Error toast — shown on landing if API is down */}
      {hasError && boroughs.length === 0 && showLanding && (
        <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 font-mono text-xs text-red-400 bg-slate-900 border border-slate-700 px-4 py-2 rounded-lg">
          Unable to connect to API — make sure backend is running on port 8000
        </div>
      )}

      {/* Landing overlay */}
      <div
        className="fixed inset-0 z-30 flex flex-col"
        style={{
          background: "rgba(2,6,23,0.65)",
          opacity: showLanding ? 1 : 0,
          filter: showLanding ? "blur(0px)" : "blur(6px)",
          transition: "opacity 1.2s ease-out, filter 1.2s ease-out",
          pointerEvents: showLanding ? "auto" : "none",
        }}
      >
        <div className="flex-1 flex flex-col items-center justify-center gap-8 px-6 py-12 max-w-2xl mx-auto">
          {isLoading && boroughs.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center z-40">
              <span className="font-mono text-sm text-[#0ea5e9] animate-pulse tracking-widest">
                SCANNING LONDON...
              </span>
            </div>
          )}
          <BulletinReport
            bulletin={bulletin}
            overallScore={londonScore.composite_score}
          />
        </div>

        <div className="flex flex-col items-center pb-12 gap-3">
          <button
            onClick={handleEnterLiveMap}
            className="group flex flex-col items-center gap-2 transition-all duration-300"
          >
            <span className="font-mono text-xs tracking-widest text-slate-500 group-hover:text-slate-300 transition-colors">
              VIEW LIVE SIGNALS
            </span>
            <svg
              width={24}
              height={24}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.5}
              className="text-slate-600 group-hover:text-slate-300 transition-colors animate-bounce"
            >
              <path d="M12 5v14M5 12l7 7 7-7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
