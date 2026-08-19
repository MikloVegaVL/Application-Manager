import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { ApplicationsComponent } from './applications.component';
import { Application } from '../../core/models/application.model';
import { environment } from '../../../environments/environment';

describe('ApplicationsComponent', () => {
  let component: ApplicationsComponent;
  let fixture: ComponentFixture<ApplicationsComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ApplicationsComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(ApplicationsComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
  });

  function flushList(applications: Application[]): void {
    const req = httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/applications`);
    req.flush(applications);
    fixture.detectChanges();
  }

  const sampleApplication: Application = {
    id: 1,
    job_offer_id: 42,
    cover_letter_text: 'Sehr geehrte Damen und Herren...',
    status: 'draft',
    sent_at: null,
    created_at: new Date().toISOString(),
    job_offer: {
      id: 42,
      title: 'Backend Engineer',
      company: 'Acme GmbH',
      location: 'Berlin',
      source_url: 'https://example.com/job/1',
      description_text: null,
      source_platform: 'arbeitsagentur',
      created_at: new Date().toISOString(),
      is_processed: true,
    },
  };

  it('should create', () => {
    flushList([]);
    expect(component).toBeTruthy();
  });

  it('Regression: fetches applications on init and renders the saved job offer instead of staying empty', () => {
    flushList([
      {
        id: 1,
        job_offer_id: 42,
        cover_letter_text: 'Sehr geehrte Damen und Herren...',
        status: 'draft',
        sent_at: null,
        created_at: new Date().toISOString(),
        job_offer: {
          id: 42,
          title: 'Backend Engineer',
          company: 'Acme GmbH',
          location: 'Berlin',
          source_url: 'https://example.com/job/1',
          description_text: null,
          source_platform: 'arbeitsagentur',
          created_at: new Date().toISOString(),
          is_processed: true,
        },
      },
    ]);

    expect(component['applications']().length).toBe(1);
    expect(component['loading']()).toBeFalse();
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Backend Engineer');
    expect(text).toContain('Acme GmbH');
  });

  it('shows an empty-state message when no applications exist yet', () => {
    flushList([]);

    expect(component['applications']().length).toBe(0);
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Noch keine Bewerbungen vorhanden');
  });

  it('shows an error message when the request fails', () => {
    const req = httpMock.expectOne((request) => request.url === `${environment.apiBaseUrl}/applications`);
    req.flush('server error', { status: 500, statusText: 'Internal Server Error' });
    fixture.detectChanges();

    expect(component['errorMessage']()).not.toBeNull();
    expect(component['applications']().length).toBe(0);
  });

  it('deletes an application after confirmation and removes it from the list', () => {
    spyOn(window, 'confirm').and.returnValue(true);
    flushList([sampleApplication]);

    component.onDelete(sampleApplication);

    const deleteReq = httpMock.expectOne(
      (request) => request.url === `${environment.apiBaseUrl}/applications/1` && request.method === 'DELETE',
    );
    deleteReq.flush(null, { status: 204, statusText: 'No Content' });

    expect(component['applications']().length).toBe(0);
    expect(component['deletingId']()).toBeNull();
  });

  it('does not delete when the user cancels the confirmation', () => {
    spyOn(window, 'confirm').and.returnValue(false);
    flushList([sampleApplication]);

    component.onDelete(sampleApplication);

    httpMock.expectNone((request) => request.url === `${environment.apiBaseUrl}/applications/1`);
    expect(component['applications']().length).toBe(1);
  });

  it('keeps the application in the list and shows an error when deletion fails', () => {
    spyOn(window, 'confirm').and.returnValue(true);
    flushList([sampleApplication]);

    component.onDelete(sampleApplication);

    const deleteReq = httpMock.expectOne(
      (request) => request.url === `${environment.apiBaseUrl}/applications/1` && request.method === 'DELETE',
    );
    deleteReq.flush('server error', { status: 500, statusText: 'Internal Server Error' });

    expect(component['applications']().length).toBe(1);
    expect(component['deletingId']()).toBeNull();
  });
});
