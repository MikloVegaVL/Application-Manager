"""Geteilte Quellen-Schicht für alle Job-Quellen.

Dieses Modul bündelt die quellenübergreifende Maschinerie, die zuvor pro
Client dupliziert war (KTD1/KTD2/KTD5/KTD10 im Plan
docs/plans/2026-09-11-001-feat-job-search-broader-source-coverage-plan.md):

- den Browser-artigen User-Agent,
- die Playwright-Renderlogik samt begrenztem Start-Semaphore,
- die CSS-Klassen-Muster und das "Überschrift vor Anker"-Karten-Mapping,
- die generische zweistufige Extraktion (JSON-LD, dann Heuristik),
- Board-Deskriptoren samt Adapter mit `search(keywords, location)`,
- den Salary/Homeoffice-Prosa-Helfer, URL-Validierung,
  Credential-Redaktion und BeautifulSoup-basiertes HTML-Stripping.

Abhängigkeitsrichtung bleibt einseitig (KTD1): `job_sources/` importiert
NIE aus `app.services.job_search_service`. `job_search_service.py` und alle
Quellen-Clients importieren stattdessen aus diesem Modul.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from app.schemas.job_offer import JobOfferCreate

logger = logging.getLogger(__name__)


class SourceNotConfiguredError(Exception):
    """Eine Quelle hat keine gültigen Zugangsdaten (KTD9).

    API-Clients werfen diese Exception, wenn eine Zugangsberechtigung
    serverseitig abgelehnt wird (z. B. HTTP 401/403/410). Der Orchestrator
    mappt sie auf `status="unavailable", reason="not-configured"` - dieselbe
    Kennzeichnung wie für Quellen, deren `is_configured()` vorab `False`
    meldet.
    """


class CooldownMixin:
    """Geteilte Rate-Limit-Cooldown-Mechanik für die API-Clients (KTD5).

    Der Cooldown ist bewusst Klassen-Level-State, nicht Instanzattribut: die
    Clients werden pro Request neu instanziiert (siehe
    `get_job_search_service()`), ein Instanzattribut würde den Cooldown also
    nie tatsächlich greifen lassen. Jede konkrete Client-Klasse bekommt beim
    ersten `_set_cooldown()` ihr eigenes `_cooldown_until` - der Cooldown
    bleibt damit pro Client unabhängig. Voraussetzung ist, dass die
    verwendende Klasse `self._cooldown_seconds` setzt.
    """

    _cooldown_until: float = 0.0

    @classmethod
    def is_cooldown_active(cls) -> bool:
        """Öffentliche Abfrage, ob der Client sich aktuell im Rate-Limit-
        Cooldown befindet - genutzt vom Orchestrator (`JobSearchService`),
        um eine leere Ergebnisliste als "rate-limited" statt generisch
        "empty" zu kennzeichnen (KTD5)."""
        return cls._in_cooldown()

    @classmethod
    def _in_cooldown(cls) -> bool:
        return time.monotonic() < cls._cooldown_until

    def _set_cooldown(self) -> None:
        # Bewusst auf der konkreten Klasse geschrieben (nicht `self` und nicht
        # dem Mixin), damit jeder Client seinen eigenen Cooldown-State hält.
        type(self)._cooldown_until = time.monotonic() + self._cooldown_seconds


# Browser-artiger User-Agent, um von Zielseiten nicht pauschal als Bot
# geblockt zu werden. Für produktive Nutzung sollte jede Quelle einzeln auf
# robots.txt / Nutzungsbedingungen geprüft werden.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ApplicationManagerBot/1.0; "
    "+https://github.com/application-manager)"
)

# Heuristische CSS-Klassen-Muster, die auf Job-Karten hindeuten. Xings genaue
# CSS-Klassen sind unbestätigt/undokumentiert, daher derselbe tolerante Ansatz
# für alle HTML-Quellen.
JOB_CLASS_PATTERN = re.compile(r"job|stelle|vacan", re.IGNORECASE)
COMPANY_CLASS_PATTERN = re.compile(r"company|arbeitgeber|employer|firma", re.IGNORECASE)
LOCATION_CLASS_PATTERN = re.compile(r"location|ort|city|standort", re.IGNORECASE)

MAX_HEURISTIC_RESULTS = 25


def inner_timeout_for(deadline_seconds: float) -> float:
    """Leitet den inneren Per-Quelle-Timeout aus der äußeren Such-Deadline ab.

    KTD8: der innere Timeout muss strikt unter der äußeren Deadline liegen -
    auch bei einer sehr kleinen Deadline (`deadline_seconds <= 1.0`), wo die
    frühere `max(1.0, deadline - 1.0)`-Formel die Deadline erreichen oder
    überschreiten konnte. Der Untergrenze 0.1s bleibt bestehen, damit ein
    Timeout überhaupt greifen kann.
    """
    return max(0.1, deadline_seconds * 0.8)

# Modul-Level-Import statt Import innerhalb der Methode: dadurch lässt sich
# `sync_playwright` in Tests einfach patchen (siehe test_shared.py/test_xing.py).
# Playwright ist eine harte Dependency (requirements.txt); der Fallback greift
# nur, falls die Installation dennoch unvollständig ist.
try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - playwright ist in requirements.txt gelistet
    sync_playwright = None  # type: ignore[assignment]

# Prozessweites Semaphore - begrenzt gleichzeitige Playwright/Chromium-Starts
# unabhängig von der Anzahl gleichzeitig laufender Suchen (KTD5/KTD6). Gilt für
# Xing UND den generischen Render-Pfad.
PLAYWRIGHT_LAUNCH_LIMIT = 2
playwright_launch_semaphore = threading.Semaphore(PLAYWRIGHT_LAUNCH_LIMIT)


# --- Playwright / HTTP-Beschaffung -----------------------------------------


def playwright_available() -> bool:
    """Ob die Playwright-Bindung importierbar ist."""
    return sync_playwright is not None


def render_html(url: str, timeout: float) -> str | None:
    """Rendert `url` mit Playwright und liefert den fertigen Seiteninhalt.

    Der Browser-Start läuft durch das geteilte Semaphore, damit ein
    Doppel-Tab/Doppel-Klick-Burst nicht beliebig viele Chromium-Instanzen
    gleichzeitig startet. Liefert bei jedem Fehler (fehlende Binaries,
    Timeout, Geoblock) `None` statt einer Exception - der Aufrufer entscheidet
    über den Status. Der Browser wird auch im Fehlerfall geschlossen.
    """
    if sync_playwright is None:
        logger.warning("Playwright ist nicht installiert - Rendering nicht möglich.")
        return None

    with playwright_launch_semaphore:
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(user_agent=DEFAULT_USER_AGENT)
                    page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
                    return page.content()
                finally:
                    browser.close()
        except Exception as exc:  # noqa: BLE001 - z. B. Timeout, Geoblock, fehlende Browser-Binaries
            logger.warning(
                "Playwright-Rendering von %s fehlgeschlagen: %s",
                sanitize_url_for_log(url),
                _safe_error_text(exc, url),
            )
            return None


def fetch_with_requests(url: str, timeout: float = 15.0) -> str | None:
    """Lädt `url` per HTTP GET und liefert den HTML-Text (oder `None`)."""
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": DEFAULT_USER_AGENT},
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        logger.warning(
            "Abruf von %s fehlgeschlagen: %s",
            sanitize_url_for_log(url),
            _safe_error_text(exc, url),
        )
        return None


def fetch_html(url: str, *, use_playwright: bool = False, timeout: float = 15.0) -> str | None:
    """Beschafft den HTML-Inhalt einer Seite - optional per Playwright.

    Ist Playwright angefordert, aber nicht installiert, wird auf einen
    einfachen HTTP-Abruf zurückgefallen (wie bisher im generischen Scraper).
    Schlägt das Rendering dagegen fehl, wird `None` geliefert.
    """
    if use_playwright:
        if not playwright_available():
            logger.warning("Playwright ist nicht installiert - Fallback auf requests.")
            return fetch_with_requests(url, timeout=timeout)
        return render_html(url, timeout=timeout)
    return fetch_with_requests(url, timeout=timeout)


# --- HTML-Stripping / Credential-Redaktion ---------------------------------


def strip_html(raw: str | None) -> str | None:
    """Entfernt HTML-Markup aus `raw` über BeautifulSoup (nie per Regex)."""
    if not raw:
        return None
    return BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True) or None


_SECRET_QUERY_PARAM = re.compile(
    r"(?i)\b(app_key|app_id|api_key|apikey|access_token|token|secret|password)=([^&\s]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")


def redact_credentials(value: str) -> str:
    """Entfernt API-Keys/Tokens aus Log- und Fehlertexten (KTD10/R9)."""
    redacted = _SECRET_QUERY_PARAM.sub(r"\1=***", value)
    return _BEARER_TOKEN.sub(r"\1***", redacted)


def sanitize_url_for_log(url: str | None) -> str:
    """Entfernt Userinfo und Query/Fragment aus einer URL für Logs.

    So gelangen in einer URL eingebettete Zugangsdaten (z. B.
    `https://user:pass@host/...?token=...`) nie in Logzeilen (KTD10/R9).
    """
    if not url:
        return "<unknown>"
    try:
        parsed = urlparse(url)
    except ValueError:
        return "<invalid-url>"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme, host, parsed.path or "", "", "", ""))


_URL_IN_TEXT = re.compile(r"https?://[^\s'\"<>()]+", re.IGNORECASE)


def _safe_error_text(exc: BaseException, url: str | None) -> str:
    """Bereitet eine Fehler-Exception für Logs auf: jede URL wird um
    Userinfo/Query erleichtert und bekannte Secrets zusätzlich redigiert."""
    text = _URL_IN_TEXT.sub(lambda match: sanitize_url_for_log(match.group(0)), str(exc))
    if url:
        text = text.replace(url, sanitize_url_for_log(url))
    return redact_credentials(text)


# --- URL-Validierung --------------------------------------------------------


def validate_source_url(url: str | None) -> bool:
    """Erlaubt nur `http`/`https` auf öffentliche Hosts (KTD10/R3).

    Weist `javascript:`/`data:`/andere Schemata sowie Loopback-, private,
    Link-Local- und reservierte IP-Hosts ab. Wird vor dem Persistieren einer
    `source_url` und vor jedem serverseitigen Abruf angewendet.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    host = parsed.hostname
    if not host:
        return False

    normalized_host = host.lower()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        return False

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # regulärer Domainname

    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


