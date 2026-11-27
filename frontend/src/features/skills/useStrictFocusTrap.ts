import { useEffect, type RefObject } from 'react';

const TABBABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'button',
  'input:not([type="hidden"])',
  'select',
  'textarea',
  'iframe',
  'audio[controls]',
  'video[controls]',
  'summary',
  '[contenteditable]:not([contenteditable="false"])',
  '[tabindex]',
].join(',');

function isTabbable(element: HTMLElement): boolean {
  if (element.tabIndex < 0 || element.hasAttribute('disabled')) return false;
  if (element.getAttribute('aria-disabled') === 'true') return false;
  if (element.closest('[inert]')) return false;

  try {
    if (element.matches(':disabled')) return false;
  } catch {
    return false;
  }

  const style = window.getComputedStyle(element);
  if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') {
    return false;
  }

  return element.getClientRects().length > 0;
}

function getTabbableElements(container: HTMLElement): HTMLElement[] {
  const elements = [...container.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR)]
    .filter(isTabbable);

  // Positive tabindex values are visited first, then the remaining elements in DOM order.
  return elements.sort((left, right) => {
    const leftOrder = left.tabIndex > 0 ? left.tabIndex : Number.MAX_SAFE_INTEGER;
    const rightOrder = right.tabIndex > 0 ? right.tabIndex : Number.MAX_SAFE_INTEGER;
    return leftOrder - rightOrder;
  });
}

/**
 * Keeps Tab and Shift+Tab inside a dialog without changing how the dialog
 * receives its initial focus or how it restores focus after closing.
 */
export function useStrictFocusTrap(active: boolean, dialogRef: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!active) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Tab' || event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) {
        return;
      }

      const dialog = dialogRef.current;
      if (!dialog) return;

      const target = event.target instanceof Node ? event.target : null;
      if (!target || !dialog.contains(target)) return;

      const focusables = getTabbableElements(dialog);
      if (!focusables.length) {
        event.preventDefault();
        dialog.focus({ preventScroll: true });
        return;
      }

      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const focused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      const focusIsInside = Boolean(focused && dialog.contains(focused));

      if (event.shiftKey) {
        if (!focusIsInside || focused === dialog || focused === first) {
          event.preventDefault();
          last.focus({ preventScroll: true });
        }
      } else if (!focusIsInside || focused === dialog || focused === last) {
        event.preventDefault();
        first.focus({ preventScroll: true });
      }
    }

    window.addEventListener('keydown', handleKeyDown, true);
    return () => window.removeEventListener('keydown', handleKeyDown, true);
  }, [active, dialogRef]);
}
