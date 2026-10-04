export const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:4000').replace(/\/$/, '');

const TOKEN_KEY = 'wfp_token';

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage unavailable (private mode); the session lasts until reload.
  }
}

export class ApiError extends Error {
  constructor(message, status, code, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export async function api(path, { method = 'GET', body, query } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let url = `${API_URL}${path}`;
  if (query) {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') params.set(k, String(v));
    });
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  let res;
  try {
    res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(`Cannot reach the server at ${API_URL}. Is the backend running?`, 0, 'NETWORK');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = data.error || {};
    throw new ApiError(fieldMessage(err) || err.message || res.statusText, res.status, err.code, err.details);
  }
  return data;
}

// Surface the first field-level validation message when there is one.
function fieldMessage(err) {
  const fields = err && err.details && err.details.fieldErrors;
  if (!fields) return null;
  const first = Object.entries(fields).find(([, msgs]) => msgs && msgs.length);
  return first ? `${first[0]}: ${first[1][0]}` : null;
}
