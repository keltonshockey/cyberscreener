/**
 * QUAEST.TECH — Formatting Utilities
 */

// ── Timezone ──
export const TZ_KEY = 'quaest_tz';
export const TZ_OPTIONS = [
  { label: 'Auto', value: '' },
  { label: 'PT', value: 'America/Los_Angeles' },
  { label: 'MT', value: 'America/Denver' },
  { label: 'CT', value: 'America/Chicago' },
  { label: 'ET', value: 'America/New_York' },
  { label: 'UTC', value: 'UTC' },
];

export function getStoredTz() {
  return localStorage.getItem(TZ_KEY) || '';
}

export function setStoredTz(tz) {
  localStorage.setItem(TZ_KEY, tz);
}

// ── Timestamp Parsing ──
function parseTS(ts) {
  if (!ts) return null;
  const s = String(ts);
  const clean = s.includes('T') || s.endsWith('Z') ? s : s.replace(' ', 'T') + 'Z';
  const d = new Date(clean);
  return isNaN(d) ? null : d;
}

// ── Format: "Feb 24, 3:15 PM" ──
export function fmtTS(ts, tz, opts) {
  const d = parseTS(ts);
  if (!d) return '—';
  const tzVal = tz || Intl.DateTimeFormat().resolvedOptions().timeZone;
  try {
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit',
      ...(opts || {}),
      timeZone: tzVal,
    });
  } catch {
    return d.toLocaleString();
  }
}

// ── Format: "3:15 PM" ──
export function fmtTimeOnly(ts, tz) {
  const d = parseTS(ts);
  if (!d) return '—';
  const tzVal = tz || Intl.DateTimeFormat().resolvedOptions().timeZone;
  try {
    return d.toLocaleString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: tzVal });
  } catch {
    return d.toLocaleTimeString();
  }
}

// ── Format: "Feb 24" ──
export function fmtDateOnly(ts, tz) {
  const d = parseTS(ts);
  if (!d) return '—';
  const tzVal = tz || Intl.DateTimeFormat().resolvedOptions().timeZone;
  try {
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', timeZone: tzVal });
  } catch {
    return d.toLocaleDateString();
  }
}

// ── Format expiry date: "Mar 21" ──
export function fmtExpiry(dateStr) {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr + 'T12:00:00Z');
    if (isNaN(d)) return dateStr;
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
  } catch {
    return dateStr;
  }
}

// ── Format: "Feb 24, 3:15 PM" (calendar row) ──
export function fmtCalRow(ts, tz) {
  const d = parseTS(ts);
  if (!d) return '—';
  const tzVal = tz || Intl.DateTimeFormat().resolvedOptions().timeZone;
  try {
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit',
      timeZone: tzVal,
    });
  } catch {
    return String(ts).slice(0, 16);
  }
}

// ── Number formatting ──
export function fmtPct(value, decimals = 1) {
  if (value == null || isNaN(value)) return '—';
  return `${value >= 0 ? '+' : ''}${Number(value).toFixed(decimals)}%`;
}

export function fmtPrice(value) {
  if (value == null || isNaN(value)) return '—';
  return `$${Number(value).toFixed(2)}`;
}

export function fmtNum(value, decimals = 1) {
  if (value == null || isNaN(value)) return '—';
  return Number(value).toFixed(decimals);
}
