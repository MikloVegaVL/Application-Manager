import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { JobService } from './job.service';
import {
  ApplicationEmailLookupResult,
  JobSearchResponse,
} from '../models/job-offer.model';
import { environment } from '../../../environments/environment';

describe('JobService', () => {
  let service: JobService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });

    service = TestBed.inject(JobService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('passes a JobSearchResponse (results + sources) straight through', () => {
    const mockResponse: JobSearchResponse = {
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
        { platform: 'linkedin', status: 'unavailable', reason: 'timeout' },
        { platform: 'xing', status: 'unavailable', reason: 'empty' },
      ],
    };

    let received: JobSearchResponse | undefined;
    service.searchJobs('Angular', 'Berlin').subscribe((response) => (received = response));

    const req = httpMock.expectOne(
      (request) => request.url === `${environment.apiBaseUrl}/jobs/search`,
    );
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('keywords')).toBe('Angular');
    expect(req.request.params.get('location')).toBe('Berlin');

    req.flush(mockResponse);

    expect(received).toEqual(mockResponse);
    expect(received?.sources.length).toBe(3);
  });

  it('Covers R1: findApplicationEmail POSTs the job payload and maps the result', () => {
    const payload = {
      source_url: 'https://example.com/job/1',
      company: 'Acme',
    };
    const mockResult: ApplicationEmailLookupResult = {
      status: 'found',
      email: 'bewerbung@acme.example',
      source_url: 'https://acme.example/karriere',
    };

    let received: ApplicationEmailLookupResult | undefined;
    service.findApplicationEmail(payload).subscribe((result) => (received = result));

    const req = httpMock.expectOne(
      (request) => request.url === `${environment.apiBaseUrl}/jobs/application-email-lookup`,
    );
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(payload);

    req.flush(mockResult);

    expect(received).toEqual(mockResult);
  });
});
