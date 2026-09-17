"""On-Demand-Suche nach einer Bewerbungs-E-Mail für eine Stellenanzeige.

Wenn der Text einer Stellenanzeige selbst keine E-Mail-Adresse hergibt
(R12), löst der Nutzer diese Suche explizit aus (R1/R2). Der Service:

1. löst die Arbeitgeber-Domain auf - zuerst über Links auf der
   Anzeigenseite, sonst über den Firmennamen (R3/A2) - und baut daraus
   Karriere-/Jobs-, Kontakt- und Impressum-URLs plus die Anzeigenseite als
   Fallback. Links auf die eigene Domain der Jobbörse und auf bekannte
   Jobbörsen/-Aggregatoren werden dabei ausgeschlossen: sonst crawlt die
   Suche die Muttergesellschaft der Börse (z. B. XINGs `new-work.se`) statt
   den Arbeitgeber und läuft in die Deadline. Der Firmenname wird nicht nur
   als Ganzes slugifiziert, sondern in Marken-Tokens zerlegt, weil
   `deutschebausparkassebadenia.de` nie auflöst, `badenia.de` aber schon,
2. validiert jede URL vor dem Abruf SSRF-gehärtet: der Host wird aufgelöst
   und private/Loopback/Link-Local/reservierte Adressen werden abgelehnt;
   Weiterleitungen werden hop-für-hop erneut validiert statt blind verfolgt
   oder pauschal deaktiviert (KTD3),
3. strippt HTML und liest die Adressen per Regex aus dem Seitentext (plus
   `mailto:`-Links). Kein LLM pro Seite: da R4 ohnehin nur wörtlich belegte
   Adressen zulässt, kann ein Modell nie mehr gültige Kandidaten liefern,
   kostete aber mit `keep_alive=0` 7-40 s pro Seite und sprengte die
   Deadline (KTD4),
4. behält nur Adressen, die wörtlich (case-insensitiv) im begrenzten
   Seitentext vorkommen (R4), und
5. rankt anwendungsspezifische Adressen (`bewerbung@`, `jobs@`, `karriere@`,
   `hr@`) vor benannten Kontakten vor generischen (`info@`, `kontakt@`) (R5).

Das Ergebnis ist `found`, `not-found` oder `failed` (A5). Kein Fehlerpfad
liefert jemals eine aus einem Muster abgeleitete Adresse (R6/KTD4).

Aufbau wie `JobSearchService`: die Fetch-, Extraktions- und Resolver-Aufrufe
sind Konstruktor-Seams, sodass Tests Fakes injizieren statt Globals zu
patchen; `get_application_email_lookup_service()` ist der FastAPI-Provider.
"""
from __future__ import annotations

import logging
import re
import socket
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from time import monotonic
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.core.config import settings
from app.schemas.application_email_lookup import (
    ApplicationEmailLookupRequest,
    ApplicationEmailLookupResult,
)
from app.services.job_sources.shared import (
    DEFAULT_USER_AGENT,
    is_public_ip,
    read_capped_body,
    sanitize_url_for_log,
    strip_html,
    validate_source_url,
)

logger = logging.getLogger(__name__)

Fetcher = Callable[[str], str | None]
EmailExtractor = Callable[[str], list[str]]
Resolver = Callable[[str], list[str]]

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Zeichen, die Teil einer E-Mail-Adresse sind. Der Verbatim-Nachweis (R4) darf
# eine Adresse nur an einer echten Grenze matchen, damit `kontakt@acme.de`
# nicht in `kontakt@acme.development` "passt".
_EMAIL_CHAR_CLASS = r"[A-Za-z0-9._%+\-@]"
_EMAIL_TRIM_CHARS = ".,;:<>()[]{}\"'"

