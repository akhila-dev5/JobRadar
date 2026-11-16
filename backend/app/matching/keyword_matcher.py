"""Keyword qualification (OR logic).

A job QUALIFIES when at least ONE enabled keyword (or one of its aliases) is found
in the job title or description. There is deliberately no AND mode anywhere.

This module knows nothing about AI scores, embeddings or the database, so the
qualification rule can never be influenced by similarity scoring.

How a term becomes a regex:
  * case-insensitive
  * whitespace inside a phrase matches any run of spaces/hyphens ("Full Stack"
    matches "full-stack")
  * the term must not be glued to other letters or digits:
        "Java"  does not match "JavaScript"
        "Go"    does not match "Google"
        "C"     does not match "C#" or "C++"
  * terms that start with punctuation (".NET") need no boundary on that side, so
    ".NET" matches inside "ASP.NET"
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

_ALNUM = "A-Za-z0-9_"


def compile_term(term: str, case_sensitive: bool = False) -> re.Pattern[str]:
    term = " ".join(term.split())
    if not term:
        raise ValueError("empty keyword")
    parts = [re.escape(p) for p in term.split(" ")]
    body = r"[\s\-]+".join(parts)
    prefix = f"(?<![{_ALNUM}])" if re.match(rf"[{_ALNUM}]", term[0]) else ""
    # '#' and '+' are also blocked after the term so "C" cannot match the start of "C#" / "C++"
    suffix = rf"(?![{_ALNUM}#+])" if re.match(rf"[{_ALNUM}]", term[-1]) else ""
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(prefix + body + suffix, flags)


@dataclass(frozen=True)
class KeywordRule:
    keyword: str
    aliases: tuple[str, ...] = ()

    def terms(self) -> list[str]:
        seen: dict[str, None] = {}
        for t in (self.keyword, *self.aliases):
            t = " ".join(t.split())
            if t:
                seen.setdefault(t.lower(), None)
        return [t for t in (self.keyword, *self.aliases) if " ".join(t.split()).lower() in seen]


@dataclass
class Hit:
    keyword: str  # the configured keyword (canonical name)
    matched_text: str  # what was actually found in the text
    field: str  # "title" | "description"
    start: int
    end: int


@dataclass
class MatchResult:
    qualified: bool
    matched_keywords: list[str] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)

    @property
    def title_keywords(self) -> list[str]:
        return sorted({h.keyword for h in self.hits if h.field == "title"})


class KeywordMatcher:
    """Compile once, match many jobs."""

    def __init__(self, rules: list[KeywordRule]):
        self._compiled: list[tuple[str, re.Pattern[str]]] = []
        for rule in rules:
            for term in rule.terms():
                self._compiled.append((rule.keyword, compile_term(term)))
        self.rule_count = len(rules)

    def _scan(self, text: str, field_name: str) -> list[Hit]:
        hits: list[Hit] = []
        for keyword, pattern in self._compiled:
            for m in pattern.finditer(text):
                hits.append(Hit(keyword, m.group(0), field_name, m.start(), m.end()))
        return hits

    def match(self, title: str, description: str) -> MatchResult:
        hits = self._scan(title or "", "title") + self._scan(description or "", "description")
        matched: list[str] = []
        for h in hits:
            if h.keyword not in matched:
                matched.append(h.keyword)
        # OR logic: one hit is enough. An empty rule list qualifies nothing.
        return MatchResult(qualified=len(matched) > 0, matched_keywords=matched, hits=hits)

    def highlight(self, text: str, matched_only: list[str] | None = None) -> str:
        """Return HTML-safe text with <mark> around keyword hits."""
        spans: list[tuple[int, int]] = []
        for keyword, pattern in self._compiled:
            if matched_only is not None and keyword not in matched_only:
                continue
            spans.extend((m.start(), m.end()) for m in pattern.finditer(text))
        spans.sort()
        merged: list[list[int]] = []
        for s, e in spans:
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        out, pos = [], 0
        for s, e in merged:
            out.append(html.escape(text[pos:s]))
            out.append(f"<mark>{html.escape(text[s:e])}</mark>")
            pos = e
        out.append(html.escape(text[pos:]))
        return "".join(out)
