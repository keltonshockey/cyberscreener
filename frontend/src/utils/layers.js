/**
 * QUAEST.TECH — Layer view composition (SESSION-BASELINE-WEIGHTS).
 *
 * The backend baseline score funds only evidence-backed components
 * (LT = Valuation, Opt = Asymmetry). Every demoted component is still
 * computed and persisted per scan; the user can ADD it back here as an
 * explicitly experimental view.
 *
 * View semantics (mirrors /layers `view_semantics`): the view score for a
 * stack is the reference-weighted composite over {baseline components +
 * selected layers}, renormalized to 100:
 *     view = sum(raw_k * ref_w_k) / sum(ref_w_k) * 100
 * Baseline alone reduces to the pure baseline score; selecting every layer
 * reproduces the legacy composite (minus the earnings multiplier, which is
 * a non-composable context layer). Captions and weights come from /layers —
 * never hard-coded here.
 */

function parseBreakdown(row, stack) {
  const raw = stack === 'lt' ? row?.lt_breakdown : row?.opt_breakdown;
  if (!raw) return null;
  try {
    return typeof raw === 'string' ? JSON.parse(raw) : raw;
  } catch {
    return null;
  }
}

function componentRaw(bd, key) {
  const entry = bd?.[key];
  if (!entry) return 0;
  if (typeof entry.raw === 'number') return Math.max(0, Math.min(1, entry.raw));
  const max = entry.max || 0;
  return max > 0 ? Math.max(0, Math.min(1, (entry.points || 0) / max)) : 0;
}

/** Layer keys that can mathematically join a composite (ref weight > 0). */
export function composableLayers(cfg, stack) {
  if (!cfg?.layers) return [];
  return Object.entries(cfg.layers)
    .filter(([key, l]) => l.stack === stack && (cfg.ref_weights?.[stack]?.[key] || 0) > 0)
    .map(([key, l]) => ({ key, ...l }));
}

/** Context-only layers (multiplier / modifier) — shown, never composed. */
export function contextLayers(cfg) {
  if (!cfg?.layers) return [];
  return Object.entries(cfg.layers)
    .filter(([key, l]) => (cfg.ref_weights?.[l.stack]?.[key] || 0) === 0)
    .map(([key, l]) => ({ key, ...l }));
}

/**
 * Compose one stack's view score for a row. Returns null when the row has no
 * usable breakdown (callers fall back to the served baseline score).
 */
export function composeStackScore(row, stack, activeKeys, cfg) {
  const bd = parseBreakdown(row, stack);
  const refW = cfg?.ref_weights?.[stack];
  const baselineComps = Object.keys(cfg?.baseline?.[stack] || {});
  if (!bd || !refW || baselineComps.length === 0) return null;

  const selected = new Set(baselineComps);
  for (const k of activeKeys) {
    if (cfg.layers?.[k]?.stack === stack && (refW[k] || 0) > 0) selected.add(k);
  }
  let total = 0;
  let sum = 0;
  for (const k of selected) {
    const w = refW[k] || 0;
    total += w;
    sum += componentRaw(bd, k) * w;
  }
  if (total <= 0) return null;
  return Math.round((sum / total) * 1000) / 10;
}

/**
 * Map rows to their layer-view equivalents: lt_score / opt_score replaced by
 * the composed view (so sorting, conviction, and badges all follow), with the
 * served baseline kept under baseline_lt_score / baseline_opt_score.
 * No layers active -> rows returned untouched.
 */
export function applyLayerView(rows, activeKeys, cfg) {
  if (!cfg || !activeKeys || activeKeys.size === 0) return rows;
  const keys = [...activeKeys];
  return rows.map(r => {
    const lt = composeStackScore(r, 'lt', keys, cfg);
    const opt = composeStackScore(r, 'opt', keys, cfg);
    if (lt === null && opt === null) return r;
    return {
      ...r,
      baseline_lt_score: r.lt_score,
      baseline_opt_score: r.opt_score,
      lt_score: lt ?? r.lt_score,
      opt_score: opt ?? r.opt_score,
    };
  });
}
