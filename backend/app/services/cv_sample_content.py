"""Fester Beispiel-Inhalt für die CV-Vorschau (R8).

Die Vorschau zeigt einen vollständigen Lebenslauf-Skeleton, damit eine Vorlage
schon vor dem Ausfüllen beurteilt werden kann (R7). Leere Felder/Abschnitte
werden dafür mit diesem Inhalt gefüllt; der Export enthält ihn nie (R9).

Es gibt je einen Beispiel-Inhalt pro Dokumentsprache (`SAMPLE_EN`,
`SAMPLE_DE`) - `render_cv_pdf` wählt anhand der gewählten Sprache, damit eine
deutsche Vorschau vollständig deutsch liest (CV-Document-Language-Plan
2026-09-13, U2). Nutzerinhalte werden dabei nie übersetzt; die Sprache gilt
ausschließlich für die feste Dokument-Chrome und dieses Skeleton.

Die Einträge sind bereits in Render-Form (inkl. `date_range`), damit die
Templates sie ohne weitere Normalisierung wie echte Daten rendern können. Die
`date_range`-Werte sind entsprechend der jeweiligen Sprache vorformatiert.
"""
from __future__ import annotations

from typing import Any

# Sprachunabhängige Beispieldaten: Skill-Namen sind Eigennamen und die
# Kompetenzgrade sind in beiden Sprachen dieselben `SkillLevel`-Enum-Werte,
# daher teilen sich `SAMPLE_EN` und `SAMPLE_DE` diese Liste.
_SAMPLE_SKILLS: list[dict[str, str]] = [
    {"name": "JavaScript", "level": "Experte"},
    {"name": "TypeScript", "level": "Sehr gut"},
    {"name": "Angular", "level": "Sehr gut"},
    {"name": "Node.js", "level": "Gut"},
    {"name": "PostgreSQL", "level": "Gut"},
    {"name": "Docker", "level": "Gut"},
    {"name": "Git", "level": "Sehr gut"},
]

SAMPLE_EN: dict[str, Any] = {
    "summary": (
        "Experienced professional focused on modern web applications and "
        "structured, maintainable solutions. Used to working independently and "
        "guiding projects from concept through delivery."
    ),
    "berufsbezeichnung": "Frontend Developer",
    # Generische Platzhalter für einzelne leere Unterfelder eines ECHTEN
    # Eintrags (KTD3) - anders als die vollständigen Beispiel-Einträge unten.
    "entry_description": "Description of the role …",
    "project_description": "Short project description …",
    "phone": "+49 170 0000000",
    "address": "1 Example Street, 12345 Example City",
    "experiences": [
        {
            "company": "Example GmbH",
            "role": "Frontend Developer",
            "date_range": "2022 – present",
            "description": "Development and maintenance of modern web applications.",
        },
        {
            "company": "Sample AG",
            "role": "Junior Developer",
            "date_range": "2020 – 2022",
            "description": "Contributed to frontend projects and quality assurance.",
        },
    ],
    "education": [
        {
            "institution": "University of Example City",
            "degree": "B.Sc. Computer Science",
            "field_of_study": "Computer Science",
            "date_range": "2017 – 2020",
        }
    ],
    "skills": _SAMPLE_SKILLS,
    "languages": [
        {"name": "German", "level": "C2"},
        {"name": "English", "level": "B2"},
    ],
    "projects": [
        {
            "title": "Portfolio Website",
            "description": "Personal portfolio site with a project overview.",
            "date_range": "2023",
            "link": "https://example.com/portfolio",
        }
    ],
}

SAMPLE_DE: dict[str, Any] = {
    "summary": (
        "Erfahrene Fachkraft mit Fokus auf moderne Webanwendungen und "
        "strukturierte, wartbare Lösungen. Selbstständiges Arbeiten und die "
        "Begleitung von Projekten von der Idee bis zur Umsetzung gewohnt."
    ),
    "berufsbezeichnung": "Frontend-Entwickler",
    "entry_description": "Beschreibung der Position …",
    "project_description": "Kurze Projektbeschreibung …",
    "phone": "+49 170 0000000",
    "address": "Beispielstraße 1, 12345 Beispielstadt",
    "experiences": [
        {
            "company": "Beispiel GmbH",
            "role": "Frontend-Entwickler",
            "date_range": "seit 2022",
            "description": "Entwicklung und Pflege moderner Webanwendungen.",
        },
        {
            "company": "Muster AG",
            "role": "Junior-Entwickler",
            "date_range": "2020 – 2022",
            "description": "Mitarbeit an Frontend-Projekten und Qualitätssicherung.",
        },
    ],
    "education": [
        {
            "institution": "Universität Beispielstadt",
            "degree": "B.Sc. Informatik",
            "field_of_study": "Informatik",
            "date_range": "2017 – 2020",
        }
    ],
    "skills": _SAMPLE_SKILLS,
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
