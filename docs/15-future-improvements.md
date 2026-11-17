# 15 - Future Improvements

Ordered roughly by value for a job seeker. None are needed for the current acceptance criteria.

## Sources

1. **More public ATS platforms** as new collectors: Workable, SmartRecruiters, Recruitee,
   Teamtailor, BambooHR. Each is one class plus a registry entry (doc 06).
2. **Official feeds or partner APIs** for large job portals, if an official programme exists
   for your use. Scraping LinkedIn, Naukri, Foundit or Indeed is intentionally excluded.
3. **Cross-platform duplicate merging** (same company + title + location posted twice).
4. ~~Auto-detect the platform~~ Done: add by name (board discovery) or paste a careers link.
   Next step: detect more boards for names that currently end as "no public job board found" (for example from a
   company website's own careers link, using an official or permitted data source rather than scraping search engines).

## Matching quality

5. **Evaluate the scorer**: label 50 jobs yourself (good / bad), compare with the scores, tune
   weights and `calibration` ranges. Currently they are sensible defaults, not measured values.
6. Section-aware job parsing (requirements vs benefits) so "nice to have" skills count less.
7. Better experience parsing ("5-8 years", "a decade", seniority words).
8. **Optional Ollama** explanations: a local LLM that writes a short "why this fits" paragraph.
   Must stay optional (the app works without an LLM). Suggested seam: a function that takes
   `ScoreResult` and returns text, called from `matching_service`.
9. Skill dictionary maintenance UI (add skills and aliases without editing JSON).

## Product

10. Location and work-mode filtering driven by preferences (they are stored, but only preferred titles
    feed the score today).
11. Salary extraction where boards provide it (Ashby `includeCompensation`).
12. Email on a schedule with a daily digest; Slack/Telegram notifications.
13. OAuth-based email sending (Gmail API) as an alternative to SMTP app passwords.
14. Export tracker to CSV; calendar reminders for follow-ups.

## Engineering

15. Run the test suite against a real PostgreSQL (CI service container) in addition to SQLite.
16. GitHub Actions: `ruff` + `pytest` on every push.
17. Docker Compose for one-command start (not required initially, per project constraints).
18. A proper job queue (RQ/Celery) if searches ever need to survive restarts or run in parallel.
19. Authentication and per-user rows (add `user_id`, turn on real RLS policies) if the app is
    ever shared.
20. Move JSON list filters (matched keywords) to PostgreSQL JSONB queries or a join table
    when the job table grows large.
21. Add pagination at the SQL level (currently filtering by keyword happens in Python after the query).

## Interview angle

For each item, be ready to explain the trade-off: what you would build, what it costs, and
how you would test it.
