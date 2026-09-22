import { Component, DebugElement, getDebugNode } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatTooltip } from '@angular/material/tooltip';

import {
  CompactCardComponent,
  CompactCardViewModel,
  InlineAttentionDirective,
} from './compact-card.component';
import { cleanupCompactCardOverlays, openCompactCardMenu } from './compact-card-test-helpers';

function baseViewModel(overrides: Partial<CompactCardViewModel> = {}): CompactCardViewModel {
  return {
    title: 'Backend Engineer',
    company: 'Acme GmbH',
    location: 'Berlin, Germany',
    primaryAction: { label: 'Generate letter' },
    ...overrides,
  };
}

describe('CompactCardComponent', () => {
  let fixture: ComponentFixture<CompactCardComponent>;
  let component: CompactCardComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CompactCardComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(CompactCardComponent);
    component = fixture.componentInstance;
  });

  afterEach(() => {
    cleanupCompactCardOverlays();
  });

  function setViewModel(viewModel: CompactCardViewModel, busy = false): void {
    fixture.componentRef.setInput('viewModel', viewModel);
    fixture.componentRef.setInput('busy', busy);
    fixture.detectChanges();
  }

  it('renders header fields from the view-model input', () => {
    setViewModel(baseViewModel());

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Backend Engineer');
    expect(text).toContain('Acme GmbH');
    expect(text).toContain('Berlin, Germany');
  });

  it('renders at most 2 chips even when more are supplied', () => {
    setViewModel(
      baseViewModel({
        chips: [{ label: 'Remote' }, { label: 'Full-time' }, { label: 'Senior' }],
      }),
    );

    const chips = fixture.nativeElement.querySelectorAll('.compact-card__chip');
    expect(chips.length).toBe(2);
    expect(chips[0].textContent).toContain('Remote');
    expect(chips[1].textContent).toContain('Full-time');
  });

  it('renders the snippet only when provided', () => {
    setViewModel(baseViewModel());
    expect(fixture.nativeElement.querySelector('.compact-card__snippet')).toBeNull();

    setViewModel(baseViewModel({ snippet: 'Great opportunity for a backend role.' }));
    const snippet = fixture.nativeElement.querySelector('.compact-card__snippet');
    expect(snippet?.textContent).toContain('Great opportunity for a backend role.');
  });

  it('renders the primary action label and emits primaryActionClick on click', () => {
    setViewModel(baseViewModel({ primaryAction: { label: 'Generate letter' } }));

    const button = fixture.nativeElement.querySelector(
      '.compact-card__primary-action',
    ) as HTMLButtonElement;
    expect(button.tagName).toBe('BUTTON');
    expect(button.textContent).toContain('Generate letter');

    const emitted: void[] = [];
    component.primaryActionClick.subscribe(() => emitted.push(undefined));
    button.click();

    expect(emitted.length).toBe(1);
  });

  it('renders the primary action as a native anchor when the view-model supplies a link', () => {
    setViewModel(
      baseViewModel({
        primaryAction: { label: 'View job', link: { href: 'https://example.com/job/1' } },
      }),
    );

    const anchor = fixture.nativeElement.querySelector(
      '.compact-card__primary-action',
    ) as HTMLAnchorElement;
    expect(anchor.tagName).toBe('A');
    expect(anchor.getAttribute('href')).toBe('https://example.com/job/1');

    const emitted: void[] = [];
    component.primaryActionClick.subscribe(() => emitted.push(undefined));
    anchor.click();

    // Native navigation, not a synthetic click through the component's output.
    expect(emitted.length).toBe(0);
  });

  it('opens the ⋮ menu on trigger click and emits menuItemClick for an enabled item', async () => {
    setViewModel(
      baseViewModel({
        menuItems: [{ id: 'archive', label: 'Archive' }],
      }),
    );

    await openCompactCardMenu(fixture);

    const menuItem = document.querySelector('.mat-mdc-menu-item') as HTMLButtonElement;
    expect(menuItem).toBeTruthy();
    expect(menuItem.textContent).toContain('Archive');

    const emitted: string[] = [];
    component.menuItemClick.subscribe((id) => emitted.push(id));
    menuItem.click();

    expect(emitted).toEqual(['archive']);
  });

  it('does not emit menuItemClick for a disabled menu item and renders a tooltip explaining why', async () => {
    setViewModel(
      baseViewModel({
        menuItems: [
          {
            id: 'delete',
            label: 'Delete',
            disabled: true,
            disabledReason: 'Cannot delete a sent application',
          },
        ],
      }),
    );

    await openCompactCardMenu(fixture);

    const menuItem = document.querySelector('.mat-mdc-menu-item') as HTMLButtonElement;
    expect(menuItem).toBeTruthy();
    expect(menuItem.disabled).toBe(true);

    const emitted: string[] = [];
    component.menuItemClick.subscribe((id) => emitted.push(id));
    menuItem.click();
    expect(emitted.length).toBe(0);

    // The menu panel is portaled to document.body via the CDK overlay, so
    // it's not reachable through fixture.debugElement - resolve its
    // DebugElement via Angular's node registry instead.
    const menuItemDebugEl = getDebugNode(menuItem) as DebugElement;
    const tooltip = menuItemDebugEl.injector.get(MatTooltip);
    expect(tooltip.disabled).toBe(false);
    expect(tooltip.message).toBe('Cannot delete a sent application');
  });

  it('renders a detail-row item as non-interactive content that never emits menuItemClick', async () => {
    setViewModel(
      baseViewModel({
        detailRowItems: [{ label: 'Sent to: recruiter@example.com' }],
      }),
    );

    await openCompactCardMenu(fixture);

    const detailRow = document.querySelector('.compact-card__menu-detail-row');
    expect(detailRow?.textContent).toContain('Sent to: recruiter@example.com');
    expect(detailRow?.tagName).not.toBe('BUTTON');

    const emitted: string[] = [];
    component.menuItemClick.subscribe((id) => emitted.push(id));
    (detailRow as HTMLElement).click();

    expect(emitted.length).toBe(0);
  });

  it('disables the primary action and ⋮ trigger and shows the busy indicator when busy', () => {
    setViewModel(baseViewModel(), true);

    const button = fixture.nativeElement.querySelector(
      '.compact-card__primary-action',
    ) as HTMLButtonElement;
    const trigger = fixture.nativeElement.querySelector(
      '.compact-card__menu-trigger',
    ) as HTMLButtonElement;

    expect(button.disabled).toBe(true);
    expect(trigger.disabled).toBe(true);
    expect(fixture.nativeElement.querySelector('.compact-card__busy')).toBeTruthy();
  });

  it('shows no busy indicator and enabled controls when busy is absent/false', () => {
    setViewModel(baseViewModel());

    const button = fixture.nativeElement.querySelector(
      '.compact-card__primary-action',
    ) as HTMLButtonElement;
    const trigger = fixture.nativeElement.querySelector(
      '.compact-card__menu-trigger',
    ) as HTMLButtonElement;

    expect(button.disabled).toBe(false);
    expect(trigger.disabled).toBe(false);
    expect(fixture.nativeElement.querySelector('.compact-card__busy')).toBeNull();
  });
});

