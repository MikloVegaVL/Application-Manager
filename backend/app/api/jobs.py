"""API-Router für die Jobsuche und das Speichern von Stellenangeboten."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.job_offer import JobOffer
from app.schemas.job_offer import JobOfferCreate, JobOfferRead
from app.services.job_search_service import JobSearchService, get_job_search_service

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/search", response_model=list[JobOfferCreate])
def search_jobs(
    keywords: str = Query(..., min_length=2, description="Jobtitel / Suchbegriff"),
    location: str | None = Query(default=None, description="Ort oder PLZ"),
    fallback_url: str | None = Query(
        default=None,
        description=(
            "URL einer Jobbörsen-Ergebnisseite, die der generische "
            "Fallback-Scraper auswertet, falls die Arbeitsagentur-API "
            "keine Treffer liefert."
        ),
    ),
    service: JobSearchService = Depends(get_job_search_service),
) -> list[JobOfferCreate]:
    """Sucht Stellenangebote über die Arbeitsagentur-API und - bei Bedarf -
    über einen generischen Fallback-Scraper. Liefert die Ergebnisse
    harmonisiert im `JobOfferCreate`-Format, ohne sie zu speichern."""
    return service.search(keywords=keywords, location=location, fallback_url=fallback_url)


@router.post("/save", response_model=JobOfferRead, status_code=status.HTTP_201_CREATED)
def save_job(payload: JobOfferCreate, db: Session = Depends(get_db)) -> JobOffer:
    """Speichert ein ausgewähltes Suchergebnis dauerhaft als `JobOffer`."""
    existing = db.query(JobOffer).filter(JobOffer.source_url == payload.source_url).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Dieses Stellenangebot wurde bereits gespeichert.",
        )

    job_offer = JobOffer(**payload.model_dump())
    db.add(job_offer)
    db.commit()
    db.refresh(job_offer)
    return job_offer
