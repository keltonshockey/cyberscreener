"""
Slim scanning universe loader (SESSION-SLIM-SCOPE).

The scanner's active ticker list comes from core/universe_slim.json (~100
liquid names selected by documented, reproducible criteria — see
scripts/build_universe.py) instead of the full ~480-name registry.

Guarantees:
- Journal continuity is DYNAMIC: every ticker with an OPEN journal play is
  unioned into the scan list until its plays close, whether or not it made
  the slim list. Dropped tickers therefore exit the scan only after their
  forward-test obligations are settled.
- `always_include` in the config is a manual pin list (e.g. a thesis name
  whose cap dipped under the floor).
- CYBERSCREENER_FULL_UNIVERSE=1 reverts to the full universe (one env flip,
  no code change). A missing or disabled config also falls back to full.
- Historical data for dropped tickers is untouched (retention is PR #11's
  prune policy, not this module).
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "universe_slim.json"

_config_cache = None
_config_loaded = False


def load_slim_config(force=False):
    """The slim-universe config dict, or None when absent/unreadable."""
    global _config_cache, _config_loaded
    if not _config_loaded or force:
        try:
            _config_cache = json.loads(CONFIG_PATH.read_text())
        except Exception as e:
            if CONFIG_PATH.exists():
                logger.warning(f"universe_slim.json unreadable ({e}) - full universe")
            _config_cache = None
        _config_loaded = True
    return _config_cache


def slim_enabled():
    if os.environ.get("CYBERSCREENER_FULL_UNIVERSE", "0") == "1":
        return False
    cfg = load_slim_config()
    return bool(cfg and cfg.get("enabled"))


def open_play_tickers():
    """Tickers with open forward-test journal plays (scan-time union for
    journal continuity). Fail-safe: any DB problem returns an empty set
    rather than blocking the scan."""
    try:
        from db.models import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM options_plays WHERE status = 'open'"
        ).fetchall()
        conn.close()
        return {r[0] for r in rows if r[0]}
    except Exception as e:
        logger.warning(f"open-play ticker lookup failed (scanning slim list only): {e}")
        return set()


def get_active_tickers(full_universe):
    """The list run_scan should iterate: slim list + manual pins + open-play
    union when slim mode is on; otherwise the full universe unchanged."""
    if not slim_enabled():
        return list(full_universe)
    cfg = load_slim_config()
    active = set(cfg.get("tickers", {}).keys())
    active |= set(cfg.get("always_include", []))
    continuity = open_play_tickers() - active
    if continuity:
        logger.info(
            f"slim universe: +{len(continuity)} journal-continuity tickers "
            f"({', '.join(sorted(continuity)[:10])}{'...' if len(continuity) > 10 else ''})")
        active |= continuity
    logger.info(f"slim universe active: {len(active)} tickers "
                f"(config {len(cfg.get('tickers', {}))}, built from scan "
                f"#{cfg.get('built_from_scan')})")
    return sorted(active)
