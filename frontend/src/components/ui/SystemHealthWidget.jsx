/**
 * QUAEST — System Health Widget
 * Polls /health/detailed every 5 min and displays scanner/data/weight sanity status.
 * Collapsed by default; expands on click to show per-check breakdown.
 */

import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || '';

const STATUS_COLOR = {
  healthy:  'var(--color-success)',
  degraded: 'var(--forge-amber, #d4a017)',
  critical: 'var(--color-danger)',
};

const CHECK_COLOR = {
  ok:   'var(--color-success)',
  warn: 'var(--forge-amber, #d4a017)',
  fail: 'var(--color-danger)',
};

const CHECK_ICON = { ok: '●', warn: '▲', fail: '✕' };

const CHECK_LABELS = {
  scanner:  'Scanner',
  coverage: 'Data Coverage',
  weights:  'Scoring Weights',
  database: 'Database',
};

export function SystemHealthWidget() {
  const [health, setHealth] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [lastFetch, setLastFetch] = useState(null);

  const fetch_ = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/health/detailed`);
      if (!r.ok) return;
      const d = await r.json();
      setHealth(d);
      setLastFetch(new Date());
    } catch {
      // silent — don't break page if health check fails
    }
  }, []);

  useEffect(() => {
    fetch_();
    const id = setInterval(fetch_, 5 * 60 * 1000); // every 5 min
    return () => clearInterval(id);
  }, [fetch_]);

  if (!health) return null;

  const color = STATUS_COLOR[health.status] || 'var(--color-text-secondary)';
  const checks = Object.entries(health.checks || {});
  const hasIssues = health.status !== 'healthy';

  // Summarise issues for the collapsed line
  const failedChecks = checks.filter(([, c]) => c.status !== 'ok');
  const summary = hasIssues
    ? failedChecks.map(([, c]) => c.message).join(' · ')
    : 'All systems nominal';

  return (
    <div
      onClick={() => setExpanded(e => !e)}
      style={{
        cursor: 'pointer',
        borderRadius: 8,
        border: `1px solid ${hasIssues ? color + '60' : 'var(--color-border-subtle)'}`,
        background: hasIssues ? color + '08' : 'var(--color-bg)',
        padding: '8px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: expanded ? 10 : 0,
        transition: 'all 0.15s ease',
        userSelect: 'none',
      }}
    >
      {/* Collapsed row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 9, color, fontWeight: 700, letterSpacing: '0.08em', fontFamily: 'var(--font-mono)' }}>
          ● {health.status.toUpperCase()}
        </span>
        <span style={{ fontSize: 10, color: 'var(--color-text-secondary)', flex: 1 }}>
          {summary}
        </span>
        <span style={{ fontSize: 9, color: 'var(--color-text-tertiary)' }}>
          {lastFetch ? `updated ${Math.round((Date.now() - lastFetch) / 60000) || '<1'}m ago` : ''}
          {' '}{expanded ? '▲' : '▼'}
        </span>
      </div>

      {/* Expanded breakdown */}
      {expanded && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }} onClick={e => e.stopPropagation()}>
          <div style={{ height: 1, background: 'var(--color-border-subtle)', margin: '2px 0' }} />
          {checks.map(([key, check]) => (
            <div key={key} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
              <span style={{ fontSize: 10, color: CHECK_COLOR[check.status], fontWeight: 700, minWidth: 10, marginTop: 1 }}>
                {CHECK_ICON[check.status]}
              </span>
              <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--color-text)', minWidth: 110 }}>
                {CHECK_LABELS[key] || key}
              </span>
              <span style={{ fontSize: 10, color: 'var(--color-text-secondary)', flex: 1 }}>
                {check.message}
              </span>
            </div>
          ))}
          <div style={{ marginTop: 2, fontSize: 9, color: 'var(--color-text-tertiary)' }}>
            Refreshes every 5 min · plays with CAUTION or FAIL rating are flagged independently
          </div>
        </div>
      )}
    </div>
  );
}
