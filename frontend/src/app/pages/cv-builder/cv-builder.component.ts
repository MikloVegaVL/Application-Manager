import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTabsModule } from '@angular/material/tabs';

import { ProfileService } from '../../core/services/profile.service';

type CvBuilderState = 'loading' | 'empty' | 'error' | 'ready';

/**
 * CV Builder-Seite (Lebenslauf-Editor). Baut auf dem bestehenden Master-
 * Profil auf (`GET /api/profile`) - siehe KTD9: existiert noch kein Profil
 * (HTTP 404), zeigt diese Seite einen Empty-State statt eines Formulars,
 * analog zur bestehenden 404-Behandlung in `profile.component.ts`. Ein
 * eigener "Builder legt das Profil an"-Pfad wird bewusst nicht gebaut.
 *
 * Die Tab-Inhalte (7 Content-Sektionen + Import + Vorschau & Export) sind in
 * dieser Unit nur Platzhalter und werden von nachfolgenden Units befüllt.
 */
@Component({
  selector: 'app-cv-builder',
  standalone: true,
  imports: [RouterLink, MatButtonModule, MatIconModule, MatProgressSpinnerModule, MatTabsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="cv-builder-page">
      <header class="cv-builder-page__intro">
        <h1>Lebenslauf</h1>
        <p>Inhalte für deinen Lebenslauf pflegen, per KI importieren und als Vorlage exportieren.</p>
      </header>

      @switch (state()) {
        @case ('loading') {
          <div class="cv-builder-page__loading">
            <mat-progress-spinner mode="indeterminate" diameter="48" />
            <p>Profil wird geladen ...</p>
          </div>
        }
        @case ('empty') {
          <div class="cv-builder-page__empty">
            <mat-icon>info</mat-icon>
            <p>Es wurde noch kein Profil angelegt. Bitte lege zuerst dein Profil an, bevor du den Lebenslauf bearbeitest.</p>
            <a mat-flat-button color="primary" routerLink="/profile">Zum Profil</a>
          </div>
        }
        @case ('error') {
          <div class="cv-builder-page__error">
            <mat-icon>error_outline</mat-icon>
            <p>Profil konnte nicht geladen werden.</p>
            <button
              mat-stroked-button
              type="button"
              class="cv-builder-page__retry"
              (click)="retry()"
            >
              Erneut versuchen
            </button>
          </div>
        }
        @case ('ready') {
          <mat-tab-group animationDuration="150ms">
            <mat-tab label="Zusammenfassung">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
            <mat-tab label="Berufserfahrung">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
            <mat-tab label="Ausbildung">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
            <mat-tab label="Skills">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
            <mat-tab label="Sprachen">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
            <mat-tab label="Projekte">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
            <mat-tab label="Foto">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
            <mat-tab label="Import">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
            <mat-tab label="Vorschau & Export">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
          </mat-tab-group>
        }
      }
    </div>
  `,
  styles: `
    .cv-builder-page {
      max-width: 1000px;
      margin: 0 auto;
      padding: 24px;

      &__intro {
        margin-bottom: 16px;

        h1 {
          margin: 0 0 4px;
        }

        p {
          margin: 0;
        }
      }

      &__loading,
      &__empty,
      &__error {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        padding: 64px 0;
        text-align: center;
        color: rgba(0, 0, 0, 0.6);
      }
    }

    .tab-content {
      padding: 24px 0;
    }
  `,
})
export class CvBuilderComponent implements OnInit {
  private readonly profileService = inject(ProfileService);

  protected readonly state = signal<CvBuilderState>('loading');

  ngOnInit(): void {
    this.loadProfile();
  }

  protected retry(): void {
    this.loadProfile();
  }

  private loadProfile(): void {
    this.state.set('loading');
    this.profileService.getProfile().subscribe({
      next: () => {
        this.state.set('ready');
      },
      error: (error: HttpErrorResponse) => {
        this.state.set(error.status === 404 ? 'empty' : 'error');
      },
    });
  }
}
