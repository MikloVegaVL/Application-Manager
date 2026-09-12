"""Job-Quellen-Clients (LinkedIn, Xing) und geteilte Quellen-Schicht.

Bewusst getrennt von `app.services.job_search_service`, das den Orchestrator
`JobSearchService` sowie den generischen Fallback-Scraper enthält - siehe
KTD1/KTD3 im Plan
(docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md und
docs/plans/2026-09-11-001-feat-job-search-broader-source-coverage-plan.md).

Abhängigkeitsrichtung ist bewusst einseitig: Module in diesem Package
importieren NIE aus `app.services.job_search_service` (Vermeidung eines
zirkulären Imports zwischen Orchestrator und diesem Package). Was beide
Seiten brauchen (User-Agent, Playwright-Renderlogik, Karten-Extraktion,
URL-Validierung, Salary-Prosa, Redaktion, HTML-Stripping) lebt stattdessen
in `job_sources/shared.py` und wird von beiden Seiten importiert.
"""
