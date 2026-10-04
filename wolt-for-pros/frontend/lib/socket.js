'use client';

import { useEffect, useRef } from 'react';
import { io } from 'socket.io-client';
import { API_URL, getToken } from './api';
import { isDemoMode } from './demo/mode';
import { demoSocket } from './demo/mockServer';

let socket = null;
let socketToken = null;

export function getSocket() {
  const token = getToken();
  if (!token) return null;
  if (isDemoMode()) return demoSocket;
  if (socket && socketToken === token) return socket;
  if (socket) socket.disconnect();
  socket = io(API_URL, { auth: { token }, transports: ['websocket', 'polling'] });
  socketToken = token;
  return socket;
}

export function closeSocket() {
  if (socket) socket.disconnect();
  socket = null;
  socketToken = null;
}

// Subscribe to a socket event for the lifetime of the component. The handler
// can change between renders without re-subscribing.
export function useSocketEvent(event, handler) {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  useEffect(() => {
    const s = getSocket();
    if (!s) return undefined;
    const listener = (...args) => handlerRef.current(...args);
    s.on(event, listener);
    return () => {
      s.off(event, listener);
    };
  }, [event]);
}

// Join a job's room (and re-join after every reconnect, since rooms do not
// survive one). onJoined receives the server's ack, including the last known
// tradesperson location.
export function useJobChannel(jobId, onJoined) {
  const joinedRef = useRef(onJoined);
  joinedRef.current = onJoined;

  useEffect(() => {
    const s = getSocket();
    if (!s || !jobId) return undefined;
    const join = () => {
      s.emit('job:subscribe', { jobId }, (ack) => {
        if (ack && ack.ok && joinedRef.current) joinedRef.current(ack);
      });
    };
    if (s.connected) join();
    s.on('connect', join);
    return () => {
      s.off('connect', join);
      s.emit('job:unsubscribe', { jobId });
    };
  }, [jobId]);
}
