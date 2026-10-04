'use client';

import { useState } from 'react';
import { Star } from 'lucide-react';

const LABELS = ['', 'Poor', 'Fair', 'Good', 'Very good', 'Excellent'];

// Read-only stars with the average and count, e.g. ★ 4.7 (23).
export function RatingBadge({ rating = 0, count = 0, className = '' }) {
  if (!count) return <span className={`text-xs text-slate-500 ${className}`}>New pro</span>;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold text-slate-700 ${className}`} title={`${rating} out of 5 from ${count} review(s)`}>
      <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" aria-hidden="true" />
      {Number(rating).toFixed(1)}
      <span className="font-normal text-slate-500">({count})</span>
    </span>
  );
}

// Interactive 1-5 picker. Arrow keys work through the radio group.
export default function StarRating({ value, onChange, size = 'h-9 w-9' }) {
  const [hover, setHover] = useState(0);
  const shown = hover || value;
  return (
    <div>
      <div role="radiogroup" aria-label="Rating" className="flex gap-1" onMouseLeave={() => setHover(0)}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={value === n}
            aria-label={`${n} star${n > 1 ? 's' : ''}`}
            onClick={() => onChange(n)}
            onMouseEnter={() => setHover(n)}
            className="rounded-lg p-0.5 transition hover:scale-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          >
            <Star className={`${size} ${n <= shown ? 'fill-amber-400 text-amber-400' : 'text-slate-300'}`} />
          </button>
        ))}
      </div>
      <p className="mt-1 h-5 text-sm font-medium text-slate-600">{LABELS[shown]}</p>
    </div>
  );
}
