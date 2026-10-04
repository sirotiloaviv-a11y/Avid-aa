'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, getToken, setToken } from './api.js';
import { closeSocket } from './socket.js';
import { DEMO_PHONE_BY_ROLE } from './demo/mockServer.js';
import { useDemo } from './demo/DemoContext';

const SessionContext = createContext(null);

export const HOME_BY_ROLE = {
  client: '/client',
  tradesperson: '/pro',
  admin: '/admin/flagged-jobs',
};

export function SessionProvider({ children = null }) {
  const { mode, bumpEpoch } = useDemo();
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setProfile(null);
      setLoading(false);
      return;
    }
    try {
      const data = await api('/api/auth/me');
      setUser(data.user);
      setProfile(data.profile);
    } catch (err) {
      if (err.status === 401 || err.code === 'SWITCHED_TO_DEMO') setToken(null);
      setUser(null);
      setProfile(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Runs once the mode is known, and again if the app falls back to demo.
  useEffect(() => {
    if (mode) refresh();
  }, [refresh, mode]);

  const applyAuth = useCallback((data) => {
    setToken(data.token);
    closeSocket();
    setUser(data.user);
    setProfile(data.profile);
    return data.user;
  }, []);

  // With OTP enabled on the server, call requestOtp(phone) first and pass the
  // texted code as otpCode.
  const requestOtp = useCallback((phone) => api('/api/auth/otp/request', { method: 'POST', body: { phone } }), []);
  const login = useCallback(
    async (phone, otpCode) => applyAuth(await api('/api/auth/login', { method: 'POST', body: { phone, otpCode: otpCode || undefined } })),
    [applyAuth],
  );
  const register = useCallback(async (payload) => applyAuth(await api('/api/auth/register', { method: 'POST', body: payload })), [applyAuth]);

  // Demo mode only: sign in as the seeded account for a role.
  const loginAsRole = useCallback(async (role) => {
    const u = await login(DEMO_PHONE_BY_ROLE[role]);
    bumpEpoch();
    return u;
  }, [login, bumpEpoch]);

  const logout = useCallback(() => {
    setToken(null);
    closeSocket();
    setUser(null);
    setProfile(null);
  }, []);

  const value = useMemo(
    () => ({ user, profile, setProfile, loading, login, requestOtp, register, logout, refresh, loginAsRole }),
    [user, profile, loading, login, requestOtp, register, logout, refresh, loginAsRole],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside SessionProvider');
  return ctx;
}
