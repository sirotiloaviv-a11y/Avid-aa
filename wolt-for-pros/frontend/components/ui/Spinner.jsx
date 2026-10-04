import { Loader2 } from 'lucide-react';

export default function Spinner({ label = 'Loading…', className = '' }) {
  return (
    <div className={`flex items-center justify-center gap-2 py-10 text-sm text-slate-500 ${className}`}>
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}
