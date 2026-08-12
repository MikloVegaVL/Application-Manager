"""Tests für `LinkedInJobsClient` (siehe backend/app/services/job_sources/linkedin.py).

Deckt die Testszenarien aus U2 des Plans ab:
docs/plans/2026-08-12-001-feat-job-search-external-platforms-plan.md
"""
from __future__ import annotations

import requests

from app.services.job_sources.linkedin import LinkedInJobsClient

TWO_CARDS_FRAGMENT = """
<ul>
  <li>
    <div class="base-card">
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/1111?refId=abc"></a>
      <h3 class="base-search-card__title">Angular Developer</h3>
      <h4 class="base-search-card__subtitle">Acme GmbH</h4>
      <span class="job-search-card__location">Berlin, Germany</span>
    </div>
  </li>
  <li>
    <div class="base-card">
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/2222"></a>
      <h3 class="base-search-card__title">Backend Engineer</h3>
      <h4 class="base-search-card__subtitle">Beta AG</h4>
      <span class="job-search-card__location">Munich, Germany</span>
    </div>
  </li>
</ul>
"""

ZERO_CARDS_FRAGMENT = "<ul></ul>"


def _client(**kwargs) -> LinkedInJobsClient:
    # Jeder Test bekommt eine frische Instanz - der Cooldown ist bewusst
    # Klassen-Level-State, daher wird er zwischen Tests explizit
    # zurückgesetzt (siehe Fixture unten).
    return LinkedInJobsClient(**kwargs)


def _reset_cooldown() -> None:
    LinkedInJobsClient._cooldown_until = 0.0  # noqa: SLF001 - bewusster Test-Reset


def setup_function() -> None:
    _reset_cooldown()


def teardown_function() -> None:
    _reset_cooldown()


def test_happy_path_returns_mapped_offers(requests_mock):
    requests_mock.get(LinkedInJobsClient.BASE_URL, text=TWO_CARDS_FRAGMENT)

    offers = _client().search("Angular", "Berlin")

    assert len(offers) == 2
    assert all(offer.source_platform == "linkedin" for offer in offers)
    assert offers[0].title == "Angular Developer"
    assert offers[0].company == "Acme GmbH"
    assert offers[0].location == "Berlin, Germany"


def test_zero_cards_returns_empty_list(requests_mock):
    requests_mock.get(LinkedInJobsClient.BASE_URL, text=ZERO_CARDS_FRAGMENT)

    offers = _client().search("Nonexistent Role")

    assert offers == []


def test_source_url_comes_from_fragment_link_not_a_second_fetch(requests_mock):
    """Covers AE2: der Link zeigt direkt auf die echte LinkedIn-Job-Detailseite,
    ohne dass ein zweiter Request für die JSON-LD-Detailseite nötig ist."""
    requests_mock.get(LinkedInJobsClient.BASE_URL, text=TWO_CARDS_FRAGMENT)

    offers = _client().search("Angular")

    assert offers[0].source_url == "https://www.linkedin.com/jobs/view/1111"
    assert offers[1].source_url == "https://www.linkedin.com/jobs/view/2222"
    # Nur ein Request wurde ausgeführt - kein zusätzlicher Detail-Fetch pro Ergebnis.
    assert requests_mock.call_count == 1


def test_request_exception_returns_empty_list_without_raising(requests_mock):
    requests_mock.get(LinkedInJobsClient.BASE_URL, exc=requests.ConnectionError("boom"))

    offers = _client().search("Angular")

    assert offers == []


def test_429_returns_empty_list_and_records_cooldown(requests_mock):
    requests_mock.get(LinkedInJobsClient.BASE_URL, status_code=429)

    offers = _client().search("Angular")

    assert offers == []
    assert LinkedInJobsClient._in_cooldown() is True  # noqa: SLF001


def test_cooldown_skips_request_on_next_search(requests_mock):
    requests_mock.get(LinkedInJobsClient.BASE_URL, status_code=429)
    _client().search("Angular")  # trips the cooldown
    assert requests_mock.call_count == 1

    offers = _client(cooldown_seconds=300.0).search("Angular")

    assert offers == []
    # Kein zweiter Request - der Cooldown hat die Anfrage komplett übersprungen.
    assert requests_mock.call_count == 1


def test_cooldown_persists_across_separate_instances(requests_mock):
    """Beweist, dass der Cooldown Klassen-/Modul-Level-State ist, nicht ein
    Instanzattribut - pro Request wird ein neuer Client instanziiert (KTD3),
    ein `self._cooldown_until` würde also nie tatsächlich greifen."""
    requests_mock.get(LinkedInJobsClient.BASE_URL, status_code=429)
    first_client = _client()
    first_client.search("Angular")  # trips the cooldown
    assert requests_mock.call_count == 1

    second_client = LinkedInJobsClient()  # komplett neue Instanz
    offers = second_client.search("Angular")

    assert offers == []
    assert requests_mock.call_count == 1
