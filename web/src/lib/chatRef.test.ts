import { describe, expect, it } from 'vitest';
import { normalizeBotApiChatRef, normalizeTdlChatRef } from './chatRef';

describe('chat reference normalization', () => {
  it('accepts TDL IDs, usernames, public links, and phone numbers', () => {
    expect(normalizeTdlChatRef('@IYear')).toBe('iyear');
    expect(normalizeTdlChatRef('iyear')).toBe('iyear');
    expect(normalizeTdlChatRef('123456789')).toBe('123456789');
    expect(normalizeTdlChatRef('https://t.me/IYear')).toBe('iyear');
    expect(normalizeTdlChatRef('+1 123456789')).toBe('+1123456789');
  });

  it('formats Bot API destinations and rejects phone targets', () => {
    expect(normalizeBotApiChatRef('-100123456789')).toBe('-100123456789');
    expect(normalizeBotApiChatRef('iyear')).toBe('@iyear');
    expect(normalizeBotApiChatRef('https://t.me/IYear')).toBe('@iyear');
    expect(normalizeBotApiChatRef('https://t.me/c/123456789/12')).toBe('-100123456789');
    expect(normalizeBotApiChatRef('+1 123456789')).toBeNull();
  });
});
