import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { JobSearchStateService } from './job-search-state.service';
import {
  ApplicationEmailLookupRequest,
  ApplicationEmailLookupResult,
} from '../models/job-offer.model';
import { environment } from '../../../environments/environment';

describe('JobSearchStateService', () => {
  let service: JobSearchStateService;
  let httpMock: HttpTestingController;

  const payload: ApplicationEmailLookupRequest = {
    source_url: 'https://example.com/job/1',
    company: 'Acme',
  };

  const lookupUrl = `${environment.apiBaseUrl}/jobs/application-email-lookup`;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });

    service = TestBed.inject(JobSearchStateService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('Covers R1: runs the lookup and caches the result by source_url', () => {
    const result: ApplicationEmailLookupResult = {
      status: 'found',
      email: 'bewerbung@acme.example',
      source_url: 'https://acme.example/karriere',
    };

    let received: ApplicationEmailLookupResult | undefined;
    service.lookupApplicationEmail(payload).subscribe((value) => (received = value));

    const req = httpMock.expectOne((request) => request.url === lookupUrl);
    expect(req.request.method).toBe('POST');
    req.flush(result);

    expect(received).toEqual(result);
    expect(service.applicationEmailResult(payload.source_url)).toEqual(result);
  });

  it('returns a cached result for a source_url without a second request', () => {
    const result: ApplicationEmailLookupResult = {
      status: 'found',
      email: 'bewerbung@acme.example',
      source_url: 'https://acme.example/karriere',
    };
    service.cacheApplicationEmailResult(payload.source_url, result);

    let received: ApplicationEmailLookupResult | undefined;
    service.lookupApplicationEmail(payload).subscribe((value) => (received = value));

    httpMock.expectNone((request) => request.url === lookupUrl);
    expect(received).toEqual(result);
  });

  it('Covers R11: force re-runs the lookup even when a result is cached', () => {
    const cached: ApplicationEmailLookupResult = { status: 'not-found' };
    const refreshed: ApplicationEmailLookupResult = {
      status: 'found',
      email: 'jobs@acme.example',
      source_url: 'https://acme.example/jobs',
    };
    service.cacheApplicationEmailResult(payload.source_url, cached);

    let received: ApplicationEmailLookupResult | undefined;
    service
      .lookupApplicationEmail(payload, { force: true })
      .subscribe((value) => (received = value));

    const req = httpMock.expectOne((request) => request.url === lookupUrl);
    req.flush(refreshed);

    expect(received).toEqual(refreshed);
    expect(service.applicationEmailResult(payload.source_url)).toEqual(refreshed);
  });

  it('clearResults() also clears the cached application-email results', () => {
    service.cacheApplicationEmailResult(payload.source_url, { status: 'found', email: 'a@b.c' });
    expect(service.applicationEmailResult(payload.source_url)).not.toBeNull();

    service.clearResults();

    expect(service.applicationEmailResult(payload.source_url)).toBeNull();
  });

  it('clearResults() resets the applied-hidden count', () => {
    service.appliedHiddenCount.set(3);

    service.clearResults();

    expect(service.appliedHiddenCount()).toBe(0);
  });
});
