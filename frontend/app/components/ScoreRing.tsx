import { bandFor, BAND_COLOR, BAND_LABEL } from "./scoreThreshold";

type Props = {
  score: number;
  size?: number;
  stroke?: number;
};

export function ScoreRing({ score, size = 160, stroke = 14 }: Props) {
  const clamped = Math.max(0, Math.min(100, score));
  const band = bandFor(clamped);
  const color = BAND_COLOR[band];
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = (clamped / 100) * circumference;
  const center = size / 2;

  return (
    <div
      className="inline-flex flex-col items-center"
      role="img"
      aria-label={`Overall score ${clamped} out of 100 (${BAND_LABEL[band]})`}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="#e2e8f0"
          strokeWidth={stroke}
        />
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference - dash}`}
          transform={`rotate(-90 ${center} ${center})`}
        />
        <text
          x={center}
          y={center}
          textAnchor="middle"
          dominantBaseline="central"
          className="fill-ink"
          style={{ fontSize: size * 0.28, fontWeight: 600 }}
        >
          {clamped}
        </text>
      </svg>
      <span className="mt-2 text-sm font-medium" style={{ color }}>
        {BAND_LABEL[band]}
      </span>
    </div>
  );
}