# Prozessweit geteilter, begrenzter Executor statt eines Executors pro
# Request: `shutdown(wait=False)` ließ hängende Worker (und damit den
# prozessweiten Ollama-Lock) beliebig lange weiterlaufen. Der Cap begrenzt,
# wie viele Lookups gleichzeitig laufen; ein `threading.Event` bricht die
# noch wartende Arbeit nach der Deadline ab (KTD4).
_LOOKUP_EXECUTOR_MAX_WORKERS = 4
# Kleine Nachfrist, damit ein Worker, der seine Deadline selbst bemerkt,
# einen bereits gefundenen Kandidaten noch als `found` zurückgeben kann,
# statt vom äußeren Wait exakt an der Grenze abgeschnitten zu werden.
_LOOKUP_DEADLINE_GRACE_SECONDS = 0.25
# Maximale Weiterleitungs-Hops pro Seite; jeder Hop wird erneut SSRF-validiert
# (KTD3). Apex -> www ist der Normalfall, mehr als ein Hop ist selten.
_MAX_REDIRECT_HOPS = 3
_lookup_executor: ThreadPoolExecutor | None = None
_lookup_executor_lock = threading.Lock()


def _get_lookup_executor() -> ThreadPoolExecutor:
    """Liefert den geteilten Lookup-Executor (lazy, einmal pro Prozess)."""
    global _lookup_executor
    with _lookup_executor_lock:
        if _lookup_executor is None:
            _lookup_executor = ThreadPoolExecutor(
                max_workers=_LOOKUP_EXECUTOR_MAX_WORKERS,
                thread_name_prefix="email-lookup",
            )
        return _lookup_executor


# Lokale Teile, die anwendungsspezifisch sind und zuerst angeboten werden (R5).
_APPLICATION_LOCALPART_PREFIXES = (
    "bewerbung",
    "bewerbungen",
    "application",
    "apply",
    "karriere",
    "career",
    "jobs",
    "job",
    "recruiting",
    "hr",
    "personal",
)
# Generische Postfächer - erst nach benannten Kontakten (R5/AE3).
_GENERIC_LOCALPARTS = {
    "info",
    "kontakt",
    "contact",
    "mail",
    "hello",
    "hallo",
    "office",
    "post",
    "service",
    "team",
    "presse",
    "webmaster",
    "noreply",
    "no-reply",
}

_CAREER_PATH_RE = re.compile(r"(karriere|career|jobs?|stellen)", re.IGNORECASE)
_CONTACT_PATH_RE = re.compile(r"(kontakt|contact|impressum|imprint)", re.IGNORECASE)
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(gmbh|mbh|ag|kg|kgaa|ug|ohg|gbr|co|inc|ltd|llc|se|ev|e\.v|vvag)\b",
    re.IGNORECASE,
)
_UMLAUT_MAP = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"}
)
_COMPANY_TLDS = (".de", ".com")
_EMPLOYER_PATH_CANDIDATES = ("karriere", "jobs", "kontakt", "impressum")

# Bekannte Jobbörsen/-Aggregatoren (Registrable Domains). Links dorthin sind
# NIE Arbeitgeber-Hosts: sonst crawlt die Suche die Börse selbst bzw. deren
# Muttergesellschaft (XING -> `new-work.se`) und läuft in die Deadline,
# statt den Arbeitgeber zu erreichen.
_JOB_BOARD_DOMAINS = frozenset(
    {
        "arbeitsagentur.de",
        "arbeitnow.com",
        "devjobs.de",
        "get-in-it.de",
        "glassdoor.com",
        "indeed.com",
        "instaffo.com",
        "jobs.de",
        "jobware.de",
        "kimeta.de",
        "linkedin.com",
        "meinestadt.de",
        "monster.de",
        "monster.com",
        "new-work.se",
        "persy.jobs",
        "relaxx.center",
        "stellenanzeigen.de",
        "stepstone.de",
        "xing.com",
        "yourfirm.de",
    }
)


def _default_resolver(host: str) -> list[str]:
    """Löst `host` per DNS in alle zugehörigen IP-Adressen auf."""
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


def is_valid_email(value: str | None) -> bool:
    """Grobe Formatprüfung einer E-Mail-Adresse.

    `fullmatch` statt `^...$` mit `.match`: `$` passt auch vor einem
    abschließenden `\\n`, `fullmatch` (bzw. `\\Z`) nicht - ein Wert mit
    Trailing-Newline wird damit abgelehnt.
    """
    return bool(value) and _EMAIL_RE.fullmatch(value) is not None


def _email_appears_verbatim(email: str, text: str) -> bool:
    """Ob `email` wörtlich im `text` vorkommt - an Adressgrenzen (R4).

    Reine Substring-Suche würde `kontakt@acme.de` fälschlich in
    `kontakt@acme.development` finden; die Lookarounds verbieten ein
    angrenzendes Adresszeichen.
    """
    pattern = re.compile(
        rf"(?<!{_EMAIL_CHAR_CLASS}){re.escape(email)}(?!{_EMAIL_CHAR_CLASS})",
        re.IGNORECASE,
    )
    return pattern.search(text) is not None


