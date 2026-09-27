import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import TtsPage from '../../routes/tts/+page.svelte';

describe('TTS page target controls', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('submits the selected TTS worker with the job', async () => {
    const requests: { path: string; method: string; body?: Record<string, unknown> }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
      requests.push({ path, method, body });
      if (path.endsWith('/tts/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', queued_jobs: 1 }, { name: 'remote-tts', queued_jobs: 0 },
      ] }), { status: 200 });
      if (path.endsWith('/runtime/secrets')) return new Response(JSON.stringify({ telegram_tts_chat_configured: true }), { status: 200 });
      if (path.endsWith('/tts/jobs') && method === 'POST') return new Response(JSON.stringify({ id: 'tts-job-1', status: 'queued' }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(TtsPage);
    await fireEvent.change(await screen.findByLabelText('Worker untuk job ini'), { target: { value: 'remote-tts' } });
    await fireEvent.input(screen.getByLabelText('Judul audio'), { target: { value: 'Bab 1' } });
    await fireEvent.input(screen.getByLabelText(/Teks/), { target: { value: 'Teks untuk dibacakan' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Buat job TTS' }));

    expect(await screen.findByText('Job TTS masuk antrean.')).toBeTruthy();
    expect(requests.find((request) => request.path.endsWith('/tts/jobs') && request.method === 'POST')?.body)
      .toMatchObject({ title: 'Bab 1', text: 'Teks untuk dibacakan', worker: 'remote-tts' });
  });

  it('saves the MP3 destination chat ID without exposing the saved value', async () => {
    const updates: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      if (path.endsWith('/tts/workers')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (path.endsWith('/runtime/secrets') && method === 'PUT') {
        updates.push(JSON.parse(String(init?.body || '{}')) as Record<string, unknown>);
        return new Response(JSON.stringify({ telegram_tts_chat_configured: true, restart_required_services: [] }), { status: 200 });
      }
      if (path.endsWith('/runtime/secrets')) return new Response(JSON.stringify({ telegram_tts_chat_configured: false }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(TtsPage);
    await fireEvent.input(await screen.findByLabelText('ID chat Telegram'), { target: { value: '-100123456789' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Simpan ID chat' }));

    await waitFor(() => expect(updates).toEqual([{ telegram_tts_chat_id: '-100123456789' }]));
    expect(await screen.findByText(/Job TTS berikutnya akan dikirim lewat profil TDL aktif/)).toBeTruthy();
    expect(screen.queryByDisplayValue('-100123456789')).toBeNull();
  });

  it('normalizes a public Telegram username link for TDL delivery', async () => {
    const updates: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      if (path.endsWith('/tts/workers')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (path.endsWith('/runtime/secrets') && method === 'PUT') {
        updates.push(JSON.parse(String(init?.body || '{}')) as Record<string, unknown>);
        return new Response(JSON.stringify({ telegram_tts_chat_configured: true, restart_required_services: [] }), { status: 200 });
      }
      if (path.endsWith('/runtime/secrets')) return new Response(JSON.stringify({ telegram_tts_chat_configured: false }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(TtsPage);
    await fireEvent.input(await screen.findByLabelText('ID chat Telegram'), { target: { value: 'https://t.me/IYear' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Simpan ID chat' }));

    await waitFor(() => expect(updates).toEqual([{ telegram_tts_chat_id: 'iyear' }]));
  });

  it('accepts an international phone reference for TDL delivery', async () => {
    const updates: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      if (path.endsWith('/tts/workers')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (path.endsWith('/runtime/secrets') && method === 'PUT') {
        updates.push(JSON.parse(String(init?.body || '{}')) as Record<string, unknown>);
        return new Response(JSON.stringify({ telegram_tts_chat_configured: true, restart_required_services: [] }), { status: 200 });
      }
      if (path.endsWith('/runtime/secrets')) return new Response(JSON.stringify({ telegram_tts_chat_configured: false }), { status: 200 });
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(TtsPage);
    await fireEvent.input(await screen.findByLabelText('ID chat Telegram'), { target: { value: '+1 123456789' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Simpan ID chat' }));

    await waitFor(() => expect(updates).toEqual([{ telegram_tts_chat_id: '+1123456789' }]));
  });
});
