"use client";

/**
 * AnalyticsPanel — side panel showing the deprivation vs health scatter plot.
 *
 * Follows the same panel structure as DoctorChat and BulletinPanel:
 * dark background, left border, header with close button, scrollable content.
 */

import { X } from "lucide-react";
import type { BoroughScore } from "@/lib/types";
import DeprivationScatter from "@/components/charts/DeprivationScatter";

interface AnalyticsPanelProps {
  boroughs: BoroughScore[];
  deprivation: Record<string, { imd_rank: number; name: string }>;
  onClose: () => void;
}

export default function AnalyticsPanel({
  boroughs,
  deprivation,
  onClose,
}: AnalyticsPanelProps) {
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
          ANALYTICS
        </span>
        <button
          onClick={onClose}
          className="p-1 rounded text-[#64748b] hover:text-slate-200 transition-colors duration-200"
          aria-label="Close analytics"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <DeprivationScatter boroughs={boroughs} deprivation={deprivation} />
      </div>
    </div>
  );
}
