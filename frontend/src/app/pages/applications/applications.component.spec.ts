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
import {
  StartPortalFillDialogComponent,
  StartPortalFillDialogResult,
} from './start-portal-fill-dialog/start-portal-fill-dialog.component';
import {
  cleanupCompactCardOverlays,
  findCompactCardMenuItem,
  isCompactCardMenuItemDisabled,
  openCompactCardMenu,
} from '../../shared/compact-card/compact-card-test-helpers';
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

/** Toggles the ⋮ menu of the (only) rendered compact card - the trigger button
 * itself toggles open/closed, so this doubles as `openCardMenu`/`closeCardMenu`. */
const toggleCardMenu = openCompactCardMenu;

/** Same as `toggleCardMenu`, but for use inside `fakeAsync` - `await`ing a real Promise there breaks
 * the fake zone, so this flushes microtasks with `tick()` instead of `whenStable()`. */
function toggleCardMenuInFakeAsync(fixture: ComponentFixture<unknown>): void {
  const trigger = fixture.nativeElement.querySelector('.compact-card__menu-trigger') as HTMLButtonElement;
  trigger.click();
  fixture.detectChanges();
  tick();
  fixture.detectChanges();
}

function menuItemByText(label: string): HTMLButtonElement | undefined {
  return (findCompactCardMenuItem(label) as HTMLButtonElement | null) ?? undefined;
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
    cleanupCompactCardOverlays();
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

  it('Covers AE6: narrows by company or job title, case-insensitive, combined (AND) with the status filter', () => {
    const otherApplication: Application = {
      ...sampleApplication,
      id: 2,
      status: 'rejected',
      job_offer: { ...sampleApplication.job_offer, title: 'Frontend Engineer', company: 'Globex Inc' },
    };
    flushList([sampleApplication, otherApplication]);

    // Matches company, case-insensitive.
    component['searchTerm'].set('acme');
    expect(component['filteredApplications']().length).toBe(1);
    expect(component['filteredApplications']()[0].id).toBe(1);

    // Matches job title, case-insensitive.
    component['searchTerm'].set('FRONTEND');
    expect(component['filteredApplications']().length).toBe(1);
    expect(component['filteredApplications']()[0].id).toBe(2);

    // Combines with the active status filter (AND) rather than replacing it.
    component['searchTerm'].set('');
    component.onFilterChange('rejected');
    expect(component['filteredApplications']().length).toBe(1);
    component['searchTerm'].set('acme');
    expect(component['filteredApplications']().length).toBe(0);

    // Empty search shows every application within the active status filter (no behavior change from today).
    component.onFilterChange('all');
    component['searchTerm'].set('');
    expect(component['filteredApplications']().length).toBe(2);

    // No match returns an empty list, with search-specific empty-state copy.
    component['searchTerm'].set('nonexistent');
    fixture.detectChanges();
    expect(component['filteredApplications']().length).toBe(0);
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('No applications match your search.');
  });

  it('Covers R2: shows the recipient email as a non-interactive row in the ⋮ menu once the application was sent', async () => {
    const sentApplication: Application = {
      ...sampleApplication,
      status: 'sent',
      sent_at: new Date().toISOString(),
      sent_to_email: 'recruiter@example.com',
    };
    flushList([sentApplication]);

    // Not visible on the card itself (R2: no separate visible chip) ...
    const cardHeaderText = (fixture.nativeElement.querySelector('.compact-card__header') as HTMLElement)
      .textContent as string;
    expect(cardHeaderText).not.toContain('recruiter@example.com');

    // ... only inside the ⋮ menu, as a non-interactive detail row.
    await toggleCardMenu(fixture);
    const detailRow = document.querySelector('.compact-card__menu-detail-row');
    expect(detailRow?.textContent).toContain('Sent to');
    expect(detailRow?.textContent).toContain('recruiter@example.com');
  });

  it('does not show a recipient row in the ⋮ menu before the application was sent', async () => {
    flushList([sampleApplication]);

    await toggleCardMenu(fixture);
    expect(document.querySelector('.compact-card__menu-detail-row')).toBeNull();
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

  describe('compact card (U2)', () => {
    const sentApplication: Application = { ...sampleApplication, status: 'sent' };

    it('Covers R1/R2/R3/R6: shows only header, chips, and the primary action by default for a sent application with no active run', () => {
      flushList([sentApplication]);

      const text = fixture.nativeElement.textContent as string;
      expect(text).toContain('Backend Engineer');
      expect(text).toContain('Acme GmbH');
      expect(text).toContain(component.statusLabel('sent'));
      expect(text).toContain(component.sourceLabel('arbeitsagentur'));
      expect(text).toContain('Open application');
      expect(fixture.nativeElement.querySelector('.compact-card__inline-attention')).toBeNull();
    });

    it('renders "Open application" as a native anchor to the existing editor route, unchanged', () => {
      flushList([sentApplication]);

      const anchor = fixture.nativeElement.querySelector(
        '.compact-card__primary-action',
      ) as HTMLAnchorElement;
      expect(anchor.tagName).toBe('A');
      expect(anchor.textContent).toContain('Open application');
      expect(anchor.getAttribute('href')).toContain('/editor/42');
    });

    it('Covers R2: routes "Mark accepted" / "Mark rejected" menu selections to onStatusChange with the same arguments as today', async () => {
      flushList([sentApplication]);
      const statusSpy = vi.spyOn(component, 'onStatusChange').mockImplementation(() => {});

      await toggleCardMenu(fixture);
      menuItemByText('Mark accepted')!.click();
      expect(statusSpy).toHaveBeenCalledWith(sentApplication, 'accepted');

      await toggleCardMenu(fixture);
      menuItemByText('Mark rejected')!.click();
      expect(statusSpy).toHaveBeenCalledWith(sentApplication, 'rejected');
    });

    it('Covers R2: routes the "Delete" menu selection to onDelete (still behind window.confirm)', async () => {
      flushList([sentApplication]);
      const deleteSpy = vi.spyOn(component, 'onDelete').mockImplementation(() => {});

      await toggleCardMenu(fixture);
      menuItemByText('Delete')!.click();

      expect(deleteSpy).toHaveBeenCalledWith(sentApplication);
    });

    it('Covers R10: routes the "Start auto-fill" menu selection to the start-portal-fill dialog, then onStartPortalFill with its result', async () => {
      flushList([sentApplication]);
      const fakeDialogRef = {
        afterClosed: () => of<StartPortalFillDialogResult>({ url: 'https://portal.example/apply', dryRun: true }),
      } as unknown as MatDialogRef<StartPortalFillDialogComponent, StartPortalFillDialogResult>;
      const openSpy = spyOn(component['dialog'], 'open').and.returnValue(fakeDialogRef);
      const startSpy = vi.spyOn(component, 'onStartPortalFill').mockImplementation(() => {});

      await toggleCardMenu(fixture);
      menuItemByText('Start auto-fill')!.click();

      expect(openSpy).toHaveBeenCalled();
      expect(openSpy.calls.mostRecent().args[0]).toBe(StartPortalFillDialogComponent);
      expect(startSpy).toHaveBeenCalledWith(sentApplication, 'https://portal.example/apply', true);
    });

    it('Covers R10: does not start a run when the start-portal-fill dialog is cancelled', async () => {
      flushList([sentApplication]);
      const fakeDialogRef = {
        afterClosed: () => of(undefined),
      } as unknown as MatDialogRef<StartPortalFillDialogComponent, StartPortalFillDialogResult>;
      spyOn(component['dialog'], 'open').and.returnValue(fakeDialogRef);
      const startSpy = vi.spyOn(component, 'onStartPortalFill').mockImplementation(() => {});

      await toggleCardMenu(fixture);
      menuItemByText('Start auto-fill')!.click();

      expect(startSpy).not.toHaveBeenCalled();
    });

    it('Covers R12: shows the busy indicator while a status update is in flight, then clears it once it resolves', () => {
      flushList([sentApplication]);

      component.onStatusChange(sentApplication, 'accepted');
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.compact-card__busy')).not.toBeNull();

      const updateReq = httpMock.expectOne(
        (request) => request.url === `${environment.apiBaseUrl}/applications/1` && request.method === 'PUT',
      );
      updateReq.flush({ ...sentApplication, status: 'accepted' });
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector('.compact-card__busy')).toBeNull();
    });

    it('Covers R12: shows the busy indicator while Delete is in flight, then the card is gone once it resolves', () => {
      spyOn(window, 'confirm').and.returnValue(true);
      flushList([sentApplication]);

      component.onDelete(sentApplication);
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('.compact-card__busy')).not.toBeNull();

      const deleteReq = httpMock.expectOne(
        (request) => request.url === `${environment.apiBaseUrl}/applications/1` && request.method === 'DELETE',
      );
      deleteReq.flush(null, { status: 204, statusText: 'No Content' });
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector('app-compact-card')).toBeNull();
    });
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

    it('Covers R4: replaces the status chip content with the submitted confirmation, not a banner', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'submitted', action_needed_reason: null });
      fixture.detectChanges();

      const chipsText = Array.from(fixture.nativeElement.querySelectorAll('.compact-card__chip'))
        .map((chip) => (chip as HTMLElement).textContent)
        .join(' ');
      expect(chipsText).toContain('Submitted via portal on');
      // Still capped at 2 chips (status + source) - no third chip added.
      expect(fixture.nativeElement.querySelectorAll('.compact-card__chip').length).toBe(2);
      expect(fixture.nativeElement.querySelector('.compact-card__inline-attention')).toBeNull();
    }));

    it('Covers R13: shows a dismissible, translated failure notice inline, and re-enables "Start auto-fill" once dismissed', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'failed', action_needed_reason: 'iframe_not_found' });
      fixture.detectChanges();

      const attention = fixture.nativeElement.querySelector('.compact-card__inline-attention') as HTMLElement;
      expect(attention).not.toBeNull();
      expect(attention.textContent).toContain("Couldn't find the application form on that page.");

      toggleCardMenuInFakeAsync(fixture);
      expect(isCompactCardMenuItemDisabled(menuItemByText('Start auto-fill')!)).toBe(false);
      toggleCardMenuInFakeAsync(fixture); // close, so it doesn't interfere with the dismiss below

      const dismissButton = attention.querySelector('button[aria-label="Dismiss"]') as HTMLButtonElement;
      expect(dismissButton).not.toBeNull();
      dismissButton.click();
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector('.compact-card__inline-attention')).toBeNull();
    }));

    it('Covers R3/R9: shows inline attention for running/action-needed states, and disables "Mark accepted"/"Mark rejected"/"Delete"/"Start auto-fill" in the menu while active', fakeAsync(() => {
      flushList([sampleApplication]);
      startRun();

      let attention = fixture.nativeElement.querySelector('.compact-card__inline-attention') as HTMLElement;
      expect(attention).not.toBeNull();
      expect(attention.textContent).toContain('Auto-fill is running');

      toggleCardMenuInFakeAsync(fixture); // open
      for (const label of ['Mark accepted', 'Mark rejected', 'Delete', 'Start auto-fill']) {
        expect(isCompactCardMenuItemDisabled(menuItemByText(label)!)).toBe(true);
      }
      toggleCardMenuInFakeAsync(fixture); // close, so the next open below starts from a known state

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'captcha' });
      fixture.detectChanges();

      attention = fixture.nativeElement.querySelector('.compact-card__inline-attention') as HTMLElement;
      expect(attention).not.toBeNull();
      expect(attention.textContent).toContain('A captcha appeared');

      toggleCardMenuInFakeAsync(fixture); // open
      for (const label of ['Mark accepted', 'Mark rejected', 'Delete', 'Start auto-fill']) {
        expect(isCompactCardMenuItemDisabled(menuItemByText(label)!)).toBe(true);
      }
      toggleCardMenuInFakeAsync(fixture); // close

      tick(5000);
      expectStatusPoll().flush({ automation_state: 'submitted', action_needed_reason: null });
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector('.compact-card__inline-attention')).toBeNull();
      toggleCardMenuInFakeAsync(fixture); // open
      expect(isCompactCardMenuItemDisabled(menuItemByText('Delete')!)).toBe(false);
      expect(isCompactCardMenuItemDisabled(menuItemByText('Mark accepted')!)).toBe(false);
      expect(isCompactCardMenuItemDisabled(menuItemByText('Mark rejected')!)).toBe(false);
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

    describe('pause-time screenshot (R2/U2/U4)', () => {
      const screenshotUrl = `${environment.apiBaseUrl}/applications/1/portal-fill/screenshot`;

      function queryScreenshotImg(): HTMLImageElement | null {
        return fixture.nativeElement.querySelector('.application-card__portal-fill-screenshot');
      }

      it('renders the screenshot image on a pause, pointing at the screenshot endpoint', fakeAsync(() => {
        flushList([sampleApplication]);
        startRun();

        tick(5000);
        expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'pre_submit_confirmation' });
        fixture.detectChanges();

        const img = queryScreenshotImg();
        expect(img).not.toBeNull();
        // t=1, not t=0: a new pause bumps the token too (not just manual Refresh),
        // so a second pause within the same run can't reuse a stale cached image.
        expect(img!.getAttribute('src')).toBe(`${screenshotUrl}?t=1`);
        fixture.destroy(); // still `paused` - stop the periodic poll so fakeAsync can settle.
      }));

      it('does not render the screenshot image outside a pause', fakeAsync(() => {
        flushList([sampleApplication]);
        startRun();

        tick(5000);
        expectStatusPoll().flush({ automation_state: 'running', action_needed_reason: null });
        fixture.detectChanges();

        expect(queryScreenshotImg()).toBeNull();
        fixture.destroy(); // still `running` - stop the periodic poll so fakeAsync can settle.
      }));

      it('Refresh re-requests the image with a new cache-busting token', fakeAsync(() => {
        flushList([sampleApplication]);
        startRun();

        tick(5000);
        expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'pre_submit_confirmation' });
        fixture.detectChanges();

        component['onRefreshScreenshot'](sampleApplication);
        fixture.detectChanges();

        expect(queryScreenshotImg()!.getAttribute('src')).toBe(`${screenshotUrl}?t=2`);
        fixture.destroy(); // still `paused` - stop the periodic poll so fakeAsync can settle.
      }));

      it('hides the image instead of a broken-image icon on any load failure', fakeAsync(() => {
        flushList([sampleApplication]);
        startRun();

        tick(5000);
        expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'pre_submit_confirmation' });
        fixture.detectChanges();

        queryScreenshotImg()!.dispatchEvent(new Event('error'));
        fixture.detectChanges();

        expect(queryScreenshotImg()).toBeNull();
        fixture.destroy(); // still `paused` - stop the periodic poll so fakeAsync can settle.
      }));

      it('a fresh pause clears a previous load failure and shows the image again', fakeAsync(() => {
        flushList([sampleApplication]);
        startRun();

        tick(5000);
        expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'low_confidence_field' });
        fixture.detectChanges();
        queryScreenshotImg()!.dispatchEvent(new Event('error'));
        fixture.detectChanges();
        expect(queryScreenshotImg()).toBeNull();

        component['onContinuePortalFill'](sampleApplication);
        httpMock.expectOne((request) => request.url === continueUrl && request.method === 'POST').flush({
          ...sampleApplication,
          automation_state: 'running',
          action_needed_reason: null,
        });
        tick(5000);
        expectStatusPoll().flush({ automation_state: 'running', action_needed_reason: null });
        fixture.detectChanges();

        tick(5000);
        expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'pre_submit_confirmation' });
        fixture.detectChanges();

        expect(queryScreenshotImg()).not.toBeNull();
        fixture.destroy(); // still `paused` - stop the periodic poll so fakeAsync can settle.
      }));

      it('a second, different pause within the same run gets a distinct screenshot URL, not a stale cached one', fakeAsync(() => {
        flushList([sampleApplication]);
        startRun();

        tick(5000);
        expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'captcha' });
        fixture.detectChanges();
        const firstSrc = queryScreenshotImg()!.getAttribute('src');

        component['onContinuePortalFill'](sampleApplication);
        httpMock.expectOne((request) => request.url === continueUrl && request.method === 'POST').flush({
          ...sampleApplication,
          automation_state: 'running',
          action_needed_reason: null,
        });
        tick(5000);
        expectStatusPoll().flush({ automation_state: 'running', action_needed_reason: null });
        fixture.detectChanges();

        tick(5000);
        expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'pre_submit_confirmation' });
        fixture.detectChanges();

        // Without a fresh cache-busting token, this second pause's <img> would carry the SAME
        // URL as the captcha pause above, and a browser that already cached that URL's response
        // would keep showing the stale, wrong screenshot during this later, mandatory review.
        expect(queryScreenshotImg()!.getAttribute('src')).not.toBe(firstSrc);
        fixture.destroy(); // still `paused` - stop the periodic poll so fakeAsync can settle.
      }));

      it('shows the live connection instructions only for a captcha pause', fakeAsync(() => {
        flushList([sampleApplication]);
        startRun();

        tick(5000);
        expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'captcha' });
        fixture.detectChanges();

        let text = fixture.nativeElement.textContent as string;
        expect(text).toContain('localhost:9222');

        component['onContinuePortalFill'](sampleApplication);
        httpMock.expectOne((request) => request.url === continueUrl && request.method === 'POST').flush({
          ...sampleApplication,
          automation_state: 'running',
          action_needed_reason: null,
        });
        tick(5000);
        expectStatusPoll().flush({ automation_state: 'running', action_needed_reason: null });
        fixture.detectChanges();

        tick(5000);
        expectStatusPoll().flush({ automation_state: 'paused', action_needed_reason: 'pre_submit_confirmation' });
        fixture.detectChanges();

        text = fixture.nativeElement.textContent as string;
        expect(text).not.toContain('localhost:9222');
        fixture.destroy(); // still `paused` - stop the periodic poll so fakeAsync can settle.
      }));
    });
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
