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
import {
  cleanupCompactCardOverlays,
  findCompactCardMenuItem,
  openCompactCardMenu,
} from '../../shared/compact-card/compact-card-test-helpers';
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
    cleanupCompactCardOverlays();
  });

  /** Opens the compact card's `⋮` menu (single-card fixtures only). */
  const openCardMenu = () => openCompactCardMenu(fixture);

  const cardMenuItemByText = findCompactCardMenuItem;

  function cardMenuDetailRowText(): string {
    return Array.from(document.querySelectorAll('.compact-card__menu-detail-row'))
      .map((row) => row.textContent ?? '')
      .join(' ');
  }

  async function settle(): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  /** Opens the menu, clicks the item whose text includes `text`, and settles -
   * the menu is expected closed beforehand (it auto-closes on selection, so
   * chaining calls of this is safe). */
  async function clickCardMenuItem(text: string): Promise<void> {
    await openCardMenu();
    const item = cardMenuItemByText(text);
    if (!item) {
      throw new Error(`Menu item containing "${text}" not found`);
    }
    item.click();
    await settle();
  }

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

  describe('recipient email on the result card (U4: rendered as a ⋮ menu detail row)', () => {
    it('shows the recipient email extracted from the job description as a menu detail row', async () => {
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

      await openCardMenu();
      expect(cardMenuDetailRowText()).toContain('bewerbung@acme.example');
      // extractEmail() already found an address - the "Find email" action
      // must not offer to look one up (R8: gating unchanged).
      expect(cardMenuItemByText('Find email')).toBeNull();
    });

    it('shows no recipient detail row and offers "Find email" when the description has no email address', async () => {
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

      await openCardMenu();
      expect(cardMenuDetailRowText()).toBe('');
      expect(cardMenuItemByText('Find email')).toBeTruthy();
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

  describe('application-email lookup action (U4: "Find email"/"Find email again" in the ⋮ menu)', () => {
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

    function chipsText(): string {
      return Array.from(fixture.nativeElement.querySelectorAll('.compact-card__chip'))
        .map((chip) => chip.textContent)
        .join(' ');
    }

    function flushLookup(result: ApplicationEmailLookupResult) {
      const req = httpMock.expectOne((request) => request.url === lookupUrl);
      expect(req.request.method).toBe('POST');
      req.flush(result);
      fixture.detectChanges();
      return req;
    }

    it('Covers R1, R7, R11: renders the returned address as a detail row and its source link as a real anchor', async () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      await openCardMenu();
      const findEmailItem = cardMenuItemByText('Find email');
      expect(findEmailItem).toBeTruthy();
      (findEmailItem as HTMLElement).click();
      await settle();

      flushLookup({
        status: 'found',
        email: 'bewerbung@acme.example',
        source_url: 'https://acme.example/karriere',
      });

      await openCardMenu();
      expect(cardMenuDetailRowText()).toContain('bewerbung@acme.example');

      const link = cardMenuItemByText('Source of this address') as HTMLAnchorElement;
      expect(link).toBeTruthy();
      expect(link.tagName).toBe('A');
      expect(link.getAttribute('href')).toBe('https://acme.example/karriere');
      expect(link.getAttribute('target')).toBe('_blank');
      expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    });

    it('Covers R2, R12: the "Find email" action is absent when the posting text already yields an address', async () => {
      flushJobSearch('Bitte sende deine Bewerbung an bewerbung@acme.example.');

      await openCardMenu();
      expect(cardMenuItemByText('Find email')).toBeFalsy();
      httpMock.expectNone((request) => request.url === lookupUrl);
    });

    it('Covers R9: a not-found result renders the not-found state as a header chip', async () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      await clickCardMenuItem('Find email');
      flushLookup({ status: 'not-found' });

      const chips = chipsText();
      expect(chips).toContain('No application email found');
      expect(chips).not.toContain("Couldn't reach the employer's site");
    });

    it('Covers R9: a failed result renders the distinct failure copy as a header chip', async () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      await clickCardMenuItem('Find email');
      flushLookup({ status: 'failed' });

      const chips = chipsText();
      expect(chips).toContain("Couldn't reach the employer's site — try again");
      expect(chips).not.toContain('No application email found');
    });

    it('Covers A5: an HTTP error on the lookup maps to the distinct failure copy and re-enables the action', async () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      await clickCardMenuItem('Find email');

      const req = httpMock.expectOne((request) => request.url === lookupUrl);
      req.flush(null, { status: 500, statusText: 'Internal Server Error' });
      fixture.detectChanges();

      const chips = chipsText();
      expect(chips).toContain("Couldn't reach the employer's site — try again");
      expect(chips).not.toContain('No application email found');

      const trigger = fixture.nativeElement.querySelector('.compact-card__menu-trigger') as HTMLButtonElement;
      expect(trigger.disabled).toBeFalse();

      await openCardMenu();
      expect((cardMenuItemByText('Find email') as HTMLButtonElement).disabled).toBeFalse();
    });

    it('Covers R11: a re-run can be triggered after an address is already displayed, even though the item stays (existing gating preserved)', async () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      await clickCardMenuItem('Find email');
      flushLookup({
        status: 'found',
        email: 'bewerbung@acme.example',
        source_url: 'https://acme.example/karriere',
      });

      await openCardMenu();
      const rerunItem = cardMenuItemByText('Find email again');
      expect(rerunItem).toBeTruthy();
      (rerunItem as HTMLElement).click();
      await settle();

      flushLookup({
        status: 'found',
        email: 'jobs@acme.example',
        source_url: 'https://acme.example/jobs',
      });

      await openCardMenu();
      const detailText = cardMenuDetailRowText();
      expect(detailText).toContain('jobs@acme.example');
      expect(detailText).not.toContain('bewerbung@acme.example');
    });

    it('Covers R11: a re-run sends force=true in the lookup payload so the backend re-scrapes', async () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      await clickCardMenuItem('Find email');
      const firstReq = flushLookup({ status: 'not-found' });
      expect(firstReq.request.body.force).toBeFalse();

      await clickCardMenuItem('Find email again');
      const rerunReq = flushLookup({
        status: 'found',
        email: 'jobs@acme.example',
        source_url: 'https://acme.example/jobs',
      });
      expect(rerunReq.request.body.force).toBeTrue();
    });

    it('Covers KTD7/A1: saving after a successful lookup sends the cached address and its source url', async () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      await clickCardMenuItem('Find email');
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

    it('Covers R12: the busy indicator shows and the primary action + ⋮ trigger disable while the lookup is in flight', async () => {
      flushJobSearch('Wir suchen eine Softwareentwicklerin (m/w/d).');
      await openCardMenu();
      const item = cardMenuItemByText('Find email') as HTMLButtonElement;
      item.click();
      fixture.detectChanges();

      const trigger = fixture.nativeElement.querySelector('.compact-card__menu-trigger') as HTMLButtonElement;
      const primaryButton = fixture.nativeElement.querySelector(
        '.compact-card__primary-action',
      ) as HTMLButtonElement;
      expect(trigger.disabled).toBeTrue();
      expect(primaryButton.disabled).toBeTrue();
      expect(fixture.nativeElement.querySelector('.compact-card__busy')).toBeTruthy();

      flushLookup({ status: 'not-found' });

      expect(
        (fixture.nativeElement.querySelector('.compact-card__menu-trigger') as HTMLButtonElement).disabled,
      ).toBeFalse();
      expect(fixture.nativeElement.querySelector('.compact-card__busy')).toBeFalsy();
    });
  });

  describe('compact card layout (U4)', () => {
    function flushSingleJob(overrides: Partial<{ description_text: string | null }> = {}) {
      triggerSearch();
      flushSearch({
        results: [
          {
            title: 'Angular Developer',
            company: 'Acme',
            location: 'Berlin',
            source_url: 'https://example.com/job/1',
            description_text: overrides.description_text ?? 'Bitte sende deine Bewerbung an bewerbung@acme.example.',
            source_platform: 'arbeitsagentur',
          },
        ],
        sources: [{ platform: 'arbeitsagentur', status: 'ok', reason: null }],
      });
      return component['results']()[0];
    }

    it('Covers R5, R6: shows the snippet, source chip and "Generate application" as the sole primary action', () => {
      flushSingleJob();

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('bewerbung@acme.example');
      // The chip uses the friendly source label (sourceLabel()), same as the
      // existing source-filter chips - not the raw platform key.
      expect(text).toContain('Arbeitsagentur');

      const primaryButton = fixture.nativeElement.querySelector(
        '.compact-card__primary-action',
      ) as HTMLButtonElement;
      expect(primaryButton.textContent).toContain('Generate application');
    });

    it('Covers R6, R8: clicking the primary action calls onGenerateApplication unchanged and disables while generating', () => {
      const job = flushSingleJob();
      const router = TestBed.inject(Router);
      spyOn(router, 'navigate').and.resolveTo(true);
      spyOn(component, 'onGenerateApplication').and.callThrough();

      const primaryButton = fixture.nativeElement.querySelector(
        '.compact-card__primary-action',
      ) as HTMLButtonElement;
      primaryButton.click();
      fixture.detectChanges();

      expect(component.onGenerateApplication).toHaveBeenCalledWith(job);
      expect(primaryButton.disabled).toBeTrue();

      httpMock
        .expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/save`)
        .flush({ ...job, id: 3, created_at: new Date().toISOString(), is_processed: false });
    });

    it('Covers R6: selecting "Save job" from the menu calls onSaveJob, removing the card on success (unchanged)', async () => {
      const job = flushSingleJob();
      spyOn(component, 'onSaveJob').and.callThrough();

      await clickCardMenuItem('Save job');

      expect(component.onSaveJob).toHaveBeenCalledWith(job);

      httpMock
        .expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/save`)
        .flush({ ...job, id: 4, created_at: new Date().toISOString(), is_processed: false });

      expect(component['results']().length).toBe(0);
    });

    it('Covers R6: "Open ad" renders as a native anchor to job.source_url, unchanged', async () => {
      const job = flushSingleJob();

      await openCardMenu();
      const link = cardMenuItemByText('Open ad') as HTMLAnchorElement;
      expect(link.tagName).toBe('A');
      expect(link.getAttribute('href')).toBe(job.source_url);
      expect(link.getAttribute('target')).toBe('_blank');
      expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    });
  });
});
