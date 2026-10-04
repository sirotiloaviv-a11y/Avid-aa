export const SEVERITIES = ['critical', 'high', 'medium', 'low'];

export const SEVERITY_STYLE = {
  critical: { label: 'Critical', text: 'text-rose-300', bg: 'bg-rose-500/15', border: 'border-rose-500/40', dot: 'bg-rose-500', bar: '#f43f5e' },
  high: { label: 'High', text: 'text-orange-300', bg: 'bg-orange-500/15', border: 'border-orange-500/40', dot: 'bg-orange-500', bar: '#f97316' },
  medium: { label: 'Medium', text: 'text-amber-200', bg: 'bg-amber-400/10', border: 'border-amber-400/30', dot: 'bg-amber-400', bar: '#fbbf24' },
  low: { label: 'Low', text: 'text-sky-300', bg: 'bg-sky-500/10', border: 'border-sky-500/30', dot: 'bg-sky-400', bar: '#38bdf8' },
};

export function scoreColor(score) {
  if (score >= 80) return '#34d399';
  if (score >= 70) return '#a3e635';
  if (score >= 55) return '#fbbf24';
  if (score >= 40) return '#fb923c';
  return '#f43f5e';
}

const UNITS = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
];
const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

export function timeAgo(iso, now = Date.now()) {
  if (!iso) return 'never';
  const seconds = Math.round((Date.parse(iso) - now) / 1000);
  if (Math.abs(seconds) < 45) return 'just now';
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return rtf.format(Math.round(seconds / 60), 'minute');
}

export const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;
