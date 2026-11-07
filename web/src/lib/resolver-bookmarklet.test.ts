import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it, vi } from 'vitest';

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const documentation = readFileSync(resolve(repositoryRoot, 'docs/resolver-bookmarklet.md'), 'utf8');
const bookmarklet = documentation.match(/```bookmarklet\s*([\s\S]*?)```/)?.[1]?.trim();

interface FakeElement {
  tagName: string;
  textContent: string;
  value: string;
  style: { cssText: string };
  children: FakeElement[];
  listeners: Record<string, () => void | Promise<void>>;
  addEventListener: (name: string, callback: () => void | Promise<void>) => void;
  appendChild: (child: FakeElement) => FakeElement;
  setAttribute: (name: string, value: string) => void;
}

function element(tagName: string): FakeElement {
  const value: FakeElement = {
    tagName,
    textContent: '',
    value: '',
    style: { cssText: '' },
    children: [],
    listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
    appendChild(child) { this.children.push(child); return child; },
    setAttribute() {}
  };
  return value;
}

function runBookmarklet({
  url,
  page,
  stepText,
  bodyText,
  response,
  stepButtonAvailable,
}: {
  url: string;
  page?: Record<string, unknown> | null;
  stepText?: string;
  bodyText?: string;
  response?: Record<string, unknown>;
  stepButtonAvailable?: boolean;
}) {
  if (!bookmarklet) throw new Error('Copyable bookmarklet is missing from its documentation.');
  const parsedUrl = new URL(url);
  const outputs: FakeElement[] = [];
  const stepControl = stepButtonAvailable ? {
    disabled: false,
    getAttribute: () => null,
    getClientRects: () => [{}],
    click: vi.fn()
  } : null;
  const currentPage = page === undefined ? {
    fingerprint: { id: 'component-1', name: 'pages.show' },
    serverMemo: { data: { phase: 0, captcha: false, hasCaptcha: false }, checksum: 'test-checksum' }
  } : page;
  const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
    ok: true,
    status: 200,
    json: async () => response || {
      effects: { emits: [{ event: 'setLink', params: ['https://invest.datapendidikan.com/step/2'] }] }
    }
  }));
  const location = {
    href: parsedUrl.href,
    origin: parsedUrl.origin,
    hostname: parsedUrl.hostname,
    assign: vi.fn()
  };
  const document = {
    documentElement: { innerHTML: "<script>window.livewire_token='csrf-test'</script>" },
    body: {
      innerText: bodyText || stepText || 'Step 1/5',
      textContent: bodyText || stepText || 'Step 1/5',
      appendChild: (child: FakeElement) => outputs.push(child)
    },
    querySelector(selector: string) {
      if (selector === '[wire\\:initial-data]') {
        return currentPage ? { getAttribute: () => JSON.stringify(currentPage) } : null;
      }
      if (selector === '.step-btn') return stepControl;
      return null;
    },
    getElementById: () => null,
    execCommand: vi.fn(() => true),
    createElement: (tagName: string) => element(tagName)
  };
  const copied: string[] = [];
  const navigator = { clipboard: { writeText: vi.fn(async (text: string) => copied.push(text)) } };
  const execute = new Function(
    'window', 'document', 'fetch', 'navigator', 'URL', 'URLSearchParams', 'atob', 'TextDecoder',
    `return ${bookmarklet.replace(/^javascript:/i, '')};`
  ) as (...args: unknown[]) => Promise<void>;
  const pending = execute(
    { location },
    document,
    fetch,
    navigator,
    URL,
    URLSearchParams,
    (value: string) => Buffer.from(value, 'base64').toString('binary'),
    TextDecoder
  );
  return { pending, fetch, location, outputs, copied, navigator, stepControl };
}

