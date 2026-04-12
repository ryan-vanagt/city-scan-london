"use client";

/**
 * Animated EKG SVG line for the vital signs header.
 *
 * Four variants with distinct waveform shapes:
 *   - air: smooth sine wave (breathing rhythm)
 *   - transit: sharp heartbeat spikes (classic ECG)
 *   - sentiment: gentle undulation (brain waves)
 *   - immune: small regular pulses (immune ticks)
 *
 * Animated via translateX on a <g> wrapper using the `ekg-scroll` CSS class.
 * The path is drawn twice (0-120 and 120-240) so translating by -120 is seamless.
 */

interface EkgLineProps {
  variant: "air" | "transit" | "sentiment" | "immune";
  colour: string;
}

/** SVG path data for each EKG variant. Paths are designed for a 120x30 viewBox, drawn twice to 240. */
const EKG_PATHS: Record<EkgLineProps["variant"], string> = {
  // Smooth sine wave — breathing
  air: "M0,15 Q10,5 20,15 Q30,25 40,15 Q50,5 60,15 Q70,25 80,15 Q90,5 100,15 Q110,25 120,15 Q130,5 140,15 Q150,25 160,15 Q170,5 180,15 Q190,25 200,15 Q210,5 220,15 Q230,25 240,15",

  // Classic ECG heartbeat — sharp P-QRS-T spikes
  transit:
    "M0,15 L15,15 L18,12 L20,15 L25,15 L27,15 L29,2 L31,28 L33,15 L38,15 L42,10 L48,15 L60,15 L75,15 L78,12 L80,15 L85,15 L87,15 L89,2 L91,28 L93,15 L98,15 L102,10 L108,15 L120,15 L135,15 L138,12 L140,15 L145,15 L147,15 L149,2 L151,28 L153,15 L158,15 L162,10 L168,15 L180,15 L195,15 L198,12 L200,15 L205,15 L207,15 L209,2 L211,28 L213,15 L218,15 L222,10 L228,15 L240,15",

  // Gentle undulation — brain waves
  sentiment:
    "M0,15 Q8,10 16,13 Q24,16 32,15 Q40,12 48,14 Q56,18 64,15 Q72,11 80,14 Q88,17 96,15 Q104,12 112,14 Q120,17 128,15 Q136,10 144,13 Q152,16 160,15 Q168,12 176,14 Q184,18 192,15 Q200,11 208,14 Q216,17 224,15 Q232,12 240,15",

  // Small regular pulses — immune ticks
  immune:
    "M0,15 L12,15 L14,8 L16,22 L18,15 L30,15 L42,15 L44,8 L46,22 L48,15 L60,15 L72,15 L74,8 L76,22 L78,15 L90,15 L102,15 L104,8 L106,22 L108,15 L120,15 L132,15 L134,8 L136,22 L138,15 L150,15 L162,15 L164,8 L166,22 L168,15 L180,15 L192,15 L194,8 L196,22 L198,15 L210,15 L222,15 L224,8 L226,22 L228,15 L240,15",
};

export default function EkgLine({ variant, colour }: EkgLineProps) {
  const pathD = EKG_PATHS[variant];

  return (
    <svg
      width={120}
      height={30}
      viewBox="0 0 120 30"
      className="overflow-hidden"
      aria-hidden="true"
    >
      <g className="ekg-scroll">
        <path
          d={pathD}
          fill="none"
          stroke={colour}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ opacity: 0.8 }}
        />
      </g>
    </svg>
  );
}
