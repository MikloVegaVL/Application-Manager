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
    tailored_cv_json: {
      full_name: 'Erika Musterfrau',
      email: 'erika@example.com',
      phone: null,
      address: null,
      summary: 'Zusammenfassung',
      experiences: [],
      education: [],
      skills: ['Angular'],
    },
    pdf_path: '/generated/applications/application_1.pdf',
    status: 'draft',
    sent_at: null,
    created_at: '2026-08-11T00:00:00',
    job_offer: defaultJobOffer,
  };
}

/** Flusht Job- und Bewerbungs-Requests, damit `application()`/`jobOffer()` befüllt sind. */
function loadApplication(
  httpMock: HttpTestingController,
  options: { coverLetterText?: string | null; withJobOffer?: boolean } = {},
): void {
  const { coverLetterText = null, withJobOffer = true } = options;

  const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
  if (withJobOffer) {
    jobReq.flush(defaultJobOffer);
  } else {
    jobReq.flush({ detail: 'not found' }, { status: 404, statusText: 'Not Found' });
  }

  const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
  appReq.flush(buildApplication(coverLetterText));

  httpMock.expectOne((req) => req.url.endsWith('/applications/1/pdf')).flush(new Blob(['%PDF-1.4']));
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
    jobReq.flush({
      id: 1,
      title: 'Backend Engineer',
      company: 'Acme GmbH',
      location: 'Berlin',
      source_url: 'https://example.com/jobs/1',
      description_text: null,
      source_platform: 'arbeitsagentur',
      created_at: '2026-08-11T00:00:00',
      is_processed: false,
    });

    const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
    appReq.flush({ detail: 'not found' }, { status: 404, statusText: 'Not Found' });

    const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
    expect(generateReq.request.body).toEqual({ job_offer_id: 1 });
    generateReq.flush({
      id: 1,
      job_offer_id: 1,
      cover_letter_text: 'Sehr geehrte Damen und Herren,',
      tailored_cv_json: {
        full_name: 'Erika Musterfrau',
        email: 'erika@example.com',
        phone: null,
        address: null,
        summary: 'Zusammenfassung',
        experiences: [],
        education: [],
        skills: ['Angular'],
      },
      pdf_path: '/generated/applications/application_1.pdf',
      status: 'draft',
      sent_at: null,
      created_at: '2026-08-11T00:00:00',
    });

    const pdfReq = httpMock.expectOne((req) => req.url.endsWith('/applications/1/pdf'));
    pdfReq.flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));

    expect(component['application']()?.id).toBe(1);
    expect(component['skills']()).toEqual(['Angular']);
  });

  it('Regression: shows the "can take minutes" hint only while a first-time generation is in flight', () => {
    // (ce-debug-Untersuchung, 2026-08-18: "Generate Application" auf einem
    // neuen Job-Angebot lief messbar 4+ Minuten - ohne Hinweis wirkte das wie
    // hängengeblieben statt nur langsam.)
    const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
    jobReq.flush({
      id: 1,
      title: 'Backend Engineer',
      company: 'Acme GmbH',
      location: 'Berlin',
      source_url: 'https://example.com/jobs/1',
      description_text: null,
      source_platform: 'arbeitsagentur',
      created_at: '2026-08-11T00:00:00',
      is_processed: false,
    });

    const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
    appReq.flush({ detail: 'not found' }, { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    // Generierung läuft noch (generateReq absichtlich nicht geflusht) - der
    // Hinweis muss jetzt sichtbar sein.
    expect(component['isFirstGeneration']()).toBeTrue();
    expect(fixture.nativeElement.textContent as string).toContain('mehrere Minuten dauern');

    const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
    generateReq.flush({
      id: 1,
      job_offer_id: 1,
      cover_letter_text: 'Sehr geehrte Damen und Herren,',
      tailored_cv_json: {
        full_name: 'Erika Musterfrau',
        email: 'erika@example.com',
        phone: null,
        address: null,
        summary: 'Zusammenfassung',
        experiences: [],
        education: [],
        skills: ['Angular'],
      },
      pdf_path: '/generated/applications/application_1.pdf',
      status: 'draft',
      sent_at: null,
      created_at: '2026-08-11T00:00:00',
    });

    httpMock.expectOne((req) => req.url.endsWith('/applications/1/pdf')).flush(new Blob(['%PDF-1.4']));

    expect(component['isFirstGeneration']()).toBeFalse();
  });

  it('does not show the generation hint when an already-generated application loads instantly', () => {
    const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
    jobReq.flush({
      id: 1,
      title: 'Backend Engineer',
      company: 'Acme GmbH',
      location: 'Berlin',
      source_url: 'https://example.com/jobs/1',
      description_text: null,
      source_platform: 'arbeitsagentur',
      created_at: '2026-08-11T00:00:00',
      is_processed: true,
    });

    const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
    appReq.flush({
      id: 1,
      job_offer_id: 1,
      cover_letter_text: 'Sehr geehrte Damen und Herren,',
      tailored_cv_json: {
        full_name: 'Erika Musterfrau',
        email: 'erika@example.com',
        phone: null,
        address: null,
        summary: 'Zusammenfassung',
        experiences: [],
        education: [],
        skills: ['Angular'],
      },
      pdf_path: '/generated/applications/application_1.pdf',
      status: 'draft',
      sent_at: null,
      created_at: '2026-08-11T00:00:00',
    });

    httpMock.expectOne((req) => req.url.endsWith('/applications/1/pdf')).flush(new Blob(['%PDF-1.4']));

    expect(component['isFirstGeneration']()).toBeFalse();
  });

  describe('onOpenSendDialog()', () => {
    it('Tab-3 empty + Anschreiben has a Betreff line -> dialog opens with the derived subject and message', () => {
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
    });

    it('Tab-3 has a manually-typed subject -> dialog opens with Tab-3\'s subject, not the derived one', () => {
      loadApplication(httpMock, {
        coverLetterText: 'Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,',
      });
      component['emailForm'].patchValue({ subject: 'Meine eigene Betreffzeile' });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.subject).toBe('Meine eigene Betreffzeile');
    });

    it('per-field evaluation: Tab-3 subject + empty Tab-3 message -> Tab-3 subject AND the Betreff-derived message', () => {
      // Doc-review-flagged scenario: a value in one Tab-3 field must not
      // suppress Betreff-derivation for the other field.
      loadApplication(httpMock, {
        coverLetterText: 'Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,',
      });
      component['emailForm'].patchValue({ subject: 'Meine eigene Betreffzeile', message: '' });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.subject).toBe('Meine eigene Betreffzeile');
      expect(data.message).toBe('Sehr geehrte Damen und Herren,');
    });

    it('Anschreiben has no Betreff line + Tab-3 empty -> dialog subject shows the job-title-based fallback', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren, ich bewerbe mich...' });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.subject).toBe('Bewerbung als Backend Engineer');
    });

    it('no job offer linked + no Betreff line + Tab-3 empty -> dialog subject shows the generic "Bewerbung" fallback', () => {
      loadApplication(httpMock, {
        coverLetterText: 'Sehr geehrte Damen und Herren, ich bewerbe mich...',
        withJobOffer: false,
      });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.subject).toBe('Bewerbung');
    });

    it('Regression: after a failed send, reopening the dialog still shows the previously-confirmed values', () => {
      loadApplication(httpMock, {
        coverLetterText: 'Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,',
      });

      const confirmedResult: SendApplicationDialogResult = {
        to_email: 'empfaenger@example.com',
        subject: 'Vom Nutzer bestätigter Betreff',
        message: 'Vom Nutzer bestätigte Nachricht',
      };
      const firstDialogRef = {
        afterClosed: () => of(confirmedResult),
      } as unknown as MatDialogRef<SendApplicationDialogComponent, SendApplicationDialogResult>;
      // Second open() call is a fresh dialog the user hasn't confirmed yet -
      // it must not trigger another send while we only assert on the data
      // it was pre-filled with.
      const secondDialogRef = {
        afterClosed: () => of(undefined),
      } as unknown as MatDialogRef<SendApplicationDialogComponent, SendApplicationDialogResult>;
      const openSpy: jasmine.Spy = spyOn(component['dialog'], 'open').and.returnValues(
        firstDialogRef,
        secondDialogRef,
      );

      component.onOpenSendDialog();

      httpMock
        .expectOne((req) => req.url.endsWith('/applications/1/send'))
        .flush({ detail: 'SMTP-Fehler' }, { status: 500, statusText: 'Internal Server Error' });

      // Reopen: emailForm now holds the previously-confirmed, non-empty
      // values, so onOpenSendDialog treats them as a Tab-3 override and
      // keeps them - unchanged `patchValue(result)` behavior.
      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.subject).toBe('Vom Nutzer bestätigter Betreff');
      expect(data.message).toBe('Vom Nutzer bestätigte Nachricht');
    });

    it('Regression (R7): opening the send dialog does not modify the saved Anschreiben text or coverLetterForm', () => {
      const coverLetterText = 'Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,';
      loadApplication(httpMock, { coverLetterText });
      spyOnDialogOpen(component);

      component.onOpenSendDialog();

      expect(component['application']()?.cover_letter_text).toBe(coverLetterText);
      expect(component['coverLetterForm'].getRawValue().cover_letter_text).toBe(coverLetterText);
    });
  });

  describe('onDownloadPdf()', () => {
    it('sets link.download to lebenslauf_{id}.pdf', () => {
      loadApplication(httpMock);

      let capturedLink: HTMLAnchorElement | undefined;
      const originalCreateElement = document.createElement.bind(document);
      spyOn(document, 'createElement').and.callFake((tagName: string) => {
        const element = originalCreateElement(tagName);
        if (tagName === 'a') {
          capturedLink = element as HTMLAnchorElement;
          spyOn(capturedLink, 'click');
        }
        return element;
      });

      component.onDownloadPdf();
      httpMock.expectOne((req) => req.url.endsWith('/applications/1/pdf')).flush(new Blob(['%PDF-1.4']));

      expect(capturedLink?.download).toBe('lebenslauf_1.pdf');
    });
  });
});
