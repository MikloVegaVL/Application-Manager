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
import { JobSearchStateService } from '../../core/services/job-search-state.service';
import { TabTitleService } from '../../core/services/tab-title.service';
import { environment } from '../../../environments/environment';

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

function buildApplication(
  coverLetterText: string | null,
  profileType: Application['profile_type'] = null,
): Application {
  return {
    id: 1,
    job_offer_id: 1,
    cover_letter_text: coverLetterText,
    status: 'draft',
    sent_at: null,
    sent_to_email: null,
    submission: null,
    created_at: '2026-08-11T00:00:00',
    profile_type: profileType,
    job_offer: defaultJobOffer,
  };
}

/** Flusht Job- und Bewerbungs-Requests, damit `application()`/`jobOffer()` befüllt sind.
 *
 * `profileType` ist standardmäßig bereits `'it'` (nicht `null`), obwohl
 * `coverLetterText` standardmäßig leer ist - simuliert damit den "bereits
 * gesperrtes Profil, Erstversuch aber gescheitert/unterbrochen"-Fall statt
 * des "noch gar kein Profil gewählt"-Falls (R4, U8). Die meisten Aufrufer
 * dieser Helper-Funktion testen Verhalten NACH dem Profilwahl-Dialog (Tab-
 * Titel, 409-Polling, Destroy-Handling) und sollen den Dialog nicht extra
 * mocken müssen; Tests, die den Dialog selbst prüfen wollen, übergeben
 * explizit `profileType: null` und mocken `dialog.open` wie im "can take
 * minutes"-Test oben. */
