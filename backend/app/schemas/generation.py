"""Pydantic-Schemas für die KI-gestützte Bewerbungsgenerierung
(siehe `app.services.ai_generator`).

Die KI generiert ausschließlich das Anschreiben - der Lebenslauf wird nicht
mehr KI-generiert/gerendert, sondern vom Nutzer als eigene Datei im Profil
hochgeladen und beim Versand als Anhang verwendet (siehe `app.api.profile`,
`app.api.applications.send_application`).
"""
from pydantic import BaseModel, model_validator


class AiGenerationResult(BaseModel):
    """Rohes Ergebnis des LLM-Aufrufs (siehe `_SYSTEM_PROMPT` in `ai_generator.py`)."""

    cover_letter_text: str


class RequirementAssessment(BaseModel):
    """Einschätzung einer einzelnen Stellenanforderung gegen das tatsächliche
    Bewerberprofil (siehe `_MATCH_ANALYSIS_SYSTEM_PROMPT` in `ai_generator.py`,
    R1/R2/KTD9).

    `is_core` unterscheidet eine Muss-Anforderung von einer, die die
    Stellenanzeige selbst als optional/Nice-to-have framt (R2/KTD4). `matched`
    hält fest, ob das Profil dafür eine tatsächliche Grundlage bietet;
    `evidence` nennt in diesem Fall das konkrete Profil-Fakt, das das belegt.
    """

    requirement: str
    is_core: bool
    matched: bool
    evidence: str | None = None

    @model_validator(mode="after")
    def _evidence_required_when_matched(self) -> "RequirementAssessment":
        # KTD9: ein "matched"-Urteil ohne belegendes Profil-Fakt ist keine
        # Einschätzung, sondern eine unbelegte Behauptung - genau das soll
        # dieses Schema verhindern.
        if self.matched and not (self.evidence and self.evidence.strip()):
            raise ValueError(
                "evidence darf nicht leer sein, wenn matched=True ist."
            )
        return self


class CoverLetterFitAssessment(BaseModel):
    """Ergebnis des Match-Analyse-Aufrufs: pro Stellenanforderung ein
    `RequirementAssessment` (R1)."""

    requirements: list[RequirementAssessment]