def _collect_mailto_addresses(html: str) -> list[str]:
    """Sammelt Adressen aus `a[href^="mailto:"]` vor dem HTML-Stripping.

    `get_text()` verwirft `href`-Attribute, wodurch eine ausschließlich als
    `mailto:`-Link vorhandene Adresse nie an den Verbatim-Nachweis gelangen
    würde. Sie werden daher an den Seitentext angehängt.
    """
    soup = BeautifulSoup(html, "html.parser")
    addresses: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("href") or "").strip()
        if not href.lower().startswith("mailto:"):
            continue
        raw = href[len("mailto:"):].split("?", 1)[0]
        for part in raw.split(","):
            address = part.strip()
            if address and address not in addresses:
                addresses.append(address)
    return addresses


def _clean_email(value: str) -> str:
    """Entfernt Whitespace, `mailto:`-Präfix und umgebende Satzzeichen."""
    cleaned = value.strip()
    if cleaned.lower().startswith("mailto:"):
        cleaned = cleaned[len("mailto:"):]
    return cleaned.strip().strip(_EMAIL_TRIM_CHARS).strip()


def _rank_email(email: str) -> int:
    """0 = anwendungsspezifisch, 1 = benannter Kontakt, 2 = generisch (R5)."""
    local_part = email.split("@", 1)[0].lower()
    if any(local_part.startswith(prefix) for prefix in _APPLICATION_LOCALPART_PREFIXES):
        return 0
    if local_part in _GENERIC_LOCALPARTS:
        return 2
    return 1


def _company_tokens(company: str) -> list[str]:
    """Zerlegt den Firmennamen in normalisierte Tokens.

    `&` wird entfernt (`G&S` -> `gs`), Umlaute werden transliteriert und alles
    außer Buchstaben/Ziffern/Bindestrichen wird zum Trenner. Bindestriche
    bleiben erhalten, damit eine zusammengesetzte Marke wie `HUK-COBURG` ein
    Token bleibt.
    """
    normalized = company.translate(_UMLAUT_MAP).lower().replace("&", "")
    return [token for token in re.split(r"[^a-z0-9-]+", normalized) if token]


def _company_slug_candidates(company: str) -> list[str]:
    """Domain-Slugs in absteigender Wahrscheinlichkeit.

    Der Ganzname-Slug (`deutschebausparkassebadenia`) löst praktisch nie auf.
    Deshalb wird zusätzlich das Token direkt vor dem Rechtsform-Suffix als
    Marke behandelt (`... Badenia AG` -> `badenia`, `FERCHAU GmbH ...` ->
    `ferchau`) und danach in Paaren/Einzeltokens gesucht (`G&S IT Group` ->
    `gs-it`, `HUK-COBURG VVaG` -> `huk-coburg`).
    """
    translated = company.translate(_UMLAUT_MAP).lower()
    tokens = _company_tokens(translated)
    if not tokens:
        return []

    candidates: list[str] = []

    def add(slug: str) -> None:
        if len(slug) >= 3 and slug not in candidates:
            candidates.append(slug)

    # 1. Token direkt vor der ersten Rechtsform (`... Badenia AG` -> badenia).
    suffix = _LEGAL_SUFFIX_RE.search(translated)
    if suffix:
        before = _company_tokens(translated[: suffix.start()])
        if before:
            add(before[-1])

    # 2. Der komplette Name als ein Slug (bisheriges Verhalten).
    add("".join(token.replace("-", "") for token in tokens))

    # 3. Erstes Token (Marken stehen oft am Anfang, z. B. `FERCHAU GmbH ...`).
    add(tokens[0].replace("-", ""))

    # 4. Benachbarte Paare - deckt `HUK-COBURG` und `G&S IT Group` -> `gs-it`.
    for first, second in zip(tokens, tokens[1:]):
        add(f"{first}-{second}")
        add(f"{first}{second}")

    # 5. Einzelne Tokens, längste zuerst (längere Tokens sind meist die Marke).
    for token in sorted(tokens, key=len, reverse=True):
        add(token)

    return candidates


