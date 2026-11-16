# 08 - Keyword Matching Logic (OR)

Code: `backend/app/matching/keyword_matcher.py`. Tests: `tests/unit/test_keyword_matcher.py`.

## The rule

> A job **qualifies** if **at least one** enabled keyword (or one of its aliases) appears
> in the job title or description.

```python
matched = [kw for kw in enabled_keywords if found_in(title, description)]
qualified = len(matched) > 0        # OR, never "all of them"
```

| Keywords | Job text | Result |
|---|---|---|
| Python, .NET, React, Microservices | "Python developer" | qualifies |
| same | "React engineer" | qualifies |
| same | "Python + Microservices" | qualifies |
| same | "Java and Go" | does not qualify |

There is no AND mode anywhere in the code. With zero enabled keywords nothing qualifies,
and the search reports an error asking you to add one.

## Why this is separate from AI scoring

`KeywordMatcher` imports no database, no model and no scoring code. The search pipeline
runs it first; only qualified jobs are stored and scored. Consequences:

- A qualified job with an AI score of 12% is still stored and findable.
- The AI threshold (default 40%) only filters the default job list and email alerts.
- You can change scoring weights without ever changing which jobs qualify.

## How a keyword becomes a regular expression

`compile_term()` builds one pattern per keyword or alias:

1. **Case-insensitive**: "python" matches "Python".
2. **Phrases**: spaces become `[\s\-]+`, so "Full Stack" matches "full-stack".
3. **No partial words**: the term must not touch letters or digits:
   - `Java` does not match `JavaScript`
   - `Go` does not match `Google`
   - `C` does not match `C#` or `C++` (the end check also rejects `#` and `+`)
4. **Punctuation-led terms**: `.NET` has no left boundary, so it matches inside `ASP.NET`.
5. **Escaping**: `re.escape` makes `C++`, `C#`, `CI/CD` literal text, not regex syntax.

Lookarounds (`(?<![A-Za-z0-9_])` and `(?![A-Za-z0-9_#+])`) are used instead of `\b` because
`\b` breaks on terms that start or end with symbols (`\bC#\b` fails).

## Aliases

A keyword has a canonical name and optional aliases: `PostgreSQL` with alias `postgres`.
A hit on any alias counts as a hit on the keyword, and the keyword's canonical name is what
you see in results.

## Highlighting

`highlight()` merges overlapping hit ranges, HTML-escapes everything, and wraps hits in
`<mark>`. Escaping first matters: job descriptions come from the internet and must never be
rendered as raw HTML.

## Try it

Settings > Keywords > **Test match** lets you paste a title and description and see which
keywords fire and the highlighted text, without running a search.

## Common errors

| Symptom | Cause |
|---|---|
| Expected job missing | keyword disabled, or text uses a form not in the aliases ("k8s" vs "kubernetes") |
| Too many results for a short keyword | very short words ("R", "C") are noisy; keep them specific or rely on titles |
| `.NET` matches "network"? | it does not: the literal dot must be present |

## Interview questions

- Difference between `\b` and lookarounds? When does `\b` fail?
- Why compile a regex once and reuse it?
- Why keep a business rule (OR qualification) in a pure function with no I/O?
- What is regex injection and how does `re.escape` prevent it?
