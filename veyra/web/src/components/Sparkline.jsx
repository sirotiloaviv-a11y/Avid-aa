import { useId } from 'react';

export function Sparkline({ points, color = '#38d5f0', height = 56 }) {
  const id = useId().replace(/:/g, '');
  if (!points?.length) return null;
  const width = 300;
  const values = points.map((p) => p.score);
  const min = Math.min(...values) - 3;
  const max = Math.max(...values) + 3;
  const x = (i) => (points.length === 1 ? width : (i / (points.length - 1)) * width);
  const y = (v) => height - ((v - min) / (max - min || 1)) * height;
  const line = values.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const area = `${line} L${width},${height} L0,${height} Z`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="h-14 w-full overflow-visible" aria-hidden="true">
      <defs>
        <linearGradient id={`spark-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity=".28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#spark-${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}