@Component({
  standalone: true,
  imports: [CompactCardComponent, InlineAttentionDirective],
  template: `
    <app-compact-card [viewModel]="viewModel">
      <div inlineAttention class="attention-marker">Auto-filling application…</div>
    </app-compact-card>
  `,
})
class HostWithInlineAttentionComponent {
  viewModel = baseViewModel();
}

@Component({
  standalone: true,
  imports: [CompactCardComponent],
  template: `<app-compact-card [viewModel]="viewModel"></app-compact-card>`,
})
class HostWithoutInlineAttentionComponent {
  viewModel = baseViewModel();
}

describe('CompactCardComponent inline-attention projection', () => {
  it('renders the projected inline-attention content when provided', () => {
    const fixture = TestBed.configureTestingModule({
      imports: [HostWithInlineAttentionComponent, NoopAnimationsModule],
    }).createComponent(HostWithInlineAttentionComponent);
    fixture.detectChanges();

    const wrapper = fixture.nativeElement.querySelector('.compact-card__inline-attention');
    expect(wrapper).toBeTruthy();
    expect(wrapper.querySelector('.attention-marker')?.textContent).toContain(
      'Auto-filling application…',
    );
  });

  it('omits the inline-attention slot entirely when nothing is projected', () => {
    const fixture = TestBed.configureTestingModule({
      imports: [HostWithoutInlineAttentionComponent, NoopAnimationsModule],
    }).createComponent(HostWithoutInlineAttentionComponent);
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.compact-card__inline-attention')).toBeNull();
  });
});
