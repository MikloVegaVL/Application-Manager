import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { SentEmailService } from './sent-email.service';
import { SentEmail } from '../models/sent-email.model';
import { environment } from '../../../environments/environment';

describe('SentEmailService', () => {
  let service: SentEmailService;
  let httpMock: HttpTestingController;

  const baseUrl = `${environment.apiBaseUrl}/sent-emails`;

  const sampleEntry: SentEmail = {
    id: 1,
    application_id: 1,
    job_offer_id: 1,
    company: 'Acme GmbH',
    job_title: 'Backend Engineer',
    source_platform: 'linkedin',
    recipient_email: 'recruiter@example.com',
    sent_at: '2026-09-01T10:00:00Z',
    sender_email: 'absender@example.com',
    subject: 'Bewerbung',
    attachment_filename: 'lebenslauf.pdf',
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });

    service = TestBed.inject(SentEmailService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('list() requests the base URL with only the supplied filter params', () => {
    let received: SentEmail[] | undefined;
    service.list({ company: 'Acme GmbH' }).subscribe((entries) => (received = entries));

    const req = httpMock.expectOne((request) => request.url === baseUrl);
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('company')).toBe('Acme GmbH');
    expect(req.request.params.has('sender_email')).toBe(false);
    expect(req.request.params.has('date_from')).toBe(false);
    expect(req.request.params.has('date_to')).toBe(false);

    req.flush([sampleEntry]);
    expect(received).toEqual([sampleEntry]);
  });

  it('list() omits all params when the filter is empty', () => {
    service.list({}).subscribe();

    const req = httpMock.expectOne((request) => request.url === baseUrl);
    expect(req.request.params.keys().length).toBe(0);
    req.flush([]);
  });

  it('exportCurrent() requests the export URL with the same filter params and blob response type', () => {
    let received: unknown;
    service
      .exportCurrent({ company: 'Acme GmbH', date_from: '2026-09-01', date_to: '2026-09-30' })
      .subscribe((response) => (received = response));

    const req = httpMock.expectOne((request) => request.url === `${baseUrl}/export`);
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('company')).toBe('Acme GmbH');
    expect(req.request.params.get('date_from')).toBe('2026-09-01');
    expect(req.request.params.get('date_to')).toBe('2026-09-30');
    expect(req.request.responseType).toBe('blob');

    const blob = new Blob(['%PDF-1.4'], { type: 'application/pdf' });
    req.flush(blob);
    expect(received).toBeTruthy();
  });

  it('exportAll() requests the export-all URL with no filter params', () => {
    service.exportAll().subscribe();

    const req = httpMock.expectOne((request) => request.url === `${baseUrl}/export/all`);
    expect(req.request.method).toBe('GET');
    expect(req.request.params.keys().length).toBe(0);
    expect(req.request.responseType).toBe('blob');

    req.flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
  });
});
