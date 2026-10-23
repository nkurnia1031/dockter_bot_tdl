import { describe, expect, it } from 'vitest';
import {
  chooseProfileWorker,
  normalizeLocalProfileCatalog,
  normalizeRuntimeReadiness,
  profileOptionLabel,
  profileOptionsForWorker,
  runtimeReadinessFor
} from './profile-catalog';

describe('verified local profile catalog helpers', () => {
  const profiles = normalizeLocalProfileCatalog({ profiles: [
    { name: 'shared', workers: ['local', 'remote-1'], exclusive_worker: '' },
    { name: 'remote-only', workers: ['remote-1'], exclusive_worker: 'remote-1' },
    { name: 'unavailable', workers: [] }
  ] });

  it('labels exclusive profiles with their owner and filters shared profiles by worker', () => {
    expect(profileOptionLabel(profiles[0])).toBe('remote-only (remote-1)');
    expect(profileOptionsForWorker(profiles, 'local').map((item) => item.name)).toEqual(['shared']);
  });

  it('pins exclusive profiles and keeps or selects only a verified shared worker', () => {
    expect(chooseProfileWorker(profiles[0], 'local')).toBe('remote-1');
    expect(chooseProfileWorker(profiles[1], 'local')).toBe('local');
    expect(chooseProfileWorker(profiles[1], 'remote-1')).toBe('remote-1');
  });

  it('reads persisted Export readiness separately from worker reachability', () => {
    const snapshot = normalizeRuntimeReadiness({
      workers: [
        { name: 'local', status: 'success', checked_at: 'scan-1' },
        { name: 'remote', status: 'failed', checked_at: 'scan-1', reason_code: 'WORKER_UNAVAILABLE' }
      ],
      cells: [
        { worker: 'local', profile: 'default', runtime: 'export', status: 'ready', checked_at: 'scan-1', fingerprint: 'private' },
        { worker: 'local', profile: 'archive', runtime: 'export', status: 'not_ready', checked_at: 'scan-1', reason_code: 'PROFILE_SESSION_TDL_INVALID' },
        { worker: 'local', profile: null, runtime: 'utility', status: 'ready', checked_at: 'scan-1', fingerprint: 'private' }
      ]
    });

    expect(runtimeReadinessFor(snapshot, 'default', 'local').status).toBe('ready');
    expect(runtimeReadinessFor(snapshot, 'archive', 'local')).toMatchObject({
      status: 'not_ready', reason_code: 'PROFILE_SESSION_TDL_INVALID'
    });
    expect(runtimeReadinessFor(snapshot, 'default', 'remote').status).toBe('offline');
    expect(runtimeReadinessFor(snapshot, 'missing', 'local').status).toBe('unscanned');
    expect(runtimeReadinessFor(snapshot, null, 'local', 'utility').status).toBe('ready');
    expect(JSON.stringify(snapshot)).not.toContain('fingerprint');
  });
});
