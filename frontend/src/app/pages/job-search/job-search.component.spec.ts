import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { By } from '@angular/platform-browser';
import { provideRouter, Router } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { MatChipOption } from '@angular/material/chips';

import { JobSearchComponent } from './job-search.component';
import {
  ApplicationEmailLookupResult,
  JobSearchResponse,
} from '../../core/models/job-offer.model';
import { JobSearchStateService } from '../../core/services/job-search-state.service';
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

  function triggerSearch(keywords = 'Angular', location = '', radiusKm = ''): void {
    component['searchForm'].setValue({ keywords, location, radiusKm });
    component.onSearch();
  }

  function flushSearch(response: JobSearchResponse): void {
    const req = httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/search`);
    req.flush(response);
    fixture.detectChanges();
  }

  describe('radius control (R1/R2/R3)', () => {
    it('starts disabled when Location is empty', () => {
      expect(component['searchForm'].controls.radiusKm.disabled).toBeTrue();
    });

    it('becomes enabled once Location gets a value', () => {
      component['searchForm'].controls.location.setValue('Berlin');

      expect(component['searchForm'].controls.radiusKm.disabled).toBeFalse();
    });

    it('becomes disabled again once Location is cleared', () => {
      component['searchForm'].controls.location.setValue('Berlin');
      component['searchForm'].controls.location.setValue('');

      expect(component['searchForm'].controls.radiusKm.disabled).toBeTrue();
    });

    it('sends radius_km when a radius is chosen alongside a location', () => {
      triggerSearch('Angular', 'Berlin', '50');

      const req = httpMock.expectOne(
        (request) => request.url === `${environment.apiBaseUrl}/jobs/search`,
      );
      expect(req.request.params.get('radius_km')).toBe('50');
      req.flush({ results: [], sources: [] });
    });

    it('omits radius_km when no radius is selected', () => {
      triggerSearch('Angular', '');

      const req = httpMock.expectOne(
        (request) => request.url === `${environment.apiBaseUrl}/jobs/search`,
      );
      expect(req.request.params.has('radius_km')).toBeFalse();
      req.flush({ results: [], sources: [] });
    });
  });

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
    expect(chipText).toContain('unavailable');
  });

  it('Covers R4/R6: shows the applied empty state when every result was already applied', () => {
    triggerSearch();
    flushSearch({
      results: [],
      sources: [{ platform: 'arbeitsagentur', status: 'ok', reason: null }],
      excluded_applied_count: 2,
    });

    expect(component['allResultsApplied']()).toBeTrue();
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('already been applied');
    expect(text).not.toContain('No job offers found');
  });

  it('keeps the generic empty state when nothing was excluded as applied', () => {
    triggerSearch();
    flushSearch({
      results: [],
      sources: [{ platform: 'arbeitsagentur', status: 'ok', reason: null }],
      excluded_applied_count: 0,
    });

    expect(component['allResultsApplied']()).toBeFalse();
    expect(fixture.nativeElement.textContent).toContain('No job offers found');
  });

  it('resets the applied state when a new search starts', () => {
    triggerSearch();
    flushSearch({
      results: [],
      sources: [{ platform: 'arbeitsagentur', status: 'ok', reason: null }],
      excluded_applied_count: 2,
    });
    expect(component['allResultsApplied']()).toBeTrue();

    triggerSearch('Backend');
    expect(component['allResultsApplied']()).toBeFalse();

    httpMock
      .expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/search`)
      .flush({ results: [], sources: [], excluded_applied_count: 0 });
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
    expect(text).toContain('All sources were unreachable just now');
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
    expect(component['results']().length).toBe(0);
  });

  it('Covers R5: removes the card via the cached-id generate path', () => {
    triggerSearch();
    flushSearch({
      results: [
        {
          title: 'Angular Developer',
          company: 'Acme',
          location: 'Berlin',
          source_url: 'https://example.com/job/cached',
          description_text: null,
          source_platform: 'linkedin',
        },
      ],
      sources: [{ platform: 'linkedin', status: 'ok', reason: null }],
    });
    const job = component['results']()[0];
    const router = TestBed.inject(Router);
    const navigateSpy = spyOn(router, 'navigate').and.resolveTo(true);
    TestBed.inject(JobSearchStateService).cacheSavedJob(job.source_url, 77);

    component.onGenerateApplication(job);

    expect(navigateSpy).toHaveBeenCalledWith(['/editor', 77]);
    expect(component['results']().length).toBe(0);
  });

  it('Covers R6/KTD5: an in-session save that empties the list shows the applied empty state', () => {
    triggerSearch();
    flushSearch({
      results: [
        {
          title: 'Angular Developer',
          company: 'Acme',
          location: 'Berlin',
          source_url: 'https://example.com/job/last',
          description_text: null,
          source_platform: 'linkedin',
        },
      ],
      sources: [{ platform: 'linkedin', status: 'ok', reason: null }],
    });
    const job = component['results']()[0];

    component.onSaveJob(job);

    httpMock
      .expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/save`)
      .flush({ ...job, id: 5, created_at: new Date().toISOString(), is_processed: false });

    fixture.detectChanges();
    expect(component['allResultsApplied']()).toBeTrue();
    expect(fixture.nativeElement.textContent).toContain('already been applied');
  });

  it('Covers R5: removes the card immediately after a successful save', () => {
    triggerSearch();
    flushSearch({
      results: [
        {
          title: 'Angular Developer',
          company: 'Acme',
          location: 'Berlin',
          source_url: 'https://example.com/job/keep',
          description_text: null,
          source_platform: 'linkedin',
        },
        {
          title: 'Angular Engineer',
          company: 'Beta AG',
          location: 'Berlin',
          source_url: 'https://example.com/job/remove',
          description_text: null,
          source_platform: 'linkedin',
        },
      ],
      sources: [{ platform: 'linkedin', status: 'ok', reason: null }],
    });
    const [keep, remove] = component['results']();

    component.onSaveJob(remove);

    httpMock
      .expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/save`)
      .flush({ ...remove, id: 1, created_at: new Date().toISOString(), is_processed: false });

    expect(component['results']().map((job) => job.source_url)).toEqual([keep.source_url]);
  });

  it('Covers R5: removes the card when a save reports it was already saved (409)', () => {
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

    httpMock
      .expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/save`)
      .flush(
        { detail: { message: 'already saved', job_offer_id: 42 } },
        { status: 409, statusText: 'Conflict' },
      );

    expect(component['results']().length).toBe(0);
  });

  it('Covers R5: removes the card when generating an application', () => {
    triggerSearch();
    flushSearch({
      results: [
        {
          title: 'Angular Developer',
          company: 'Acme',
          location: 'Berlin',
          source_url: 'https://example.com/job/generate',
          description_text: null,
          source_platform: 'linkedin',
        },
      ],
      sources: [{ platform: 'linkedin', status: 'ok', reason: null }],
    });
    const job = component['results']()[0];
    const router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);

    component.onGenerateApplication(job);

    httpMock
      .expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/save`)
      .flush({ ...job, id: 9, created_at: new Date().toISOString(), is_processed: false });

    expect(component['results']().length).toBe(0);
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

  describe('recipient email on the result card', () => {
    it('shows the recipient email extracted from the job description', () => {
      triggerSearch();
      flushSearch({
        results: [
          {
            title: 'Angular Developer',
            company: 'Acme',
            location: 'Berlin',
            source_url: 'https://example.com/job/1',
            description_text: 'Bitte sende deine Bewerbung an bewerbung@acme.example.',
            source_platform: 'arbeitsagentur',
          },
        ],
        sources: [{ platform: 'arbeitsagentur', status: 'ok', reason: null }],
      });

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('Recipient');
      expect(text).toContain('bewerbung@acme.example');
    });

    it('shows a placeholder when the description has no email address', () => {
      triggerSearch();
      flushSearch({
        results: [
          {
            title: 'Angular Developer',
            company: 'Acme',
            location: 'Berlin',
            source_url: 'https://example.com/job/1',
            description_text: 'Wir suchen eine Softwareentwicklerin (m/w/d).',
            source_platform: 'arbeitsagentur',
          },
        ],
        sources: [{ platform: 'arbeitsagentur', status: 'ok', reason: null }],
      });

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('Recipient');
      expect(text).toContain('—');
    });
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
      expect(component['searchForm'].getRawValue()).toEqual({
        keywords: 'Angular',
        location: 'Berlin',
        radiusKm: '',
      });
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
      expect(text).toContain('not configured');
      expect(text).not.toContain('unavailable');
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
      expect(text).toContain('unavailable');
      expect(text).not.toContain('not configured');
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

    it('renders the friendly name and not-configured label', () => {
      triggerSearch();
      flushSearch({
        results: [],
        sources: [{ platform: 'devjobs', status: 'unavailable', reason: 'not-configured' }],
      });

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('DEVjobs.de');
      expect(text).toContain('not configured');
    });
  });

  describe('source filtering via the status chips', () => {
    function flushTwoSourceSearch(): void {
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
          {
            title: 'Backend Engineer',
            company: 'Beta AG',
            location: 'Munich',
            source_url: 'https://example.com/job/2',
            description_text: null,
            source_platform: 'linkedin',
          },
        ],
        sources: [
          { platform: 'arbeitsagentur', status: 'ok', reason: null },
          { platform: 'linkedin', status: 'ok', reason: null },
        ],
      });
    }

    it('shows every result until a source chip is selected', () => {
      flushTwoSourceSearch();

      expect(component['filteredResults']().length).toBe(2);
      expect(component['hasActiveSourceFilter']()).toBeFalse();
    });

    it('narrows the displayed results to the selected sources', () => {
      flushTwoSourceSearch();

      component.onSourceFilterChange(['linkedin']);
      fixture.detectChanges();

      expect(component['filteredResults']().map((job) => job.source_platform)).toEqual(['linkedin']);
      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('Backend Engineer');
      expect(text).not.toContain('Angular Developer');
    });

    it('shows the filter-no-match message when the selected source has no results', () => {
      flushTwoSourceSearch();

      component.onSourceFilterChange(['xing']);
      fixture.detectChanges();

      expect(component['filteredResults']().length).toBe(0);
      expect(fixture.nativeElement.textContent).toContain('No results for the selected sources');
    });

    it('clears the filter and shows all results again', () => {
      flushTwoSourceSearch();
      component.onSourceFilterChange(['linkedin']);
      expect(component['hasActiveSourceFilter']()).toBeTrue();

      component.clearSourceFilter();
      fixture.detectChanges();

      expect(component['hasActiveSourceFilter']()).toBeFalse();
      expect(component['filteredResults']().length).toBe(2);
    });

    it('resets the filter when a new search starts', () => {
      flushTwoSourceSearch();
      component.onSourceFilterChange(['linkedin']);
      expect(component['hasActiveSourceFilter']()).toBeTrue();

      triggerSearch();
      expect(component['hasActiveSourceFilter']()).toBeFalse();

      httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/search`).flush({
        results: [],
        sources: [],
      });
    });

    it('does not offer unavailable sources as selectable filters', () => {
      triggerSearch();
      flushSearch({
        results: [],
        sources: [
          { platform: 'linkedin', status: 'unavailable', reason: 'timeout' },
          { platform: 'arbeitsagentur', status: 'ok', reason: null },
        ],
      });

      const options = fixture.debugElement.queryAll(By.directive(MatChipOption));
      const byValue = new Map(options.map((option) => [option.componentInstance.value, option.componentInstance]));

      expect(byValue.get('linkedin')?.disabled).toBeTrue();
      expect(byValue.get('arbeitsagentur')?.disabled).toBeFalse();
    });
  });

  describe('application-email lookup action', () => {
    const lookupUrl = `${environment.apiBaseUrl}/jobs/application-email-lookup`;

    function flushJobSearch(descriptionText: string | null): void {
      triggerSearch();
      flushSearch({
        results: [
          {
            title: 'Angular Developer',
            company: 'Acme',
            location: 'Berlin',
            source_url: 'https://example.com/job/1',
            description_text: descriptionText,
            source_platform: 'arbeitsagentur',
          },
        ],
        sources: [{ platform: 'arbeitsagentur', status: 'ok', reason: null }],
      });
    }

    function findEmailButton() {
      return fixture.debugElement.query(By.css('.job-card__find-email-btn'));
    }

    function clickFindEmail(): void {
      (findEmailButton().nativeElement as HTMLButtonElement).click();
      fixture.detectChanges();
    }

    function flushLookup(result: ApplicationEmailLookupResult) {
      const req = httpMock.expectOne((request) => request.url === lookupUrl);
      expect(req.request.method).toBe('POST');
      req.flush(result);
      fixture.detectChanges();
      return req;
    }

    it('Covers R1, R7: renders the returned address and its source link', () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      expect(findEmailButton()).toBeTruthy();

      clickFindEmail();
      flushLookup({
        status: 'found',
        email: 'bewerbung@acme.example',
        source_url: 'https://acme.example/karriere',
      });

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('bewerbung@acme.example');
      expect(text).toContain('Source of this address');

      const link = fixture.debugElement.query(By.css('.job-card__recipient-source'));
      expect(link.nativeElement.getAttribute('href')).toBe('https://acme.example/karriere');
      expect(link.nativeElement.getAttribute('target')).toBe('_blank');
      expect(link.nativeElement.getAttribute('rel')).toBe('noopener noreferrer');
    });

    it('Covers R2, R12: the action is absent when the posting text already yields an address', () => {
      flushJobSearch('Bitte sende deine Bewerbung an bewerbung@acme.example.');

      expect(findEmailButton()).toBeFalsy();
      httpMock.expectNone((request) => request.url === lookupUrl);
    });

    it('Covers R9: a not-found result renders the not-found state and keeps the placeholder', () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      clickFindEmail();
      flushLookup({ status: 'not-found' });

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('No application email found');
      expect(text).toContain('—');
      expect(text).not.toContain("Couldn't reach the employer's site");
    });

    it('Covers R9: a failed result renders the distinct failure copy', () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      clickFindEmail();
      flushLookup({ status: 'failed' });

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain("Couldn't reach the employer's site — try again");
      expect(text).not.toContain('No application email found');
    });

    it('Covers A5: an HTTP error on the lookup maps to the distinct failure copy and re-enables the action', () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      clickFindEmail();

      const req = httpMock.expectOne((request) => request.url === lookupUrl);
      req.flush(null, { status: 500, statusText: 'Internal Server Error' });
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain("Couldn't reach the employer's site — try again");
      expect(text).not.toContain('No application email found');
      expect((findEmailButton().nativeElement as HTMLButtonElement).disabled).toBeFalse();
    });

    it('Covers R11: a re-run can be triggered after an address is already displayed', () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      clickFindEmail();
      flushLookup({
        status: 'found',
        email: 'bewerbung@acme.example',
        source_url: 'https://acme.example/karriere',
      });

      expect(findEmailButton().nativeElement.textContent).toContain('Find email again');

      clickFindEmail();
      flushLookup({
        status: 'found',
        email: 'jobs@acme.example',
        source_url: 'https://acme.example/jobs',
      });

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('jobs@acme.example');
      expect(text).not.toContain('bewerbung@acme.example');
    });

    it('Covers R11: a re-run sends force=true in the lookup payload so the backend re-scrapes', () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      clickFindEmail();
      const firstReq = flushLookup({ status: 'not-found' });
      expect(firstReq.request.body.force).toBeFalse();

      clickFindEmail();
      const rerunReq = flushLookup({
        status: 'found',
        email: 'jobs@acme.example',
        source_url: 'https://acme.example/jobs',
      });
      expect(rerunReq.request.body.force).toBeTrue();
    });

    it('Covers KTD7/A1: saving after a successful lookup sends the cached address and its source url', () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      clickFindEmail();
      flushLookup({
        status: 'found',
        email: 'bewerbung@acme.example',
        source_url: 'https://acme.example/karriere',
      });

      const job = component['results']()[0];
      component.onSaveJob(job);

      const saveReq = httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/save`);
      expect(saveReq.request.body.application_email).toBe('bewerbung@acme.example');
      expect(saveReq.request.body.application_email_source_url).toBe('https://acme.example/karriere');
      saveReq.flush({ ...job, id: 1, created_at: new Date().toISOString(), is_processed: false });
    });

    it('Loading: the action is disabled and a spinner shows while the request is in flight', () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      clickFindEmail();

      const button = findEmailButton().nativeElement as HTMLButtonElement;
      expect(button.disabled).toBeTrue();
      expect(button.querySelector('mat-progress-spinner')).toBeTruthy();

      flushLookup({ status: 'not-found' });

      expect((findEmailButton().nativeElement as HTMLButtonElement).disabled).toBeFalse();
    });
  });
});
