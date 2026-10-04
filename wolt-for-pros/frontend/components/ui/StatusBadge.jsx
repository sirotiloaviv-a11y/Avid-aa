import { STATUS_STYLES } from '@/lib/format';

export default function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || { label: status, className: 'bg-slate-100 text-slate-700' };
  return <span className={`badge ${style.className}`}>{style.label}</span>;
}
