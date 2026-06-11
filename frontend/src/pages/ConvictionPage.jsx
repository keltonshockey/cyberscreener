/**
 * QUAEST.TECH — Forum (long-term value rankings)
 * The hero data grid: Imperial Twilight, gold hairlines, tabular figures,
 * conviction tier badges, sparklines, Roman-tinted polarity. Two-stack spine
 * (segmented control), sector filter chips (multi-tag), saved views, column
 * chooser, instant client-side re-sort, sticky header, hover-explain on every
 * metric. Detail panel rebuilds the signals feed with relevance + polarity.
 * Targets: ui-grid.html + ui-mockup.html.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Stat } from '../components/ui/Stat';
import { Chip } from '../components/ui/Chip';
import { Explain } from '../components/ui/Explain';
import { Sparkline } from '../components/ui/Sparkline';
import { TierBadge } from '../components/ui/TierBadge';
import { SegmentedControl } from '../components/ui/SegmentedControl';
import { BreakdownPanel } from '../components/ui/BreakdownPanel';
import { InteractiveScoreChart } from '../components/charts/InteractiveScoreChart';
import { InteractivePriceChart } from '../components/charts/InteractivePriceChart';
import {
  LineChart, Zap, Activity, ListFilter, ChevronDown, Star, ChevronUp, ChevronRight,
} from '../components/ui/icons';
import {
  fetchScoreHistory, fetchSignals, fetchWatchlist, addWatchlistTicker, removeWatchlistTicker,
  fetchSparklines, fetchLayers,
} from '../api/endpoints';
import {
  ltBreakdown, optBreakdown, rowDirection, convictionScore, trendSeries,
} from '../utils/scoring';
import { applyLayerView, composableLayers } from '../utils/layers';
import { tagsFor, tagCounts, SECTOR_TAGS } from '../utils/sectors';
import { classifySignals } from '../utils/signals';
import styles from './ConvictionPage.module.css';

const STACKS = [
  { value: 'lt', label: 'Long-term value', Icon: LineChart },
  { value: 'options', label: 'Tactical options', Icon: Zap },
];

// Grid columns. accessor -> sortable value. `optional` columns are toggleable
// via the column chooser.
const COLUMNS = [
  { key: 'ticker', label: 'Ticker', align: 'l', get: r => r.ticker },
  { key: 'lt', label: 'LT', term: 'lt_score', get: r => r.lt_score },
  { key: 'opt', label: 'Opt', term: 'opt_score', get: r => r.opt_score, optional: true },
  // Real per-row reality-check proxy (ticker-level, play-independent) — now emitted
  // on every score row, so the column is honest rather than aliased to Opt.
  { key: 'reality', label: 'Reality', term: 'rc_score', get: r => r.rc_score, optional: true },
  { key: 'conviction', label: 'Conviction', term: 'conviction', get: r => convictionScore(r) },
  { key: 'pe', label: 'P/E', term: 'pe', get: r => r.pe_ratio, optional: true },
  { key: 'trend', label: '50-day trend', term: 'trend50', get: r => (r.perf_3m ?? 0), optional: true },
  { key: 'lean', label: 'Lean', term: 'direction', get: r => r.opt_score },
];

const POLARITY_COLOR = { up: 'var(--gain)', down: 'var(--loss)', flat: 'var(--ink-mut)' };

function leanMeta(dir) {
  const d = (dir || '').toLowerCase();
  if (d.startsWith('bull')) return { cls: 'up', label: 'Bullish' };
  if (d.startsWith('bear')) return { cls: 'dn', label: 'Bearish' };
  return { cls: 'nt', label: 'Neutral' };
}

export function ConvictionPage({ latest }) {
  const location = useLocation();
  const navigate = useNavigate();
  const results = latest?.results || [];

  const [stack, setStack] = useState('lt');
  const [tags, setTags] = useState(() => new Set());
  const [moreTags, setMoreTags] = useState(false);
  const [sortKey, setSortKey] = useState('conviction');
  const [sortDir, setSortDir] = useState('desc');
  const [hiddenCols, setHiddenCols] = useState(() => new Set());
  const [colMenu, setColMenu] = useState(false);
  const [viewMenu, setViewMenu] = useState(false);
  const [savedViews, setSavedViews] = useState(() => {
    try { return JSON.parse(localStorage.getItem('quaest-screens') || '[]'); } catch { return []; }
  });

  const [sel, setSel] = useState(null);
  const [hist, setHist] = useState(null);
  const [signals, setSignals] = useState(null);
  const [watchlist, setWatchlist] = useState(() => new Set());
  const [wlOnly, setWlOnly] = useState(false);
  const [sparks, setSparks] = useState(() => ({}));
  // Baseline-vs-layers: config from /layers; user-selected experimental layers.
  const [layersCfg, setLayersCfg] = useState(null);
  const [activeLayers, setActiveLayers] = useState(() => new Set());
  const [layersOpen, setLayersOpen] = useState(false);
  const detailRef = useRef(null);

  useEffect(() => {
    fetchWatchlist().then(d => {
      if (d?.tickers) setWatchlist(new Set(d.tickers.map(t => t.ticker || t)));
    });
  }, []);

  // Real recent-price series for the grid sparklines (§3) — one batched call.
  useEffect(() => {
    const tickers = results.map(r => r.ticker).filter(Boolean);
    if (!tickers.length) return;
    let live = true;
    fetchSparklines(tickers, 30)
      .then(d => { if (live && d?.series) setSparks(d.series); })
      .catch(() => {});
    return () => { live = false; };
  }, [results]);

  const counts = useMemo(() => tagCounts(results), [results]);

  const load = useCallback(async (ticker) => {
    setSel(ticker);
    setHist(null);
    setSignals(null);
    const [h, sig] = await Promise.all([
      fetchScoreHistory(ticker, 180),
      fetchSignals(ticker, 60),
    ]);
    if (h) setHist(h);
    if (sig) setSignals(sig);
    requestAnimationFrame(() => detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  }, []);

  // Incoming ticker from search-bar navigation.
  useEffect(() => {
    if (location.state?.ticker) load(location.state.ticker);
  }, [location.state?.ticker, load]);

  // Layers config (captions + ref weights) — served by /layers, never hard-coded.
  useEffect(() => {
    fetchLayers().then(setLayersCfg).catch(() => setLayersCfg(null));
  }, []);

  const toggleLayer = (key) => setActiveLayers(prev => {
    const next = new Set(prev);
    next.has(key) ? next.delete(key) : next.add(key);
    return next;
  });

  // Rows the grid actually shows: baseline scores by default; an explicitly
  // experimental recomposed view when the user adds layers.
  const viewResults = useMemo(
    () => applyLayerView(results, activeLayers, layersCfg),
    [results, activeLayers, layersCfg],
  );

  // Default sort follows the active stack.
  useEffect(() => {
    setSortKey(stack === 'options' ? 'opt' : 'conviction');
    setSortDir('desc');
  }, [stack]);

  const toggleTag = (tag) => setTags(prev => {
    const next = new Set(prev);
    next.has(tag) ? next.delete(tag) : next.add(tag);
    return next;
  });

  const onSort = (key) => {
    if (key === sortKey) setSortDir(d => (d === 'desc' ? 'asc' : 'desc'));
    else { setSortKey(key); setSortDir(key === 'ticker' || key === 'pe' ? 'asc' : 'desc'); }
  };

  const rows = useMemo(() => {
    const col = COLUMNS.find(c => c.key === sortKey) || COLUMNS[3];
    const dir = sortDir === 'asc' ? 1 : -1;
    return viewResults
      .filter(r => !wlOnly || watchlist.has(r.ticker))
      .filter(r => tags.size === 0 || tagsFor(r).some(t => tags.has(t)))
      .slice()
      .sort((a, b) => {
        const va = col.get(a), vb = col.get(b);
        if (typeof va === 'string') return va.localeCompare(vb) * dir;
        return ((va ?? -Infinity) - (vb ?? -Infinity)) * dir;
      });
  }, [viewResults, tags, wlOnly, watchlist, sortKey, sortDir]);

  const toggleWatch = async (ticker, e) => {
    e.stopPropagation();
    const next = new Set(watchlist);
    if (next.has(ticker)) { next.delete(ticker); removeWatchlistTicker(ticker); }
    else { next.add(ticker); addWatchlistTicker(ticker); }
    setWatchlist(next);
  };

  const saveView = () => {
    const name = window.prompt('Name this screen (e.g. "AI bullish ≥75")');
    if (!name) return;
    const view = { name, stack, tags: [...tags], sortKey, sortDir, wlOnly };
    const next = [...savedViews.filter(v => v.name !== name), view];
    setSavedViews(next);
    try { localStorage.setItem('quaest-screens', JSON.stringify(next)); } catch { /* ignore */ }
    setViewMenu(false);
  };
  const recallView = (v) => {
    setStack(v.stack); setTags(new Set(v.tags)); setSortKey(v.sortKey);
    setSortDir(v.sortDir); setWlOnly(!!v.wlOnly); setViewMenu(false);
  };
  const deleteView = (name) => {
    const next = savedViews.filter(v => v.name !== name);
    setSavedViews(next);
    try { localStorage.setItem('quaest-screens', JSON.stringify(next)); } catch { /* ignore */ }
  };

  const selRow = sel ? results.find(r => r.ticker === sel) : null;
  const cols = COLUMNS.filter(c => !hiddenCols.has(c.key));
  const shownTags = moreTags ? SECTOR_TAGS : SECTOR_TAGS.slice(0, 8);

  // Score-history chart series (dedup by day).
  const chartData = useMemo(() => {
    if (!hist?.history?.length) return [];
    const byDay = new Map();
    for (const h of hist.history) {
      if (!h.timestamp) continue;
      const day = h.timestamp.split('T')[0];
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) continue;
      byDay.set(day, { date: day, lt_score: h.lt_score, opt_score: h.opt_score, price: h.price, rsi: h.rsi });
    }
    return Array.from(byDay.values()).sort((a, b) => a.date.localeCompare(b.date));
  }, [hist]);

  return (
    <div className="fade-in">
      <h1 className={styles.title}>
        {stack === 'options' ? 'Forum — tactical lens' : 'Forum — long-term value'}
      </h1>
      <div className={styles.sub}>
        {stack === 'options'
          ? 'Days-to-weeks directional setups · ranked by options opportunity'
          : 'Buy-and-hold & LEAPS candidates · ranked by conviction'} · {rows.length} names
      </div>

      {/* ── Controls ── */}
      <div className={styles.controls}>
        <SegmentedControl options={STACKS} value={stack} onChange={setStack} />

        <div className={styles.chips}>
          {shownTags.map(tag => (
            <Chip key={tag} label={tag} count={counts[tag] || 0}
              active={tags.has(tag)} onClick={() => toggleTag(tag)} />
          ))}
          <Chip label={moreTags ? '− less' : '+ more'} muted onClick={() => setMoreTags(m => !m)} />
          <Chip
            label={<span className={styles.watchChip}><Star size={11} fill={wlOnly ? 'currentColor' : 'none'} /> Watch</span>}
            active={wlOnly} onClick={() => setWlOnly(w => !w)} />
        </div>

        <div className={styles.rightControls}>
          <div className={styles.menuWrap}>
            <button className={styles.menuBtn} onClick={() => { setColMenu(c => !c); setViewMenu(false); }}>
              <ListFilter size={13} /> Columns <ChevronDown size={12} />
            </button>
            {colMenu && (
              <div className={styles.menu}>
                {COLUMNS.filter(c => c.optional).map(c => (
                  <label key={c.key} className={styles.menuItem}>
                    <input type="checkbox" checked={!hiddenCols.has(c.key)}
                      onChange={() => setHiddenCols(prev => {
                        const n = new Set(prev); n.has(c.key) ? n.delete(c.key) : n.add(c.key); return n;
                      })} />
                    {c.label}
                  </label>
                ))}
              </div>
            )}
          </div>

          <div className={styles.menuWrap}>
            <button className={styles.menuBtn} onClick={() => { setViewMenu(v => !v); setColMenu(false); }}>
              <ListFilter size={13} /> My screens <ChevronDown size={12} />
            </button>
            {viewMenu && (
              <div className={styles.menu}>
                {savedViews.length === 0 && <div className={styles.menuEmpty}>No saved screens yet</div>}
                {savedViews.map(v => (
                  <div key={v.name} className={styles.menuItem}>
                    <button className={styles.viewName} onClick={() => recallView(v)}>{v.name}</button>
                    <button className={styles.viewDel} onClick={() => deleteView(v.name)}>×</button>
                  </div>
                ))}
                <button className={styles.menuSave} onClick={saveView}>＋ Save current view</button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Layers: baseline by default; user-added layers are an experimental view ── */}
      {layersCfg && (
        <div className={styles.layersBar}>
          <button className={styles.menuBtn} onClick={() => setLayersOpen(o => !o)}>
            <Activity size={13} /> Layers {activeLayers.size > 0 ? `(${activeLayers.size} added)` : '(baseline only)'} <ChevronDown size={12} />
          </button>
          {activeLayers.size > 0 && (
            <>
              <span className={styles.expBadge}>
                EXPERIMENTAL VIEW - includes unvalidated layers; the baseline is the only scored claim
              </span>
              <button className={styles.layerReset} onClick={() => setActiveLayers(new Set())}>
                Reset to baseline
              </button>
            </>
          )}
        </div>
      )}
      {layersCfg && layersOpen && (
        <Card className={styles.layersPanel}>
          <div className={styles.baselineNote}>
            Baseline ({layersCfg.score_version}): LT = Valuation, Opt = Asymmetry - the only
            components with pre-registered out-of-sample evidence. Direction comes from the
            symmetric rule (unweighted). Layers below stay computed every scan and can be
            added to your view; promotion to the baseline follows PROMOTION_CRITERIA.md.
          </div>
          {['lt', 'opt'].map(stk => (
            <div key={stk}>
              <div className={styles.layerGroupTitle}>
                {stk === 'lt' ? 'Long-term layers' : 'Options layers'}
              </div>
              {composableLayers(layersCfg, stk).map(l => (
                <label key={l.key} className={styles.layerRow}>
                  <input
                    type="checkbox"
                    checked={activeLayers.has(l.key)}
                    onChange={() => toggleLayer(l.key)}
                  />
                  <span className={styles.layerName}>
                    {l.key.replace(/_/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase())}
                  </span>
                  <span className={styles.layerStatus}>{l.status}</span>
                  <span className={styles.layerCaption}>{l.caption}</span>
                </label>
              ))}
            </div>
          ))}
        </Card>
      )}

      {/* ── Detail panel (selected) ── */}
      {selRow && (
        <div ref={detailRef}>
          <DetailCard
            row={selRow} hist={hist} signals={signals} stack={stack}
            chartData={chartData}
            isWatched={watchlist.has(selRow.ticker)}
            onWatch={(e) => toggleWatch(selRow.ticker, e)}
            onClose={() => setSel(null)}
            onDeepDive={() => navigate(`/ticker/${selRow.ticker}`)}
          />
        </div>
      )}

      {/* ── Rankings grid ── */}
      <div className={styles.gridWrap}>
        <table className={styles.grid}>
          <thead>
            <tr>
              {cols.map(c => (
                <th key={c.key}
                  className={`${c.align === 'l' ? styles.l : ''} ${sortKey === c.key ? styles.sorted : ''}`}
                  onClick={() => onSort(c.key)}>
                  <span className={styles.thInner}>
                    {c.label}
                    {c.term && <Explain term={c.term} align={c.align === 'l' ? 'left' : 'right'} />}
                    {sortKey === c.key && (sortDir === 'desc' ? <ChevronDown size={12} /> : <ChevronUp size={12} />)}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const dir = rowDirection(r);
              const lean = leanMeta(dir);
              const conv = convictionScore(r);
              // Real recent-price path when loaded; MA-slope proxy until then.
              const real = sparks[r.ticker];
              const series = (real && real.length > 1) ? real : trendSeries(r);
              const trendColor = lean.cls === 'up' ? 'var(--gain)' : lean.cls === 'dn' ? 'var(--loss)' : 'var(--ink-mut)';
              return (
                <tr key={r.ticker} onClick={() => load(r.ticker)}
                  className={sel === r.ticker ? styles.rowSel : ''}>
                  {cols.map(c => {
                    if (c.key === 'ticker') return (
                      <td key={c.key} className={styles.l}>
                        <div className={styles.tkLine}>
                          <button className={styles.star} title="Watchlist"
                            onClick={(e) => toggleWatch(r.ticker, e)}>
                            <Star size={12} fill={watchlist.has(r.ticker) ? 'var(--gold)' : 'none'}
                              color={watchlist.has(r.ticker) ? 'var(--gold)' : 'var(--ink-dim)'} />
                          </button>
                          <span className={styles.tk}>{r.ticker}</span>
                        </div>
                        <div className={styles.secs}>
                          {tagsFor(r).slice(0, 2).map(t => <span key={t} className={styles.sec}>{t}</span>)}
                        </div>
                      </td>
                    );
                    if (c.key === 'lt') return <td key={c.key} className={`${styles.num} ${styles.strong}`}>{Math.round(r.lt_score)}</td>;
                    if (c.key === 'opt') return <td key={c.key} className={styles.num}>{Math.round(r.opt_score)}</td>;
                    if (c.key === 'reality') return <td key={c.key} className={styles.num}>{r.rc_score != null ? Math.round(r.rc_score) : '—'}</td>;
                    if (c.key === 'conviction') return <td key={c.key}><TierBadge score={conv} /></td>;
                    if (c.key === 'pe') return <td key={c.key} className={styles.num}>{r.pe_ratio ? r.pe_ratio.toFixed(0) : '—'}</td>;
                    if (c.key === 'trend') return <td key={c.key}><Sparkline points={series} color={trendColor} /></td>;
                    if (c.key === 'lean') return (
                      <td key={c.key}>
                        <span className={`${styles.dir} ${styles[lean.cls]}`}>
                          <DirLeanIcon cls={lean.cls} />{lean.label}
                        </span>
                      </td>
                    );
                    return <td key={c.key} className={styles.num}>{c.get(r) ?? '—'}</td>;
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && <div className={styles.empty}>No names match these filters.</div>}
      </div>

      <div className={styles.foot}>
        Imperial Twilight · gold hairlines as inlay · tabular figures · hover any metric to explain · zero emoji
      </div>
    </div>
  );
}

function DirLeanIcon({ cls }) {
  if (cls === 'up') return <ChevronUp size={13} strokeWidth={2.2} />;
  if (cls === 'dn') return <ChevronDown size={13} strokeWidth={2.2} />;
  return <span style={{ width: 13, textAlign: 'center' }}>–</span>;
}

const WHY = {
  tailwind: 'Supports the thesis for this name in the current view.',
  headwind: 'Weighs against the setup — factor it into sizing.',
  event: 'A dated catalyst that could move the stock near-term.',
};

function SignalRow({ sig }) {
  const Icon = sig.Icon;
  const polCls = sig.polarity === 'tailwind' ? 'polPos' : sig.polarity === 'headwind' ? 'polNeg' : '';
  return (
    <div className={styles.sig}>
      <span className={`${styles.ic} ${sig.polarity === 'headwind' ? styles.icNeg : ''}`}>
        <Icon size={15} />
      </span>
      <span className={styles.sigTxt}>{sig.text}</span>
      {sig.count > 1 && <span className={styles.sigCount}>×{sig.count}</span>}
      <span className={`${styles.meta} ${styles[polCls] || ''}`}>
        <Explain title={sig.polarity} body={WHY[sig.polarity]}>{sig.polarity}</Explain>
      </span>
    </div>
  );
}

function DetailCard({ row, hist, signals, stack, chartData, isWatched, onWatch, onClose, onDeepDive }) {
  const dir = rowDirection(row);
  const lean = leanMeta(dir);
  const grouped = useMemo(
    () => classifySignals(signals?.signals, row, stack),
    [signals, row, stack]
  );
  const smaPct = row.sma_50 && row.price ? Math.min(100, (row.price / row.sma_50) * 50) : 50;

  return (
    <Card className={styles.detail}>
      <div className={styles.row1}>
        <span className={styles.tkr}>{row.ticker}</span>
        <span className={styles.name}>{tagsFor(row).join(' · ')}</span>
        <span className={styles.price}>
          <b>${row.price?.toFixed?.(2) ?? row.price}</b>
          {row.perf_1m != null && (
            <span className={row.perf_1m >= 0 ? styles.chgUp : styles.chgDn}>
              {row.perf_1m >= 0 ? '+' : ''}{row.perf_1m.toFixed(1)}% 1m
            </span>
          )}
        </span>
        <button className={styles.detailStar} onClick={onWatch} title="Watchlist">
          <Star size={16} fill={isWatched ? 'var(--gold)' : 'none'} color={isWatched ? 'var(--gold)' : 'var(--ink-dim)'} />
        </button>
        <button className={styles.detailClose} onClick={onClose} aria-label="Close">×</button>
      </div>

      <div className={styles.tags}>
        {tagsFor(row).map(t => <span key={t} className={styles.tag}>{t}</span>)}
        <span className={`${styles.tag} ${styles[lean.cls === 'up' ? 'tagUp' : lean.cls === 'dn' ? 'tagDn' : 'tagNt']}`}>
          {lean.label}
        </span>
      </div>

      <div className={styles.scores}>
        <Stat label="LT value" term="lt_score" value={Math.round(row.lt_score)} pct={row.lt_score} />
        <Stat label="Opt score" term="opt_score" value={Math.round(row.opt_score)} pct={row.opt_score} />
        <Stat label="50-day SMA" term="sma" value={row.sma_50 ? `$${row.sma_50.toFixed(1)}` : '—'} pct={smaPct} accent="var(--gain)" />
      </div>

      {/* Score breakdowns */}
      <div className={styles.breakdownGrid}>
        <BreakdownPanel items={ltBreakdown(row)} title="LT score breakdown" accent="var(--gold)" />
        <BreakdownPanel items={optBreakdown(row)} title="Opt score breakdown" accent="var(--tyrian)" />
      </div>

      {/* ── Signals (relevance-gated) ── */}
      <div className={styles.sigH}>
        <Activity size={15} color="var(--gold)" /> Signals for this thesis
      </div>
      {!signals && <div className={styles.loading}>Loading signals…</div>}
      {signals && (
        <>
          {grouped.drivers.length > 0 && <>
            <div className={styles.grp}>Thesis drivers</div>
            {grouped.drivers.map((s, i) => <SignalRow key={`d${i}`} sig={s} />)}
          </>}
          {grouped.catalysts.length > 0 && <>
            <div className={styles.grp}>Catalysts</div>
            {grouped.catalysts.map((s, i) => <SignalRow key={`c${i}`} sig={s} />)}
          </>}
          {grouped.risks.length > 0 && <>
            <div className={styles.grp}>Risks</div>
            {grouped.risks.map((s, i) => <SignalRow key={`r${i}`} sig={s} />)}
          </>}
          {grouped.drivers.length + grouped.catalysts.length + grouped.risks.length === 0 && (
            <div className={styles.loading}>No relevant signals for this view.</div>
          )}
          {grouped.hidden > 0 && (
            <div className={styles.grp}>
              Hidden in this view{' '}
              <span className={styles.hiddenNote}>
                — {grouped.hidden} {stack === 'lt' ? 'options-only' : 'value-only'} signal{grouped.hidden > 1 ? 's' : ''} suppressed.
              </span>
            </div>
          )}
        </>
      )}

      {/* Charts */}
      {chartData.length > 1 && (
        <div className={styles.chartRow}>
          <div className={styles.chartTitle}>{row.ticker} — score history</div>
          <InteractiveScoreChart
            data={chartData}
            lines={[
              { key: 'lt_score', name: 'LT', color: 'var(--gold)' },
              { key: 'opt_score', name: 'Opt', color: 'var(--tyrian)' },
            ]}
            height={240}
          />
        </div>
      )}
      <div className={styles.chartRow}>
        <div className={styles.chartTitle}>{row.ticker} — price & signals</div>
        <InteractivePriceChart ticker={row.ticker} days={90} height={380} />
      </div>

      <button className={styles.deepDive} onClick={onDeepDive}>
        Open {row.ticker} deep dive <ChevronRight size={14} />
      </button>
    </Card>
  );
}
