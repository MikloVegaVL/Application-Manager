import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormArray, FormGroup } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { SkillsSectionComponent } from './skills-section.component';

describe('SkillsSectionComponent', () => {
  let fixture: ComponentFixture<SkillsSectionComponent>;
  let component: SkillsSectionComponent;
  let formArray: FormArray<FormGroup>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SkillsSectionComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(SkillsSectionComponent);
    component = fixture.componentInstance;
    formArray = new FormArray<FormGroup>([]);
    fixture.componentRef.setInput('formArray', formArray);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('offers exactly the four KTD3 skill levels', () => {
    expect(component['skillLevels']).toEqual(['Grundkenntnisse', 'Gut', 'Sehr gut', 'Experte']);
  });

  it('adds a skill with a name and level to the form array', () => {
    component.add();
    formArray.at(0).patchValue({ name: 'TypeScript', level: 'Experte' });

    expect(formArray.length).toBe(1);
    expect(formArray.at(0).getRawValue()).toEqual({ name: 'TypeScript', level: 'Experte' });
  });

  it('removes a skill from the form array', () => {
    component.add();
    component.add();

    component.remove(0);

    expect(formArray.length).toBe(1);
  });

  it('defaults a newly added skill to the migration-default level', () => {
    component.add();

    expect(formArray.at(0).get('level')?.value).toBe('Grundkenntnisse');
  });

  it('shows the review hint for a skill at the migration-default level', () => {
    component.add();
    formArray.at(0).patchValue({ name: 'Excel', level: 'Grundkenntnisse' });
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.skill-row__hint')).toBeTruthy();
    expect(compiled.textContent).toContain('Auto-migriert');
  });

  it('does not show the review hint for a skill at a non-default level', () => {
    component.add();
    formArray.at(0).patchValue({ name: 'TypeScript', level: 'Experte' });
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.skill-row')).toBeTruthy();
    expect(compiled.querySelector('.skill-row__hint')).toBeFalsy();
  });
});
