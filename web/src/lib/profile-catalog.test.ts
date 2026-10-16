import { describe, expect, it } from 'vitest';
import {
  chooseProfileWorker,
  normalizeLocalProfileCatalog,
  profileOptionLabel,
  profileOptionsForWorker
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
});
