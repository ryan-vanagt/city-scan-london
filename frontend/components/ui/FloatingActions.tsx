/**
 * FloatingActions — fixed bottom-right FAB stack for Doctor and Bulletin panels.
 *
 * Two pill-shaped buttons (auto-width, 36px tall):
 *   1. ClipboardList + "REPORT"     — toggles the Bulletin panel
 *   2. Stethoscope   + "DIAGNOSTIC" — toggles the Doctor chat panel
 *
 * The stethoscope pulsates via the `stethoscope-pulse` CSS class when the doctor
 * panel is closed (inviting interaction). Active panels get a brighter border.
 * Hover shows a glow in x-ray blue (#0ea5e9).
 */

"use client";

import { useState } from "react";
// Icons removed — text-only FABs
import type { PanelState } from "@/lib/types";

interface FloatingActionsProps {
  panelState: PanelState;
  onToggleDoctor: () => void;
  onToggleBulletin: () => void;
}

interface FabButtonProps {
  onClick: () => void;
  isActive: boolean;
  ariaLabel: string;
  label: string;
}

function FabButton({
  onClick,
  isActive,
  ariaLabel,
  label,
}: FabButtonProps) {
  const [hovered, setHovered] = useState(false);

  const borderColour = isActive || hovered ? "#0ea5e9" : "#1e293b";
  const boxShadow =
    hovered || isActive
      ? "0 0 16px rgba(14, 165, 233, 0.4)"
      : "none";

  return (
    <button
      onClick={onClick}
      aria-label={ariaLabel}
      aria-pressed={isActive}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        borderRadius: 24,
        background: "#0f172a",
        border: `1px solid ${borderColour}`,
        boxShadow,
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 16px",
        cursor: "pointer",
        transition: "border-color 0.2s ease-out, box-shadow 0.2s ease-out",
        color: isActive || hovered ? "#0ea5e9" : "#64748b",
        whiteSpace: "nowrap",
      }}
    >
      <span
        style={{
          fontSize: 11,
          fontWeight: 600,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          fontFamily: "var(--font-inter, Inter, sans-serif)",
        }}
      >
        {label}
      </span>
    </button>
  );
}

export default function FloatingActions({
  panelState,
  onToggleDoctor,
  onToggleBulletin,
}: FloatingActionsProps) {
  const doctorOpen = panelState.type === "doctor";
  const bulletinOpen = panelState.type === "bulletin";

  return (
    <div
      style={{
        position: "fixed",
        bottom: 56,
        right: 24,
        zIndex: 50,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      {/* Bulletin button — text only */}
      <FabButton
        onClick={onToggleBulletin}
        isActive={bulletinOpen}
        ariaLabel="Toggle daily bulletin panel"
        label="DAILY BULLETIN"
      />

      {/* Doctor button — pulsates when panel is closed */}
      {/* Doctor button — text only */}
      <FabButton
        onClick={onToggleDoctor}
        isActive={doctorOpen}
        ariaLabel="Toggle Doctor chat panel"
        label="ASK THE DOCTOR"
      />
    </div>
  );
}
