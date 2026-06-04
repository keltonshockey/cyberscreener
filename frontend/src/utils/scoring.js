/**
 * QUAEST.TECH — Scoring Utilities
 * LT/Opt breakdown extraction, Reality Check computation, Tempering Grades.
 */

// ── Component names for display ──
const LT_COMPONENTS = [
  { key: 'rule_of_40', name: 'Rule of 40', icon: '📐' },
  { key: 'valuation', name: 'Valuation', icon: '⚖️' },
  { key: 'fcf_margin', name: 'FCF Margin', icon: '💰' },
  { key: 'trend', name: 'Trend', icon: '📈' },
  { key: 'earnings_quality', name: 'Earnings', icon: '📊' },
  { key: 'discount_momentum', name: 'Momentum', icon: '🔄' },
];

// earnings_catalyst is no longer a base-scored component — it is applied as a
// multiplier on the final Opt Score (surfaced in the play's reason text).
const OPT_COMPONENTS = [
  { key: 'iv_context', name: 'IV Context', icon: '📉' },
  { key: 'directional', name: 'Directional', icon: '🎯' },
  { key: 'technical', name: 'Technical', icon: '🔧' },
  { key: 'liquidity', name: 'Liquidity', icon: '💧' },
  { key: 'asymmetry', name: 'Asymmetry', icon: '⚖️' },
];

// ── RC component display config ──
const RC_COMPONENTS = [
  { key: 'trade_quality', name: 'Trade Quality', icon: '📊', max: 25 },
  { key: 'execution', name: 'Execution', icon: '💧', max: 20 },
  { key: 'score_alignment', name: 'Score Align', icon: '🎯', max: 20 },
  { key: 'iv_context', name: 'IV Context', icon: '📉', max: 15 },
  { key: 'catalyst', name: 'Catalyst', icon: '⚡', max: 10 },
  { key: 'technical', name: 'Technical', icon: '🔧', max: 10 },
];

/**
 * Extract LT breakdown from a score row.
 * Returns array of { key, name, icon, points, max, raw, pct }
 */
export function ltBreakdown(row) {
  if (!row) return [];
  let bd;
  try {
    bd = typeof row.lt_breakdown === 'string' ? JSON.parse(row.lt_breakdown) : row.lt_breakdown;
  } catch { return []; }
  if (!bd) return [];

  return LT_COMPONENTS.map(c => {
    const entry = bd[c.key] || {};
    const points = entry.points ?? 0;
    const max = entry.max ?? 1;
    const raw = entry.raw ?? (max > 0 ? points / max : 0);
    return { ...c, points, max, raw, pct: max > 0 ? (points / max) * 100 : 0 };
  });
}

/**
 * Extract Options breakdown from a score row.
 */
export function optBreakdown(row) {
  if (!row) return [];
  let bd;
  try {
    bd = typeof row.opt_breakdown === 'string' ? JSON.parse(row.opt_breakdown) : row.opt_breakdown;
  } catch { return []; }
  if (!bd) return [];

  return OPT_COMPONENTS.map(c => {
    const entry = bd[c.key] || {};
    const points = entry.points ?? 0;
    const max = entry.max ?? 1;
    const raw = entry.raw ?? (max > 0 ? points / max : 0);
    return { ...c, points, max, raw, pct: max > 0 ? (points / max) * 100 : 0 };
  });
}

/**
 * Get the Reality Check score for a play.
 * Server always computes RC now — no client fallback needed.
 */
export function getRC(play) {
  if (!play) return 0;
  return play.rc_score || 0;
}

/**
 * Extract RC breakdown from server-provided data.
 * Returns array of { key, name, icon, points, max, detail, pct } or empty.
 */
export function rcBreakdown(play) {
  if (!play?.rc_breakdown) return [];
  const bd = play.rc_breakdown;
  return RC_COMPONENTS.map(c => {
    const entry = bd[c.key] || {};
    return {
      ...c,
      points: entry.points ?? 0,
      max: entry.max ?? c.max,
      detail: entry.detail || '',
      pct: entry.max > 0 ? ((entry.points ?? 0) / entry.max) * 100 : 0,
    };
  });
}

// computeRC removed — server always computes unified RC now

/**
 * Tempering Grades based on Sharpe ratio and drawdown.
 */
export function temperingGrade(sharpe, maxDrawdown) {
  if (sharpe == null) return { grade: 'UNTEMPERED', color: 'var(--color-text-tertiary)' };

  if (sharpe > 1.5 && (maxDrawdown == null || Math.abs(maxDrawdown) < 15)) {
    return { grade: 'DAMASCUS', color: 'var(--forge-amber)' };
  }
  if (sharpe > 1.0) {
    return { grade: 'STEEL', color: 'var(--denarius-silver)' };
  }
  if (sharpe > 0.5) {
    return { grade: 'BRONZE', color: 'var(--oxidized-bronze)' };
  }
  return { grade: 'IRON', color: 'var(--color-text-secondary)' };
}

/**
 * Get RC verdict label + color.
 */
export function rcVerdict(score) {
  if (score >= 70) return { label: 'PASS', color: 'var(--color-success)' };
  if (score >= 40) return { label: 'CAUTION', color: 'var(--color-warning)' };
  return { label: 'FAIL', color: 'var(--color-danger)' };
}
