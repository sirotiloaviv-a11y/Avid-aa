const ils = new Intl.NumberFormat('en-IL', {
  style: 'currency',
  currency: 'ILS',
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

export function formatILS(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return ils.format(Number(value));
}

export function formatDateTime(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString('en-IL', { dateStyle: 'medium', timeStyle: 'short' });
}

export function timeAgo(value) {
  if (!value) return '';
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

export const SERVICE_LABELS = {
  electrician: 'Electrician',
  plumber: 'Plumber',
  handyman: 'Handyman',
};

export const STATUS_STYLES = {
  requested: { label: 'Finding a pro', className: 'bg-amber-100 text-amber-800' },
  assigned: { label: 'On the way', className: 'bg-brand-100 text-brand-800' },
  in_progress: { label: 'In progress', className: 'bg-indigo-100 text-indigo-800' },
  completed: { label: 'Completed', className: 'bg-emerald-100 text-emerald-800' },
  cancelled: { label: 'Cancelled', className: 'bg-slate-200 text-slate-700' },
  flagged: { label: 'Under review', className: 'bg-rose-100 text-rose-800' },
};
