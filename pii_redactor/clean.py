"""Text hygiene applied before detection.

Word files pick up invisible junk (non-breaking spaces, zero-width characters,
soft hyphens, runs of spaces) that breaks regexes and name matching. Only
whitespace and invisible characters are touched; visible characters are kept.
"""
import re
from collections import Counter

_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))
_MULTI_SPACE = re.compile(r" {2,}")


def clean_text(text: str, stats: Counter | None = None) -> str:
    stats = stats if stats is not None else Counter()
    out = text.translate(_INVISIBLE)
    stats["invisible_chars_removed"] += len(text) - len(out)

    n_nbsp = out.count(" ") + out.count(" ")
    out = out.replace(" ", " ").replace(" ", " ")
    stats["non_breaking_spaces_fixed"] += n_nbsp

    collapsed = _MULTI_SPACE.sub(" ", out)
    stats["repeated_spaces_collapsed"] += len(_MULTI_SPACE.findall(out))
    return collapsed
