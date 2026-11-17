"""Company-name normalisation shared by board discovery and duplicate detection.

"Stripe", "stripe" and "Stripe, Inc." all reduce to the same key, so adding the same company
twice under slightly different spellings is caught.
"""

from __future__ import annotations

import re
import unicodedata

LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
    "plc", "gmbh", "pvt", "private", "llp", "sa", "ag", "bv", "pte", "lp",
}  # fmt: skip
GENERIC_WORDS = {
    "technologies", "technology", "tech", "systems", "software", "labs", "group", "holdings",
    "solutions", "global", "international", "the",
}  # fmt: skip


def _words(name: str) -> list[str]:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", ascii_name.lower().replace("&", " and "))


def _core_words(name: str) -> tuple[list[str], list[str]]:
    words = _words(name)
    core = [w for w in words if w not in LEGAL_SUFFIXES] or words
    core2 = [w for w in core if w not in GENERIC_WORDS] or core
    return core, core2


def name_key(name: str) -> str:
    """Comparable form of a company name: 'Stripe, Inc.' and 'stripe' share one key."""
    return "".join(_core_words(name)[1])


def same_company(a: str, b: str) -> bool:
    ka, kb = name_key(a), name_key(b)
    return bool(ka) and ka == kb
