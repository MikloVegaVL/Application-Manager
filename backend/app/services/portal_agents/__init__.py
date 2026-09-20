"""Portal-Auto-Fill-Agent: füllt und (nach expliziter Nutzerbestätigung)
sendet Bewerbungsdaten in externe Karriereportal-Formulare (Personio für v1)
über einen headed Playwright-Browser ab.

Siehe docs/plans/2026-09-19-002-feat-portal-application-auto-fill-agent-plan.md.
`session.py` (U2) besitzt ausschließlich den Browser-Lebenszyklus
(Start/Pause/Resume/Abbruch); das eigentliche Feld-Mapping folgt in U3/U4.
"""
