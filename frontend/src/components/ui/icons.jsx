/**
 * QUAEST.TECH — Iconography (Imperial Twilight)
 * ONE icon family: Lucide (thin-line). Never mix sets, never an emoji.
 * Import semantic icons from here so usage stays consistent everywhere.
 */
import {
  TrendingUp, TrendingDown, Minus,
  LineChart, Zap, Info, HelpCircle, Activity, DollarSign,
  FileText, AlertTriangle, Star, Search, ListFilter,
  ChevronDown, ChevronUp, ChevronRight,
  Landmark, Scroll, Library, Map as MapIcon, Globe,
  Sun, Moon, MessageCircle, Waves, Play, RefreshCw, Target,
  AlertCircle, ShieldAlert, Flame, Scale, Bookmark, X, Plus,
  Gauge, Percent, Ruler, Calendar, Award,
  Mail, Crosshair, Sprout, Shield, Settings, Brain, Clock, Layers,
  BarChart3, Coins, Compass, Hourglass, KeyRound, MessageSquare,
} from 'lucide-react';

export {
  TrendingUp, TrendingDown, Minus,
  LineChart, Zap, Info, HelpCircle, Activity, DollarSign,
  FileText, AlertTriangle, Star, Search, ListFilter,
  ChevronDown, ChevronUp, ChevronRight,
  Landmark, Scroll, Library, MapIcon, Globe,
  Sun, Moon, MessageCircle, Waves, Play, RefreshCw, Target,
  AlertCircle, ShieldAlert, Flame, Scale, Bookmark, X, Plus,
  Gauge, Percent, Ruler, Calendar, Award,
  Mail, Crosshair, Sprout, Shield, Settings, Brain, Clock, Layers,
  BarChart3, Coins, Compass, Hourglass, KeyRound, MessageSquare,
};

/** Directional lean glyph — bullish / bearish / neutral. */
export function DirectionIcon({ dir, size = 13, ...rest }) {
  const d = (dir || '').toLowerCase();
  if (d.startsWith('bull')) return <TrendingUp size={size} {...rest} />;
  if (d.startsWith('bear')) return <TrendingDown size={size} {...rest} />;
  return <Minus size={size} {...rest} />;
}

/** Conviction-tier seal mark (3-step laurel feel via Award). */
export function TierSeal({ size = 12, ...rest }) {
  return <Award size={size} {...rest} />;
}

/**
 * Map a server-side reason/signal string to a semantic icon. The backend now
 * emits emoji-free text (core/text.strip_emoji), so we pick an icon purely from
 * the text's meaning — no client-side stripping needed.
 */
export function signalIcon(text = '', impact = '') {
  const t = text.toLowerCase();
  if (/rule of 40|growth|uptrend|trend|momentum/.test(t)) return TrendingUp;
  if (/fcf|cash|margin|value|valuation|p\/e|ev\/rev/.test(t)) return DollarSign;
  if (/threat|breach|demand|landscape|squeeze/.test(t)) return ShieldAlert;
  if (/8-k|filing|analyst|target|insider|sec/.test(t)) return FileText;
  if (/earnings|catalyst|expiry|dte/.test(t)) return Calendar;
  if (/iv|volatility|premium|rank/.test(t)) return Activity;
  if (/whale|flow|institutional|unusual/.test(t)) return Waves;
  if (/rsi|oversold|overbought|technical|sma|moving average/.test(t)) return Gauge;
  if (impact === 'negative' || /risk|headwind|cooling|expensive|burn|weak/.test(t)) return AlertTriangle;
  return Info;
}
