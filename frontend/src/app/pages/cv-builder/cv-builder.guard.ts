import { CanDeactivateFn } from '@angular/router';

// `import type`, damit dieser Guard (von `app.routes.ts` NICHT lazy geladen,
// siehe `canDeactivate`) `CvBuilderComponent` und seine Abhängigkeiten nicht
// aus dem lazy Route-Chunk in den Hauptbundle zieht - nur der Typ wird
// gebraucht, kein Laufzeitwert.
import type { CvBuilderComponent } from './cv-builder.component';

/**
 * R14/KTD13: `CanDeactivate`-Guard für die Navigation weg vom CV Builder.
 * Fragt `CvBuilderComponent.hasUnsavedChanges()` - dieselbe KTD12-
 * Vergleichslogik (siehe `cv-section-diff.util.ts`) wie der Re-Import-
 * Konfliktcheck (R13), hier aber über das GESAMTE Formular statt nur die vom
 * Parse betroffenen Sektionen. Nutzt bewusst `window.confirm` statt eines
 * `MatDialog` (einfachste ausreichende Lösung für einen einzelnen Ja/Nein-
 * Hinweis). Der `beforeunload`-Schutz für Tab-Schließen/Reload lebt separat
 * in `CvBuilderComponent` (ein Router-Guard greift dort nicht).
 */
export const cvBuilderCanDeactivateGuard: CanDeactivateFn<CvBuilderComponent> = (component) => {
  if (!component.hasUnsavedChanges()) {
    return true;
  }

  return window.confirm(
    'Es gibt ungespeicherte Änderungen im Lebenslauf. Trotzdem verlassen und Änderungen verwerfen?',
  );
};
