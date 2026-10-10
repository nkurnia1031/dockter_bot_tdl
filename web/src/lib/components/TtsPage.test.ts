import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import TtsPage from '../../routes/tts/+page.svelte';

describe('TTS page target controls', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('submits the selected TTS worker with the job', async () => {
    const requests: { path: string; method: string; body?: Record<string, unknown> }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
      requests.push({ path, method, body });
      if (path.endsWith('/tts/workers')) return new Response(JSON.stringify({ items: [
        { name: 'local', enabled: true, ready: true, reason_code: 'ready', helpers: [], queued_jobs: 1 },
        { name: 'remote-tts', enabled: true, ready: true, reason_code: 'ready', helpers: [], queued_jobs: 0 },
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

  it('verifies a worker sender through an operation and refreshes status manually', async () => {
    const requests: { path: string; method: string; body?: Record<string, unknown> }[] = [];
    let workerReady = false;
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const path = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined;
      requests.push({ path, method, body });
      if (path.endsWith('/tts/workers')) return new Response(JSON.stringify({ items: [{
        name: 'local', enabled: true, ready: workerReady,
        reason_code: workerReady ? 'ready' : 'tdl_access_unverified',
        helpers: [{ slot: 1, status: 'ready' }],
        verified_profiles: workerReady ? ['default'] : [],
      }] }), { status: 200 });
      if (path.endsWith('/runtime/secrets')) return new Response(JSON.stringify({ telegram_tts_chat_configured: true }), { status: 200 });
      if (path.endsWith('/tdl-access/verification') && method === 'POST') {
        return new Response(JSON.stringify({ operation_id: 'operation-1', status: 'queued', phase: 'queued', job_id: 'verify-job-1' }), { status: 202 });
      }
      if (path.endsWith('/operations/operation-1')) {
        return new Response(JSON.stringify({ operation_id: 'operation-1', status: 'succeeded', phase: 'completed', job_id: 'verify-job-1' }), { status: 200 });
      }
      if (path.endsWith('/jobs/verify-job-1')) {
        return new Response(JSON.stringify({ result: { value: { profiles: [{ profile: 'default', ready: true }] } } }), { status: 200 });
      }
      if (path.includes('/tdl-access/verification?')) {
        workerReady = true;
        return new Response(JSON.stringify({ worker: 'local', ready: true, profiles: [{ profile: 'default', ready: true }] }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(TtsPage);
    await fireEvent.click(await screen.findByRole('button', { name: 'Verifikasi akses kirim' }));
    expect(await screen.findByText(/Operation queued/)).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Muat status' }));

    expect(await screen.findByText('default: dapat mengirim')).toBeTruthy();
    await fireEvent.input(screen.getByLabelText('Judul audio'), { target: { value: 'Bab teruji' } });
    await fireEvent.input(screen.getByLabelText(/Teks/), { target: { value: 'Isi teruji' } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Buat job TTS' }).hasAttribute('disabled')).toBe(false));
    const submitted = requests.find((request) => request.path.endsWith('/tdl-access/verification') && request.method === 'POST');
    expect(submitted?.body).toEqual({ purpose: 'tts', worker: 'local' });
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
    expect(await screen.findByText(/ID chat tersimpan\. Verifikasi akses kirim untuk worker yang akan dipakai/)).toBeTruthy();
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
