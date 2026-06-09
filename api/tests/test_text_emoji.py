"""
Emoji-at-source (UI_OVERHAUL_PLAN §1): the API must never emit a pictograph.
`core.text.strip_emoji` is the canonical sanitizer; these tests pin its behaviour
and assert the data-emitting source modules carry no emoji literals.
"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.text import strip_emoji

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U00002190-\U000021FF\U00002300-\U000023FF\U000025A0-\U000025FF"
    "\U0001F1E6-\U0001F1FF\U0000FE0F\U0000200D]"
)


def test_strips_leading_emoji_and_trims():
    assert strip_emoji("📉 Bearish") == "Bearish"
    assert strip_emoji("🎯 Earnings 7d — prime window") == "Earnings 7d — prime window"
    assert strip_emoji("🐋 3 unusual calls detected") == "3 unusual calls detected"


def test_strips_flags_and_zwj_sequences():
    assert strip_emoji("🇺🇸 US") == "US"
    assert strip_emoji("⚠️ Risk") == "Risk"


def test_passes_through_non_strings_and_plain_text():
    assert strip_emoji(None) is None
    assert strip_emoji(42) == 42
    assert strip_emoji("Rule of 40: 75 (elite)") == "Rule of 40: 75 (elite)"


def test_collapses_interior_whitespace():
    assert strip_emoji("Strong 📈 momentum") == "Strong momentum"


def test_scanner_and_market_sources_are_emoji_free():
    """The strings that scanner.py / routers/market.py generate must be clean at
    the source so the frontend stripEmoji shim becomes dead code."""
    here = os.path.dirname(__file__)
    sources = (
        "../core/scanner.py", "../routers/market.py",
        "../intel/sentiment.py", "../intel/news_intel.py", "../intel/sec_filings.py",
    )
    for rel in sources:
        text = open(os.path.join(here, rel), encoding="utf-8").read()
        found = EMOJI_RE.findall(text)
        assert not found, f"{rel} still contains emoji: {set(found)}"
