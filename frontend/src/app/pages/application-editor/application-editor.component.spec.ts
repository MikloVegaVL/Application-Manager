import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatDialogRef } from '@angular/material/dialog';
import { of } from 'rxjs';

import { ApplicationEditorComponent } from './application-editor.component';
import {
  SendApplicationDialogComponent,
  SendApplicationDialogData,
  SendApplicationDialogResult,
} from './send-application-dialog/send-application-dialog.component';
import { Application } from '../../core/models/application.model';
import { JobOfferRead } from '../../core/models/job-offer.model';

const defaultJobOffer: JobOfferRead = {
  id: 1,
  title: 'Backend Engineer',
  company: 'Acme GmbH',
  location: 'Berlin',
  source_url: 'https://example.com/jobs/1',
  description_text: null,
  source_platform: 'arbeitsagentur',
  created_at: '2026-08-11T00:00:00',
  is_processed: false,
};

function buildApplication(coverLetterText: string | null): Application {
  return {
    id: 1,
    job_offer_id: 1,
    cover_letter_text: coverLetterText,
    status: 'draft',
    sent_at: null,
    created_at: '2026-08-11T00:00:00',
    job_offer: defaultJobOffer,
  };
}

/** Flusht Job- und Bewerbungs-Requests, damit `application()`/`jobOffer()` befüllt sind. */
function loadApplication(
  httpMock: HttpTestingController,
  options: {
    coverLetterText?: string | null;
    withJobOffer?: boolean;
    jobOffer?: JobOfferRead;
  } = {},
): void {
  const { coverLetterText = null, withJobOffer = true, jobOffer = defaultJobOffer } = options;

  const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
  if (withJobOffer) {
    jobReq.flush(jobOffer);
  } else {
    jobReq.flush({ detail: 'not found' }, { status: 404, statusText: 'Not Found' });
  }

  const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
  appReq.flush(buildApplication(coverLetterText));
}

/** Ersetzt `MatDialog.open()` durch einen Fake, der sofort mit `result` schließt. */
function spyOnDialogOpen(
  component: ApplicationEditorComponent,
  result?: SendApplicationDialogResult,
): jasmine.Spy {
  const fakeDialogRef = {
    afterClosed: () => of(result),
  } as unknown as MatDialogRef<SendApplicationDialogComponent, SendApplicationDialogResult>;
  return spyOn(component['dialog'], 'open').and.returnValue(fakeDialogRef);
}

