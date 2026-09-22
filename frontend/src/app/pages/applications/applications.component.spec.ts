import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router, provideRouter } from '@angular/router';
import { MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of } from 'rxjs';
import { vi } from 'vitest';

import { ApplicationsComponent } from './applications.component';
import { Application } from '../../core/models/application.model';
import { JobOfferRead } from '../../core/models/job-offer.model';
import {
  AddJobOfferDialogComponent,
  AddJobOfferDialogResult,
} from './add-job-offer-dialog/add-job-offer-dialog.component';
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
    localStorage.clear();
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
    submission: null,
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
        submission: null,
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

    it('adds "Open ad" to the ⋮ menu as a native anchor to the job offer source URL, mirroring Job search', async () => {
      flushList([sentApplication]);

      await toggleCardMenu(fixture);
      const link = menuItemByText('Open ad') as unknown as HTMLAnchorElement;

      expect(link.tagName).toBe('A');
      expect(link.getAttribute('href')).toBe(sentApplication.job_offer.source_url);
      expect(link.getAttribute('target')).toBe('_blank');
      expect(link.getAttribute('rel')).toBe('noopener noreferrer');
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

  describe('apply via LinkedIn (U4)', () => {
    const fillRequestUrl = `${environment.apiBaseUrl}/applications/1/fill-request`;

    const linkedInApplication: Application = {
      ...sampleApplication,
      job_offer: { ...sampleApplication.job_offer, source_platform: 'linkedin' },
    };

    const submittedApplication: Application = {
      ...linkedInApplication,
      submission: {
        platform: 'linkedin',
        portal_url: 'https://www.linkedin.com/jobs/view/1',
        submitted_at: new Date('2026-09-01T10:00:00Z').toISOString(),
      },
    };

    it('Covers R1/R2: shows "Apply via LinkedIn" for a LinkedIn-sourced application with no submission', async () => {
      flushList([linkedInApplication]);

      await toggleCardMenu(fixture);
      const item = menuItemByText('Apply via LinkedIn');
      expect(item).toBeDefined();
      expect(isCompactCardMenuItemDisabled(item!)).toBe(false);
    });

    it('Covers R1/P2: opens a blank tab synchronously and points it at the job URL on success', async () => {
      flushList([linkedInApplication]);
      const pendingTab = {
        location: { href: '' },
        close: jasmine.createSpy('close'),
        opener: null,
      } as unknown as Window;
      const openSpy = spyOn(window, 'open').and.returnValue(pendingTab);

      await toggleCardMenu(fixture);
      menuItemByText('Apply via LinkedIn')!.click();

      // Der Tab wird synchron im Klick geöffnet, nicht erst im HTTP-Callback.
      expect(openSpy).toHaveBeenCalledWith('', '_blank');

      const req = httpMock.expectOne(
        (request) => request.url === fillRequestUrl && request.method === 'POST',
      );
      expect(req.request.body).toEqual({});
      req.flush({ job_url: 'https://www.linkedin.com/jobs/view/123' });
      fixture.detectChanges();

      expect(pendingTab.location.href).toBe('https://www.linkedin.com/jobs/view/123');
      expect(component['fillRequestingId']()).toBeNull();
    });

    it('Covers R11: shows the applied indicator and hides the trigger once a submission exists', async () => {
      flushList([submittedApplication]);

      await toggleCardMenu(fixture);
      expect(menuItemByText('Apply via LinkedIn')).toBeUndefined();
      const detailRow = document.querySelector('.compact-card__menu-detail-row');
      expect(detailRow?.textContent).toContain('Applied via LinkedIn on');
    });

    it('Covers R2: never shows the trigger for a non-LinkedIn application', async () => {
      flushList([sampleApplication]);

      await toggleCardMenu(fixture);
      expect(menuItemByText('Apply via LinkedIn')).toBeUndefined();
    });

    it('Covers U4/P2: a failed fill request closes the blank tab and re-enables the trigger', async () => {
      flushList([linkedInApplication]);
      const snackBar = TestBed.inject(MatSnackBar);
      const snackSpy = spyOn(snackBar, 'open');
      const pendingTab = {
        location: { href: '' },
        close: jasmine.createSpy('close'),
        opener: null,
      } as unknown as Window;
      const openSpy = spyOn(window, 'open').and.returnValue(pendingTab);

      await toggleCardMenu(fixture);
      menuItemByText('Apply via LinkedIn')!.click();

      const req = httpMock.expectOne((request) => request.url === fillRequestUrl);
      req.flush(
        { detail: 'Nur LinkedIn-Bewerbungen können einen Fill starten (R2).' },
        { status: 422, statusText: 'Unprocessable Entity' },
      );
      fixture.detectChanges();

      expect(snackSpy).toHaveBeenCalled();
      expect(openSpy).toHaveBeenCalledWith('', '_blank');
      expect(pendingTab.close).toHaveBeenCalled();
      expect(pendingTab.location.href).toBe('');
      expect(component['fillRequestingId']()).toBeNull();

      await toggleCardMenu(fixture);
      const item = menuItemByText('Apply via LinkedIn');
      expect(item).toBeDefined();
      expect(isCompactCardMenuItemDisabled(item!)).toBe(false);
    });

    describe('install hint', () => {
      it('Covers R17/KTD9: shows the one-time install hint when a fillable LinkedIn application exists', () => {
        flushList([linkedInApplication]);

        const text = fixture.nativeElement.textContent as string;
        expect(text).toContain('unpacked');
        expect(fixture.nativeElement.querySelector('.applications__install-hint')).not.toBeNull();
      });

      it('Covers R17/KTD9: hides the hint after it is dismissed and persists the dismissal', () => {
        flushList([linkedInApplication]);
        expect(fixture.nativeElement.querySelector('.applications__install-hint')).not.toBeNull();

        const dismiss = fixture.nativeElement.querySelector(
          'button[aria-label="Dismiss install hint"]',
        ) as HTMLButtonElement;
        dismiss.click();
        fixture.detectChanges();

        expect(fixture.nativeElement.querySelector('.applications__install-hint')).toBeNull();
        expect(localStorage.getItem('applications.extension-install-hint-dismissed')).toBe('1');
      });

      it('Covers R17: does not show the hint when no fillable LinkedIn application exists', () => {
        flushList([sampleApplication]);

        expect(fixture.nativeElement.querySelector('.applications__install-hint')).toBeNull();
      });
    });
  });
});
