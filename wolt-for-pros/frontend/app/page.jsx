'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ShieldCheck, MapPin, Wallet, Zap, Droplets, Hammer, Loader2 } from 'lucide-react';
import { HOME_BY_ROLE, useSession } from '@/lib/session';
import { useDemo } from '@/lib/demo/DemoContext';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/lib/api';

const DEMO_ACCOUNTS = [
  { phone: '0501111111', label: 'Dana', hint: 'Client' },
  { phone: '0502222222', label: 'Yossi', hint: 'Electrician' },
  { phone: '0503333333', label: 'Moshe', hint: 'Plumber, low balance' },
  { phone: '0504444444', label: 'Avi', hint: 'Handyman' },
  { phone: '0500000000', label: 'Noa', hint: 'Admin' },
];

export default function Home() {
  const { user, loading, login, register, requestOtp } = useSession();
  const { isDemo } = useDemo();
  const router = useRouter();
  const toast = useToast();
  const [mode, setMode] = useState('login');
  const [busy, setBusy] = useState(false);
  const [phone, setPhone] = useState('');
  const [form, setForm] = useState({ role: 'client', name: '', phone: '', licenseNumber: '', serviceType: 'electrician' });
  // SMS one-time code step, shown only when the server requires it.
  const [otpRequired, setOtpRequired] = useState(false);
  const [otpSentTo, setOtpSentTo] = useState(null);
  const [otpCode, setOtpCode] = useState('');

  useEffect(() => {
    if (!loading && user) router.replace(HOME_BY_ROLE[user.role] || '/');
  }, [loading, user, router]);

  useEffect(() => {
    api('/api/catalog').then((c) => setOtpRequired(Boolean(c.auth && c.auth.otpRequired))).catch(() => {});
  }, [isDemo]);

  useEffect(() => {
    setOtpSentTo(null);
    setOtpCode('');
  }, [isDemo]);

  // Returns true when the caller should stop and wait for the code.
  async function needsCode(targetPhone) {
    if (!otpRequired || otpSentTo === targetPhone) return false;
    setBusy(true);
    try {
      const res = await requestOtp(targetPhone);
      setOtpSentTo(targetPhone);
      setOtpCode('');
      toast(res.devCode ? `Code sent (development code: ${res.devCode})` : 'We texted you a 6-digit code', 'info', 8000);
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setBusy(false);
    }
    return true;
  }

  async function run(fn) {
    setBusy(true);
    try {
      const u = await fn();
      router.replace(HOME_BY_ROLE[u.role] || '/');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function onLogin(e) {
    e.preventDefault();
    if (await needsCode(phone)) return;
    run(() => login(phone, otpCode));
  }

  async function onRegister(e) {
    e.preventDefault();
    if (await needsCode(form.phone)) return;
    const base = form.role === 'client'
      ? { role: 'client', name: form.name, phone: form.phone }
      : form;
    run(() => register({ ...base, otpCode: otpCode || undefined }));
  }

  const codeField = otpSentTo ? (
    <div>
      <label className="label" htmlFor="otp">Code sent to {otpSentTo}</label>
      <input
        id="otp"
        className="input text-center font-mono text-xl tracking-[0.4em]"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={8}
        value={otpCode}
        onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ''))}
        required
        autoFocus
      />
      <button type="button" className="mt-1 text-xs font-semibold text-brand-700" onClick={() => setOtpSentTo(null)}>
        Use a different number or resend
      </button>
    </div>
  ) : null;
  const submitLabel = otpRequired && !otpSentTo ? 'Text me a code' : null;

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  return (
    <div className="min-h-screen bg-gradient-to-b from-brand-600 via-brand-600 to-slate-50 to-60%">
      <div className="mx-auto max-w-5xl px-4 pb-16 pt-10 sm:pt-16">
        <div className="grid items-start gap-8 lg:grid-cols-2">
          <section className="text-white">
            <p className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold">
              <ShieldCheck className="h-3.5 w-3.5" /> Licensed pros only
            </p>
            <h1 className="text-4xl font-extrabold leading-tight tracking-tight sm:text-5xl">
              An electrician or plumber at your door, tracked live.
            </h1>
            <p className="mt-4 max-w-md text-brand-100">
              Book in a minute, watch your pro drive over on the map, and pay only when you hand over your 4-digit completion code.
            </p>
            <div className="mt-8 grid max-w-md grid-cols-3 gap-3 text-sm">
              {[
                { icon: Zap, label: 'Electricians' },
                { icon: Droplets, label: 'Plumbers' },
                { icon: Hammer, label: 'Handymen' },
              ].map(({ icon: Icon, label }) => (
                <div key={label} className="rounded-2xl bg-white/10 p-3 text-center">
                  <Icon className="mx-auto mb-1 h-5 w-5" />
                  {label}
                </div>
              ))}
            </div>
            <ul className="mt-8 space-y-2 text-sm text-brand-50">
              <li className="flex items-center gap-2"><MapPin className="h-4 w-4" /> Real-time GPS tracking and ETA</li>
              <li className="flex items-center gap-2"><Wallet className="h-4 w-4" /> Pros work from a prepaid fee wallet</li>
              <li className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" /> Price anomalies are reviewed by our team</li>
            </ul>
          </section>

          <section className="card p-5 sm:p-6">
            <div className="mb-5 grid grid-cols-2 rounded-xl bg-slate-100 p-1 text-sm font-semibold">
              {['login', 'register'].map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={`rounded-lg py-2 ${mode === m ? 'bg-white shadow' : 'text-slate-500'}`}
                >
                  {m === 'login' ? 'Log in' : 'Sign up'}
                </button>
              ))}
            </div>

            {mode === 'login' ? (
              <>
                <form onSubmit={onLogin} className="space-y-3">
                  <div>
                    <label className="label" htmlFor="phone">Phone number</label>
                    <input id="phone" className="input" inputMode="tel" placeholder="05XXXXXXXX" value={phone} onChange={(e) => setPhone(e.target.value)} required />
                  </div>
                  {otpSentTo === phone && codeField}
                  <button className="btn-primary w-full" disabled={busy}>
                    {busy && <Loader2 className="h-4 w-4 animate-spin" />} {submitLabel || 'Continue'}
                  </button>
                </form>
                {(isDemo || !otpRequired) && (
                <div className="mt-6">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Demo accounts</p>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {DEMO_ACCOUNTS.map((a) => (
                      <button
                        key={a.phone}
                        type="button"
                        disabled={busy}
                        onClick={() => run(() => login(a.phone))}
                        className="rounded-xl bg-slate-50 px-3 py-2 text-left ring-1 ring-slate-200 hover:bg-brand-50 hover:ring-brand-200"
                      >
                        <span className="block text-sm font-semibold">{a.label}</span>
                        <span className="block text-xs text-slate-500">{a.hint}</span>
                      </button>
                    ))}
                  </div>
                </div>
                )}
              </>
            ) : (
              <form onSubmit={onRegister} className="space-y-3">
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { value: 'client', label: 'I need a pro' },
                    { value: 'tradesperson', label: 'I am a pro' },
                  ].map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, role: opt.value }))}
                      className={`rounded-xl px-3 py-2.5 text-sm font-semibold ring-1 ${form.role === opt.value ? 'bg-brand-50 text-brand-700 ring-brand-300' : 'ring-slate-200'}`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
                <div>
                  <label className="label" htmlFor="name">Full name</label>
                  <input id="name" className="input" value={form.name} onChange={set('name')} required minLength={2} />
                </div>
                <div>
                  <label className="label" htmlFor="rphone">Phone number</label>
                  <input id="rphone" className="input" inputMode="tel" placeholder="05XXXXXXXX" value={form.phone} onChange={set('phone')} required />
                </div>
                {form.role === 'tradesperson' && (
                  <>
                    <div>
                      <label className="label" htmlFor="trade">Trade</label>
                      <select id="trade" className="input" value={form.serviceType} onChange={set('serviceType')}>
                        <option value="electrician">Electrician</option>
                        <option value="plumber">Plumber</option>
                        <option value="handyman">Handyman</option>
                      </select>
                    </div>
                    <div>
                      <label className="label" htmlFor="license">License number</label>
                      <input id="license" className="input" value={form.licenseNumber} onChange={set('licenseNumber')} required minLength={3} />
                    </div>
                  </>
                )}
                {otpSentTo === form.phone && codeField}
                <button className="btn-primary w-full" disabled={busy}>
                  {busy && <Loader2 className="h-4 w-4 animate-spin" />} {submitLabel || 'Create account'}
                </button>
              </form>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