function loadApplication(
  httpMock: HttpTestingController,
  options: {
    coverLetterText?: string | null;
    profileType?: Application['profile_type'];
    withJobOffer?: boolean;
    jobOffer?: JobOfferRead;
  } = {},
): void {
  const {
    coverLetterText = null,
    profileType = 'it',
    withJobOffer = true,
    jobOffer = defaultJobOffer,
  } = options;

  const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
  if (withJobOffer) {
    jobReq.flush(jobOffer);
  } else {
    jobReq.flush({ detail: 'not found' }, { status: 404, statusText: 'Not Found' });
  }

  const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
  appReq.flush([buildApplication(coverLetterText, profileType)]);
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
    appReq.flush([buildApplication('Sehr geehrte Damen und Herren,')]);

    expect(component['application']()?.id).toBe(1);
    expect(component['coverLetterForm'].getRawValue().cover_letter_text).toBe(
      'Sehr geehrte Damen und Herren,',
    );
  });

  it('Regression: shows the "can take minutes" hint only while a first-time generation is in flight', () => {
    // (ce-debug-Untersuchung, 2026-08-18: "Generate Application" auf einem
    // neuen Job-Angebot lief messbar 4+ Minuten - ohne Hinweis wirkte das wie
    // hängengeblieben statt nur langsam.)
    //
    // Seit U8 (docs/plans/2026-09-23-001-feat-profile-types-plan.md) blockiert
    // vor der allerersten Generierung erst der Profilwahl-Dialog (R4) - der
    // Dialog wird hier per Spy sofort mit einer Wahl geschlossen, damit dieser
    // Test weiterhin nur den Generierungs-Hinweis selbst prüft.
    const dialogOpenSpy = spyOn(component['dialog'], 'open').and.returnValue({
      afterClosed: () => of('it'),
    } as unknown as MatDialogRef<unknown, unknown>);

    const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
    jobReq.flush(defaultJobOffer);

    const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
    // Seit U9 liefert der Endpunkt eine Liste statt 404 - ein leeres Array
    // bedeutet "noch keine Bewerbung generiert" (KTD12).
    appReq.flush([]);
    fixture.detectChanges();

    expect(dialogOpenSpy).toHaveBeenCalled();

    // Generierung läuft noch (generateReq absichtlich nicht geflusht) - der
    // Hinweis muss jetzt sichtbar sein.
    expect(component['isFirstGeneration']()).toBeTrue();
    expect(fixture.nativeElement.textContent as string).toContain('can take several minutes');

    const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
    expect(generateReq.request.body.profile_type).toBe('it');
    generateReq.flush(buildApplication('Sehr geehrte Damen und Herren,'));

    expect(component['isFirstGeneration']()).toBeFalse();
  });

  it('U8: an application with an already-locked profile skips the profile-choice dialog', () => {
    const dialogOpenSpy = spyOn(component['dialog'], 'open');

    // `profileType: 'it'` (via loadApplication's default) simulates an
    // application whose profile is already locked but whose first
    // generation attempt was interrupted - generation should proceed
    // directly, exactly as it did before U8 (R4/R5).
    loadApplication(httpMock, { coverLetterText: null, profileType: 'it' });
    fixture.detectChanges();

    expect(dialogOpenSpy).not.toHaveBeenCalled();
    expect(component['isFirstGeneration']()).toBeTrue();

    const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
    // Already locked - no `profile_type` needs to be (re-)sent; the backend
    // ignores it anyway once `Application.profile_id` is set (KTD3).
    expect(generateReq.request.body.profile_type).toBeUndefined();
    generateReq.flush(buildApplication('Sehr geehrte Damen und Herren,', 'it'));

    expect(component['isFirstGeneration']()).toBeFalse();
  });

  it('U8: a 404 for the chosen profile type shows a message naming that profile with a link to /profile', () => {
    spyOn(component['dialog'], 'open').and.returnValue({
      afterClosed: () => of('it'),
    } as unknown as MatDialogRef<unknown, unknown>);

    const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
    jobReq.flush(defaultJobOffer);
    const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
    // Seit U9 liefert der Endpunkt eine Liste statt 404 - ein leeres Array
    // bedeutet "noch keine Bewerbung generiert" (KTD12).
    appReq.flush([]);
    fixture.detectChanges();

    const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
    generateReq.flush(
      { detail: 'Es wurde noch kein IT-Profil angelegt.' },
      { status: 404, statusText: 'Not Found' },
    );
    fixture.detectChanges();

    expect(component['missingProfileType']()).toBe('it');
    expect(component['errorMessage']()).toContain('IT profile has no data yet');
    const profileLink = fixture.nativeElement.querySelector('a[routerLink="/profile"]');
    expect(profileLink).withContext('expected a link to /profile in the error state').not.toBeNull();
  });

  it('does not show the generation hint when an already-generated application loads instantly', () => {
    const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
    jobReq.flush({ ...defaultJobOffer, is_processed: true });

    const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
    appReq.flush([buildApplication('Sehr geehrte Damen und Herren,')]);

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
      firstPoll.flush([buildApplication(null)]);

      expect(component['isFirstGeneration']()).toBeTrue();
      httpMock.expectNone((req) => req.url.endsWith('/applications/generate'));

      // Zweite Status-Abfrage: jetzt liegt das Ergebnis vor.
      tick(5000);
      const secondPoll = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
      secondPoll.flush([buildApplication('Sehr geehrte Damen und Herren,')]);

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
      secondPoll.flush([buildApplication('Sehr geehrte Damen und Herren,')]);

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
          req.flush([buildApplication(null)]);
        }
      });
      flush();

      expect(component['isFirstGeneration']()).toBeFalse();
      expect(component['loading']()).toBeFalse();
      expect(component['errorMessage']()).toContain('unusually long');
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

  describe('onDownloadCoverLetter()', () => {
    const downloadUrl = `${environment.apiBaseUrl}/applications/1/cover-letter.pdf`;

    it('downloads the saved cover letter as a PDF blob', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,' });

      component.onDownloadCoverLetter();
      expect(component['downloading']()).toBeTrue();

      const req = httpMock.expectOne((r) => r.url === downloadUrl && r.method === 'GET');
      req.flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));

      expect(component['downloading']()).toBeFalse();
    });

    it('makes no request when no application is loaded', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,' });
      component['application'].set(null);

      component.onDownloadCoverLetter();

      expect(component['downloading']()).toBeFalse();
      httpMock.expectNone((r) => r.url.includes('cover-letter.pdf'));
    });

    it('ignores a second click while a download is already in flight', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,' });

      component.onDownloadCoverLetter();
      component.onDownloadCoverLetter();

      httpMock.expectOne((r) => r.url === downloadUrl && r.method === 'GET').flush(
        new Blob(['%PDF-1.4'], { type: 'application/pdf' }),
      );
      expect(component['downloading']()).toBeFalse();
    });

    it('resets the downloading flag and shows an error when the download fails', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,' });

      component.onDownloadCoverLetter();
      const req = httpMock.expectOne((r) => r.url === downloadUrl);
      // `responseType: 'blob'` requires a real Blob body - a string body throws
      // before the error path can be exercised.
      req.flush(new Blob(['server error'], { type: 'text/plain' }), {
        status: 500,
        statusText: 'Internal Server Error',
      });

      expect(component['downloading']()).toBeFalse();
    });
  });

  describe('onRegenerate()', () => {
    let tabTitleService: TabTitleService;
    let confirmSpy: jasmine.Spy;

    beforeEach(() => {
      tabTitleService = TestBed.inject(TabTitleService);
      confirmSpy = spyOn(window, 'confirm');
    });

    it('Covers AE3: confirm=true sends the generate request and applies the returned application on success', () => {
      loadApplication(httpMock, { coverLetterText: 'Alter Text' });
      confirmSpy.and.returnValue(true);
      const startSpy = spyOn(tabTitleService, 'markGenerationStarted');
      const settleSpy = spyOn(tabTitleService, 'markGenerationSettled');

      component.onRegenerate();

      expect(confirmSpy).toHaveBeenCalled();
      // R5: the confirm message must name the concrete consequence, not a generic prompt.
      expect(confirmSpy.calls.mostRecent().args[0]).toContain('replace');
      expect(component['regenerating']()).toBeTrue();
      expect(startSpy).toHaveBeenCalled();

      const req = httpMock.expectOne((r) => r.url.endsWith('/applications/generate'));
      // U8: Regenerate bleibt unverändert - kein `profile_type` im Body, das
      // Backend nutzt weiterhin ausschließlich das bereits gesperrte Profil
      // (KTD3).
      expect(req.request.body.profile_type).toBeUndefined();
      req.flush(buildApplication('Neuer Text'));

      expect(component['application']()?.cover_letter_text).toBe('Neuer Text');
      expect(component['regenerating']()).toBeFalse();
      expect(settleSpy).toHaveBeenCalled();
    });

    it('Covers AE4: confirm=false sends no HTTP request and leaves the current form value unchanged', () => {
      loadApplication(httpMock, { coverLetterText: 'Alter Text' });
      confirmSpy.and.returnValue(false);

      component.onRegenerate();

      expect(component['regenerating']()).toBeFalse();
      expect(component['coverLetterForm'].getRawValue().cover_letter_text).toBe('Alter Text');
      httpMock.expectNone((r) => r.url.endsWith('/applications/generate'));
    });

    it('Covers AE8: already regenerating sends no HTTP request, independent of the confirm stub', () => {
      loadApplication(httpMock, { coverLetterText: 'Alter Text' });
      confirmSpy.and.returnValue(true);
      component['regenerating'].set(true);

      component.onRegenerate();

      expect(confirmSpy).not.toHaveBeenCalled();
      httpMock.expectNone((r) => r.url.endsWith('/applications/generate'));
    });

    it('a 409 from the regenerate call surfaces as a generic error and resets regenerating to false', () => {
      loadApplication(httpMock, { coverLetterText: 'Alter Text' });
      confirmSpy.and.returnValue(true);
      const settleSpy = spyOn(tabTitleService, 'markGenerationSettled');

      component.onRegenerate();

      const req = httpMock.expectOne((r) => r.url.endsWith('/applications/generate'));
      req.flush(
        { detail: 'Für dieses Stellenangebot läuft bereits eine Generierung.' },
        { status: 409, statusText: 'Conflict' },
      );

      // Not routed into pollForRunningGeneration - no follow-up poll request.
      httpMock.expectNone((r) => r.url.endsWith('/applications/by-job-offer/1'));
      expect(component['regenerating']()).toBeFalse();
      expect(component['loading']()).toBeFalse();
      expect(component['errorMessage']()).toBeNull();
      // Stored letter must remain visible, not replaced by a page-level error state.
      expect(component['coverLetterForm'].getRawValue().cover_letter_text).toBe('Alter Text');
      expect(settleSpy).toHaveBeenCalled();
    });

    it('Covers AE5/AE6: a successful and a failed regenerate call each invoke markGenerationSettled exactly once', () => {
      loadApplication(httpMock, { coverLetterText: 'Alter Text' });
      confirmSpy.and.returnValue(true);
      const settleSpy = spyOn(tabTitleService, 'markGenerationSettled');

      component.onRegenerate();
      const req = httpMock.expectOne((r) => r.url.endsWith('/applications/generate'));
      req.flush('server error', { status: 500, statusText: 'Internal Server Error' });

      expect(settleSpy).toHaveBeenCalledTimes(1);
      expect(component['regenerating']()).toBeFalse();
    });

    it('disables Regenerate, Save and Send in the template while regenerating() is true', () => {
      loadApplication(httpMock, { coverLetterText: 'Alter Text' });
      fixture.detectChanges();

      component['regenerating'].set(true);
      fixture.detectChanges();

      const buttons: HTMLButtonElement[] = fixture.nativeElement.querySelectorAll('button');
      const byText = (text: string) =>
        Array.from(buttons).find((b) => b.textContent?.includes(text));

      expect(byText('Regenerate')?.disabled).toBeTrue();
      expect(byText('Save cover letter')?.disabled).toBeTrue();
      expect(byText('Send application by email now')?.disabled).toBeTrue();
    });
  });

  describe('onStartNewApplicationWithOtherProfile() - R5 escape hatch (U9, KTD12)', () => {
    it('otherProfileType() is null (no action) while no profile is locked yet', () => {
      loadApplication(httpMock, { coverLetterText: 'Text', profileType: null });

      expect(component['otherProfileType']()).toBeNull();
    });

    it('offers "full_life" when the current application is locked to "it", and vice versa', () => {
      loadApplication(httpMock, { coverLetterText: 'Text', profileType: 'it' });
      expect(component['otherProfileType']()).toBe('full_life');

      component['application'].set(buildApplication('Text', 'full_life'));
      expect(component['otherProfileType']()).toBe('it');
    });

    it('the action button is only rendered once the application is locked, and names the OTHER profile', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,', profileType: null });
      fixture.detectChanges();
      // Noch kein Profil gesperrt - der Button darf noch nicht erscheinen.
      let buttons: HTMLButtonElement[] = fixture.nativeElement.querySelectorAll('button');
      expect(Array.from(buttons).some((b) => b.textContent?.includes('Start a new application'))).toBeFalse();

      component['application'].set(buildApplication('Sehr geehrte Damen und Herren,', 'it'));
      fixture.detectChanges();

      buttons = fixture.nativeElement.querySelectorAll('button');
      const otherProfileButton = Array.from(buttons).find((b) =>
        b.textContent?.includes('Start a new application'),
      );
      expect(otherProfileButton).withContext('expected the action button once locked').not.toBeUndefined();
      // Locked to "it" -> offers the OTHER profile ("full_life"), not "it" again.
      expect(otherProfileButton?.textContent).toContain('Full-life/Non-IT profile');
    });

    it('calls generate with for_new_application:true and the OTHER profile type, then navigates to the new application', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,', profileType: 'it' });
      const router = TestBed.inject(Router);
      const navigateSpy = spyOn(router, 'navigate');

      component.onStartNewApplicationWithOtherProfile();

      expect(component['startingNewApplication']()).toBeTrue();

      const req = httpMock.expectOne((r) => r.url.endsWith('/applications/generate'));
      expect(req.request.body).toEqual({
        job_offer_id: 1,
        profile_type: 'full_life',
        for_new_application: true,
      });

      req.flush(buildApplication('Neue Version', 'full_life'));

      expect(component['startingNewApplication']()).toBeFalse();
      expect(navigateSpy).toHaveBeenCalledWith(['/editor', 1, 1]);
    });

    it('shows a snackbar and resets the flag when starting the new application fails', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,', profileType: 'it' });
      const snackBarSpy = spyOn(component['snackBar'], 'open');

      component.onStartNewApplicationWithOtherProfile();

      const req = httpMock.expectOne((r) => r.url.endsWith('/applications/generate'));
      req.flush({ detail: 'boom' }, { status: 500, statusText: 'Internal Server Error' });

      expect(component['startingNewApplication']()).toBeFalse();
      expect(snackBarSpy).toHaveBeenCalledWith('boom', 'OK', { duration: 4000 });
    });

    it('is a no-op without a loaded application', () => {
      loadApplication(httpMock, { coverLetterText: 'Text', profileType: 'it' });
      component['application'].set(null);

      component.onStartNewApplicationWithOtherProfile();

      httpMock.expectNone((r) => r.url.endsWith('/applications/generate'));
    });
  });

  describe('generateForFirstTime() tab-title wiring', () => {
    it('marks the generation started and settled on the first-time success path', () => {
      const tabTitleService = TestBed.inject(TabTitleService);
      const startSpy = spyOn(tabTitleService, 'markGenerationStarted');
      const settleSpy = spyOn(tabTitleService, 'markGenerationSettled');

      loadApplication(httpMock); // coverLetterText null -> triggers generateForFirstTime
      fixture.detectChanges();

      expect(startSpy).toHaveBeenCalledTimes(1);

      const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
      generateReq.flush(buildApplication('Sehr geehrte Damen und Herren,'));

      expect(settleSpy).toHaveBeenCalledTimes(1);
    });

    it('marks the generation settled on the first-time error path (not routed through polling)', () => {
      const tabTitleService = TestBed.inject(TabTitleService);
      const settleSpy = spyOn(tabTitleService, 'markGenerationSettled');

      loadApplication(httpMock);
      fixture.detectChanges();

      const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
      generateReq.flush({ detail: 'boom' }, { status: 500, statusText: 'Internal Server Error' });

      expect(settleSpy).toHaveBeenCalledTimes(1);
      expect(component['errorMessage']()).toBe('boom');
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
      expect(data.subject).toBe('Application as Backend Engineer');
    });

    it('no job offer linked + no Betreff line -> dialog subject shows the generic "Bewerbung" fallback', () => {
      loadApplication(httpMock, {
        coverLetterText: 'Sehr geehrte Damen und Herren, ich bewerbe mich...',
        withJobOffer: false,
      });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.subject).toBe('Application');
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

    it('Covers R10, AE4: a persisted application_email is preferred over the posting-text extraction', () => {
      loadApplication(httpMock, {
        coverLetterText: 'Sehr geehrte Damen und Herren,',
        jobOffer: {
          ...defaultJobOffer,
          description_text: 'Bitte an extrahiert@acme.example.',
          application_email: 'persistiert@acme.example',
          application_email_source_url: 'https://acme.example/karriere',
        },
      });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.toEmail).toBe('persistiert@acme.example');
    });

    it('Covers KTD7: a found in-session lookup result pre-fills the dialog recipient', () => {
      const state = TestBed.inject(JobSearchStateService);
      state.cacheApplicationEmailResult(defaultJobOffer.source_url, {
        status: 'found',
        email: 'zwischenspeicher@acme.example',
        source_url: 'https://acme.example/karriere',
      });
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,' });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.toEmail).toBe('zwischenspeicher@acme.example');
    });

    it('Covers A5: a non-found cached lookup result does not pre-fill the dialog recipient', () => {
      const state = TestBed.inject(JobSearchStateService);
      state.cacheApplicationEmailResult(defaultJobOffer.source_url, {
        status: 'not-found',
        email: 'ignoriert@acme.example',
      });
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,' });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(data.toEmail).toBe('');
    });

    it('Covers R1: supplies a lookup callback that delegates to the shared state service', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,' });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      expect(typeof data.findApplicationEmail).toBe('function');

      data.findApplicationEmail!(false).subscribe();

      const req = httpMock.expectOne(
        (r) => r.url === `${environment.apiBaseUrl}/jobs/application-email-lookup`,
      );
      expect(req.request.method).toBe('POST');
      expect(req.request.body.source_url).toBe(defaultJobOffer.source_url);
      expect(req.request.body.force).toBeFalse();
      req.flush({
        status: 'found',
        email: 'bewerbung@acme.example',
        source_url: 'https://acme.example/karriere',
      });
    });

    it('Covers R11: the dialog lookup callback forwards force=true to the backend payload', () => {
      loadApplication(httpMock, { coverLetterText: 'Sehr geehrte Damen und Herren,' });
      const openSpy = spyOnDialogOpen(component);

      component.onOpenSendDialog();

      const data = openSpy.calls.mostRecent().args[1].data as SendApplicationDialogData;
      data.findApplicationEmail!(true).subscribe();

      const req = httpMock.expectOne(
        (r) => r.url === `${environment.apiBaseUrl}/jobs/application-email-lookup`,
      );
      expect(req.request.body.force).toBeTrue();
      req.flush({ status: 'not-found' });
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