# --- Salary/Homeoffice-Prosa ------------------------------------------------


def fold_salary_homeoffice(
    description_text: str | None,
    *,
    salary: str | None = None,
    homeoffice: str | None = None,
) -> str | None:
    """Hängt Salary-/Homeoffice-Angaben als Prosa an `description_text`.

    Bewusst kein neues strukturiertes Feld (KD8/KTD6): vorhandener Text bleibt
    erhalten, die Zusatzangaben werden als kurze Zeilen angehängt. Liegt nichts
    vor, bleibt das Ergebnis `None`.
    """
    parts: list[str] = []
    if description_text and description_text.strip():
        parts.append(description_text.strip())
    if salary and salary.strip():
        parts.append(f"Gehalt: {salary.strip()}")
    if homeoffice and homeoffice.strip():
        parts.append(f"Homeoffice: {homeoffice.strip()}")
    return "\n\n".join(parts) or None


# --- Karten-Mapping und Extraktion -----------------------------------------


def map_heuristic_card(
    node: Any,
    source_url: str,
    source_platform: str,
    *,
    seen_titles: set[str],
    require_link: bool = False,
) -> JobOfferCreate | None:
    """Mappt einen Heuristik-Kartenknoten auf ein `JobOfferCreate`.

    Sucht erst nach einer echten Überschrift, erst danach auf ein `<a>`:
    viele Kartenlayouts wickeln die ganze Karte in ein textloses Overlay-`<a>`
    (Linktext nur im aria-label), das im DOM VOR der sichtbaren Überschrift
    steht - `find()` mit einer Tag-Liste matcht in Dokumentreihenfolge, nicht
    nach Priorität der Liste, und würde sonst immer das leere `<a>` statt der
    echten Überschrift treffen.

    Mit `require_link=True` werden Karten ohne echten Detail-Link verworfen
    (R3: kein Link auf die Suchseite).
    """
    title_el = node.find(["h1", "h2", "h3"]) or node.find("a")
    if title_el is None:
        return None
    title = title_el.get_text(strip=True)
    if len(title) < 3 or title in seen_titles:
        return None

    # Ist die Überschrift selbst schon ein verlinktes `<a>`, würde die zweite
    # Suche dasselbe Element nur erneut finden - dann direkt übernehmen.
    if title_el.name == "a" and title_el.get("href"):
        link_el = title_el
    else:
        link_el = node.find("a", href=True)
    href = link_el["href"] if link_el else None
    if not href:
        if require_link:
            return None
        full_url = source_url
    else:
        full_url = href if href.startswith("http") else urljoin(source_url, href)

    company_el = node.find(class_=COMPANY_CLASS_PATTERN)
    company = company_el.get_text(strip=True) if company_el else "Unbekanntes Unternehmen"

    location_el = node.find(class_=LOCATION_CLASS_PATTERN)
    location = location_el.get_text(strip=True) if location_el else None

    seen_titles.add(title)
    return JobOfferCreate(
        title=title,
        company=company,
        location=location,
        source_url=full_url,
        description_text=None,
        source_platform=source_platform,
    )


