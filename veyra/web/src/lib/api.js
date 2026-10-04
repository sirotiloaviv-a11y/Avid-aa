export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error ?? `Request failed (${status})`);
    this.status = status;
    this.fields = body?.fields ?? {};
  }
}

async function request(method, path, body) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, { error: 'Cannot reach the Veyra API. Is the server running on port 4000?' });
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, payload);
  return payload;
}

const enc = encodeURIComponent;

export const api = {
  dashboard: () => request('GET', '/dashboard'),
  recommendations: (limit) => request('GET', `/recommendations${limit ? `?limit=${limit}` : ''}`),
  findings: (filters = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString();
    return request('GET', `/findings${query ? `?${query}` : ''}`);
  },
  remediate: (id) => request('POST', `/findings/${enc(id)}/remediate`),
  connect: (id, credentials) => request('POST', `/integrations/${enc(id)}/connect`, { credentials }),
  disconnect: (id) => request('POST', `/integrations/${enc(id)}/disconnect`),
  setEnabled: (id, enabled) => request('PATCH', `/integrations/${enc(id)}`, { enabled }),
  sync: (id) => request('POST', `/integrations/${enc(id)}/sync`),
  syncAll: () => request('POST', '/sync'),
  reset: () => request('POST', '/demo/reset'),
};
