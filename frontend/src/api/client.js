/**
 * QUAEST.TECH — API Client
 * JWT-authenticated fetch wrapper with auto-refresh on 401.
 */

const TOKEN_KEY = 'quaest_jwt';
const REFRESH_KEY = 'quaest_refresh';
const USER_KEY = 'quaest_user';

// ── Token Management ──

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setTokens(access, refresh) {
  localStorage.setItem(TOKEN_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getStoredUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setStoredUser(user) {
  if (user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  } else {
    localStorage.removeItem(USER_KEY);
  }
}

// ── API Fetch Wrapper ──

/**
 * Fetch wrapper that handles JWT auth + auto-refresh on 401.
 * @param {string} path - API path (e.g. '/scores/latest')
 * @param {RequestInit} opts - Fetch options (method, body, headers, etc.)
 * @returns {Promise<any|null>} Parsed JSON or null on error
 */
export async function api(path, opts = {}) {
  try {
    const token = getToken();
    const headers = { ...(opts.headers || {}) };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(path, { ...opts, headers });

    // Auto-refresh on 401
    if (response.status === 401 && token) {
      const refreshToken = localStorage.getItem(REFRESH_KEY);
      if (refreshToken) {
        const refreshResp = await fetch('/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });

        if (refreshResp.ok) {
          const data = await refreshResp.json();
          setTokens(data.access_token, data.refresh_token);
          headers['Authorization'] = `Bearer ${data.access_token}`;
          const retry = await fetch(path, { ...opts, headers });
          if (!retry.ok) throw new Error(retry.status);
          return await retry.json();
        } else {
          clearTokens();
          return null;
        }
      }
    }

    if (!response.ok) throw new Error(response.status);
    return await response.json();
  } catch (err) {
    console.error(`API ${path}:`, err);
    return null;
  }
}
