import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/svelte';
import RequestIndicator from './RequestIndicator.svelte';

describe('RequestIndicator', () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('shows success feedback after a mutation request', async () => {
    render(RequestIndicator);
    window.dispatchEvent(new CustomEvent('tme3:request-start', { detail: { pending: 1, mutation: true } }));
    window.dispatchEvent(new CustomEvent('tme3:request-success', { detail: { pending: 1, mutation: true } }));
    expect(await screen.findByText('Permintaan berhasil diterima.')).toBeTruthy();
  });
});
