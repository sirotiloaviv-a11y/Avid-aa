'use client';

import { Zap, Droplets, Hammer } from 'lucide-react';
import { formatILS } from '@/lib/format';

export const SERVICE_ICONS = { electrician: Zap, plumber: Droplets, handyman: Hammer };
const ACCENTS = {
  electrician: 'bg-amber-100 text-amber-700',
  plumber: 'bg-sky-100 text-sky-700',
  handyman: 'bg-emerald-100 text-emerald-700',
};

export default function ServicePicker({ services, value, onChange }) {
  return (
    <div className="grid grid-cols-3 gap-2 sm:gap-3">
      {services.map((s) => {
        const Icon = SERVICE_ICONS[s.type];
        const selected = value === s.type;
        return (
          <button
            key={s.type}
            type="button"
            onClick={() => onChange(s.type)}
            aria-pressed={selected}
            className={`card flex flex-col items-center gap-2 p-3 text-center transition sm:p-4 ${selected ? 'ring-2 ring-brand-500' : 'hover:ring-slate-300'}`}
          >
            <span className={`flex h-11 w-11 items-center justify-center rounded-2xl ${ACCENTS[s.type]}`}>
              {Icon && <Icon className="h-5 w-5" />}
            </span>
            <span className="text-sm font-semibold">{s.label}</span>
            <span className="text-xs text-slate-500">from {formatILS(s.min)}</span>
          </button>
        );
      })}
    </div>
  );
}
