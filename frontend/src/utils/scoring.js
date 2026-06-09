/**
 * QUAEST.TECH — Scoring Utilities
 * LT/Opt breakdown extraction, Reality Check computation, Tempering Grades.
 */

import {
  Ruler, Scale, DollarSign, TrendingUp, FileText, RefreshCw,
  Activity, Target, Gauge, Waves, Zap,
} from '../components/ui/icons';

// ── Component names for display (Icon = Lucide component, never an emoji) ──
const LT_COMPONENTS = [
  { key: 'rule_of_40', name: 'Rule of 40', Icon: Ruler },
  { key: 'valuation', name: 'Valuation', Icon: Scale },
  { key: 'fcf_margin', name: 'FCF Margin', Icon: DollarSign },
  { key: 'trend', name: 'Trend', Icon: TrendingUp },
  { key: 'earnings_quality', name: 'Earnings', Icon: FileText },
  { key: 'discount_momentum', name: 'Momentum', Icon: RefreshCw },
];

// earnings_catalyst is no longer a base-scored component — it is applied as a
// multiplier on the final Opt Score (surfaced in the play's reason text).
const OPT_COMPONENTS = [
  { key: 'iv_context', name: 'IV Context', Icon: Activity },
  { key: 'directional', name: 'Directional', Icon: Target },
  { key: 'technical', name: 'Technical', Icon: Gauge },
  { key: 'liquidity', name: 'Liquidity', Icon: Waves },
  { key: 'asymmetry', name: 'Asymmetry', Icon: Scale },
];

// ── RC component display config ──
const RC_COMPONENTS = [
  { key: 'trade_quality', name: 'Trade Quality', Icon: Activity, max: 25 },
  { key: 'execution', name: 'Execution', Icon: Waves, max: 20 },
  { key: 'score_alignment', name: 'Score Align', Icon: Target, max: 20 },
  { key: 'iv_context', name: 'IV Context', Icon: Activity, max: 15 },
  { key: 'catalyst', name: 'Catalyst', Icon: Zap, max: 10 },
  { key: 'technical', name: 'Technical', Icon: Gauge, max: 10 },
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
 * Read the unified directional bias persisted in opt_breakdown
 * (single source of truth — scanner.compute_directional_bias).
 * Returns 'bullish' | 'bearish' | 'neutral'.
 */
export function rowDirection(row) {
  if (!row) return 'neutral';
  let bd;
  try {
    bd = typeof row.opt_breakdown === 'string' ? JSON.parse(row.opt_breakdown) : row.opt_breakdown;
  } catch { return 'neutral'; }
  const dir = bd?.directional?.raw_value?.direction;
  return dir || 'neutral';
}

/** Combined conviction: opt_score × 0.6 + lt_score × 0.4 (CLAUDE.md). */
export function convictionScore(row) {
  if (!row) return 0;
  return (row.opt_score || 0) * 0.6 + (row.lt_score || 0) * 0.4;
}

/** A small [sma200, sma50, sma20, price] series for the 50-day trend sparkline. */
export function trendSeries(row) {
  if (!row) return [];
  return [row.sma_200, row.sma_50, row.sma_20, row.price].filter(v => typeof v === 'number' && isFinite(v) && v > 0);
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
