"""Fester Beispiel-Inhalt für die CV-Vorschau (R8).

Die Vorschau zeigt einen vollständigen Lebenslauf-Skeleton, damit eine Vorlage
schon vor dem Ausfüllen beurteilt werden kann (R7). Leere Felder/Abschnitte
werden dafür mit diesem Inhalt gefüllt; der Export enthält ihn nie (R9).

`SAMPLE_EN` ist der einzige Beispiel-Inhalt - die App ist fest englischsprachig
(Global Language Unification, 2026-09-13). Nutzerinhalte werden dabei nie
übersetzt; das Skeleton betrifft ausschließlich die feste Dokument-Chrome und
diesen Vorschau-Platzhalterinhalt.

Die Einträge sind bereits in Render-Form (inkl. `date_range`), damit die
Templates sie ohne weitere Normalisierung wie echte Daten rendern können.
"""
from __future__ import annotations

from typing import Any

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
