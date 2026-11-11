import { mount, flushPromises } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import OverviewPage from './OverviewPage.vue';

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('../lib/api', () => ({ api: mocks.api }));

describe('OverviewPage', () => {
  beforeEach(() => {
    mocks.api.mockReset();
    mocks.api.mockImplementation((path: string) => {
      if (path === '/dashboard/summary') return Promise.resolve({ profile: 'default', worker: 'local', jobs: { active: 2, failed: 1 } });
      if (path.startsWith('/jobs?') && path.includes('status=failed')) return Promise.resolve({ items: [{ id: 'failed-1', kind: 'storage_upload', worker: 'local', status: 'failed', error: { message: 'raw secret path', reason_code: 'TDL_UPLOAD_FAILED' }, created_at: '2026-11-11T09:00:00Z' }] });
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [{ id: 'active-1', kind: 'export', worker: 'local', status: 'running', progress: { active_file: '/workspace/private/Mengambil-file.json', message: 'raw status' } }] });
      if (path === '/jobs/metrics?scope=current') return Promise.resolve({ workers: [{ worker: 'local', status: 'busy', active_jobs: 1 }] });
      if (path === '/profiles/local') return Promise.resolve({ runtime_readiness: { checked_at: '2026-11-11T09:00:00Z', workers: [{ name: 'local', status: 'success' }], cells: [{ worker: 'local', profile: null, runtime: 'tts_helper', status: 'ready' }] } });
      throw new Error(`Unexpected API path ${path}`);
    });
  });

  it('shows active jobs, worker readiness, and recent failures from a single page load', async () => {
    const wrapper = mount(OverviewPage);
    await flushPromises();

    expect(wrapper.text()).toContain('2');
    expect(wrapper.text()).toContain('local');
    expect(wrapper.text()).toContain('Mengambil-file.json');
    expect(wrapper.text()).not.toContain('/workspace/private');
    expect(wrapper.text()).not.toContain('raw status');
    expect(wrapper.text()).toContain('storage upload');
    expect(wrapper.text()).toContain('TTS runtime siap');
    expect(wrapper.text()).toContain('Siap');
    expect(wrapper.text()).toContain('Job berjalan');
    expect(wrapper.text()).toContain('TDL_UPLOAD_FAILED');
    expect(wrapper.text()).not.toContain('raw secret path');
    expect(mocks.api).toHaveBeenCalledTimes(5);
  });

  it('reloads only after an explicit refresh and does not poll while idle', async () => {
    vi.useFakeTimers();
    const wrapper = mount(OverviewPage);
    await flushPromises();
    const callsAfterLoad = mocks.api.mock.calls.length;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(mocks.api).toHaveBeenCalledTimes(callsAfterLoad);

    await wrapper.get('button[aria-label="Muat ulang ringkasan"]').trigger('click');
    await flushPromises();
    expect(mocks.api).toHaveBeenCalledTimes(callsAfterLoad + 5);
    vi.useRealTimers();
  });

  it('keeps available sections visible when one summary endpoint is unavailable', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path === '/dashboard/summary') return Promise.resolve({ profile: 'default', worker: 'local', jobs: { active: 0, failed: 0 } });
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [] });
      if (path === '/jobs/metrics?scope=current') return Promise.reject(new Error('metrics unavailable'));
      if (path === '/profiles/local') return Promise.resolve({ runtime_readiness: { workers: [], cells: [] } });
      throw new Error(`Unexpected API path ${path}`);
    });
    const wrapper = mount(OverviewPage);
    await flushPromises();

    expect(wrapper.text()).toContain('1 bagian ringkasan belum tersedia');
    expect(wrapper.text()).toContain('default');
  });

  it('shows every service cell, including entries beyond the former compact limit', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path === '/dashboard/summary') return Promise.resolve({ profile: 'default', worker: 'local', jobs: { active: 0, failed: 0 } });
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [] });
      if (path === '/jobs/metrics?scope=current') return Promise.resolve({ workers: [{ worker: 'local', status: 'idle', active_jobs: 0 }] });
      if (path === '/profiles/local') return Promise.resolve({ runtime_readiness: { workers: [{ name: 'local', status: 'success' }], cells: Array.from({ length: 10 }, (_, index) => ({ worker: 'local', profile: `profile-${index}`, runtime: `service-${index}`, status: 'ready' })) } });
      throw new Error(`Unexpected API path ${path}`);
    });
    const wrapper = mount(OverviewPage);
    await flushPromises();

    expect(wrapper.findAll('.service-chip')).toHaveLength(10);
    expect(wrapper.text()).toContain('service-9 siap');
  });

  it('shows failed runtime cells even when the worker-level scan completed', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path === '/dashboard/summary') return Promise.resolve({ profile: 'default', worker: 'local', jobs: { active: 0, failed: 0 } });
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [] });
      if (path === '/jobs/metrics?scope=current') return Promise.resolve({ workers: [{ worker: 'remote-1', status: 'idle', active_jobs: 0 }] });
      if (path === '/profiles/local') return Promise.resolve({ runtime_readiness: {
        workers: [{ name: 'remote-1', status: 'success' }],
        cells: [
          { worker: 'remote-1', profile: 'default', runtime: 'rclone_storage', status: 'failed' },
          { worker: 'remote-1', profile: 'default', runtime: 'tts_helper', status: 'ready' }
        ]
      } });
      throw new Error(`Unexpected API path ${path}`);
    });
    const wrapper = mount(OverviewPage);
    await flushPromises();

    expect(wrapper.text()).toContain('Rclone gagal');
    expect(wrapper.text()).toContain('TTS runtime siap');
  });

  it('does not infer worker readiness from an empty job queue', async () => {
    mocks.api.mockImplementation((path: string) => {
      if (path === '/dashboard/summary') return Promise.resolve({ profile: 'default', worker: 'local', jobs: { active: 0, failed: 0 } });
      if (path.startsWith('/jobs?')) return Promise.resolve({ items: [] });
      if (path === '/jobs/metrics?scope=current') return Promise.resolve({ workers: [{ worker: 'local', status: 'idle', active_jobs: 0 }] });
      if (path === '/profiles/local') return Promise.resolve({ runtime_readiness: { workers: [], cells: [] } });
      throw new Error(`Unexpected API path ${path}`);
    });
    const wrapper = mount(OverviewPage);
    await flushPromises();

    expect(wrapper.text()).toContain('Antrean kosong');
    expect(wrapper.text()).toContain('Belum discan');
    expect(wrapper.text()).not.toContain('Siap');
  });
});
