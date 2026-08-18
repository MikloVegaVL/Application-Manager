"""Neue Job-Quellen-Clients (LinkedIn, Xing).

Bewusst getrennt von `app.services.job_search_service`, das die bereits
bestehenden Quellen (`ArbeitsagenturJobsClient`, `GenericJobScraper`) sowie
den Orchestrator `JobSearchService` enthält - siehe KTD3 im Plan
(docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md).

Abhängigkeitsrichtung ist bewusst einseitig: Module in diesem Package
importieren NIE aus `app.services.job_search_service` (Vermeidung eines
zirkulären Imports zwischen Orchestrator und diesem Package). Was beide
Seiten brauchen (z. B. der User-Agent-String, die Playwright-Startlogik)
wird hier dupliziert statt geteilt importiert.
"""
