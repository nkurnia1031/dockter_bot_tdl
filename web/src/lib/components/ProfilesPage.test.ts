import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import ProfilesPage from './ProfilesPage.svelte';

describe('ProfilesPage', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('uploads a TDL session ZIP to the selected secure worker', async () => {
    const requests: { url: string; method: string; body?: BodyInit | null }[] = [];
    let managementCalls = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method || 'GET').toUpperCase();
      requests.push({ url, method, body: init?.body });
      if (url.endsWith('/profiles/management')) {
        managementCalls += 1;
        return new Response(JSON.stringify({
          items: managementCalls > 1 ? [{
            name: 'novel', active: false, status: 'distributing', vault: true,
            operation_id: 'operation-1', workers: [{ worker: 'local', status: 'waiting' }]
          }] : [],
          workers: [{ name: 'local', enabled: true, online: true, secure: true }]
        }), { status: 200 });
      }
      if (url.includes('/profiles/provisionings/upload?')) {
        return new Response(JSON.stringify({ id: 'operation-1', status: 'distributing' }), { status: 200 });
      }
      if (url.endsWith('/profiles/provisionings/operation-1')) {
        return new Response(JSON.stringify({
          id: 'operation-1', profile: 'novel', status: 'distributing', source: 'upload',
          workers: [{ worker: 'local', status: 'waiting' }]
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }));

    render(ProfilesPage);
    await screen.findByLabelText('Nama profil');
    await screen.findByRole('option', { name: 'local' });
    await fireEvent.input(screen.getByLabelText('Nama profil'), { target: { value: 'novel' } });
    await fireEvent.change(screen.getByLabelText('Worker untuk menyiapkan sesi'), { target: { value: 'local' } });
    const file = new File(['session'], 'session.zip', { type: 'application/zip' });
    await fireEvent.change(screen.getByLabelText(/ZIP berisi folder/), { target: { files: [file] } });
    const submit = screen.getByRole('button', { name: 'Validasi dan sebarkan' });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    await fireEvent.click(submit);

    expect(await screen.findByText('Sinkronisasi')).toBeTruthy();
    const upload = requests.find((item) => item.url.includes('/profiles/provisionings/upload'));
    expect(upload?.method).toBe('POST');
    expect(upload?.url).toContain('name=novel');
    expect(upload?.url).toContain('worker=local');
    expect(upload?.body).toBe(file);
  });
});
