"""Skill dictionary + extractor shared by resume parsing and job analysis.

Using the same dictionary for resumes and job descriptions is what makes
"matched skills" and "missing skills" comparable. The extractor reuses the
keyword boundary rules, so "Java" never matches "JavaScript".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from backend.app.matching.keyword_matcher import compile_term

_DATA = Path(__file__).resolve().parents[1] / "data" / "skills.json"

# Short names that are also ordinary English words ("go to market", "the rest").
# Their canonical spelling is matched case-sensitively; aliases stay case-insensitive.
CASE_SENSITIVE = {"Go", "R", "C", "Swift", "Ruby", "Rust", "Oracle", "Scala"}


@dataclass(frozen=True)
class Skill:
    name: str
    category: str


class SkillExtractor:
    def __init__(self, catalog: dict[str, dict[str, list[str]]]):
        self._patterns: list[tuple[Skill, list[re.Pattern[str]]]] = []
        for category, skills in catalog.items():
            for name, aliases in skills.items():
                patterns = [compile_term(name, case_sensitive=name in CASE_SENSITIVE)]
                patterns += [compile_term(a) for a in aliases]
                self._patterns.append((Skill(name, category), patterns))
        self.known = {s.name for s, _ in self._patterns}
        self.category_of = {s.name: s.category for s, _ in self._patterns}

    def extract(self, text: str) -> list[Skill]:
        found: list[Skill] = []
        for skill, patterns in self._patterns:
            if any(p.search(text) for p in patterns):
                found.append(skill)
        return found


@lru_cache
def get_skill_extractor() -> SkillExtractor:
    return SkillExtractor(json.loads(_DATA.read_text(encoding="utf-8")))
