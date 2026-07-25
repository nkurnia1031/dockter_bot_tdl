import { describe, expect, it } from 'vitest';
import { formatBytes, groupIdsByWorker, textValue } from './presentation';

describe('presentation helpers', () => {
  it('never stringifies objects implicitly', () => {
    expect(textValue({ label: 'arsip' })).toBe('-');
    expect(textValue(['satu', 'dua'])).toBe('satu, dua');
  });

  it('groups artifact selection by its pinned worker', () => {
    expect([...groupIdsByWorker([
      { id: 'a', worker: 'local' },
      { id: 'b', worker: 'remote-1' },
      { id: 'c', worker: 'local' }
    ])]).toEqual([['local', ['a', 'c']], ['remote-1', ['b']]]);
    expect(formatBytes(1073741824)).toBe('1.0 GB');
  });
});
