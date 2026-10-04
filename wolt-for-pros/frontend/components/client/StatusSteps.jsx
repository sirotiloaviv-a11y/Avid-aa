import { Check } from 'lucide-react';

const STEPS = [
  { key: 'requested', label: 'Requested' },
  { key: 'assigned', label: 'Pro on the way' },
  { key: 'in_progress', label: 'Working' },
  { key: 'completed', label: 'Done' },
];

export default function StatusSteps({ status }) {
  const index = status === 'flagged' ? 3 : STEPS.findIndex((s) => s.key === status);
  return (
    <ol className="flex items-center gap-1">
      {STEPS.map((step, i) => {
        const done = i < index || (i === index && status === 'completed');
        const current = i === index && status !== 'completed';
        return (
          <li key={step.key} className="flex flex-1 flex-col items-center gap-1 text-center">
            <span
              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${
                done ? 'bg-emerald-500 text-white' : current ? 'bg-brand-600 text-white ring-4 ring-brand-100' : 'bg-slate-200 text-slate-500'
              }`}
            >
              {done ? <Check className="h-4 w-4" /> : i + 1}
            </span>
            <span className={`text-[11px] leading-tight ${current ? 'font-semibold text-slate-900' : 'text-slate-500'}`}>{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
