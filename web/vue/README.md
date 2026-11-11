# TME3Bot Web

The static control center uses Vue 3, TypeScript, Vite, and Vue Router. It keeps
the same same-origin `/api/v1` contract and is built as a static bundle for the
existing aaPanel deployment and rollback flow.

From `web/`:

```bash
pnpm dev
pnpm check
pnpm test
pnpm build
pnpm preview
```

The static bundle is emitted to `build/`. It includes `200.html` for deep-link
fallback, `build-info.json` for release validation, and the existing public
assets. The current production bundle remains active until the Vue release is
validated and explicitly deployed; deployment can then be rolled back with the
existing static release command.

The browser API client reuses the same same-origin `/api/v1` contract, CSRF
header, HttpOnly session cookies, refresh behavior, and request events as the
existing control plane. CI uses mocked API responses and local static preview;
it does not contact production.
