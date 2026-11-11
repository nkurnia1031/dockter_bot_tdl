# Vue migration preview

This app is a parallel Vue 3 + TypeScript + Vite preview. The SvelteKit build
remains the production UI until every route has parity and the final cutover is
approved by the migration plan.

From `web/`:

```bash
pnpm dev:vue
pnpm check:vue
pnpm test:vue
pnpm build:vue
pnpm preview:vue
```

The preview registers all current URLs. Pages not yet migrated are marked as
pending and do not replace the production route. The Vue build is emitted to
`build-vue/` and includes `200.html` for static-host deep-link fallback. It is
not published by the current static release workflow.

The browser API client reuses the same same-origin `/api/v1` contract, CSRF
header, HttpOnly session cookies, refresh behavior, and request events as the
Svelte client. CI uses mocked API responses; it does not contact production.