describe('copyable Safelink bookmarklet', () => {
  it('is a compact single-line JavaScript URL ready to paste into a bookmark', () => {
    expect(bookmarklet).toBeDefined();
    expect(bookmarklet).not.toMatch(/[\r\n]/);
    expect(bookmarklet?.length).toBeLessThan(7000);
  });

  it('advances one phase across previously unlisted gate domains', async () => {
    const result = runBookmarklet({
      url: 'https://new-shortlink.example.test/step/1',
      response: { effects: { emits: [{ event: 'setLink', params: ['https://new-gate.example.test/step/2'] }] } }
    });

    await result.pending;

    expect(result.fetch).toHaveBeenCalledTimes(1);
    expect(result.fetch.mock.calls[0]?.[0]).toBe('https://new-shortlink.example.test/livewire/message/pages.show');
    expect(result.fetch.mock.calls[0]?.[1]?.redirect).toBe('error');
    expect(result.location.assign).toHaveBeenCalledWith('https://new-gate.example.test/step/2');
    expect(result.outputs).toHaveLength(0);
  });

  it('shows and copies the final URL without opening it or calling the app backend', async () => {
    const destination = 'https://files.example.test/archive.zip';
    const result = runBookmarklet({
      url: 'https://new-shortlink.example.test/step/5',
      stepText: 'Step 5/5',
      page: {
        fingerprint: { id: 'component-5', name: 'pages.show' },
        serverMemo: { data: { phase: 5, captcha: false, hasCaptcha: false }, checksum: 'test-checksum' }
      },
      response: { effects: { emits: [{ event: 'setLink', params: [destination] }] } }
    });

    await result.pending;

    expect(result.fetch).toHaveBeenCalledTimes(1);
    expect(result.fetch.mock.calls[0]?.[0]).toBe('https://new-shortlink.example.test/livewire/message/pages.show');
    const requestBody = JSON.parse(String(result.fetch.mock.calls[0]?.[1]?.body || '{}'));
    expect(requestBody.updates[0].payload.event).toBe('getData');
    expect(result.location.assign).not.toHaveBeenCalled();
    expect(result.outputs).toHaveLength(1);
    const output = result.outputs[0]!;
    const input = output.children.find((child) => child.tagName === 'input');
    const copy = output.children.find((child) => child.tagName === 'button');
    expect(input?.value).toBe(destination);
    await copy?.listeners.click?.();
    expect(result.navigator.clipboard.writeText).toHaveBeenCalledWith(destination);
    expect(result.copied).toEqual([destination]);
    expect(result.fetch.mock.calls.every(([target]) => String(target).startsWith('https://new-shortlink.example.test/'))).toBe(true);
  });

  it('asks the user to handle a CAPTCHA even when the interstitial has no Livewire state', async () => {
    const result = runBookmarklet({
      url: 'https://invest.datapendidikan.com/captcha',
      page: null,
      bodyText: 'Complete this CAPTCHA to continue'
    });

    await result.pending;

    expect(result.fetch).not.toHaveBeenCalled();
    expect(result.outputs[0]?.children.find((child) => child.tagName === 'p')?.textContent)
      .toContain('Selesaikan CAPTCHA secara manual');
  });

  it('waits for the Cloudflare browser challenge before processing the Safelink page', async () => {
    const result = runBookmarklet({
      url: 'https://crm.urlwebsite.com/v/example',
      page: null,
      bodyText: 'Just a moment... Enable JavaScript and cookies to continue',
      stepButtonAvailable: true
    });

    await result.pending;

    expect(result.fetch).not.toHaveBeenCalled();
    expect(result.stepControl?.click).not.toHaveBeenCalled();
    expect(result.outputs[0]?.children.find((child) => child.tagName === 'p')?.textContent)
      .toContain('Cloudflare');
    expect(result.outputs[0]?.children.find((child) => child.tagName === 'p')?.textContent)
      .toContain('jalankan bookmarklet lagi');
  });

  it('clicks one visible step button when the gate page has no Livewire state', async () => {
    const result = runBookmarklet({
      url: 'https://new-shortlink.example.test/step/1',
      page: null,
      bodyText: 'Step 1/5 Click to verify',
      stepButtonAvailable: true
    });

    await result.pending;

    expect(result.stepControl?.click).toHaveBeenCalledTimes(1);
    expect(result.fetch).not.toHaveBeenCalled();
    expect(result.outputs[0]?.children.find((child) => child.tagName === 'p')?.textContent)
      .toContain('Tombol verifikasi diklik');
  });
});