def map_json_ld_offer(
    item: dict[str, Any],
    source_url: str,
    source_platform: str,
) -> JobOfferCreate | None:
    """Mappt ein `schema.org/JobPosting`-JSON-LD-Objekt auf ein JobOffer."""
    title = item.get("title")
    if not title:
        return None

    organization = item.get("hiringOrganization")
    if isinstance(organization, dict):
        company = organization.get("name")
    else:
        company = organization
    company = company or "Unbekanntes Unternehmen"

    job_location = item.get("jobLocation")
    if isinstance(job_location, list):
        job_location = job_location[0] if job_location else {}
    address = job_location.get("address") if isinstance(job_location, dict) else None
    address = address if isinstance(address, dict) else {}
    location = ", ".join(
        filter(None, [address.get("addressLocality"), address.get("addressRegion")])
    ) or None

    # Relative JSON-LD-URLs genauso gegen die Seiten-URL auflösen wie im
    # Heuristik-Pfad (`map_heuristic_card`), sonst bliebe ein `/jobs/1` als
    # relative `source_url` stehen.
    raw_url = item.get("url")
    if raw_url:
        raw_url = str(raw_url)
        full_url = raw_url if raw_url.startswith("http") else urljoin(source_url, raw_url)
    else:
        full_url = source_url

    return JobOfferCreate(
        title=str(title).strip(),
        company=str(company).strip(),
        location=location,
        source_url=full_url,
        description_text=strip_html(item.get("description") or ""),
        source_platform=source_platform,
    )


