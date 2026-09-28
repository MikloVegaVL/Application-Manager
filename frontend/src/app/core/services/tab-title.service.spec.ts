import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';

import { TabTitleService } from './tab-title.service';

/**
 * Minimal stand-in for `Document` exposing only what `TabTitleService` reads
 * (title, visibilityState) and the `visibilitychange` listener registration.
 * No existing service spec in this repo stubs `DOCUMENT`, so this follows the
 * standard Angular `TestBed` DI-override pattern instead of a repo convention.
 */
function createFakeDocument(title: string, visibilityState: DocumentVisibilityState = 'visible') {
  const listeners: Array<() => void> = [];

  return {
    title,
    visibilityState,
    // Stubbed only so Angular's own TestBed teardown (DOMTestComponentRenderer,
    // which also reads the DOCUMENT token) doesn't blow up between tests -
    // TabTitleService itself never calls this.
    querySelectorAll: () => [],
    addEventListener: (type: string, listener: () => void) => {
      if (type === 'visibilitychange') {
        listeners.push(listener);
      }
    },
    removeEventListener: (type: string, listener: () => void) => {
      if (type === 'visibilitychange') {
        const index = listeners.indexOf(listener);
        if (index !== -1) {
          listeners.splice(index, 1);
        }
      }
    },
    fireVisibilityChange(newState: DocumentVisibilityState) {
      this.visibilityState = newState;
      [...listeners].forEach((listener) => listener());
    },
    listenerCount: () => listeners.length,
  };
}

type FakeDocument = ReturnType<typeof createFakeDocument>;

describe('TabTitleService', () => {
  let fakeDocument: FakeDocument;

  function setup(title: string, visibilityState: DocumentVisibilityState = 'visible') {
    fakeDocument = createFakeDocument(title, visibilityState);
    TestBed.configureTestingModule({
      providers: [{ provide: DOCUMENT, useValue: fakeDocument }],
    });
    return TestBed.inject(TabTitleService);
  }

  it('Covers AE5: leaves the title unchanged while a generation is in flight, then applies the completion prefix once it settles while the tab is hidden', () => {
    const service = setup('Original Title', 'hidden');

    service.markGenerationStarted();
    expect(fakeDocument.title).toBe('Original Title');

    service.markGenerationSettled();

    expect(fakeDocument.title).not.toBe('Original Title');
    expect(fakeDocument.title.endsWith('Original Title')).toBe(true);
  });

  it('Covers AE6: applies the same completion indicator on a failed generation (settle has one code path for success and failure)', () => {
    const service = setup('Original Title', 'hidden');

    service.markGenerationStarted();
    service.markGenerationSettled();

    expect(fakeDocument.title).not.toBe('Original Title');
  });

  it('does nothing to the title when the tab stays visible throughout', () => {
    const service = setup('Original Title', 'visible');

    service.markGenerationStarted();
    service.markGenerationSettled();

    expect(fakeDocument.title).toBe('Original Title');
  });

  it('reverts the title to its original value once the tab becomes visible again', () => {
    const service = setup('Original Title', 'hidden');

    service.markGenerationStarted();
    service.markGenerationSettled();
    expect(fakeDocument.title).not.toBe('Original Title');

    fakeDocument.fireVisibilityChange('visible');

    expect(fakeDocument.title).toBe('Original Title');
  });

  it('does not nest the prefix and strips exactly one prefix on revert when a second request settles while the indicator is already showing', () => {
    const service = setup('Original Title', 'hidden');

    // First cycle settles and applies the indicator.
    service.markGenerationStarted();
    service.markGenerationSettled();
    const titleAfterFirstSettle = fakeDocument.title;
    expect(titleAfterFirstSettle).not.toBe('Original Title');

    // Second cycle starts and settles before the user has returned to the tab.
    service.markGenerationStarted();
    service.markGenerationSettled();

    // The indicator must not be re-applied on top of itself.
    expect(fakeDocument.title).toBe(titleAfterFirstSettle);
    expect(fakeDocument.listenerCount()).toBe(1);

    fakeDocument.fireVisibilityChange('visible');

    expect(fakeDocument.title).toBe('Original Title');
    expect(fakeDocument.listenerCount()).toBe(0);
  });

  it('strips the prefix from whatever document.title currently holds, not a stored snapshot, when it changed underneath while hidden (e.g. a route navigation)', () => {
    const service = setup('Original Title', 'hidden');

    service.markGenerationStarted();
    service.markGenerationSettled();
    expect(fakeDocument.title).not.toBe('Original Title');

    // Simulate Angular Router's title strategy fully overwriting document.title
    // (e.g. a navigation to a different route) while the tab is still hidden -
    // this wipes out the prefix the service applied.
    fakeDocument.title = 'New Route Title';

    fakeDocument.fireVisibilityChange('visible');

    // Must not reinstate the stale "Original Title" snapshot captured at
    // settle time - the router's newer title wins since no prefix remains
    // to strip.
    expect(fakeDocument.title).toBe('New Route Title');
  });

  it('strips the prefix from a title whose non-prefix portion changed while hidden, not the value captured at settle time', () => {
    const service = setup('Original Title', 'hidden');

    service.markGenerationStarted();
    service.markGenerationSettled();
    const prefix = fakeDocument.title.slice(0, fakeDocument.title.length - 'Original Title'.length);
    expect(prefix.length).toBeGreaterThan(0);

    // Something else rewrote the title but the prefix is still present as the
    // service left it (e.g. re-applied by another writer using the same
    // scheme) - the base content changed underneath.
    fakeDocument.title = `${prefix}Different Route Title`;

    fakeDocument.fireVisibilityChange('visible');

    expect(fakeDocument.title).toBe('Different Route Title');
  });
});