describe('ApplicationEditorComponent', () => {
  let component: ApplicationEditorComponent;
  let fixture: ComponentFixture<ApplicationEditorComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ApplicationEditorComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(ApplicationEditorComponent);
    fixture.componentRef.setInput('jobOfferId', '1');
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create and request job + application data for the given jobOfferId', () => {
    expect(component).toBeTruthy();

    const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
    jobReq.flush(defaultJobOffer);

    const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
    appReq.flush(buildApplication('Sehr geehrte Damen und Herren,'));

    expect(component['application']()?.id).toBe(1);
    expect(component['coverLetterForm'].getRawValue().cover_letter_text).toBe(
      'Sehr geehrte Damen und Herren,',
    );
  });

  it('Regression: shows the "can take minutes" hint only while a first-time generation is in flight', () => {
    // (ce-debug-Untersuchung, 2026-08-18: "Generate Application" auf einem
    // neuen Job-Angebot lief messbar 4+ Minuten - ohne Hinweis wirkte das wie
    // hängengeblieben statt nur langsam.)
    const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
    jobReq.flush(defaultJobOffer);

    const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
    appReq.flush({ detail: 'not found' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    // Generierung läuft noch (generateReq absichtlich nicht geflusht) - der
    // Hinweis muss jetzt sichtbar sein.
    expect(component['isFirstGeneration']()).toBeTrue();
    expect(fixture.nativeElement.textContent as string).toContain('mehrere Minuten dauern');

    const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
    generateReq.flush(buildApplication('Sehr geehrte Damen und Herren,'));

    expect(component['isFirstGeneration']()).toBeFalse();
  });

  it('does not show the generation hint when an already-generated application loads instantly', () => {
    const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
    jobReq.flush({ ...defaultJobOffer, is_processed: true });

    const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
    appReq.flush(buildApplication('Sehr geehrte Damen und Herren,'));

    expect(component['isFirstGeneration']()).toBeFalse();
  });

  describe('onSaveCoverLetter()', () => {
    it('saves the edited cover-letter text without triggering a new AI generation', () => {
      loadApplication(httpMock, { coverLetterText: 'Alter Text' });
      component['coverLetterForm'].patchValue({ cover_letter_text: 'Neuer Text' });

      component.onSaveCoverLetter();

      const req = httpMock.expectOne((r) => r.url.endsWith('/applications/1') && r.method === 'PUT');
      expect(req.request.body).toEqual({ cover_letter_text: 'Neuer Text' });
      req.flush(buildApplication('Neuer Text'));

      expect(component['application']()?.cover_letter_text).toBe('Neuer Text');
    });

    it('does not submit when the cover-letter text is blank', () => {
      loadApplication(httpMock, { coverLetterText: 'Text' });
      component['coverLetterForm'].patchValue({ cover_letter_text: '' });

      component.onSaveCoverLetter();

      expect(component['saving']()).toBeFalse();
      httpMock.expectNone((r) => r.url.endsWith('/applications/1') && r.method === 'PUT');
    });
  });

  describe('onOpenSendDialog()', () => {
    it('Anschreiben has a Betreff line -> dialog opens with the derived subject and message', () => {
      loadApplication(httpMock, {
        coverLetterText:
          'Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,\n\nMit freundlichen Grüßen\nMax Mustermann',
      });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.subject).toBe('Bewerbung als Softwareentwickler');
      expect(data.message).toBe(
        'Sehr geehrte Damen und Herren,\n\nMit freundlichen Grüßen\nMax Mustermann',
      );
      expect(data.toEmail).toBe('');
    });

    it('job offer text contains a contact email -> dialog opens pre-filled with it', () => {
      loadApplication(httpMock, {
        coverLetterText: 'Sehr geehrte Damen und Herren,',
        jobOffer: {
          ...defaultJobOffer,
          description_text: 'Bitte sende deine Bewerbung an bewerbung@acme.example.',
        },
      });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.toEmail).toBe('bewerbung@acme.example');
    });

    it('Anschreiben has no Betreff line -> dialog subject shows the job-title-based fallback', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren, ich bewerbe mich...' });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.subject).toBe('Bewerbung als Backend Engineer');
    });

    it('no job offer linked + no Betreff line -> dialog subject shows the generic "Bewerbung" fallback', () => {
      loadApplication(httpMock, {
        coverLetterText: 'Sehr geehrte Damen und Herren, ich bewerbe mich...',
        withJobOffer: false,
      });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.subject).toBe('Bewerbung');
    });

    it('sends with the dialog-confirmed values and shows a success message', () => {
      loadApplication(httpMock, {
        coverLetterText: 'Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,',
      });
      const confirmedResult: SendApplicationDialogResult = {
        to_email: 'empfaenger@example.com',
        subject: 'Bewerbung als Softwareentwickler',
        message: 'Sehr geehrte Damen und Herren,',
      };
      spyOnDialogOpen(component, confirmedResult);

      component.onOpenSendDialog();

      const req = httpMock.expectOne((r) => r.url.endsWith('/applications/1/send'));
      expect(req.request.body).toEqual({
        to_email: 'empfaenger@example.com',
        subject: 'Bewerbung als Softwareentwickler',
        message: 'Sehr geehrte Damen und Herren,',
      });
      req.flush(buildApplication('Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,'));

      expect(component['application']()?.status).toBe('draft');
    });

    it('Regression: opening the send dialog does not modify the saved Anschreiben text or coverLetterForm', () => {
      const coverLetterText = 'Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,';
      loadApplication(httpMock, { coverLetterText });
      spyOnDialogOpen(component);

      component.onOpenSendDialog();

      expect(component['application']()?.cover_letter_text).toBe(coverLetterText);
      expect(component['coverLetterForm'].getRawValue().cover_letter_text).toBe(coverLetterText);
    });
  });
});