def extract_json_ld_offers(
    soup: BeautifulSoup,
    source_url: str,
    source_platform: str,
    *,
    max_results: int = MAX_HEURISTIC_RESULTS,
) -> list[JobOfferCreate]:
    """Extrahiert alle `JobPosting`-Einträge aus eingebettetem JSON-LD.

    Validiert jede `source_url` an dieser geteilten Grenze (R3/KTD10), damit
    auch Xing und `GenericJobScraper` dieselbe Zusicherung wie die Board-
    Quellen bekommen, und respektiert `max_results`.
    """
    offers: list[JobOfferCreate] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                continue
            offer = map_json_ld_offer(item, source_url, source_platform)
            if offer is None or not validate_source_url(offer.source_url):
                continue
            offers.append(offer)
            if len(offers) >= max_results:
                return offers
    return offers


def extract_heuristic_offers(
    soup: BeautifulSoup,
    source_url: str,
    source_platform: str,
    *,
    max_results: int = MAX_HEURISTIC_RESULTS,
    require_link: bool = False,
    include: Callable[[JobOfferCreate], bool] | None = None,
    isolate_errors: bool = False,
    enrich_card: Callable[[JobOfferCreate, Any], None] | None = None,
) -> list[JobOfferCreate]:
    """Heuristische Extraktion anhand verbreiteter Job-Karten-Muster.

    `include` filtert Karten (z. B. Xings Länderfilter) VOR dem `max_results`-
    Cap, damit herausgefilterte Karten den Cap nicht aufbrauchen.
    `isolate_errors` fängt defekte Einzelkarten ab, ohne die übrigen zu
    verwerfen. `enrich_card` erhält die Karte selbst, damit boardspezifische
    Angaben (z. B. Gehalt/Homeoffice) pro Karte und nicht global aus dem
    ganzen Soup gelesen werden.

    Jede `source_url` wird an dieser geteilten Grenze validiert (R3/KTD10),
    damit auch Xing und `GenericJobScraper` dieselbe Zusicherung wie die
    Board-Quellen bekommen.
    """
    offers: list[JobOfferCreate] = []
    seen_titles: set[str] = set()

    # Ein `<article>` mit passender Klasse matcht beide Suchen; identische
    # Knoten (per Identität, nicht per Markup) nur einmal behalten, ohne die
    # Dokumentreihenfolge zu verändern.
    candidates: list[Any] = []
    seen_nodes: set[int] = set()
    for node in soup.find_all(class_=JOB_CLASS_PATTERN) + soup.find_all("article"):
        if id(node) in seen_nodes:
            continue
        seen_nodes.add(id(node))
        candidates.append(node)

    for node in candidates:
        try:
            offer = map_heuristic_card(
                node,
                source_url,
                source_platform,
                seen_titles=seen_titles,
                require_link=require_link,
            )
            if offer is not None and enrich_card is not None:
                enrich_card(offer, node)
        except Exception:  # noqa: BLE001 - eine defekte Karte darf die übrigen nicht verwerfen
            if not isolate_errors:
                raise
            logger.exception("Konnte Job-Karte nicht verarbeiten.")
            continue
        if offer is None:
            continue
        if not validate_source_url(offer.source_url):
            continue
        if include is not None and not include(offer):
            continue
        offers.append(offer)
        if len(offers) >= max_results:
            break

    return offers


