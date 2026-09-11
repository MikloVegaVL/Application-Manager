import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { JobSearchComponent } from './job-search.component';
import { JobSearchResponse } from '../../core/models/job-offer.model';
import { TranslationService } from '../../core/services/translation.service';
import { environment } from '../../../environments/environment';

describe('JobSearchComponent', () => {
  let component: JobSearchComponent;
  let fixture: ComponentFixture<JobSearchComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [JobSearchComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(JobSearchComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should mark the search form invalid without keywords', () => {
    expect(component['searchForm'].invalid).toBeTrue();
  });

  function triggerSearch(keywords = 'Angular', location = ''): void {
    component['searchForm'].setValue({ keywords, location });
    component.onSearch();
  }

  function flushSearch(response: JobSearchResponse): void {
    const req = httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/search`);
    req.flush(response);
    fixture.detectChanges();
  }

  it('renders every result when all sources are ok', () => {
    triggerSearch();
    flushSearch({
      results: [
        {
          title: 'Angular Developer',
          company: 'Acme',
          location: 'Berlin',
          source_url: 'https://example.com/job/1',
          description_text: null,
          source_platform: 'arbeitsagentur',
        },
      ],
      sources: [
        { platform: 'arbeitsagentur', status: 'ok', reason: null },
        { platform: 'linkedin', status: 'ok', reason: null },
        { platform: 'xing', status: 'ok', reason: null },
      ],
    });

    expect(component['results']().length).toBe(1);
    expect(component['unavailableSources']().length).toBe(0);
  });

  it('Covers AE1: keeps other sources\' results and flags the unavailable one instead of wiping results', () => {
    triggerSearch('Angular', 'Berlin');
    flushSearch({
      results: [
        {
          title: 'Backend Engineer',
          company: 'Beta AG',
          location: 'Berlin',
          source_url: 'https://example.com/job/2',
          description_text: null,
          source_platform: 'arbeitsagentur',
        },
      ],
      sources: [
        { platform: 'arbeitsagentur', status: 'ok', reason: null },
        { platform: 'linkedin', status: 'unavailable', reason: 'timeout' },
        { platform: 'xing', status: 'ok', reason: null },
      ],
    });

    expect(component['results']().length).toBe(1);
    expect(component['errorMessage']()).toBeNull();
    const unavailable = component['unavailableSources']();
    expect(unavailable.length).toBe(1);
    expect(unavailable[0].platform).toBe('linkedin');
    expect(component['allSourcesUnavailable']()).toBeFalse();

    const chipText = fixture.nativeElement.textContent as string;
    expect(chipText).toContain('LinkedIn');
    expect(chipText).toContain('nicht verfügbar');
  });

  it('resets stale source statuses when a new search starts', () => {
    triggerSearch();
    flushSearch({
      results: [],
      sources: [{ platform: 'linkedin', status: 'unavailable', reason: 'timeout' }],
    });
    expect(component['sourceStatuses']().length).toBe(1);

    // Zweite Suche startet, bevor die Antwort da ist - der alte Status
    // muss sofort verschwinden, nicht erst nach der neuen Antwort.
    triggerSearch();
    expect(component['sourceStatuses']().length).toBe(0);

    httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/search`).flush({
      results: [],
      sources: [],
    });
  });

  it('shows a distinct message when every source is unavailable', () => {
    triggerSearch();
    flushSearch({
      results: [],
      sources: [
        { platform: 'arbeitsagentur', status: 'unavailable', reason: 'empty' },
        { platform: 'linkedin', status: 'unavailable', reason: 'rate-limited' },
        { platform: 'xing', status: 'unavailable', reason: 'empty' },
      ],
    });

    expect(component['allSourcesUnavailable']()).toBeTrue();
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Alle Quellen waren gerade nicht erreichbar');
  });

  it('Regression: onSaveJob still saves a result pulled from a non-Arbeitsagentur source', () => {
    triggerSearch();
    flushSearch({
      results: [
        {
          title: 'Angular Developer',
          company: 'Acme',
          location: 'Berlin',
          source_url: 'https://example.com/job/linkedin-1',
          description_text: null,
          source_platform: 'linkedin',
        },
      ],
      sources: [{ platform: 'linkedin', status: 'ok', reason: null }],
    });

    const job = component['results']()[0];
    component.onSaveJob(job);

    const saveReq = httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/save`);
    expect(saveReq.request.method).toBe('POST');
    saveReq.flush({ ...job, id: 1, created_at: new Date().toISOString(), is_processed: false });

    expect(component.isSaved(job)).toBeTrue();
  });

  it('Regression (ce-debug, 2026-08-24): onSaveJob recovers from a 409 by caching the existing job_offer_id', () => {
    triggerSearch();
    flushSearch({
      results: [
        {
          title: 'Angular Developer',
          company: 'Acme',
          location: 'Berlin',
          source_url: 'https://example.com/job/already-saved',
          description_text: null,
          source_platform: 'linkedin',
        },
      ],
      sources: [{ platform: 'linkedin', status: 'ok', reason: null }],
    });

    const job = component['results']()[0];
    component.onSaveJob(job);

    const saveReq = httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/save`);
    saveReq.flush(
      { detail: { message: 'Dieses Stellenangebot wurde bereits gespeichert.', job_offer_id: 42 } },
      { status: 409, statusText: 'Conflict' },
    );

    // Ohne den Cache-Nachzug bliebe der Button dauerhaft im
    // "speichern"-Zustand hängen, obwohl der Job serverseitig längst
    // existiert (siehe save_job-Backfill im Backend).
    expect(component.isSaved(job)).toBeTrue();
  });

  it('Regression (ce-debug, 2026-08-24): onGenerateApplication navigates to the existing editor on a 409 instead of dead-ending', () => {
    triggerSearch();
    flushSearch({
      results: [
        {
          title: 'Angular Developer',
          company: 'Acme',
          location: 'Berlin',
          source_url: 'https://example.com/job/already-saved',
          description_text: null,
          source_platform: 'linkedin',
        },
      ],
      sources: [{ platform: 'linkedin', status: 'ok', reason: null }],
    });

    const job = component['results']()[0];
    const router = TestBed.inject(Router);
    const navigateSpy = spyOn(router, 'navigate').and.resolveTo(true);

    component.onGenerateApplication(job);

    const saveReq = httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/save`);
    saveReq.flush(
      { detail: { message: 'Dieses Stellenangebot wurde bereits gespeichert.', job_offer_id: 42 } },
      { status: 409, statusText: 'Conflict' },
    );

    expect(navigateSpy).toHaveBeenCalledWith(['/editor', 42]);
    expect(component.isSaved(job)).toBeTrue();
  });

  it('a full request failure still shows the error message and clears results', () => {
    triggerSearch();
    const req = httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/search`);
    req.flush('server error', { status: 500, statusText: 'Internal Server Error' });
    fixture.detectChanges();

    expect(component['errorMessage']()).not.toBeNull();
    expect(component['results']().length).toBe(0);
    expect(component['sourceStatuses']().length).toBe(0);
  });

  describe('onClearResults()', () => {
    it('empties the results list without touching the search form', () => {
      triggerSearch('Angular', 'Berlin');
      flushSearch({
        results: [
          {
            title: 'Angular Developer',
            company: 'Acme',
            location: 'Berlin',
            source_url: 'https://example.com/job/1',
            description_text: null,
            source_platform: 'arbeitsagentur',
          },
        ],
        sources: [{ platform: 'arbeitsagentur', status: 'ok', reason: null }],
      });
      expect(component['results']().length).toBe(1);

      component.onClearResults();

      expect(component['results']().length).toBe(0);
      expect(component['sourceStatuses']().length).toBe(0);
      expect(component['hasSearched']()).toBeFalse();
      // Suchbegriff/Ort bleiben erhalten, damit sich dieselbe Suche leicht
      // erneut auslösen oder abwandeln lässt.
      expect(component['searchForm'].getRawValue()).toEqual({ keywords: 'Angular', location: 'Berlin' });
    });
  });

  describe('cross-navigation persistence (JobSearchStateService)', () => {
    it('keeps the results list when the component is recreated (simulates leaving and returning to the page)', () => {
      triggerSearch('Angular');
      flushSearch({
        results: [
          {
            title: 'Angular Developer',
            company: 'Acme',
            location: 'Berlin',
            source_url: 'https://example.com/job/1',
            description_text: null,
            source_platform: 'arbeitsagentur',
          },
        ],
        sources: [{ platform: 'arbeitsagentur', status: 'ok', reason: null }],
      });
      expect(component['results']().length).toBe(1);

      // Neue Komponenten-Instanz im selben TestBed - entspricht einem
      // Routenwechsel weg von und zurück zur Jobsuche-Seite, ohne die
      // Anwendung (und damit den `providedIn: 'root'`-Service) neu zu laden.
      const secondFixture = TestBed.createComponent(JobSearchComponent);
      secondFixture.detectChanges();
      const secondComponent = secondFixture.componentInstance;

      expect(secondComponent['results']().length).toBe(1);
      expect(secondComponent['searchForm'].getRawValue().keywords).toBe('Angular');
    });
  });

  describe('U7: source status labels', () => {
    beforeEach(() => {
      localStorage.clear();
    });

    afterEach(() => {
      localStorage.clear();
    });

    it('renders the distinct "not configured" label for reason="not-configured"', () => {
      triggerSearch();
      flushSearch({
        results: [],
        sources: [{ platform: 'adzuna', status: 'unavailable', reason: 'not-configured' }],
      });

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('Adzuna');
      expect(text).toContain('nicht konfiguriert');
      expect(text).not.toContain('nicht verfügbar');
    });

    it('keeps the generic unavailable label for existing reasons', () => {
      triggerSearch();
      flushSearch({
        results: [],
        sources: [
          { platform: 'linkedin', status: 'unavailable', reason: 'timeout' },
          { platform: 'xing', status: 'unavailable', reason: 'error' },
          { platform: 'arbeitsagentur', status: 'unavailable', reason: 'empty' },
          { platform: 'jooble', status: 'unavailable', reason: 'rate-limited' },
        ],
      });

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('nicht verfügbar');
      expect(text).not.toContain('nicht konfiguriert');
    });

    it('falls back to the raw platform key for an unknown platform', () => {
      triggerSearch();
      flushSearch({
        results: [],
        sources: [{ platform: 'unknown-board', status: 'unavailable', reason: 'error' }],
      });

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('unknown-board');
    });

    it('renders the friendly name and not-configured label in both languages', () => {
      const i18n = TestBed.inject(TranslationService);
      i18n.setLanguage('en');

      triggerSearch();
      flushSearch({
        results: [],
        sources: [{ platform: 'germantechjobs', status: 'unavailable', reason: 'not-configured' }],
      });

      let text = fixture.nativeElement.textContent as string;
      expect(text).toContain('GermanTechJobs');
      expect(text).toContain('not configured');

      i18n.setLanguage('de');
      fixture.detectChanges();
      text = fixture.nativeElement.textContent as string;
      expect(text).toContain('GermanTechJobs');
      expect(text).toContain('nicht konfiguriert');
    });
  });
});
