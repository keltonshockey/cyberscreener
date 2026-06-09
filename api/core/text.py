"""
Text sanitizers — keep the API emoji-free at the source.

The UI mandate is "zero emoji" (UI_OVERHAUL_PLAN §1). Rather than strip emoji
client-side (the old `frontend/src/utils/text.stripEmoji` shim), we strip them
where the strings are *generated* — score reasons, signals, catalyst/direction
labels — so the API never emits a pictograph in the first place.

`strip_emoji` is also applied defensively in `db.models.save_scan` when signal
text is persisted, catching any straggler from `intel/` that bypassed the
generation-site cleanup.
"""

import re

# Pictographs, dingbats, arrows, geometric shapes, flags, variation selector,
# zero-width joiner. Mirrors the frontend EMOJI_RE so behaviour is identical on
# both sides during the migration (frontend shim becomes dead code afterwards).
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # symbols & pictographs, supplemental, extended-A
    "\U00002600-\U000027BF"   # misc symbols + dingbats
    "\U00002B00-\U00002BFF"   # misc symbols and arrows
    "\U00002190-\U000021FF"   # arrows
    "\U00002300-\U000023FF"   # technical (⚡ ⟨⟩ etc.)
    "\U000025A0-\U000025FF"   # geometric shapes
    "\U0001F1E6-\U0001F1FF"   # regional indicators (flags)
    "\U0000FE0F"              # variation selector-16
    "\U0000200D"              # zero-width joiner
    "]",
    flags=re.UNICODE,
)

_MULTISPACE_RE = re.compile(r"\s{2,}")


def strip_emoji(s):
    """Remove every emoji/pictograph from a string and collapse leftover spaces.

    Non-string input is returned unchanged so this is safe to map over mixed
    values without guarding each call site.
    """
    if not isinstance(s, str):
        return s
    return _MULTISPACE_RE.sub(" ", _EMOJI_RE.sub("", s)).strip()
