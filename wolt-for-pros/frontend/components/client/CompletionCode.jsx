import { KeyRound } from 'lucide-react';

export default function CompletionCode({ code }) {
  return (
    <div className="card overflow-hidden">
      <div className="bg-slate-900 px-5 py-4 text-white">
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
          <KeyRound className="h-4 w-4" /> Completion code
        </p>
        <div className="mt-2 flex gap-2" aria-label={`Completion code ${code.split('').join(' ')}`}>
          {code.split('').map((digit, i) => (
            <span key={i} className="flex h-14 w-12 items-center justify-center rounded-xl bg-white/10 font-mono text-3xl font-bold">
              {digit}
            </span>
          ))}
        </div>
      </div>
      <p className="px-5 py-3 text-sm text-slate-600">
        Give this code to your pro <strong>only once the work is done</strong>. It confirms the job and the final price.
      </p>
    </div>
  );
}
