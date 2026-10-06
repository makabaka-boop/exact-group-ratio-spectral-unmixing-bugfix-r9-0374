import { useMemo } from "react";
import type { Point } from "../types";

interface Props {
  points: Point[];
}

const W = 760;
const H_TOP = 320;
const H_BOT = 200;
const M = { top: 24, right: 24, bottom: 34, left: 64 };
const GAP = 46;

const COLORS = {
  observed: "#2563eb",
  reconstructed: "#dc2626",
  residual: "#7c3aed",
  zero: "#94a3b8",
  axis: "#475569",
};

function niceTicks(min: number, max: number, count = 5): number[] {
  if (min === max) return [min];
  const span = max - min;
  const raw = span / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 5 : norm >= 2 ? 2 : 1) * mag;
  const ticks: number[] = [];
  for (
    let v = Math.ceil(min / step) * step;
    v <= max + step * 1e-9;
    v += step
  ) {
    ticks.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toFixed(10)));
  }
  return ticks;
}

export default function SpectrumChart({ points }: Props) {
  const model = useMemo(() => {
    const xs = points.map((p) => p.wavelength);
    const observed = points.map((p) => p.observed);
    const recon = points.map((p) => Number(p.reconstructed.decimal));
    const resid = points.map((p) => Number(p.residual.decimal));

    const xMin = xs[0];
    const xMax = xs[xs.length - 1];

    const yAll = [...observed, ...recon];
    const yMin = Math.min(...yAll);
    const yMax = Math.max(...yAll);
    const rMin = Math.min(0, ...resid);
    const rMax = Math.max(0, ...resid);

    const plotW = W - M.left - M.right;
    const topH = H_TOP - M.top - M.bottom;
    const botH = H_BOT - 20 - M.bottom;

    const sx = (x: number) =>
      M.left + ((x - xMin) / (xMax - xMin || 1)) * plotW;
    const syTop = (y: number) =>
      M.top + topH - ((y - yMin) / (yMax - yMin || 1)) * topH;
    const syBot = (r: number) =>
      20 + botH - ((r - rMin) / (rMax - rMin || 1)) * botH;

    const path = (vals: number[], ys: (v: number) => number) =>
      vals
        .map(
          (v, i) =>
            `${i === 0 ? "M" : "L"}${sx(xs[i]).toFixed(2)},${ys(v).toFixed(2)}`,
        )
        .join(" ");

    return {
      xs,
      observed,
      recon,
      resid,
      sx,
      syTop,
      syBot,
      topH,
      botH,
      yTicks: niceTicks(yMin, yMax),
      rTicks: niceTicks(rMin, rMax),
      obsPath: path(observed, syTop),
      reconPath: path(recon, syTop),
      residPath: path(resid, syBot),
      zeroY: syBot(0),
      topOffset: 0,
      botOffset: H_TOP + GAP,
    };
  }, [points]);

  const xTickIdx = useMemo(() => {
    const want = 8;
    const step = Math.max(1, Math.round(points.length / want));
    return points.map((_, i) => i).filter((i) => i % step === 0);
  }, [points]);

  return (
    <svg
      viewBox={`0 0 ${W} ${H_TOP + GAP + H_BOT}`}
      className="chart"
      role="img"
      aria-label="观测、重建与残差并列图"
    >
      {/* ---- top panel: observed vs reconstructed ---- */}
      <rect
        x={M.left}
        y={M.top}
        width={W - M.left - M.right}
        height={model.topH}
        fill="#f8fafc"
        stroke="#e2e8f0"
      />
      {model.yTicks.map((t) => (
        <g key={`yt-${t}`}>
          <line
            x1={M.left}
            x2={W - M.right}
            y1={model.syTop(t)}
            y2={model.syTop(t)}
            stroke="#e2e8f0"
          />
          <text
            x={M.left - 8}
            y={model.syTop(t) + 4}
            textAnchor="end"
            fontSize="11"
            fill={COLORS.axis}
          >
            {t}
          </text>
        </g>
      ))}
      {xTickIdx.map((i) => (
        <g key={`xt-${i}`}>
          <line
            x1={model.sx(model.xs[i])}
            x2={model.sx(model.xs[i])}
            y1={M.top}
            y2={M.top + model.topH}
            stroke="#f1f5f9"
          />
          <text
            x={model.sx(model.xs[i])}
            y={H_TOP - 10}
            textAnchor="middle"
            fontSize="11"
            fill={COLORS.axis}
          >
            {model.xs[i]}
          </text>
        </g>
      ))}
      <path
        d={model.obsPath}
        fill="none"
        stroke={COLORS.observed}
        strokeWidth={2}
      />
      <path
        d={model.reconPath}
        fill="none"
        stroke={COLORS.reconstructed}
        strokeWidth={2}
        strokeDasharray="6 3"
      />
      {points.map((p, i) => (
        <circle
          key={`o-${i}`}
          cx={model.sx(p.wavelength)}
          cy={model.syTop(p.observed)}
          r={2.4}
          fill={COLORS.observed}
        />
      ))}
      <text x={M.left} y={16} fontSize="12" fontWeight={600} fill="#0f172a">
        观测 vs 重建
      </text>
      <g transform={`translate(${W - M.right - 240}, 10)`}>
        <line
          x1={0}
          y1={6}
          x2={26}
          y2={6}
          stroke={COLORS.observed}
          strokeWidth={2}
        />
        <text x={32} y={10} fontSize="11" fill={COLORS.axis}>
          观测
        </text>
        <line
          x1={80}
          y1={6}
          x2={106}
          y2={6}
          stroke={COLORS.reconstructed}
          strokeWidth={2}
          strokeDasharray="6 3"
        />
        <text x={112} y={10} fontSize="11" fill={COLORS.axis}>
          重建
        </text>
      </g>

      {/* ---- bottom panel: residuals ---- */}
      <g transform={`translate(0, ${model.botOffset})`}>
        <rect
          x={M.left}
          y={20}
          width={W - M.left - M.right}
          height={model.botH}
          fill="#faf5ff"
          stroke="#e2e8f0"
        />
        {model.rTicks.map((t) => (
          <g key={`rt-${t}`}>
            <line
              x1={M.left}
              x2={W - M.right}
              y1={model.syBot(t)}
              y2={model.syBot(t)}
              stroke={t === 0 ? COLORS.zero : "#ede9fe"}
              strokeWidth={t === 0 ? 1.5 : 1}
            />
            <text
              x={M.left - 8}
              y={model.syBot(t) + 4}
              textAnchor="end"
              fontSize="11"
              fill={COLORS.axis}
            >
              {t}
            </text>
          </g>
        ))}
        {xTickIdx.map((i) => (
          <text
            key={`rx-${i}`}
            x={model.sx(model.xs[i])}
            y={H_BOT - 8}
            textAnchor="middle"
            fontSize="11"
            fill={COLORS.axis}
          >
            {model.xs[i]}
          </text>
        ))}
        {/* residual stems from zero line */}
        {points.map((p, i) => (
          <line
            key={`rs-${i}`}
            x1={model.sx(p.wavelength)}
            x2={model.sx(p.wavelength)}
            y1={model.zeroY}
            y2={model.syBot(model.resid[i])}
            stroke={COLORS.residual}
            strokeWidth={1.4}
            opacity={0.7}
          />
        ))}
        <path
          d={model.residPath}
          fill="none"
          stroke={COLORS.residual}
          strokeWidth={2}
        />
        <text x={M.left} y={14} fontSize="12" fontWeight={600} fill="#0f172a">
          逐点残差（观测 − 重建）
        </text>
      </g>
    </svg>
  );
}
