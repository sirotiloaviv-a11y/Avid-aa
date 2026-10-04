'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { api, getToken, setToken } from './api';
import { closeSocket } from './socket';

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

  const logout = useCallback(() => {
    setToken(null);
    closeSocket();
    setUser(null);
    setProfile(null);
  }, []);

  const value = useMemo(
    () => ({ user, profile, setProfile, loading, login, register, logout, refresh }),
    [user, profile, loading, login, register, logout, refresh],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside SessionProvider');
  return ctx;
}
