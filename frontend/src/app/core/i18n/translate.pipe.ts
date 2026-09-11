import { Pipe, PipeTransform, inject } from '@angular/core';

import { Language } from './translations';
import { TranslationService } from '../services/translation.service';

/**
 * `{{ 'some.key' | translate: lang() }}` bzw. mit Parametern
 * `{{ 'some.key' | translate: lang() : { name: value } }}`.
 *
 * Die Sprache wird bewusst als Argument übergeben (statt den Signal-Read in
 * den Pipe zu verlagern): Das `lang()`-Signal wird im Template gelesen, markiert
 * die View bei Sprachwechsel als dirty und der reine Pipe wird mit neuem
 * Argument erneut ausgewertet - so aktualisieren sich auch OnPush-Komponenten.
 */
@Pipe({ name: 'translate', standalone: true })
export class TranslatePipe implements PipeTransform {
  private readonly translation = inject(TranslationService);

  transform(key: string, language: Language, params?: Record<string, string | number>): string {
    return this.translation.translateIn(language, key, params);
  }
}
