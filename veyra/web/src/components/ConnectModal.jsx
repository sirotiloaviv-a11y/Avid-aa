import { useEffect, useRef, useState } from 'react';
import { useVeyra } from '../lib/VeyraContext.jsx';
import { Icon, Spinner } from './Icon.jsx';
import { ProviderMark } from './primitives.jsx';

function validate(fields, values) {
  const errors = {};
  for (const field of fields) {
    const value = (values[field.name] ?? '').trim();
    if (!value) {
      if (field.required !== false) errors[field.name] = `${field.label} is required`;
    } else if (field.pattern && !new RegExp(field.pattern, field.patternFlags).test(value)) {
      errors[field.name] = field.patternMessage ?? `${field.label} has an invalid format`;
    }
  }
  return errors;
}

export function ConnectModal({ integration, onClose }) {
  const { actions, busy } = useVeyra();
  const [values, setValues] = useState(() => Object.fromEntries(integration.credentialFields.map((f) => [f.name, ''])));
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState(null);
  const firstInput = useRef(null);
  const submitting = Boolean(busy[`integration:${integration.id}`]);

  useEffect(() => {
    firstInput.current?.focus();
    const onKey = (e) => { if (e.key === 'Escape' && !submitting) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, submitting]);

  const submit = async (e) => {
    e.preventDefault();
    const clientErrors = validate(integration.credentialFields, values);
    setErrors(clientErrors);
    setFormError(null);
    if (Object.keys(clientErrors).length) return;
    try {
      await actions.connect(integration, values);
      onClose();
    } catch (error) {
      setErrors(error.fields ?? {});
      setFormError(error.message);
    }
  };

  const fillDemo = () => {
    setValues(Object.fromEntries(integration.credentialFields.map((f) => [f.name, f.example ?? ''])));
    setErrors({});
  };

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/60 p-4 backdrop-blur-sm sm:items-center" onMouseDown={(e) => e.target === e.currentTarget && !submitting && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="connect-title" className="card w-full max-w-lg animate-fade-up">
        <div className="card-header">
          <div className="flex items-center gap-3">
            <ProviderMark integration={integration} size="lg" />
            <div>
              <h2 id="connect-title" className="font-semibold text-slate-100">Connect {integration.name}</h2>
              <p className="text-xs text-slate-500">{integration.authMethod}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={submitting} className="btn-ghost p-1.5" aria-label="Close"><Icon name="x" /></button>
        </div>

        <form onSubmit={submit} noValidate className="space-y-4 p-5">
          {integration.credentialFields.map((field, index) => (
            <div key={field.name}>
              <label htmlFor={`f-${field.name}`} className="mb-1.5 flex items-center justify-between text-xs font-medium text-slate-300">
                {field.label}
                {field.required === false && <span className="font-normal text-slate-500">Optional</span>}
              </label>
              <input
                id={`f-${field.name}`}
                ref={index === 0 ? firstInput : undefined}
                className={`input font-mono ${errors[field.name] ? 'border-rose-500/60 focus:border-rose-500/60 focus:ring-rose-500/20' : ''}`}
                placeholder={field.placeholder}
                value={values[field.name]}
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                aria-invalid={Boolean(errors[field.name])}
                aria-describedby={`h-${field.name}`}
              />
              <p id={`h-${field.name}`} className={`mt-1 text-[11px] ${errors[field.name] ? 'text-rose-300' : 'text-slate-500'}`}>
                {errors[field.name] ?? field.help}
              </p>
            </div>
          ))}

          <div className="rounded-lg border border-white/[0.06] bg-ink-950/60 p-3">
            <p className="flex items-center gap-1.5 text-xs font-medium text-slate-300"><Icon name="lock" className="h-3.5 w-3.5 text-emerald-400" /> Read-only access requested</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {integration.scopes.map((s) => <span key={s} className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">{s}</span>)}
            </div>
            <p className="mt-2 text-[11px] text-slate-500">Veyra never asks for passwords or secret keys. Access is granted through {integration.vendor}'s own consent flow and can be revoked there at any time.</p>
          </div>

          {formError && <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{formError}</p>}

          <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:items-center sm:justify-between">
            <button type="button" onClick={fillDemo} className="btn-ghost text-xs" disabled={submitting}>
              <Icon name="sparkles" className="h-3.5 w-3.5" /> Use demo values
            </button>
            <div className="flex gap-2">
              <button type="button" onClick={onClose} className="btn-secondary flex-1 sm:flex-none" disabled={submitting}>Cancel</button>
              <button type="submit" className="btn-primary flex-1 sm:flex-none" disabled={submitting}>
                {submitting ? <><Spinner /> Authorizing & scanning…</> : <><Icon name="link" /> Connect</>}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
