"""Fester Beispiel-Inhalt für die CV-Vorschau (R8).

Die Vorschau zeigt einen vollständigen Lebenslauf-Skeleton, damit eine Vorlage
schon vor dem Ausfüllen beurteilt werden kann (R7). Leere Felder/Abschnitte
werden dafür mit diesem Inhalt gefüllt; der Export enthält ihn nie (R9).

Die Einträge sind bereits in Render-Form (inkl. `date_range`), damit die
Templates sie ohne weitere Normalisierung wie echte Daten rendern können.
"""
from __future__ import annotations

from typing import Any

SAMPLE: dict[str, Any] = {
    "summary": (
        "Erfahrene Fachkraft mit Fokus auf moderne Web-Anwendungen und "
        "strukturierte, wartbare Lösungen. Gewohnt, eigenverantwortlich zu "
        "arbeiten und Projekte von der Konzeption bis zur Umsetzung zu begleiten."
    ),
    "berufsbezeichnung": "Frontend Developer",
    # Generische Platzhalter für einzelne leere Unterfelder eines ECHTEN
    # Eintrags (KTD3) - anders als die vollständigen Beispiel-Einträge unten.
    "entry_description": "Beschreibung der Tätigkeit …",
    "project_description": "Kurze Projektbeschreibung …",
    "phone": "+49 170 0000000",
    "address": "Musterstraße 1, 12345 Musterstadt",
    "experiences": [
        {
            "company": "Beispiel GmbH",
            "role": "Frontend Developer",
            "date_range": "2022 – heute",
            "description": "Entwicklung und Wartung moderner Web-Anwendungen.",
        },
        {
            "company": "Muster AG",
            "role": "Junior Developer",
            "date_range": "2020 – 2022",
            "description": "Mitarbeit an Frontend-Projekten und Qualitätssicherung.",
        },
    ],
    "education": [
        {
            "institution": "Universität Musterstadt",
            "degree": "B.Sc. Informatik",
            "field_of_study": "Informatik",
            "date_range": "2017 – 2020",
        }
    ],
    "skills": [
        {"name": "JavaScript", "level": "Experte"},
        {"name": "TypeScript", "level": "Sehr gut"},
        {"name": "Angular", "level": "Sehr gut"},
    ],
    "languages": [
        {"name": "Deutsch", "level": "C2"},
        {"name": "Englisch", "level": "B2"},
    ],
    "projects": [
        {
            "title": "Portfolio-Website",
            "description": "Persönliche Portfolio-Seite mit Projektübersicht.",
            "date_range": "2023",
            "link": "https://example.com/portfolio",
        }
    ],
}
