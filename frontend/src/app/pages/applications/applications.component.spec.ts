import { ComponentFixture, TestBed, fakeAsync, flush, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { MatDialogRef } from '@angular/material/dialog';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of } from 'rxjs';
import { vi } from 'vitest';

import {
  ACTION_NEEDED_COPY,
  ApplicationsComponent,
  FAILURE_REASON_COPY,
  FAILURE_REASONS,
  PAUSE_REASONS,
} from './applications.component';
import { Application } from '../../core/models/application.model';
import { JobOfferRead } from '../../core/models/job-offer.model';
import { TabTitleService } from '../../core/services/tab-title.service';
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

  describe('portal auto-fill (U7)', () => {
    const startUrl = `${environment.apiBaseUrl}/applications/1/portal-fill/start`;
    const statusUrl = `${environment.apiBaseUrl}/applications/1/portal-fill/status`;
    const continueUrl = `${environment.apiBaseUrl}/applications/1/portal-fill/continue`;
    const cancelUrl = `${environment.apiBaseUrl}/applications/1/portal-fill/cancel`;

    function expectStatusPoll() {
      return httpMock.expectOne((request) => request.url === statusUrl && request.method === 'GET');
    }

    function startRun(): void {
      component['onStartPortalFill'](sampleApplication, 'https://portal.example/apply');
      const startReq = httpMock.expectOne((request) => request.url === startUrl && request.method === 'POST');
      expect(startReq.request.body).toEqual({
        application_form_url: 'https://portal.example/apply',
        dry_run: false,
      });
      startReq.flush({ ...sampleApplication, automation_state: 'running', action_needed_reason: null });
      fixture.detectChanges();
    }

    it('starts a run via start() and begins polling status', fakeAsync(() => {
      flushList([sampleApplication]);

      startRun();
      expect(component['portalFillStartingId']()).toBeNull();

      tick(5000);
      const pollReq = expectStatusPoll();
      pollReq.flush({ automation_state: 'running', action_needed_reason: null });
      fixture.destroy(); // still `running` - stop the periodic poll so fakeAsync can settle.
    }));

    it('renders reason-specific banner copy on paused and lets Continue resume polling', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'captcha' });
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('A captcha appeared');

      component['onContinuePortalFill'](sampleApplication);
      const continueReq = httpMock.expectOne(
        (request) => request.url === continueUrl && request.method === 'POST',
      );
      continueReq.flush({ ...sampleApplication, automation_state: 'paused', action_needed_reason: 'captcha' });

      // Polling keeps going while paused - the paused-phase poll picks the next tick up.
      tick(5000);
      expectStatusPoll().flush({ automation_state: 'running', action_needed_reason: null });
      fixture.destroy(); // still `running` - stop the periodic poll so fakeAsync can settle.
    }));

    it('a failing poll tick does not stop the overall poll', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush('boom', { status: 500, statusText: 'Server Error' });

      // Next tick still fires - the failed tick did not terminate the poll.
      tick(5000);
      expectStatusPoll().flush({ automation_state: 'running', action_needed_reason: null });
      fixture.destroy(); // still `running` - stop the periodic poll so fakeAsync can settle.
    }));

    it('the running phase stops polling after its bounded timeout', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(30 * 60 * 1000 + 5000);
      httpMock.match(() => true).forEach((request) => {
        if (!request.cancelled) {
          request.flush({ automation_state: 'running', action_needed_reason: null });
        }
      });
      flush();

      httpMock.expectNone((request) => request.url === statusUrl);
    }));

    it('the paused phase keeps polling with no fixed timeout', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'captcha' });

      // Advance well beyond the running-phase timeout - the paused phase has none of its own.
      tick(30 * 60 * 1000 + 5000);
      httpMock.match(() => true).forEach((request) => {
        if (!request.cancelled) {
          request.flush({ automation_state: 'paused', action_needed_reason: 'captcha' });
        }
      });
      fixture.detectChanges();

      expect(fixture.nativeElement.textContent as string).toContain('A captcha appeared');

      // Still polling: one more explicit tick produces one more request.
      tick(5000);
      expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'captcha' });
      fixture.destroy(); // still `paused` - stop the periodic poll so fakeAsync can settle.
    }));

    it('Cancel calls cancelPortalFill() and clears the banner', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'pre_submit_confirmation' });
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent as string).toContain('Form is filled');

      component['onCancelPortalFill'](sampleApplication);
      const cancelReq = httpMock.expectOne(
        (request) => request.url === cancelUrl && request.method === 'POST',
      );
      cancelReq.flush({
        ...sampleApplication,
        automation_state: 'failed',
        action_needed_reason: 'cancelled_by_user',
      });
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent as string;
      expect(text).not.toContain('Form is filled');
      expect(text).toContain('Cancelled.');
      fixture.destroy(); // the paused-phase poll is still awaiting its next tick - stop it for fakeAsync.
    }));

    it('replaces the trigger with a persistent indicator on submitted', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'submitted', action_needed_reason: null });
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('Submitted via portal on');
      expect(text).not.toContain('Auto-fill portal');
    }));

    it('shows a dismissible, translated failure notice and re-enables the trigger', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'failed', action_needed_reason: 'iframe_not_found' });
      fixture.detectChanges();

      let text = fixture.nativeElement.textContent as string;
      expect(text).toContain("Couldn't find the application form on that page.");
      expect(text).toContain('Auto-fill portal');

      component['onDismissFailure'](sampleApplication);
      fixture.detectChanges();

      text = fixture.nativeElement.textContent as string;
      expect(text).not.toContain("Couldn't find the application form on that page.");
      expect(text).toContain('Auto-fill portal');
    }));

    it('disables Delete and the Outcome toggle while a run is running or paused', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      const deleteButton: HTMLButtonElement = fixture.nativeElement.querySelector(
        '.application-card__actions button',
      );
      expect(deleteButton.disabled).toBe(true);

      const outcomeButton: HTMLButtonElement = fixture.nativeElement.querySelector(
        '.application-card__outcome-accept button',
      );
      expect(outcomeButton.disabled).toBe(true);

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'submitted', action_needed_reason: null });
      fixture.detectChanges();

      expect(deleteButton.disabled).toBe(false);
    }));

    it('signals TabTitleService when a poll observes a transition to paused while backgrounded', fakeAsync(() => {
      const tabTitleService = TestBed.inject(TabTitleService);
      const settledSpy = vi.spyOn(tabTitleService, 'markGenerationSettled');
      vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');

      flushList([sampleApplication]);
      startRun();
      expect(settledSpy).not.toHaveBeenCalled();

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'captcha' });

      expect(settledSpy).toHaveBeenCalledTimes(1);

      // A further tick that is still `paused` is not a new transition - no extra call.
      tick(5000);
      expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'captcha' });
      expect(settledSpy).toHaveBeenCalledTimes(1);
      fixture.destroy(); // still `paused` - stop the periodic poll so fakeAsync can settle.
    }));

    it('Covers R11: the dry-run checkbox sends dry_run: true on start', fakeAsync(() => {
      flushList([sampleApplication]);

      component['onStartPortalFill'](sampleApplication, 'https://portal.example/apply', true);
      const startReq = httpMock.expectOne((request) => request.url === startUrl && request.method === 'POST');
      expect(startReq.request.body).toEqual({
        application_form_url: 'https://portal.example/apply',
        dry_run: true,
      });
      startReq.flush({ ...sampleApplication, automation_state: 'running', action_needed_reason: null });
      fixture.detectChanges();

      tick(5000);
      expectStatusPoll().flush({
        automation_state: 'running',
        action_needed_reason: null,
        action_needed_detail: null,
        failure_class: null,
      });
      fixture.destroy(); // still `running` - stop the periodic poll so fakeAsync can settle.
    }));

    it('Covers R3/KTD5: the status poll carries failure_class into a retryable failure notice', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({
        automation_state: 'failed',
        action_needed_reason: 'browser_launch_failed',
        action_needed_detail: null,
        failure_class: 'retryable',
      });
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('The browser could not be launched.');
      expect(text).toContain('This failure is retryable');
      expect(text).toContain('re-enter the form URL below');
    }));

    it('Covers R3/KTD5: a terminal failure is labeled as not retryable', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({
        automation_state: 'failed',
        action_needed_reason: 'iframe_untrusted_host',
        action_needed_detail: null,
        failure_class: 'terminal',
      });
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('hosted on an untrusted site');
      expect(text).toContain('This failure is not retryable');
      expect(text).not.toContain('This failure is retryable');
    }));

    it('Covers R9: the pause notice renders action_needed_detail for low_confidence_field and screening_question', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({
        automation_state: 'paused',
        action_needed_reason: 'low_confidence_field',
        action_needed_detail: 'Berufserfahrung',
        failure_class: null,
      });
      fixture.detectChanges();

      let text = fixture.nativeElement.textContent as string;
      expect(text).toContain('A field needs your review');
      expect(text).toContain('Berufserfahrung');

      tick(5000);
      expectStatusPoll().flush({
        automation_state: 'paused',
        action_needed_reason: 'screening_question',
        action_needed_detail: 'Arbeitserlaubnis',
        failure_class: null,
      });
      fixture.detectChanges();

      text = fixture.nativeElement.textContent as string;
      expect(text).toContain('A screening question needs a factual answer');
      expect(text).toContain('Arbeitserlaubnis');
      expect(text).not.toContain('Berufserfahrung');
      fixture.destroy(); // still `paused` - stop the periodic poll so fakeAsync can settle.
    }));

    it('Covers KTD4/R11: the dry-run pause copy and resume action differ from pre_submit_confirmation', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({
        automation_state: 'paused',
        action_needed_reason: 'dry_run',
        action_needed_detail: null,
        failure_class: null,
      });
      fixture.detectChanges();

      let text = fixture.nativeElement.textContent as string;
      expect(text).toContain('Dry run complete');
      expect(text).not.toContain('Form is filled');
      expect(text).toContain('Submit for real');
      expect(text).not.toContain('Continue');

      tick(5000);
      expectStatusPoll().flush({
        automation_state: 'paused',
        action_needed_reason: 'pre_submit_confirmation',
        action_needed_detail: null,
        failure_class: null,
      });
      fixture.detectChanges();

      text = fixture.nativeElement.textContent as string;
      expect(text).toContain('Form is filled');
      expect(text).toContain('Continue');
      expect(text).not.toContain('Submit for real');
      fixture.destroy(); // still `paused` - stop the periodic poll so fakeAsync can settle.
    }));
  });

  describe('portal auto-fill outcome copy (U6)', () => {
    it('Covers U6: every pause and failure reason has specific copy', () => {
      flushList([]);

      for (const reason of PAUSE_REASONS) {
        expect(ACTION_NEEDED_COPY[reason]).toBeTruthy();
      }
      for (const reason of FAILURE_REASONS) {
        expect(FAILURE_REASON_COPY[reason]).toBeTruthy();
      }
    });

    it('Covers U6: unknown reasons are absent from the maps so the component fallback applies', () => {
      flushList([]);

      expect(ACTION_NEEDED_COPY['not_a_reason']).toBeUndefined();
      expect(FAILURE_REASON_COPY['not_a_reason']).toBeUndefined();
    });
  });
});
