import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { SentEmailsComponent } from './sent-emails.component';
import { SentEmail } from '../../core/models/sent-email.model';
import { environment } from '../../../environments/environment';

describe('SentEmailsComponent', () => {
  let component: SentEmailsComponent;
  let fixture: ComponentFixture<SentEmailsComponent>;
  let httpMock: HttpTestingController;

  const baseUrl = `${environment.apiBaseUrl}/sent-emails`;

  const sampleEntry: SentEmail = {
    id: 1,
    application_id: 1,
    job_offer_id: 42,
    ad_url: 'https://example.com/job/42',
    outcome: 'rejection',
    company: 'Acme GmbH',
    job_title: 'Backend Engineer',
    source_platform: 'linkedin',
    recipient_email: 'recruiter@example.com',
    sent_at: new Date('2026-09-01T10:00:00Z').toISOString(),
    sender_email: 'absender@example.com',
    subject: 'Bewerbung',
    attachment_filenames: ['lebenslauf.pdf', 'zeugnis.pdf'],
  };

  const backfilledEntry: SentEmail = {
    id: 2,
    application_id: null,
    job_offer_id: null,
    ad_url: null,
    outcome: 'pending',
    company: 'Globex',
    job_title: 'QA Engineer',
    source_platform: null,
    recipient_email: 'jobs@globex.example',
    sent_at: new Date('2026-08-01T10:00:00Z').toISOString(),
    sender_email: null,
    subject: null,
    attachment_filenames: [],
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SentEmailsComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(SentEmailsComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
  });

  function flushList(entries: SentEmail[]): void {
    const req = httpMock.expectOne((request) => request.url === baseUrl && request.method === 'GET');
    req.flush(entries);
    fixture.detectChanges();
  }

  it('should create', () => {
    flushList([]);
    expect(component).toBeTruthy();
  });

  it('renders the list returned by the service', () => {
    flushList([sampleEntry]);

    expect(component['entries']().length).toBe(1);
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Acme GmbH');
    expect(text).toContain('recruiter@example.com');
  });

  it('re-requests the list with the new filter when a filter control changes', () => {
    flushList([sampleEntry]);

    component['companyFilter'].set('Acme');
    component['onFilterChange']();

    const req = httpMock.expectOne((request) => request.url === baseUrl && request.method === 'GET');
    expect(req.request.params.get('company')).toBe('Acme');
    req.flush([sampleEntry]);
  });

  it('links a row to its application when job_offer_id is present', () => {
    flushList([sampleEntry]);

    const link: HTMLAnchorElement | null = fixture.nativeElement.querySelector('a[href="/editor/42"]');
    expect(link).not.toBeNull();
  });

  it('renders no link when job_offer_id is null (deleted application)', () => {
    flushList([backfilledEntry]);

    const link: HTMLAnchorElement | null = fixture.nativeElement.querySelector('a[href^="/editor"]');
    expect(link).toBeNull();
  });

  it('renders a delete control on each row', () => {
    flushList([sampleEntry]);

    const buttons: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('table button'));
    expect(buttons.length).toBe(1);
  });

  it('renders every attachment filename, not just the CV', () => {
    flushList([sampleEntry]);

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('lebenslauf.pdf');
    expect(text).toContain('zeugnis.pdf');
  });

  it('lets table cells wrap instead of clipping long content (no overflow hiding)', () => {
    flushList([sampleEntry]);

    // Material's `.mdc-data-table__table` sets `white-space: nowrap`; the
    // component overrides it under `.sent-emails__table th, td`. jsdom cannot
    // resolve component SCSS into `getComputedStyle`, so assert the wrapping
    // class the override is scoped to is applied to the rendered table/cells.
    const table = fixture.nativeElement.querySelector('table.sent-emails__table') as HTMLElement | null;
    expect(table).not.toBeNull();
    expect(table!.querySelector('td.mat-mdc-cell')).not.toBeNull();
  });

  it('Covers AE5: a backfilled entry renders its unknown fields as an em dash, not blank or "null"', () => {
    flushList([backfilledEntry]);

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('—');
    expect(text).not.toContain('null');
  });

  it('shows "No sent emails yet" when the log has zero total entries', () => {
    flushList([]);

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('No sent emails yet');
  });

  it('shows "No entries match these filters" when a filter matches nothing', () => {
    flushList([sampleEntry]);

    component['companyFilter'].set('Nonexistent');
    component['onFilterChange']();
    const req = httpMock.expectOne((request) => request.url === baseUrl && request.method === 'GET');
    req.flush([]);
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('No entries match these filters');
  });

  it('exports the current view, disabling the button while in flight', () => {
    flushList([sampleEntry]);

    component['exportCurrent']();
    expect(component['exportingCurrent']()).toBeTrue();

    const req = httpMock.expectOne(
      (request) => request.url === `${baseUrl}/export` && request.method === 'GET',
    );
    req.flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));

    expect(component['exportingCurrent']()).toBeFalse();
  });

  it('ignores a second export click while the first request is still in flight', () => {
    flushList([sampleEntry]);

    component['exportCurrent']();
    component['exportCurrent']();

    httpMock.expectOne((request) => request.url === `${baseUrl}/export` && request.method === 'GET').flush(
      new Blob(['%PDF-1.4'], { type: 'application/pdf' }),
    );
  });

  it('exports the full log regardless of the active filter', () => {
    flushList([sampleEntry]);
    component['companyFilter'].set('Acme');

    component['exportAll']();

    const req = httpMock.expectOne(
      (request) => request.url === `${baseUrl}/export/all` && request.method === 'GET',
    );
    expect(req.request.params.keys().length).toBe(0);
    req.flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));

    expect(component['exportingAll']()).toBeFalse();
  });

  it('surfaces an error message when export fails', () => {
    flushList([sampleEntry]);

    component['exportCurrent']();
    const req = httpMock.expectOne((request) => request.url === `${baseUrl}/export`);
    // `responseType: 'blob'` requires a real Blob body - a string body throws
    // in Angular's test backend before the error path can be exercised.
    req.flush(new Blob(['server error'], { type: 'text/plain' }), {
      status: 500,
      statusText: 'Internal Server Error',
    });

    expect(component['exportError']()).not.toBeNull();
    expect(component['exportingCurrent']()).toBeFalse();
  });

  it('renders the Offer/Rejection/Pending label for each row from entry.outcome', () => {
    flushList([sampleEntry, backfilledEntry]);

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Rejection');
    expect(text).toContain('Pending');
  });

  it('Covers AE5: selecting an Outcome filter re-requests the list with that outcome param', () => {
    flushList([sampleEntry]);

    component['outcomeFilter'].set('rejection');
    component['onFilterChange']();

    const req = httpMock.expectOne((request) => request.url === baseUrl && request.method === 'GET');
    expect(req.request.params.get('outcome')).toBe('rejection');
    req.flush([sampleEntry]);
  });

  it('treats an active Outcome filter as an active filter for hasActiveFilter()', () => {
    flushList([sampleEntry]);

    expect(component['hasActiveFilter']()).toBeFalse();
    component['outcomeFilter'].set('pending');
    expect(component['hasActiveFilter']()).toBeTrue();
  });

  it('shows an error message when the list request fails', () => {
    const req = httpMock.expectOne((request) => request.url === baseUrl && request.method === 'GET');
    req.flush('server error', { status: 500, statusText: 'Internal Server Error' });
    fixture.detectChanges();

    expect(component['errorMessage']()).not.toBeNull();
    expect(component['entries']().length).toBe(0);
  });
});
