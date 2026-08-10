/**
 * QUAEST.TECH -- Experimental index (SESSION-V3C, D2 demotion)
 *
 * Landing page for the surfaces demoted off primary nav after the
 * pre-registered forward test FAILED its 2026-08-02 gate read. The pages
 * stay fully reachable under /experimental/... while the scoring core is
 * re-architected; this page lists them under the shared gate-verdict banner.
 */
import { Link } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { ExperimentalBanner } from '../components/ExperimentalBanner';
import { Scroll, Zap, Library, ChevronRight } from '../components/ui/icons';

const SURFACES = [
  {
    to: '/experimental/conviction',
    label: 'Forum',
    sub: 'long-term value',
    Icon: Scroll,
    desc: 'Long-term conviction rankings with score breakdowns, intel layers and sector views.',
  },
  {
    to: '/experimental/pactum',
    label: 'Pactum',
    sub: 'tactical options',
    Icon: Zap,
    desc: 'Options play generation with Reality Check scoring and play history.',
  },
  {
    to: '/experimental/archive',
    label: 'Archive',
    sub: 'backtest',
    Icon: Library,
    desc: 'Backtesting engine, quintile analysis, calibration and weight history.',
  },
];

export function ExperimentalIndexPage() {
  return (
    <div className="fade-in" style={{ maxWidth: 860, margin: '0 auto' }}>
      <h1 style={{ fontSize: 22, fontWeight: 800, marginBottom: 6 }}>Experimental</h1>
      <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 16 }}>
        Surfaces demoted from primary navigation while the scoring core is re-architected.
        Everything here still runs and accrues telemetry; nothing here is a recommendation.
      </div>

      <ExperimentalBanner style={{ marginBottom: 20 }} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {SURFACES.map(({ to, label, sub, Icon, desc }) => (
          <Link key={to} to={to} style={{ textDecoration: 'none', color: 'inherit' }}>
            <Card style={{ padding: 18, display: 'flex', alignItems: 'center', gap: 14, cursor: 'pointer' }}>
              <Icon size={18} style={{ color: 'var(--gold)', flexShrink: 0 }} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 700 }}>
                  {label}
                  <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-text-tertiary)', marginLeft: 8 }}>{sub}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 3 }}>{desc}</div>
              </div>
              <ChevronRight size={16} style={{ color: 'var(--color-text-tertiary)', flexShrink: 0 }} />
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
