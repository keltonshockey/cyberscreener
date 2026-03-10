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

const OPT_COMPONENTS = [
  { key: 'earnings_catalyst', name: 'Catalyst', icon: '⚡' },
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
 * Prefers server-computed rc_score; falls back to client-side computation.
 */
export function getRC(play) {
  if (!play) return 0;
  // Prefer server-computed RC (unified scorer)
  if (play.rc_score != null) return play.rc_score;
  // Fallback: client-side computation
  return computeRC(play);
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

/**
 * Client-side Reality Check scoring (fallback if server RC not available).
 * Mirrors the unified server RC logic from _compute_rc().
 */
export function computeRC(play) {
  if (!play) return 0;
  let score = 0;

  // 1. Trade Quality (max 25)
  const rr = play.risk_reward_ratio || 0;
  const beDist = play.breakeven_distance_pct || Math.abs(play.pct_to_breakeven || 0);
  let tq = 0;
  if (rr >= 3) tq += 18;
  else if (rr >= 2) tq += 14;
  else if (rr >= 1) tq += 9;
  else if (rr >= 0.5) tq += 4;
  if (beDist < 3) tq += 7;
  else if (beDist < 6) tq += 5;
  else if (beDist < 10) tq += 3;
  else if (beDist < 15) tq += 1;
  score += Math.min(25, tq);

  // 2. Execution Quality (max 20)
  const vol = play.volume || 0;
  const oi = play.open_interest || 0;
  const spread = play.bid_ask_spread_pct || 999;
  let eq = 0;
  if (vol >= 500) eq += 6;
  else if (vol >= 100) eq += 4;
  else if (vol >= 30) eq += 2;
  if (oi >= 2000) eq += 6;
  else if (oi >= 500) eq += 4;
  else if (oi >= 100) eq += 2;
  if (spread < 5) eq += 8;
  else if (spread < 10) eq += 5;
  else if (spread < 20) eq += 2;
  score += Math.min(20, eq);

  // 3. DTE timing (max 5 — simplified without opt_score/lt_score context)
  const dte = play.dte || 0;
  if (dte >= 14 && dte <= 60) score += 5;
  else if (dte >= 7 && dte <= 90) score += 3;

  // 4. IV percentile if available (max 10 — simplified)
  const ivp = play.iv_percentile || play.iv_pct || 0;
  const dir = (play.direction || '').toLowerCase();
  if (ivp > 0) {
    const isBuying = dir.includes('bullish') || dir.includes('bearish');
    if (isBuying) {
      if (ivp < 30) score += 10;
      else if (ivp < 50) score += 6;
    } else {
      if (ivp > 60) score += 10;
      else if (ivp > 40) score += 6;
    }
  }

  return Math.min(100, score);
}

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
