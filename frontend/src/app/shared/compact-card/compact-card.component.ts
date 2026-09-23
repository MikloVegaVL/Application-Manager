import {
  ChangeDetectionStrategy,
  Component,
  ContentChild,
  Directive,
  EventEmitter,
  Input,
  Output,
  AfterContentChecked,
} from '@angular/core';

import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';

/**
 * Marks projected content as the Applications-only "inline attention" slot
 * (running/action-needed auto-fill state). Job search never projects into
 * it. Presence of this directive on a projected element - not just the
 * `<ng-content select>` - is how the card decides whether to render the
 * slot at all (R3/R6: everything else lives behind the `⋮` menu).
 */
@Directive({
  selector: '[inlineAttention]',
  standalone: true,
})
export class InlineAttentionDirective {}

export interface CompactCardLink {
  /** Angular route link - takes precedence over `href` when both are set. */
  routerLink?: string | unknown[];
  href?: string;
  target?: string;
  rel?: string;
}

export interface CompactCardChip {
  label: string;
}

export interface CompactCardPrimaryAction {
  label: string;
  disabled?: boolean;
  link?: CompactCardLink;
}

export interface CompactCardMenuItem {
  id: string;
  label: string;
  icon?: string;
  disabled?: boolean;
  /** Shown as a `matTooltip` when `disabled` is true, explaining why. */
  disabledReason?: string;
  link?: CompactCardLink;
}

export interface CompactCardDetailRowItem {
  label: string;
}

export interface CompactCardViewModel {
  title: string;
  company: string;
  location: string;
  /** Only the first two are rendered (R2/R6: consolidated chip row). */
  chips?: CompactCardChip[];
  snippet?: string;
  primaryAction: CompactCardPrimaryAction;
  /** Rendered in the `⋮` menu. */
  menuItems?: CompactCardMenuItem[];
  /** Non-interactive rows rendered in the `⋮` menu (e.g. sent-to email - R2). */
  detailRowItems?: CompactCardDetailRowItem[];
  /** When true, renders an accent-colored "Checked" label in the top-right
   * corner (e.g. after the ad's "Open ad" link was clicked). */
  checked?: boolean;
}

/**
 * Shared compact-card presentational shell (R1-R7, R9, R11, R12) for the
 * Applications and Job search list redesign - see
 * docs/plans/... (U1). Purely presentational: no HTTP/router providers
 * required to render or interact with it, only to *navigate* a link.
 */
@Component({
  selector: 'app-compact-card',
  standalone: true,
  imports: [
    RouterLink,
    MatButtonModule,
    MatIconModule,
    MatMenuModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
  ],
  templateUrl: './compact-card.component.html',
  styleUrl: './compact-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CompactCardComponent implements AfterContentChecked {
  @Input({ required: true }) viewModel!: CompactCardViewModel;

  /** While true: disables the primary action + `⋮` trigger, shows the busy indicator. */
  @Input() busy = false;

  @Output() primaryActionClick = new EventEmitter<void>();
  @Output() menuItemClick = new EventEmitter<string>();

  @ContentChild(InlineAttentionDirective)
  private readonly inlineAttentionRef?: InlineAttentionDirective;

  protected hasInlineAttention = false;

  ngAfterContentChecked(): void {
    this.hasInlineAttention = !!this.inlineAttentionRef;
  }

  protected get isPrimaryActionDisabled(): boolean {
    return this.busy || !!this.viewModel.primaryAction.disabled;
  }

  protected get visibleChips(): CompactCardChip[] {
    return (this.viewModel.chips ?? []).slice(0, 2);
  }

  protected onPrimaryActionClick(): void {
    if (this.isPrimaryActionDisabled) {
      return;
    }
    this.primaryActionClick.emit();
  }

  /** The link variant navigates natively; this only blocks it while disabled/busy. */
  protected onPrimaryActionLinkClick(event: MouseEvent): void {
    if (this.isPrimaryActionDisabled) {
      event.preventDefault();
    }
  }

  protected onMenuItemClick(item: CompactCardMenuItem): void {
    if (item.disabled) {
      return;
    }
    this.menuItemClick.emit(item.id);
  }

  /** Menu icons default to accent; the delete action is always warn (red). */
  protected menuItemIconColor(item: CompactCardMenuItem): 'accent' | 'warn' {
    return item.id === 'delete' ? 'warn' : 'accent';
  }
}
