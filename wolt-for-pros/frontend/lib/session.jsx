'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, getToken, setToken } from './api';
import { closeSocket } from './socket';
import { resolveMode } from './demo/mode';
import { DEMO_PHONE_BY_ROLE, resetDemo } from './demo/mockServer';

const SessionContext = createContext(null);

export const HOME_BY_ROLE = {
  client: '/client',
  tradesperson: '/pro',
  admin: '/admin/flagged-jobs',
};

export function SessionProvider({ children }) {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState(null); // 'live' | 'demo'
  // Bumped on demo role switches and resets so pages remount and refetch.
  const [epoch, setEpoch] = useState(0);

  const refresh = useCallback(async () => {
    setMode(await resolveMode());
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
      if (err.status === 401) setToken(null);
      setUser(null);
      setProfile(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const applyAuth = useCallback((data) => {
    setToken(data.token);
    closeSocket();
    setUser(data.user);
    setProfile(data.profile);
    return data.user;
  }, []);

  const login = useCallback(async (phone) => applyAuth(await api('/api/auth/login', { method: 'POST', body: { phone } })), [applyAuth]);
  const register = useCallback(async (payload) => applyAuth(await api('/api/auth/register', { method: 'POST', body: payload })), [applyAuth]);

  // Demo mode only: sign in as the seeded account for a role.
  const loginAsRole = useCallback(async (role) => {
    const u = await login(DEMO_PHONE_BY_ROLE[role]);
    setEpoch((e) => e + 1);
    return u;
  }, [login]);

  const resetDemoData = useCallback(async () => {
    resetDemo();
    if (user) await login(user.phone);
    setEpoch((e) => e + 1);
  }, [login, user]);

  const logout = useCallback(() => {
    setToken(null);
    closeSocket();
    setUser(null);
    setProfile(null);
  }, []);

  const value = useMemo(
    () => ({ user, profile, setProfile, loading, login, register, logout, refresh, mode, epoch, loginAsRole, resetDemoData }),
    [user, profile, loading, login, register, logout, refresh, mode, epoch, loginAsRole, resetDemoData],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside SessionProvider');
  return ctx;
}
