/**
 * KTD12: strukturelle Gleichheit für einen CV-Builder-Sektionswert (ein
 * einzelnes Feld wie `summary` oder ein Array von Einträgen wie
 * `experiences_json`) - `null` und `""` gelten als gleich, und die
 * Reihenfolge von Array-Elementen wird ignoriert (Feld-für-Feld-Vergleich).
 *
 * Genutzt sowohl vom Re-Import-Konfliktcheck (R13, siehe
 * `import/cv-import.component.ts`) als auch vom `CanDeactivate`-Guard/
 * `beforeunload`-Schutz (R14/KTD13, siehe `cv-builder.guard.ts` und
 * `cv-builder.component.ts`) - bewusst eine kleine handgeschriebene
 * Funktion statt einer Deep-Equal-Bibliothek, da der Vergleich nur auf die
 * wenigen, bereits als JSON-kompatibel bekannten CV-Builder-Formularwerte
 * angewendet wird (Strings, `null`, Arrays von flachen Objekten).
 */
function normalizeForComparison(value: unknown): unknown {
  if (value === null || value === undefined || value === '') {
    return null;
  }

  if (Array.isArray(value)) {
    // Jedes Element normalisieren + stringifizieren, dann sortieren, damit
    // die Array-Reihenfolge beim Vergleich egal ist (siehe Moduldokumentation
    // oben). Die Strings bleiben Strings - `sectionsEqual` stringifiziert das
    // Gesamtergebnis ohnehin noch einmal, ein Parse zurück in Objekte nur um
    // sie gleich wieder zu stringifizieren wäre reine Verschwendung.
    return value.map((item) => JSON.stringify(normalizeForComparison(item))).sort();
  }

  if (typeof value === 'object') {
    const source = value as Record<string, unknown>;
    const normalized: Record<string, unknown> = {};
    for (const key of Object.keys(source).sort()) {
      normalized[key] = normalizeForComparison(source[key]);
    }
    return normalized;
  }

  return value;
}

/** Vergleicht zwei Sektionswerte strukturell (siehe Modul-Dokumentation oben). */
export function sectionsEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(normalizeForComparison(a)) === JSON.stringify(normalizeForComparison(b));
}