def _company_host_candidates(company: str) -> list[str]:
    hosts: list[str] = []
    for slug in _company_slug_candidates(company):
        for tld in _COMPANY_TLDS:
            host = f"{slug}{tld}"
            if host not in hosts:
                hosts.append(host)
    return hosts


def _registrable_domain(host: str) -> str:
    """Grobe Registrable-Domain-Heuristik (ohne Public-Suffix-Liste).

    Reicht, um Fremd-Hosts (Social/Tracking) von Arbeitgeber-Hosts zu
    unterscheiden; eine vollständige PSL wäre für diesen Zweck Overkill.
    """
    normalized = (host or "").lower().strip(".")
    parts = normalized.split(".")
    if len(parts) <= 2:
        return normalized
    if parts[-2] in {"co", "com", "org", "net", "gov", "edu", "ac"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _truncate_bytes(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


@dataclass
class _Candidate:
    email: str
    source_url: str
    rank: int
    order: int
    # 0 = Domain passt zum Arbeitgeber (Firmen-Kandidat oder Seite des
    # Arbeitgebers), 1 = fremde Domain (z. B. eine im Anzeigentext eingebettete
    # Adresse eines anderen Unternehmens). Primäres Sortierkriterium, damit
    # eine wörtlich belegte Adresse einer *fremden* Firma nicht gewinnt.
    affinity: int = 1


class ApplicationEmailLookupService:
    """Löst, lädt und extrahiert eine Bewerbungs-E-Mail für einen Job-Payload."""

    def __init__(
        self,
        *,
        fetch: Fetcher | None = None,
        extract_emails: EmailExtractor | None = None,
        resolver: Resolver | None = None,
        max_pages: int | None = None,
        fetch_timeout_seconds: float | None = None,
        max_body_bytes: int | None = None,
        max_page_text_chars: int | None = None,
        deadline_seconds: float | None = None,
    ) -> None:
        self._max_pages = (
            max_pages if max_pages is not None else settings.APPLICATION_EMAIL_LOOKUP_MAX_PAGES
        )
        self._fetch_timeout = (
            fetch_timeout_seconds
            if fetch_timeout_seconds is not None
            else settings.APPLICATION_EMAIL_LOOKUP_FETCH_TIMEOUT_SECONDS
        )
        self._max_body_bytes = (
            max_body_bytes
            if max_body_bytes is not None
            else settings.APPLICATION_EMAIL_LOOKUP_MAX_BODY_BYTES
        )
        self._max_page_text_chars = (
            max_page_text_chars
            if max_page_text_chars is not None
            else settings.APPLICATION_EMAIL_LOOKUP_MAX_PAGE_TEXT_CHARS
        )
        self._deadline_seconds = (
            deadline_seconds
            if deadline_seconds is not None
            else settings.APPLICATION_EMAIL_LOOKUP_DEADLINE_SECONDS
        )
        self._resolver = resolver or _default_resolver
        self._fetch = fetch or self._fetch_html
        self._extract_emails = extract_emails or _extract_emails_via_regex

    # --- öffentliche API ---------------------------------------------------

    def lookup(self, request: ApplicationEmailLookupRequest) -> ApplicationEmailLookupResult:
        """Führt die Suche mit harter Gesamt-Deadline aus.

        Der eigentliche Lauf steckt in einem Worker des geteilten, begrenzten
        Executors, dessen Ergebnis höchstens `deadline_seconds` (plus kleiner
        Nachfrist) wartet - so löst die Anfrage auch dann auf, wenn ein Fetch
        hängt (KTD4). Bei einem Timeout wird das `cancel`-Event gesetzt, damit
        der Worker keine weitere Seite mehr lädt/extrahiert; ein bereits
        laufender Fetch kann nicht unterbrochen werden, läuft also höchstens
        bis zu seinem eigenen Timeout weiter. Jeder Fehler wird auf `failed`
        abgebildet, nie auf eine erratene Adresse (R6).
        """
        cancel = threading.Event()
        try:
            deadline = monotonic() + self._deadline_seconds
            executor = _get_lookup_executor()
            future = executor.submit(self._lookup, request, deadline, cancel)
            try:
                return future.result(
                    timeout=self._deadline_seconds + _LOOKUP_DEADLINE_GRACE_SECONDS
                )
            except FuturesTimeoutError:
                cancel.set()
                logger.warning("Bewerbungs-E-Mail-Suche hat die Deadline überschritten.")
                return ApplicationEmailLookupResult(status="failed")
            except Exception:  # noqa: BLE001 - jeder Fehler ist ein `failed`-Ergebnis
                logger.exception("Bewerbungs-E-Mail-Suche ist fehlgeschlagen.")
                return ApplicationEmailLookupResult(status="failed")
        except Exception:  # noqa: BLE001 - auch ein Executor-Fehler darf kein 5xx werden
            logger.exception("Bewerbungs-E-Mail-Suche konnte nicht gestartet werden.")
            return ApplicationEmailLookupResult(status="failed")

    # --- Ablauf ------------------------------------------------------------

    def _lookup(
        self,
        request: ApplicationEmailLookupRequest,
        deadline: float,
        cancel: threading.Event,
    ) -> ApplicationEmailLookupResult:
        candidates: list[_Candidate] = []
        order = 0
        any_page_processed = False

        # Domain-Abgleich: die eigene Adresse der Jobbörse ist nie eine
        # Bewerbungsadresse, und eine Adresse auf der Arbeitgeber-Domain
        # schlägt eine fremde (z. B. aus dem Anzeigentext eingebettete)
        # Adresse eines anderen Unternehmens.
        posting_domain = _registrable_domain(
            urlparse(request.source_url).hostname or ""
        )
        posting_is_board = posting_domain in _JOB_BOARD_DOMAINS
        company_domains = {
            _registrable_domain(host)
            for host in _company_host_candidates(request.company)
        }

        posting_html = self._fetch_page(request.source_url, deadline, cancel)
        employer_urls = self._candidate_urls(posting_html, request.source_url, request.company)

        employer_urls = list(dict.fromkeys(employer_urls))
        pages = employer_urls[: max(0, self._max_pages - 1)]
        # Die Anzeigenseite ist der Fallback (R3) und muss immer Platz im
        # Seitenbudget haben - sonst verdrängen die aus dem Firmennamen
        # erratenen Hosts sie (KTD4).
        if request.source_url not in employer_urls:
            pages.append(request.source_url)

        fetched: dict[str, str | None] = {request.source_url: posting_html}

        for page_url in pages:
            if cancel.is_set():
                break
            if self._deadline_exceeded(deadline):
                logger.warning("Bewerbungs-E-Mail-Suche: Deadline vor %s erreicht.", sanitize_url_for_log(page_url))
                # Ein bereits gefundener Kandidat darf nicht verworfen werden.
                if candidates:
                    return self._best_result(candidates)
                return ApplicationEmailLookupResult(status="failed")

            if page_url in fetched:
                html = fetched[page_url]
            else:
                html = self._fetch_page(page_url, deadline, cancel)
            if html is None:
                continue

            text = self._page_text(html)
            if not text:
                any_page_processed = True
                continue

            # Vor der Extraktion prüfen: nach Deadline/Abbruch keine weitere
            # Seite mehr aufbereiten/auswerten.
            if cancel.is_set() or self._deadline_exceeded(deadline):
                if candidates:
                    return self._best_result(candidates)
                return ApplicationEmailLookupResult(status="failed")

            try:
                emails = self._extract_emails(text)
            except Exception:  # noqa: BLE001 - eine fehlerhafte Seite darf die Suche nicht sprengen
                logger.exception(
                    "E-Mail-Extraktion für %s fehlgeschlagen.", sanitize_url_for_log(page_url)
                )
                continue
            any_page_processed = True

            page_domain = _registrable_domain(urlparse(page_url).hostname or "")
            for raw_email in emails:
                cleaned = _clean_email(raw_email)
                if not is_valid_email(cleaned):
                    continue
                if not _email_appears_verbatim(cleaned, text):
                    # R4: nur wörtlich auf der geladenen Seite gefundene Adressen.
                    continue
                email_domain = _registrable_domain(cleaned.rsplit("@", 1)[-1])
                if posting_is_board and email_domain == posting_domain:
                    # Die Support-/Footer-Adresse der Jobbörse selbst.
                    continue
                affinity = (
                    0
                    if email_domain in company_domains
                    or (
                        not posting_is_board
                        and page_domain
                        and page_domain == email_domain
                    )
                    else 1
                )
                candidates.append(
                    _Candidate(
                        email=cleaned,
                        source_url=page_url,
                        rank=_rank_email(cleaned),
                        order=order,
                        affinity=affinity,
                    )
                )
                order += 1

        if candidates:
            return self._best_result(candidates)
        if any_page_processed:
            return ApplicationEmailLookupResult(status="not-found")
        return ApplicationEmailLookupResult(status="failed")

    @staticmethod
    def _best_result(candidates: list[_Candidate]) -> ApplicationEmailLookupResult:
        best = min(
            candidates,
            key=lambda candidate: (candidate.affinity, candidate.rank, candidate.order),
        )
        return ApplicationEmailLookupResult(
            status="found",
            email=best.email,
            source_url=best.source_url,
        )

    # --- Seitentext --------------------------------------------------------

    def _fetch_page(self, url: str, deadline: float, cancel: threading.Event) -> str | None:
        if cancel.is_set():
            return None
        if not self._is_public_url(url):
            logger.warning("Bewerbungs-E-Mail-Suche: unsichere URL abgelehnt.")
            return None
        if self._deadline_exceeded(deadline):
            return None
        try:
            return self._fetch(url)
        except Exception:  # noqa: BLE001 - jeder Fetch-Fehler ist ein fehlender Text
            logger.exception("Abruf für die Bewerbungs-E-Mail-Suche fehlgeschlagen.")
            return None

    def _fetch_html(self, url: str) -> str | None:
        # KTD3: Weiterleitungen werden nicht blind verfolgt, sondern jeder Hop
        # erneut SSRF-validiert. Reines Deaktivieren war zu grob: deutsche
        # Arbeitgeber-Seiten leiten `domain.de` fast immer auf `www.domain.de`
        # um, der Redirect-Body ist dann nur ~200 Byte und die Suche endete
        # trotz korrekter Domain als `not-found`. Der Body-Cap begrenzt jeden
        # Download selbst (nicht nur die Textaufbereitung).
        current = url
        for _ in range(_MAX_REDIRECT_HOPS + 1):
            response = None
            try:
                response = requests.get(
                    current,
                    timeout=self._fetch_timeout,
                    headers={"User-Agent": DEFAULT_USER_AGENT},
                    allow_redirects=False,
                    stream=True,
                )
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        return None
                    target = urljoin(current, location)
                    if not self._is_public_url(target):
                        logger.warning(
                            "Bewerbungs-E-Mail-Suche: unsichere Weiterleitung abgelehnt."
                        )
                        return None
                    current = target
                    continue
                response.raise_for_status()
                return read_capped_body(response, self._max_body_bytes)
            except requests.RequestException as exc:
                logger.warning(
                    "Abruf von %s fehlgeschlagen: %s",
                    sanitize_url_for_log(current),
                    exc,
                )
                return None
            finally:
                if response is not None:
                    response.close()
        return None

    def _page_text(self, html: str) -> str | None:
        truncated = _truncate_bytes(html, self._max_body_bytes)
        mailto_addresses = _collect_mailto_addresses(truncated)
        text = strip_html(truncated)
        if mailto_addresses:
            joined = " ".join(mailto_addresses)
            text = f"{text} {joined}" if text else joined
        if not text:
            return None
        return text[: self._max_page_text_chars]

    # --- SSRF --------------------------------------------------------------

    def _is_public_url(self, url: str) -> bool:
        """Wörtliche Validierung plus DNS-Auflösung jedes Hosts (KTD3)."""
        if not validate_source_url(url):
            return False
        host = urlparse(url).hostname
        if not host:
            return False
        try:
            # `socket.getaddrinfo` hat kein Timeout-Parameter; die Auflösung
            # ist damit nur durch die Gesamt-Deadline des Lookups begrenzt.
            # Breiter Catch, weil ein Hostname auch Unicode-/Parsing-Fehler
            # auslösen kann (UnicodeError/ValueError), nicht nur OSError.
            addresses = self._resolver(host)
        except (OSError, UnicodeError, ValueError):
            return False
        if not addresses:
            return False
        for address in addresses:
            try:
                if not is_public_ip(address):
                    return False
            except (ValueError, UnicodeError):
                return False
        return True

    @staticmethod
    def _deadline_exceeded(deadline: float) -> bool:
        return monotonic() >= deadline

    # --- Kandidaten-URLs ---------------------------------------------------

    def _candidate_urls(
        self,
        posting_html: str | None,
        posting_url: str,
        company: str,
    ) -> list[str]:
        urls: list[str] = []
        hinted_hosts: list[str] = []
        other_hosts: list[str] = []
        posting_host = urlparse(posting_url).hostname

        # Nur Hosts, deren Registrable-Domain zur Anzeigenseite oder zum
        # Firmennamen passt, gelten als Arbeitgeber-Hosts. Sonst würden
        # beliebige verlinkte Fremd-Hosts (Social/Tracking) als Arbeitgeber
        # gescrapt und persistiert.
        allowed_domains: set[str] = set()
        if posting_host:
            allowed_domains.add(_registrable_domain(posting_host))
        for candidate in _company_host_candidates(company):
            allowed_domains.add(_registrable_domain(candidate))

        # Marken-Tokens für den Arbeitgeber-Abgleich: ein verlinkter Karriere-/
        # Kontakt-Host zählt nur dann als Arbeitgeber, wenn seine Domain den
        # Firmennamen enthält. Sonst würde jeder Partner-/Börsen-Link mit
        # `.../karriere` (z. B. `yourfirm.de/job/detail/...`) als Arbeitgeber
        # gescrapt und dessen eigene Adresse als Bewerbungsadresse geliefert.
        # Rechtsform-Tokens (`GmbH`, `AG`) sind dafür nutzlos und fliegen raus.
        company_tokens = {
            token
            for token in _company_tokens(company)
            if len(token) >= 3 and not _LEGAL_SUFFIX_RE.fullmatch(token)
        }

        if posting_html:
            soup = BeautifulSoup(posting_html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                href = (anchor["href"] or "").strip()
                if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
                    continue
                full = urljoin(posting_url, href)
                parsed = urlparse(full)
                if parsed.scheme not in ("http", "https"):
                    continue
                host = parsed.hostname
                if not host or host == posting_host:
                    continue
                host_domain = _registrable_domain(host)
                # Jobbörsen/-Aggregatoren sind nie der Arbeitgeber: XINGs
                # Footer verlinkt `new-work.se/de/karriere` und
                # `corporate.xing.com/.../pressekontakt`, LinkedIn sich
                # selbst. Ohne diesen Filter crawlt die Suche die Börse und
                # läuft in die Deadline, statt den Arbeitgeber zu erreichen.
                if host_domain in _JOB_BOARD_DOMAINS:
                    continue
                path = parsed.path or ""
                if _CAREER_PATH_RE.search(path) or _CONTACT_PATH_RE.search(path):
                    normalized_host = host.lower().replace("-", "")
                    if company_tokens and not any(
                        token.replace("-", "") in normalized_host
                        for token in company_tokens
                    ):
                        continue
                    urls.append(full)
                    if host not in hinted_hosts:
                        hinted_hosts.append(host)
                elif host not in other_hosts and host_domain in allowed_domains:
                    other_hosts.append(host)

        employer_hosts = hinted_hosts + other_hosts
        if not employer_hosts and company:
            employer_hosts = _company_host_candidates(company)

        for host in employer_hosts[:2]:
            base = f"https://{host}/"
            for path in _EMPLOYER_PATH_CANDIDATES:
                urls.append(urljoin(base, path))

        return list(dict.fromkeys(urls))


def _extract_emails_via_regex(text: str) -> list[str]:
    """Default-Extraktor: alle E-Mail-Adressen im Seitentext.

    Bewusst kein LLM: R4 akzeptiert nur wörtlich im Seitentext belegte
    Adressen, die Regex findet genau diese. Ein Modell könnte nie mehr
    gültige Kandidaten beisteuern, kostete aber pro Seite 7-40 s
    (`keep_alive=0` entlädt das Modell nach jedem Aufruf) und sprengte die
    Deadline. Nicht belegte oder unsaubere Treffer filtert der Aufrufer.
    """
    return _EMAIL_RE.findall(text)


def get_application_email_lookup_service() -> ApplicationEmailLookupService:
    """FastAPI-Dependency-Provider für den `ApplicationEmailLookupService`."""
    return ApplicationEmailLookupService()
