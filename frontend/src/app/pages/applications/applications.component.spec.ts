import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { MatDialogRef } from '@angular/material/dialog';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of } from 'rxjs';

import { ApplicationsComponent } from './applications.component';
import { Application } from '../../core/models/application.model';
import { JobOfferRead } from '../../core/models/job-offer.model';
import {
  AddJobOfferDialogComponent,
  AddJobOfferDialogResult,
} from './add-job-offer-dialog/add-job-offer-dialog.component';
import { environment } from '../../../environments/environment';

/** Ersetzt `MatDialog.open()` durch einen Fake, der sofort mit `result` schließt. */
function spyOnAddJobOfferDialog(
  component: ApplicationsComponent,
  result?: AddJobOfferDialogResult,
): jasmine.Spy {
  const fakeDialogRef = {
    afterClosed: () => of(result),
  } as unknown as MatDialogRef<AddJobOfferDialogComponent, AddJobOfferDialogResult>;
  return spyOn(component['dialog'], 'open').and.returnValue(fakeDialogRef);
}

const manualDialogResult: AddJobOfferDialogResult = {
  title: 'Backend Engineer',
  company: 'Acme GmbH',
  source_url: 'https://acme.example/careers/backend-engineer',
  description_text: 'We are looking for a backend engineer ...',
  application_email: 'jobs@acme.example',
};

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
    sent_to_email: null,
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
        sent_to_email: null,
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
    expect(text).toContain('No applications yet');
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

  it('updates the status via PUT when Zusage/Absage is selected', () => {
    flushList([sampleApplication]);

    component.onStatusChange(sampleApplication, 'accepted');

    const updateReq = httpMock.expectOne(
      (request) => request.url === `${environment.apiBaseUrl}/applications/1` && request.method === 'PUT',
    );
    expect(updateReq.request.body).toEqual({ status: 'accepted' });
    updateReq.flush({ ...sampleApplication, status: 'accepted' });

    expect(component['applications']()[0].status).toBe('accepted');
    expect(component['updatingStatusId']()).toBeNull();
  });

  it('ignores deselecting the outcome toggle (undefined status)', () => {
    flushList([sampleApplication]);

    component.onStatusChange(sampleApplication, undefined);

    httpMock.expectNone((request) => request.method === 'PUT');
    expect(component['updatingStatusId']()).toBeNull();
  });

  it('filters the rendered applications by the selected radio status', () => {
    const acceptedApplication: Application = { ...sampleApplication, id: 2, status: 'accepted' };
    flushList([sampleApplication, acceptedApplication]);

    component.onFilterChange('accepted');
    expect(component['filteredApplications']().length).toBe(1);
    expect(component['filteredApplications']()[0].id).toBe(2);

    component.onFilterChange('draft');
    expect(component['filteredApplications']().length).toBe(1);
    expect(component['filteredApplications']()[0].id).toBe(1);

    component.onFilterChange('all');
    expect(component['filteredApplications']().length).toBe(2);
  });

  it('shows the recipient email on the card once the application was sent', () => {
    const sentApplication: Application = {
      ...sampleApplication,
      status: 'sent',
      sent_at: new Date().toISOString(),
      sent_to_email: 'recruiter@example.com',
    };
    flushList([sentApplication]);

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Sent to');
    expect(text).toContain('recruiter@example.com');
  });

  it('does not show a recipient row before the application was sent', () => {
    flushList([sampleApplication]);

    const text = fixture.nativeElement.textContent as string;
    expect(text).not.toContain('Sent to');
  });

  it('Covers R4, U2: renders the Direct source label for a manually-saved job offer', () => {
    const manualApplication: Application = {
      ...sampleApplication,
      job_offer: { ...sampleApplication.job_offer, source_platform: 'manual' },
    };
    flushList([manualApplication]);

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Direct');
  });

  it('Covers AE1, R5, R7: saves a manually-entered job offer and navigates to its editor', () => {
    flushList([]);
    spyOnAddJobOfferDialog(component, manualDialogResult);
    const router = TestBed.inject(Router);
    const navigateSpy = spyOn(router, 'navigate');

    component.onAddJobOffer();

    const saveReq = httpMock.expectOne(
      (request) => request.url === `${environment.apiBaseUrl}/jobs/save` && request.method === 'POST',
    );
    expect(saveReq.request.body).toEqual(
      jasmine.objectContaining({
        title: 'Backend Engineer',
        company: 'Acme GmbH',
        source_url: 'https://acme.example/careers/backend-engineer',
        location: null,
        source_platform: 'manual',
      }),
    );
    saveReq.flush({
      id: 99,
      title: 'Backend Engineer',
      company: 'Acme GmbH',
      location: null,
      source_url: 'https://acme.example/careers/backend-engineer',
      description_text: 'We are looking for a backend engineer ...',
      source_platform: 'manual',
      application_email: 'jobs@acme.example',
      created_at: new Date().toISOString(),
      is_processed: false,
    } satisfies JobOfferRead);

    expect(navigateSpy).toHaveBeenCalledWith(['/editor', 99]);
  });

  it('Covers AE2, R6: navigates to the existing application on a duplicate reference', () => {
    flushList([]);
    spyOnAddJobOfferDialog(component, manualDialogResult);
    const router = TestBed.inject(Router);
    const navigateSpy = spyOn(router, 'navigate');

    component.onAddJobOffer();

    const saveReq = httpMock.expectOne(
      (request) => request.url === `${environment.apiBaseUrl}/jobs/save`,
    );
    saveReq.flush(
      { detail: { message: 'already saved', job_offer_id: 42 } },
      { status: 409, statusText: 'Conflict' },
    );

    expect(navigateSpy).toHaveBeenCalledWith(['/editor', 42]);
  });

  it('shows a generic error and does not navigate on a non-409 save failure', () => {
    flushList([]);
    spyOnAddJobOfferDialog(component, manualDialogResult);
    const router = TestBed.inject(Router);
    const navigateSpy = spyOn(router, 'navigate');

    component.onAddJobOffer();

    const saveReq = httpMock.expectOne(
      (request) => request.url === `${environment.apiBaseUrl}/jobs/save`,
    );
    saveReq.flush('server error', { status: 500, statusText: 'Internal Server Error' });

    expect(navigateSpy).not.toHaveBeenCalled();
    expect(component['savingNewJobOffer']()).toBeFalse();
  });

  it('makes no save request when the dialog is cancelled', () => {
    flushList([]);
    spyOnAddJobOfferDialog(component, undefined);

    component.onAddJobOffer();

    httpMock.expectNone((request) => request.url === `${environment.apiBaseUrl}/jobs/save`);
    expect(component['savingNewJobOffer']()).toBeFalse();
  });

  it('Covers AE3: saves successfully with only the required fields filled in', () => {
    flushList([]);
    spyOnAddJobOfferDialog(component, {
      title: 'Backend Engineer',
      company: 'Acme GmbH',
      source_url: 'https://acme.example/careers/backend-engineer',
      description_text: '',
      application_email: '',
    });
    const router = TestBed.inject(Router);
    spyOn(router, 'navigate');

    component.onAddJobOffer();

    const saveReq = httpMock.expectOne(
      (request) => request.url === `${environment.apiBaseUrl}/jobs/save`,
    );
    expect(saveReq.request.body).toEqual(
      jasmine.objectContaining({ description_text: null, application_email: null }),
    );
  });

  it('Covers KTD5: reopens the dialog blank rather than pre-filled after a save failure', () => {
    flushList([]);
    const openSpy = spyOnAddJobOfferDialog(component, undefined);

    component.onAddJobOffer();
    component.onAddJobOffer();

    expect(openSpy.calls.count()).toBe(2);
    for (const call of openSpy.calls.all()) {
      expect(call.args[1]?.data).toBeUndefined();
    }
  });
});
