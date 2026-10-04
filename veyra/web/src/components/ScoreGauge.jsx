import { useEffect, useRef, useState } from 'react';
import { scoreColor } from '../lib/format.js';

/** Animates a number towards `value` so score changes are visible. */
export function useAnimatedNumber(value, duration = 900) {
  const [display, setDisplay] = useState(value);
  const from = useRef(value);

  useEffect(() => {
    const start = performance.now();
    const initial = from.current;
    let frame;
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - (1 - t) ** 3;
      const next = initial + (value - initial) * eased;
      setDisplay(next);
      from.current = next;
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);

  return Math.round(display);
}

/**
 * Detects score changes for the real-time update animation. Returns the last
 * change ({ delta, key }) for a few seconds after it happens, then null.
 */
export function useScoreChange(score, visibleMs = 3000) {
  const previous = useRef(score);
  const [change, setChange] = useState(null);

  useEffect(() => {
    if (score == null) return undefined;
    const before = previous.current;
    previous.current = score;
    if (before == null || before === score) return undefined;
    setChange({ delta: score - before, key: Date.now() });
    const timer = setTimeout(() => setChange(null), visibleMs);
    return () => clearTimeout(timer);
  }, [score, visibleMs]);

  return change;
}

export function ScoreChangeChip({ change, className = '' }) {
  if (!change) return null;
  const up = change.delta > 0;
  return (
    <span
      key={change.key}
      className={`pointer-events-none inline-flex animate-score-bump items-center gap-0.5 rounded-full px-2 py-0.5 font-mono text-xs font-semibold shadow-lg ${
        up ? 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-400/40' : 'bg-rose-500/20 text-rose-300 ring-1 ring-rose-400/40'
      } ${className}`}
      aria-live="polite"
    >
      {up ? '▲' : '▼'} {up ? '+' : ''}{change.delta}
    </span>
  );
}

const SWEEP = 270; // degrees of arc used by the gauge

function polar(cx, cy, r, angle) {
  const rad = ((angle - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function arc(cx, cy, r, startAngle, endAngle) {
  const [sx, sy] = polar(cx, cy, r, startAngle);
  const [ex, ey] = polar(cx, cy, r, endAngle);
  const large = endAngle - startAngle > 180 ? 1 : 0;
  return `M ${sx} ${sy} A ${r} ${r} 0 ${large} 1 ${ex} ${ey}`;
}

export function ScoreGauge({ score, grade, label, size = 220 }) {
  const animated = useAnimatedNumber(score);
  const change = useScoreChange(score);
  const color = scoreColor(animated);
  const start = -SWEEP / 2;
  const end = start + (SWEEP * Math.max(0, Math.min(100, animated))) / 100;
  const c = 100;
  const r = 82;

  return (
    <div className="relative" style={{ width: size, height: size }}>
      {change?.delta > 0 && <span key={change.key} className="pointer-events-none absolute inset-[18%] animate-glow-pulse rounded-full" aria-hidden="true" />}
      <ScoreChangeChip change={change} className="absolute right-2 top-6 z-10" />
      <svg viewBox="0 0 200 200" className="h-full w-full" role="img" aria-label={`Security score ${score} out of 100, grade ${grade}`}>
        <defs>
          <filter id="gauge-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <path d={arc(c, c, r, start, start + SWEEP)} stroke="rgba(255,255,255,.06)" strokeWidth="14" fill="none" strokeLinecap="round" />
        {Array.from({ length: 28 }, (_, i) => {
          const angle = start + (SWEEP * i) / 27;
          const [x1, y1] = polar(c, c, 66, angle);
          const [x2, y2] = polar(c, c, i % 9 === 0 ? 60 : 63, angle);
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="rgba(148,163,184,.25)" strokeWidth="1.2" />;
        })}
        {animated > 0 && (
          <path d={arc(c, c, r, start, end)} stroke={color} strokeWidth="14" fill="none" strokeLinecap="round" filter="url(#gauge-glow)" />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="tabular font-mono text-6xl font-semibold leading-none tracking-tight text-white">{animated}</span>
        <span className="mt-1 text-xs text-slate-500">out of 100</span>
        <span className="mt-3 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold" style={{ color, borderColor: `${color}55`, background: `${color}14` }}>
          Grade {grade} · {label}
        </span>
      </div>
    </div>
  );
}
