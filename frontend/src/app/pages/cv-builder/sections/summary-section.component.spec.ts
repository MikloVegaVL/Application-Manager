import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { SummarySectionComponent } from './summary-section.component';

describe('SummarySectionComponent', () => {
  let fixture: ComponentFixture<SummarySectionComponent>;
  let component: SummarySectionComponent;
  let control: FormControl<string>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SummarySectionComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(SummarySectionComponent);
    component = fixture.componentInstance;
    control = new FormControl('', { nonNullable: true });
    fixture.componentRef.setInput('control', control);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('renders the control value in the textarea', () => {
    control.setValue('Erfahrene Softwareentwicklerin.');
    fixture.detectChanges();

    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    expect(textarea.value).toBe('Erfahrene Softwareentwicklerin.');
  });

  it('propagates textarea input back to the control', () => {
    const textarea = fixture.nativeElement.querySelector('textarea') as HTMLTextAreaElement;
    textarea.value = 'Neuer Text';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    expect(control.value).toBe('Neuer Text');
  });
});
