/**
 * QUAEST — System Health Widget
 * Polls /health/detailed every 5 min and displays scanner/data/weight sanity status.
 * Collapsed by default; expands on click to show per-check breakdown.
 */

import { useState, useEffect, useCallback } from 'react';
import { Activity, AlertTriangle, X, ChevronDown, ChevronUp } from './icons';

const API_BASE = import.meta.env.VITE_API_URL || '';

const STATUS_COLOR = {
  healthy:  'var(--gain)',
  degraded: 'var(--gold)',
  critical: 'var(--loss)',
};

const CHECK_COLOR = {
  ok:   'var(--gain)',
  warn: 'var(--gold)',
  fail: 'var(--loss)',
};

const CHECK_ICON = { ok: Activity, warn: AlertTriangle, fail: X };

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

  const color = STATUS_COLOR[health.status] || 'var(--ink-mut)';
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
        border: `1px solid ${hasIssues ? color + '60' : 'var(--line)'}`,
        background: hasIssues ? color + '12' : 'var(--surface)',
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
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 9, color, fontWeight: 700, letterSpacing: '0.08em', fontFamily: 'var(--font-mono)' }}>
          <Activity size={11} /> {health.status.toUpperCase()}
        </span>
        <span style={{ fontSize: 10, color: 'var(--ink-mut)', flex: 1 }}>
          {summary}
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 9, color: 'var(--ink-dim)' }}>
          {lastFetch ? `updated ${Math.round((Date.now() - lastFetch) / 60000) || '<1'}m ago` : ''}
          {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        </span>
      </div>

      {/* Expanded breakdown */}
      {expanded && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }} onClick={e => e.stopPropagation()}>
          <div style={{ height: 1, background: 'var(--line-soft)', margin: '2px 0' }} />
          {checks.map(([key, check]) => {
            const Icon = CHECK_ICON[check.status] || Activity;
            return (
              <div key={key} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <span style={{ color: CHECK_COLOR[check.status], minWidth: 14, marginTop: 1, display: 'inline-flex' }}>
                  <Icon size={12} />
                </span>
                <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--ink)', minWidth: 110 }}>
                  {CHECK_LABELS[key] || key}
                </span>
                <span style={{ fontSize: 10, color: 'var(--ink-mut)', flex: 1 }}>
                  {check.message}
                </span>
              </div>
            );
          })}
          <div style={{ marginTop: 2, fontSize: 9, color: 'var(--ink-dim)' }}>
            Refreshes every 5 min · plays with CAUTION or FAIL rating are flagged independently
          </div>
        </div>
      )}
    </div>
  );
}
