import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TtsPage from './TtsPage.vue';

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock('../lib/api', () => ({ ...mocks }));
const monitorStub = { props: ['kind', 'title', 'retryable'], template: '<div data-testid="tts-monitor">{{ kind }} · retry={{ retryable }}</div>' };

function setupApi() {
  mocks.api.mockImplementation(async (path: string) => {
    if (path === '/tts/workers') return { items: [
      { name: 'local', enabled: true, ready: true, reason_code: 'ready', profiles: [{ profile: 'default', status: 'ready', reason_code: '' }], queued_jobs: 1 },
      { name: 'remote-tts', enabled: true, ready: false, reason_code: 'tdl_access_unverified', profiles: [{ profile: 'archive', status: 'not_ready', reason_code: 'tdl_access_unverified' }], queued_jobs: 0 }
    ] };
    if (path === '/runtime/secrets') return { telegram_tts_chat_configured: true };
    throw new Error(`Unexpected API ${path}`);
  });
  mocks.post.mockResolvedValue({ id: 'tts-job-1', status: 'queued' });
  mocks.put.mockResolvedValue({ telegram_tts_chat_configured: true, restart_required_services: [] });
}
function renderPage() { return render(TtsPage, { global: { stubs: { JobMonitor: monitorStub } } }); }

describe('TtsPage', () => {
  beforeEach(() => { vi.clearAllMocks(); setupApi(); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it('submits the selected worker and displays profile scan results as informational', async () => {
    renderPage();
    await fireEvent.change(await screen.findByLabelText('Worker untuk job ini'), { target: { value: 'remote-tts' } });
    await fireEvent.input(screen.getByLabelText('Judul audio'), { target: { value: 'Bab 1' } });
    await fireEvent.input(screen.getByLabelText(/Teks/), { target: { value: 'Teks untuk dibacakan' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Buat job TTS' }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/tts/jobs', { title: 'Bab 1', text: 'Teks untuk dibacakan', worker: 'remote-tts' }));
    expect(await screen.findByText('Job TTS masuk antrean.')).toBeTruthy();
    expect(await screen.findByText(/Hasil scan terakhir \(informasi\): archive: Belum ada hasil command terbaru/)).toBeTruthy();
    expect(mocks.api.mock.calls.some(([path]) => String(path).includes('/tdl-access/verification') || String(path).includes('/tts/health'))).toBe(false);
    expect(screen.getByTestId('tts-monitor').textContent).toContain('tts · retry=true');
  });

  it('normalizes and saves chat destination without rendering its stored value', async () => {
    renderPage();
    await fireEvent.input(await screen.findByLabelText('ID chat Telegram'), { target: { value: 'https://t.me/IYear' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Simpan ID chat' }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith('/runtime/secrets', { telegram_tts_chat_id: 'iyear' }));
    expect(await screen.findByText(/ID chat tersimpan\. Status scan dapat diperbarui/)).toBeTruthy();
    expect(screen.queryByDisplayValue('iyear')).toBeNull();
  });

  it('normalizes international phone references and validates text length before submit', async () => {
    renderPage();
    await fireEvent.input(await screen.findByLabelText('ID chat Telegram'), { target: { value: '+1 123456789' } });
    await fireEvent.click(screen.getByRole('button', { name: 'Simpan ID chat' }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledWith('/runtime/secrets', { telegram_tts_chat_id: '+1123456789' }));
    await fireEvent.input(screen.getByLabelText('Judul audio'), { target: { value: 'Bab 1' } });
    await fireEvent.input(screen.getByLabelText(/Teks/), { target: { value: 'x'.repeat(100001) } });
    expect(screen.getByRole('button', { name: 'Buat job TTS' })).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Buat job TTS' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
