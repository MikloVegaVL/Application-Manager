import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';

/**
 * Fixed marker prepended to `document.title` to signal that a generation
 * settled while the tab was hidden. Applied as a prefix (not a full string
 * swap) so it can always be stripped from whatever `document.title` holds at
 * revert time - see the class doc for why that matters.
 */
const COMPLETION_PREFIX = '✓ ';

/**
 * Signals cover-letter generation completion via the browser tab title when
 * the tab is unfocused, mirroring `ThemeService`'s DI style
 * (`providedIn: 'root'`, `inject(DOCUMENT)`, signal-based internal state).
 *
 * In-flight state is tracked per outstanding HTTP request via
 * `markGenerationStarted` / `markGenerationSettled`, not per component
 * instance or component lifecycle - callers invoke these directly around a
 * generation call, so navigating away before the request settles can't
 * strand the service in an "in flight" state.
 *
 * Every route in this app declares a `title:` that Angular's Router title
 * strategy also writes to `document.title` on navigation - a second writer
 * of the same property. Rather than snapshotting `document.title` at settle
 * time and restoring that snapshot later (which would reinstate a stale
 * title if the user had since navigated to a different route while
 * backgrounded), the completion indicator is a fixed, known prefix: on
 * revert, that prefix is stripped from whatever `document.title` currently
 * holds. If a route navigation overwrote the title in the meantime (and with
 * it, the prefix), there is nothing to strip and the newer title is left
 * alone.
 */
@Injectable({ providedIn: 'root' })
export class TabTitleService {
  private readonly document = inject(DOCUMENT);
  private readonly inFlightCount = signal(0);
  private visibilityListener: (() => void) | null = null;

  /** Call when a generation request (first-time or Regenerate) is sent. */
  markGenerationStarted(): void {
    this.inFlightCount.update((count) => count + 1);
  }

  /** Call when that request settles - on success or on failure alike. */
  markGenerationSettled(): void {
    this.inFlightCount.update((count) => Math.max(0, count - 1));

    if (this.document.visibilityState !== 'hidden') {
      return;
    }
    if (this.document.title.startsWith(COMPLETION_PREFIX)) {
      // Indicator is already showing from an earlier settle that hasn't
      // been dismissed yet - leave it as-is. Re-applying here would nest
      // prefixes and reverting would then strip the wrong "clean" value.
      return;
    }

    this.document.title = COMPLETION_PREFIX + this.document.title;
    this.listenForReturnToTab();
  }

  private listenForReturnToTab(): void {
    if (this.visibilityListener) {
      return;
    }

    this.visibilityListener = () => {
      if (this.document.visibilityState === 'hidden') {
        return;
      }

      if (this.document.title.startsWith(COMPLETION_PREFIX)) {
        this.document.title = this.document.title.slice(COMPLETION_PREFIX.length);
      }

      this.document.removeEventListener('visibilitychange', this.visibilityListener!);
      this.visibilityListener = null;
    };

    this.document.addEventListener('visibilitychange', this.visibilityListener);
  }
}
