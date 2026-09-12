import { ComponentFixture, TestBed, fakeAsync, flush, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Router, provideRouter } from '@angular/router';
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
    sent_to_email: null,
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
    // Sprachauswahl nicht zwischen Specs teilen (sonst starten Tests je nach
    // Reihenfolge auf Englisch statt Deutsch).
    localStorage.clear();

    await TestBed.configureTestingModule({
      imports: [ApplicationEditorComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
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

  it('Regression: an application record with no cover letter yet (saved-only job) triggers first-time generation', () => {
    // (ce-debug-Untersuchung, 2026-08-20: `POST /jobs/save` legt seither
    // sofort eine Application ohne Anschreiben an, damit gespeicherte Jobs
    // auf der Bewerbungsübersicht sichtbar sind - der Editor muss diesen
    // Fall genauso wie ein bislang fehlendes (404) Anschreiben behandeln.)
    loadApplication(httpMock); // Default: coverLetterText null - genau der Fall aus POST /jobs/save
    fixture.detectChanges();

    expect(component['isFirstGeneration']()).toBeTrue();

    const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
    generateReq.flush(buildApplication('Sehr geehrte Damen und Herren,'));

    expect(component['isFirstGeneration']()).toBeFalse();
    expect(component['application']()?.cover_letter_text).toBe('Sehr geehrte Damen und Herren,');
  });

  it(
    'Regression: a 409 from an already-running generation waits for its result instead of starting another one',
    fakeAsync(() => {
      // (ce-debug-Untersuchung, 2026-08-28: erneutes Öffnen des Editors für
      // denselben Job - vor Abschluss der ersten Generierung - stieß bislang
      // ausnahmslos eine weitere, überlappende KI-Generierung an. Das
      // Backend lehnt einen zweiten, überlappenden Aufruf jetzt mit 409 ab
      // (siehe `app.api.applications.generate_application`) - der Editor
      // muss diesen Fall abwarten statt ihn wie einen echten Fehler
      // anzuzeigen.)
      loadApplication(httpMock); // Default: coverLetterText null
      fixture.detectChanges();

      const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
      generateReq.flush(
        { detail: 'Für dieses Stellenangebot läuft bereits eine Generierung. Bitte warten.' },
        { status: 409, statusText: 'Conflict' },
      );

      // Weiterhin im Warte-Zustand - und KEIN zweiter generate-Aufruf.
      expect(component['isFirstGeneration']()).toBeTrue();
      expect(component['errorMessage']()).toBeNull();
      httpMock.expectNone((req) => req.url.endsWith('/applications/generate'));

      // Erste Status-Abfrage: die laufende Generierung ist noch nicht fertig.
      tick(5000);
      const firstPoll = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
      firstPoll.flush(buildApplication(null));

      expect(component['isFirstGeneration']()).toBeTrue();
      httpMock.expectNone((req) => req.url.endsWith('/applications/generate'));

      // Zweite Status-Abfrage: jetzt liegt das Ergebnis vor.
      tick(5000);
      const secondPoll = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
      secondPoll.flush(buildApplication('Sehr geehrte Damen und Herren,'));

      expect(component['isFirstGeneration']()).toBeFalse();
      expect(component['application']()?.cover_letter_text).toBe('Sehr geehrte Damen und Herren,');
      httpMock.expectNone((req) => req.url.endsWith('/applications/generate'));

      // Kein weiteres Polling mehr, nachdem das Ergebnis übernommen wurde.
      tick(5000);
      httpMock.expectNone((req) => req.url.endsWith('/applications/by-job-offer/1'));
    }),
  );

  it(
    'Regression: a transient error on a single status poll does not end the wait (ce-code-review, 2026-08-28)',
    fakeAsync(() => {
      // Ein einzelner fehlgeschlagener Tick (z. B. kurzer Netzwerk-/Backend-
      // Hänger) darf die gesamte Wartezeit nicht sofort mit einem
      // permanenten Fehler beenden - er wird übersprungen, der nächste Tick
      // versucht es erneut.
      loadApplication(httpMock);
      fixture.detectChanges();

      const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
      generateReq.flush({ detail: 'Läuft bereits.' }, { status: 409, statusText: 'Conflict' });

      // Erster Tick: die Status-Abfrage selbst schlägt fehl (z. B. 503).
      tick(5000);
      const failingPoll = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
      failingPoll.flush({ detail: 'Service nicht verfügbar' }, { status: 503, statusText: 'Service Unavailable' });

      // Die Wartezeit läuft weiter - kein Fehler, kein zweiter generate-Aufruf.
      expect(component['isFirstGeneration']()).toBeTrue();
      expect(component['errorMessage']()).toBeNull();

      // Zweiter Tick: diesmal liegt das Ergebnis vor.
      tick(5000);
      const secondPoll = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
      secondPoll.flush(buildApplication('Sehr geehrte Damen und Herren,'));

      expect(component['isFirstGeneration']()).toBeFalse();
      expect(component['application']()?.cover_letter_text).toBe('Sehr geehrte Damen und Herren,');
    }),
  );

  it(
    'Regression: gives up and shows an error if the awaited generation never finishes (ce-code-review, 2026-08-28)',
    fakeAsync(() => {
      // Schlägt die abgewartete fremde Generierung am Ende fehl (z. B. 502
      // beim Original-Aufruf), bleibt `cover_letter_text` für immer leer -
      // ohne Obergrenze würde der Editor unbegrenzt weiter pollen (genau das
      // ursprüngliche "läuft endlos ohne Ergebnis"-Symptom, nur über einen
      // anderen Auslöser reproduziert).
      loadApplication(httpMock);
      fixture.detectChanges();

      const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
      generateReq.flush({ detail: 'Läuft bereits.' }, { status: 409, statusText: 'Conflict' });

      // Weit über die Obergrenze hinaus vorspulen - jeder Tick liefert
      // weiterhin ein leeres Anschreiben (die abgewartete Generierung ist
      // nie fertig geworden).
      tick(30 * 60 * 1000 + 5000);
      httpMock.match(() => true).forEach((req) => {
        if (!req.cancelled) {
          req.flush(buildApplication(null));
        }
      });
      flush();

      expect(component['isFirstGeneration']()).toBeFalse();
      expect(component['loading']()).toBeFalse();
      expect(component['errorMessage']()).toContain('ungewöhnlich lange');
    }),
  );

  it(
    'Regression: leaving the editor while waiting for a running generation stops the polling',
    fakeAsync(() => {
      // `takeUntilDestroyed` muss den Timer wirklich beenden, sobald der
      // Editor verlassen wird - sonst würde eine verwaiste Polling-Instanz
      // nach jedem Navigieren-weg-und-zurück weiterlaufen.
      loadApplication(httpMock);
      fixture.detectChanges();

      const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
      generateReq.flush({ detail: 'Läuft bereits.' }, { status: 409, statusText: 'Conflict' });

      fixture.destroy();

      // Nach dem Zerstören darf keine weitere Status-Abfrage mehr gestellt werden.
      tick(5000);
      httpMock.expectNone((req) => req.url.endsWith('/applications/by-job-offer/1'));
    }),
  );

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

    it('sends with the dialog-confirmed values, shows a success message and redirects to the overview', () => {
      loadApplication(httpMock, {
        coverLetterText: 'Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,',
      });
      const router = TestBed.inject(Router);
      const navigateSpy = spyOn(router, 'navigate');
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
      expect(navigateSpy).toHaveBeenCalledWith(['/applications']);
    });

    it('does not redirect when sending fails', () => {
      loadApplication(httpMock, {
        coverLetterText: 'Betreff: Bewerbung als Softwareentwickler\n\nSehr geehrte Damen und Herren,',
      });
      const router = TestBed.inject(Router);
      const navigateSpy = spyOn(router, 'navigate');
      spyOnDialogOpen(component, {
        to_email: 'empfaenger@example.com',
        subject: 'Bewerbung als Softwareentwickler',
        message: 'Sehr geehrte Damen und Herren,',
      });

      component.onOpenSendDialog();

      const req = httpMock.expectOne((r) => r.url.endsWith('/applications/1/send'));
      req.flush('server error', { status: 500, statusText: 'Internal Server Error' });

      expect(navigateSpy).not.toHaveBeenCalled();
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
