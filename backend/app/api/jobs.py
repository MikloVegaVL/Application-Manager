"""API-Router für die Jobsuche und das Speichern von Stellenangeboten."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.application import Application
from app.models.job_offer import JobOffer
from app.schemas.job_offer import JobOfferCreate, JobOfferRead, JobSearchResponse
from app.services.job_search_service import JobSearchService, get_job_search_service

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/search", response_model=JobSearchResponse)
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
) -> JobSearchResponse:
    """Sucht Stellenangebote gleichzeitig über Arbeitsagentur, LinkedIn und
    Xing (und bei Bedarf über den generischen Fallback-Scraper). Liefert
    die zusammengeführten Ergebnisse plus einen Status pro Quelle, ohne sie
    zu speichern (KTD2)."""
    return service.search(keywords=keywords, location=location, fallback_url=fallback_url)


@router.post("/save", response_model=JobOfferRead, status_code=status.HTTP_201_CREATED)
def save_job(payload: JobOfferCreate, db: Session = Depends(get_db)) -> JobOffer:
    """Speichert ein ausgewähltes Suchergebnis dauerhaft als `JobOffer`."""
    existing = db.query(JobOffer).filter(JobOffer.source_url == payload.source_url).first()
    if existing is not None:
        # Backfill: JobOffers gespeichert vor dem Atomic-Insert-Fix (98d31c0,
        # 2026-08-20) haben keine zugehörige Application - ohne dies bliebe
        # so ein Job dauerhaft mit 409 stecken (ce-debug-Untersuchung,
        # 2026-08-24: erneutes "Bewerbung generieren" scheiterte an genau
        # dieser Lücke, während `GET /applications` den Job nie zeigte). Der
        # `job_offer_id` im Detail lässt das Frontend trotz 409 direkt zum
        # Editor navigieren, statt in einer Sackgasse zu enden.
        application = db.query(Application).filter(Application.job_offer_id == existing.id).first()
        if application is None:
            db.add(Application(job_offer_id=existing.id))
            db.commit()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Dieses Stellenangebot wurde bereits gespeichert.",
                "job_offer_id": existing.id,
            },
        )

    job_offer = JobOffer(**payload.model_dump())
    db.add(job_offer)
    db.flush()  # weist job_offer.id zu, ohne die Transaktion schon zu committen

    # Legt sofort eine Bewerbung im Status "draft" ohne Anschreiben an, damit
    # das Stellenangebot auf der Bewerbungsübersicht (`GET /applications`)
    # erscheint, auch bevor das Anschreiben generiert wurde (ce-debug-
    # Untersuchung, 2026-08-20: gespeicherte Jobs waren dort zuvor gar nicht
    # sichtbar). `ApplicationEditorComponent.loadOrGenerateApplication` holt
    # die KI-Generierung nach, sobald `cover_letter_text` noch leer ist. Ein
    # gemeinsamer Commit hält beide Inserts atomar - schlägt er fehl, bleibt
    # kein JobOffer ohne zugehörige Application zurück.
    db.add(Application(job_offer_id=job_offer.id))
    db.commit()
    db.refresh(job_offer)

    return job_offer


@router.get("/{job_offer_id}", response_model=JobOfferRead)
def get_job(
    job_offer_id: int,
    db: Session = Depends(get_db),
    service: JobSearchService = Depends(get_job_search_service),
) -> JobOffer:
    """Liefert ein einzelnes gespeichertes Stellenangebot (z. B. für die
    Kopfzeile des Bewerbungs-Editors).

    Fehlt `description_text` noch (z. B. weil die Suche, aus der die Stelle
    stammt, nur die Trefferliste kannte, siehe KTD2/`ArbeitsagenturJobsClient
    .fetch_description`), wird es hier einmalig nachgeladen und persistiert -
    ab dem zweiten Aufruf entfällt der externe Call. Schlägt das Nachladen
    fehl oder liefert die Quelle keinen Text, bleibt `description_text` leer
    und die Anfrage liefert trotzdem normal die gespeicherten Felder zurück.
    """
    job_offer = db.get(JobOffer, job_offer_id)
    if job_offer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stellenangebot wurde nicht gefunden.")

    if not job_offer.description_text:
        description = service.enrich_description(job_offer.source_platform, job_offer.source_url)
        if description:
            job_offer.description_text = description
            db.commit()
            db.refresh(job_offer)

    return job_offer
