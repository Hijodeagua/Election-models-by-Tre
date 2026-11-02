"""Candidate-name matching that survives the ways sources differ.

"John Sununu" / "John E. Sununu", "Ben Ray Lujan" / "Ben Ray Luján",
"James Byrd" / "James W. Byrd", "Darline Graham" / "Darline Graham Nordone"
are the same people. Compare on accent-stripped, lower-cased tokens with
middle initials dropped, and accept a match when first and last tokens agree
or when one name's tokens are a contiguous subsequence of the other's.
"""

from __future__ import annotations

import re
import unicodedata

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def normalize_name(name: str | None) -> list[str]:
    """Lower-case ASCII tokens, no punctuation, no initials, no suffixes."""
    if not name:
        return []
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\([^)]*\)", " ", s)  # "(D)", "(R)", "(Nordone)"
    s = re.sub(r"['’.,\-]", " ", s.lower())
    toks = [t for t in s.split() if t and t not in _SUFFIXES]
    # Drop one-letter tokens (middle initials) unless that is all we have.
    full = [t for t in toks if len(t) > 1]
    return full or toks


def names_match(a: str | None, b: str | None) -> bool:
    ta, tb = normalize_name(a), normalize_name(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    if ta[0] == tb[0] and ta[-1] == tb[-1]:
        return True
    # One is contained in the other ("darline graham" in "darline graham nordone",
    # "sununu" in "john sununu").
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    n = len(short)
    return any(long_[i : i + n] == short for i in range(len(long_) - n + 1))


_POLLSTER_STOP = {
    "the", "poll", "polls", "polling", "college", "university", "u", "inc",
    "llc", "group", "co", "partners", "and", "of", "for",
}
_POLLSTER_ALIASES = {
    "new york times": "nyt",
    "ny times": "nyt",
    "nytimes": "nyt",
    "insider advantage": "insideradvantage",
    "public policy polling": "ppp",
    "east carolina university": "east carolina",
    "east carolina u": "east carolina",
}


def pollster_key(name: str | None) -> str:
    """Spelling-tolerant pollster identity: 'NY Times/Siena', 'Siena/NYT' and
    'Siena College/The New York Times' all map to 'nyt siena'. Partisan
    suffixes like '(D)' and sponsors after a slash are kept as tokens only
    when they are not generic words, so 'Emerson' matches 'Emerson College'."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"\((d|r|i)[^)]*\)", " ", s)  # partisan tags
    for k, v in _POLLSTER_ALIASES.items():
        s = s.replace(k, v)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = sorted({t for t in s.split() if t not in _POLLSTER_STOP})
    return " ".join(toks)


def pollsters_match(a: str | None, b: str | None) -> bool:
    """Same pollster if the keys are equal or one key's tokens are a subset of
    the other's: 'Emerson College' ~ 'Emerson College/WPRI-TV',
    'Chism Strategies' ~ 'Chism Strategies / Blueprint Polling',
    'Hart Research' ~ 'Hart Research Associates'."""
    ka, kb = set(pollster_key(a).split()), set(pollster_key(b).split())
    if not ka or not kb:
        return False
    return ka <= kb or kb <= ka
