# Graph Report - web  (2026-07-24)

## Corpus Check
- 37 files · ~5,268 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 222 nodes · 342 edges · 24 communities (16 shown, 8 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `cf80297d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- dependencies
- devDependencies
- compilerOptions
- bff.ts
- components.json
- scripts
- components/page.tsx
- admin.tsx
- api
- app-shell.tsx
- ui.tsx
- storage.tsx
- exports.tsx
- utility/page.tsx
- next.config.ts
- next-env.d.ts
- DELETE
- GET
- PATCH
- POST
- PUT

## God Nodes (most connected - your core abstractions)
1. `api()` - 20 edges
2. `compilerOptions` - 16 edges
3. `Card()` - 11 edges
4. `Button()` - 9 edges
5. `scripts` - 8 edges
6. `PageHeader()` - 8 edges
7. `tone()` - 8 edges
8. `JobList()` - 8 edges
9. `Badge()` - 8 edges
10. `Empty()` - 8 edges

## Surprising Connections (you probably didn't know these)
- `ExportsPage()` --calls--> `api()`  [EXTRACTED]
  src/components/exports.tsx → src/lib/api.ts
- `ActivityPage()` --calls--> `api()`  [EXTRACTED]
  src/components/activity.tsx → src/lib/api.ts
- `WorkersPage()` --calls--> `api()`  [EXTRACTED]
  src/components/admin.tsx → src/lib/api.ts
- `BackupsPage()` --calls--> `tone()`  [EXTRACTED]
  src/components/admin.tsx → src/components/page.tsx
- `BackupsPage()` --calls--> `api()`  [EXTRACTED]
  src/components/admin.tsx → src/lib/api.ts

## Import Cycles
- None detected.

## Communities (24 total, 8 thin omitted)

### Community 0 - "dependencies"
Cohesion: 0.06
Nodes (33): clsx, @hookform/resolvers, lucide-react, next, next-themes, dependencies, clsx, @hookform/resolvers (+25 more)

### Community 1 - "devDependencies"
Cohesion: 0.07
Nodes (29): @axe-core/playwright, jsdom, openapi-typescript, devDependencies, @axe-core/playwright, jsdom, openapi-typescript, @playwright/test (+21 more)

### Community 2 - "compilerOptions"
Cohesion: 0.07
Nodes (27): dom, dom.iterable, esnext, .next/dev/types/**/*.ts, next-env.d.ts, .next/types/**/*.ts, node_modules, **/*.ts (+19 more)

### Community 3 - "bff.ts"
Cohesion: 0.24
Nodes (13): POST(), POST(), proxy(), GET(), PUT(), backendFetch(), clearSession(), copyResponse() (+5 more)

### Community 4 - "components.json"
Cohesion: 0.12
Nodes (15): aliases, components, hooks, lib, ui, utils, iconLibrary, rsc (+7 more)

### Community 5 - "scripts"
Cohesion: 0.15
Nodes (12): name, packageManager, private, scripts, build, dev, lint, openapi (+4 more)

### Community 6 - "components/page.tsx"
Cohesion: 0.32
Nodes (6): ActivityPage(), Job, JobList(), PageHeader(), tone(), Empty()

### Community 7 - "admin.tsx"
Cohesion: 0.21
Nodes (5): Backup, BackupsPage(), SettingsPage(), Worker, WorkersPage()

### Community 8 - "api"
Cohesion: 0.26
Nodes (7): DownloadsPage(), Overview(), Summary, api(), ApiError, csrf(), formatBytes()

### Community 9 - "app-shell.tsx"
Cohesion: 0.24
Nodes (6): metadata, Providers(), AppShell(), links, Session, Login()

### Community 10 - "ui.tsx"
Cohesion: 0.50
Nodes (5): Artifact, Badge(), Button(), Card(), cn()

### Community 11 - "storage.tsx"
Cohesion: 0.33
Nodes (4): Item, StoragePage(), ConfirmDialog(), Field()

### Community 12 - "exports.tsx"
Cohesion: 0.33
Nodes (5): ExportsPage(), Form, SavedLabel, schema, Source

## Knowledge Gaps
- **96 isolated node(s):** `$schema`, `style`, `rsc`, `tsx`, `css` (+91 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `dependencies` connect `dependencies` to `scripts`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `devDependencies` connect `devDependencies` to `scripts`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **What connects `$schema`, `style`, `rsc` to the rest of the system?**
  _96 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `dependencies` be split into smaller, more focused modules?**
  _Cohesion score 0.06060606060606061 - nodes in this community are weakly interconnected._
- **Should `devDependencies` be split into smaller, more focused modules?**
  _Cohesion score 0.06896551724137931 - nodes in this community are weakly interconnected._
- **Should `compilerOptions` be split into smaller, more focused modules?**
  _Cohesion score 0.07142857142857142 - nodes in this community are weakly interconnected._
- **Should `components.json` be split into smaller, more focused modules?**
  _Cohesion score 0.125 - nodes in this community are weakly interconnected._