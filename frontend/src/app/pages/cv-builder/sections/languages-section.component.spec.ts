import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormArray, FormGroup } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { LanguagesSectionComponent } from './languages-section.component';

describe('LanguagesSectionComponent', () => {
  let fixture: ComponentFixture<LanguagesSectionComponent>;
  let component: LanguagesSectionComponent;
  let formArray: FormArray<FormGroup>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LanguagesSectionComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(LanguagesSectionComponent);
    component = fixture.componentInstance;
    formArray = new FormArray<FormGroup>([]);
    fixture.componentRef.setInput('formArray', formArray);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('offers exactly the six CEFR levels', () => {
    expect(component['languageLevels']).toEqual(['A1', 'A2', 'B1', 'B2', 'C1', 'C2']);
  });

  it('adds a language with a name and CEFR level to the form array', () => {
    component.add();
    formArray.at(0).patchValue({ name: 'Englisch', level: 'C1' });

    expect(formArray.length).toBe(1);
    expect(formArray.at(0).getRawValue()).toEqual({ name: 'Englisch', level: 'C1' });
  });

  it('removes a language from the form array', () => {
    component.add();
    component.add();

    component.remove(0);

    expect(formArray.length).toBe(1);
  });

  it('defaults a newly added language to A1', () => {
    component.add();

    expect(formArray.at(0).get('level')?.value).toBe('A1');
  });
});