def extract_offers_from_soup(
    soup: BeautifulSoup,
    source_url: str,
    source_platform: str,
    *,
    max_results: int = MAX_HEURISTIC_RESULTS,
    require_link: bool = False,
    isolate_errors: bool = False,
    enrich_card: Callable[[JobOfferCreate, Any], None] | None = None,
) -> list[JobOfferCreate]:
    """Zweistufige Extraktion aus einem bereits geparsten Soup: zuerst
    JSON-LD, dann Heuristik."""
    offers = extract_json_ld_offers(
        soup, source_url, source_platform, max_results=max_results
    )
    if offers:
        return offers

    return extract_heuristic_offers(
        soup,
        source_url,
        source_platform,
        max_results=max_results,
        require_link=require_link,
        isolate_errors=isolate_errors,
        enrich_card=enrich_card,
    )


def extract_offers(
    html: str,
    source_url: str,
    source_platform: str,
    *,
    max_results: int = MAX_HEURISTIC_RESULTS,
) -> list[JobOfferCreate]:
    """Zweistufige Extraktion: parst `html` und delegiert an
    `extract_offers_from_soup`."""
    return extract_offers_from_soup(
        BeautifulSoup(html, "html.parser"),
        source_url,
        source_platform,
        max_results=max_results,
    )


# --- Board-Deskriptor und Adapter -------------------------------------------


@dataclass(frozen=True)
class BoardDescriptor:
    """Beschreibt eine generisch lesbare HTML-Jobbörse.

    `source_platform` ist der eindeutige Plattform-Schlüssel (nicht
    "web-scraper"), `build_search_url(keywords, location)` baut die
    Ergebnisseiten-URL der Börse.
    """

    source_platform: str
    build_search_url: Callable[[str, str | None], str]
    use_playwright: bool = False
    max_results: int = MAX_HEURISTIC_RESULTS


def make_search_url_builder(
    base_url: str,
    *,
    keyword_param: str = "q",
    location_param: str = "l",
) -> Callable[[str, str | None], str]:
    """Baut einen einfachen `?keyword_param=...&location_param=...`-Builder."""

    def _build(keywords: str, location: str | None) -> str:
        query: dict[str, str] = {keyword_param: keywords}
        if location:
            query[location_param] = location
        return f"{base_url}?{urlencode(query)}"

    return _build


class BoardSourceAdapter:
    """Quellen-Adapter mit einheitlicher `search(keywords, location)`-Signatur.

    Nutzt den geteilten Render-/Extraktionspfad, sodass ein neues HTML-Board
    ohne eigenen Scraper nur über seinen `BoardDescriptor` teilnimmt (R6).
    """

    def __init__(self, descriptor: BoardDescriptor, *, timeout: float = 15.0) -> None:
        self._descriptor = descriptor
        self._timeout = timeout
        self.SOURCE_PLATFORM = descriptor.source_platform

    def search(
        self,
        keywords: str,
        location: str | None = None,
    ) -> list[JobOfferCreate]:
        url = self._descriptor.build_search_url(keywords, location)
        html = fetch_html(
            url,
            use_playwright=self._descriptor.use_playwright,
            timeout=self._timeout,
        )
        if not html:
            return []
        # Einmal parsen und denselben Soup an Extraktion und Hook weitergeben.
        soup = BeautifulSoup(html, "html.parser")
        offers = extract_offers_from_soup(
            soup,
            url,
            self._descriptor.source_platform,
            max_results=self._descriptor.max_results,
            # Eine Board-Karte ohne echten Detail-Link darf nicht die
            # Suchseite als `source_url` persistieren (R3).
            require_link=True,
            # Eine defekte Karte darf nicht das ganze Board verwerfen.
            isolate_errors=True,
            enrich_card=self._enrich_offer,
        )
        return self._postprocess(offers, soup)

    def _enrich_offer(self, offer: JobOfferCreate, node: Any) -> None:
        """Hook für kartenbezogene Zusatzangaben (Standard: no-op)."""
        return None

    def _postprocess(
        self,
        offers: list[JobOfferCreate],
        soup: BeautifulSoup,
    ) -> list[JobOfferCreate]:
        """Hook für boardspezifische Nachbearbeitung.

        Die Basis validiert die Ziel-URLs, damit auch der generische Pfad
        ohne eigene Subklasse sicher ist (R3/KTD10).
        """
        return [offer for offer in offers if validate_source_url(offer.source_url)]
