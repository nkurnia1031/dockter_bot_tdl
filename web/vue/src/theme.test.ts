import { describe, expect, it } from 'vitest';
import { resolveTheme } from './theme';

describe('theme preference', () => {
  it('defaults to dark for a new browser', () => {
    expect(resolveTheme(null)).toBe('dark');
  });

  it('preserves saved light, dark, and system preferences', () => {
    expect(resolveTheme('light')).toBe('light');
    expect(resolveTheme('dark')).toBe('dark');
    expect(resolveTheme('system')).toBe('system');
    expect(resolveTheme('unknown')).toBe('dark');
  });
});
