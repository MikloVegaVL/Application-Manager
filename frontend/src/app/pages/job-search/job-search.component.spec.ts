import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { JobSearchComponent } from './job-search.component';
import { JobSearchResponse } from '../../core/models/job-offer.model';
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

  it('a full request failure still shows the error message and clears results', () => {
    triggerSearch();
    const req = httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/jobs/search`);
    req.flush('server error', { status: 500, statusText: 'Internal Server Error' });
    fixture.detectChanges();

    expect(component['errorMessage']()).not.toBeNull();
    expect(component['results']().length).toBe(0);
    expect(component['sourceStatuses']().length).toBe(0);
  });
});
