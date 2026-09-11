import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TranslatePipe } from './translate.pipe';
import { TranslationService } from '../services/translation.service';

@Component({
  standalone: true,
  imports: [TranslatePipe],
  template: `<span>{{ 'jobSearch.title' | translate: i18n.language() }}</span>`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class HostComponent {
  protected readonly i18n = inject(TranslationService);
}

describe('TranslatePipe', () => {
  let fixture: ComponentFixture<HostComponent>;
  let i18n: TranslationService;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();

    fixture = TestBed.createComponent(HostComponent);
    i18n = TestBed.inject(TranslationService);
    fixture.detectChanges();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('renders German by default', () => {
    expect(fixture.nativeElement.textContent).toContain('Jobsuche');
  });

  it('renders English after switching the language', () => {
    i18n.setLanguage('en');
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Job search');
  });
});
