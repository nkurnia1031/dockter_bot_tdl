const usernamePattern = /^@?([A-Za-z0-9_]{5,32})$/;
const numericPattern = /^-?\d+$/;
const phonePattern = /^\+\s*[0-9][0-9\s().-]*[0-9]$/;

/** Normalize a TDL chat selector to the peer spelling used by job payloads. */
export function normalizeTdlChatRef(raw: string): string | null {
  const value = String(raw || '').trim();
  if (!value) return null;
  if (numericPattern.test(value)) return value;
  if (phonePattern.test(value)) {
    const digits = value.replace(/\D/g, '');
    return digits.length >= 7 && digits.length <= 15 ? `+${digits}` : null;
  }
  if (/^https?:\/\//i.test(value)) {
    try {
      const url = new URL(value);
      if (!['t.me', 'www.t.me'].includes(url.hostname.toLowerCase())) return null;
      const parts = url.pathname.split('/').filter(Boolean);
      if (parts.length >= 2 && parts[0].toLowerCase() === 'c' && /^\d+$/.test(parts[1])) return parts[1];
      if (parts.length === 2 && /^\d+$/.test(parts[1])) {
        const match = parts[0].match(usernamePattern);
        return match ? match[1].toLowerCase() : null;
      }
      if (parts.length === 1) {
        const match = parts[0].match(usernamePattern);
        return match ? match[1].toLowerCase() : null;
      }
      return null;
    } catch {
      return null;
    }
  }
  const match = value.match(usernamePattern);
  return match ? match[1].toLowerCase() : null;
}

/** Bot API destinations must be numeric IDs or public usernames, not phones. */
export function normalizeBotApiChatRef(raw: string): string | null {
  const value = normalizeTdlChatRef(raw);
  if (!value || value.startsWith('+')) return null;
  if (numericPattern.test(value)) {
    try {
      const url = new URL(String(raw || '').trim());
      const parts = url.pathname.split('/').filter(Boolean);
      if (parts.length >= 2 && parts[0].toLowerCase() === 'c' && /^\d+$/.test(parts[1])) return `-100${parts[1]}`;
    } catch { /* raw is already validated by normalizeTdlChatRef */ }
    return value;
  }
  return `@${value}`;
}
