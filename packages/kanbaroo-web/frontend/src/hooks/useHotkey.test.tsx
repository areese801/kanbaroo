import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useHotkey } from './useHotkey';

function dispatchKey(key: string, target?: EventTarget): void {
  const event = new KeyboardEvent('keydown', { key, bubbles: true });
  if (target) {
    Object.defineProperty(event, 'target', { value: target });
    target.dispatchEvent(event);
  } else {
    window.dispatchEvent(event);
  }
}

describe('useHotkey', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('fires the handler on a matching key', () => {
    const handler = vi.fn();
    renderHook(() => useHotkey('n', handler));
    dispatchKey('n');
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('does not fire when the event target is an input or textarea', () => {
    const handler = vi.fn();
    renderHook(() => useHotkey('n', handler));
    const input = document.createElement('input');
    document.body.appendChild(input);
    try {
      input.focus();
      dispatchKey('n', input);
      const textarea = document.createElement('textarea');
      document.body.appendChild(textarea);
      textarea.focus();
      dispatchKey('n', textarea);
      textarea.remove();
    } finally {
      input.remove();
    }
    expect(handler).not.toHaveBeenCalled();
  });

  it('fires in an input when allowInInputs is true', () => {
    const handler = vi.fn();
    renderHook(() => useHotkey('Escape', handler, { allowInInputs: true }));
    const input = document.createElement('input');
    document.body.appendChild(input);
    try {
      input.focus();
      dispatchKey('Escape', input);
    } finally {
      input.remove();
    }
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('unbinds the listener on unmount', () => {
    const handler = vi.fn();
    const { unmount } = renderHook(() => useHotkey('n', handler));
    unmount();
    dispatchKey('n');
    expect(handler).not.toHaveBeenCalled();
  });

  it('does not fire when enabled is false', () => {
    const handler = vi.fn();
    renderHook(() => useHotkey('n', handler, { enabled: false }));
    dispatchKey('n');
    expect(handler).not.toHaveBeenCalled();
  });

  it('ignores key events while Ctrl/Meta/Alt are held', () => {
    const handler = vi.fn();
    renderHook(() => useHotkey('n', handler));
    const event = new KeyboardEvent('keydown', { key: 'n', ctrlKey: true });
    window.dispatchEvent(event);
    expect(handler).not.toHaveBeenCalled();
  });
});
