import { useEffect } from 'react';

export type HotkeyOptions = {
  enabled?: boolean;
  allowInInputs?: boolean;
};

function isEditableTarget(target: EventTarget | null): boolean {
  if (!target || !(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA') {
    return true;
  }
  if (target.isContentEditable) {
    return true;
  }
  return false;
}

export function useHotkey(
  key: string,
  handler: (event: KeyboardEvent) => void,
  options: HotkeyOptions = {},
): void {
  const enabled = options.enabled !== false;
  const allowInInputs = options.allowInInputs === true;
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== key) {
        return;
      }
      if (event.ctrlKey || event.metaKey || event.altKey) {
        return;
      }
      if (!allowInInputs && isEditableTarget(event.target)) {
        return;
      }
      handler(event);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [key, handler, enabled, allowInInputs]);
}
