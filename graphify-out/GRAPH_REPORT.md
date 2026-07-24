# Graph Report - dockter_bot_tdl  (2026-07-24)

## Corpus Check
- 126 files · ~48,567 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1391 nodes · 3552 edges · 64 communities (42 shown, 22 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 364 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `cf80297d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ProfileManager
- TelegramBotApp
- TDLClient
- SerialPerKeyQueue
- telegram_messages_to_json.py
- organize_media_from_json.py
- LabelStore
- bot_text.py
- UtilityHandler
- ProfileManager
- DownloadQueueWorker
- run.py
- SerialPerKeyQueue
- boltStorage
- TDLClient
- WorkerRegistry
- StorageCatalog
- find_best_combination
- config.py
- ProfileManager
- DownloadProgressTracker
- SerialPerKeyQueue
- ProfileTests
- tme3bot-leave-helper
- DomainError
- tme3bot Agent Context
- build.py
- RunScriptTests
- Path
- dependencies
- tme3bot/__init__.py
- pindah.sh script
- bff.ts
- composition.py
- ExportService
- scripts
- package.json
- next-themes
- @playwright/test
- @radix-ui/react-dropdown-menu
- recharts
- tailwind-merge
- @types/react-dom
- next.config.ts
- next-env.d.ts
- SourceState
- BatchDownloadService
- request_json
- ControlPlane
- SqliteAuthRepository
- DomainError
- GET
- PATCH
- POST
- PUT
- FakeProfiles
- next
- tme3bot
- ArchitectureBoundaryTests
- infrastructure/__init__.py

## God Nodes (most connected - your core abstractions)
1. `BackendContext` - 59 edges
2. `TelegramFrontendApp` - 54 edges
3. `StorageCatalog` - 50 edges
4. `AppConfig` - 44 edges
5. `DomainError` - 43 edges
6. `StateStore` - 42 edges
7. `SqliteJobRepository` - 39 edges
8. `ControlPlane` - 37 edges
9. `create_backend_app()` - 35 edges
10. `TDLClient` - 34 edges

## Surprising Connections (you probably didn't know these)
- `AuthServiceTests` --uses--> `BotAuthService`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `AuthServiceTests` --uses--> `SqliteAuthRepository`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `FakeProfiles` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py
- `FakeProfiles` --uses--> `Actor`  [INFERRED]
  tests/test_backend_api.py → tme3bot/domain/models.py
- `FakeProfiles` --uses--> `BotAuthService`  [INFERRED]
  tests/test_backend_api.py → tme3bot/infrastructure/auth.py

## Import Cycles
- None detected.

## Communities (64 total, 22 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.21
Nodes (11): has_downloadable_media(), is_image_message(), Any, BatchDownloadResult, BatchDownloadService, DownloadedJsonResult, media_ids_in_export(), Any (+3 more)

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.10
Nodes (11): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+3 more)

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.06
Nodes (38): Popen, ProgressCallback, Queue, FakeRunner, TDLClientTests, decode_process_output(), clean_tdl_output_line(), CommandProgress (+30 more)

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.15
Nodes (28): HTMLParser, build_orphan_group_entry(), build_reply_group_entry(), build_root_catalog(), build_root_entries(), discover_html_files(), entry_sort_key(), first_text_line() (+20 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.20
Nodes (7): _dump(), _load(), Connection, Job, Path, Row, SqliteJobRepository

### Community 6 - "LabelStore"
Cohesion: 0.16
Nodes (6): Path, ValueError, UtilityPathError, UtilityResult, UtilityRunner, _validate_size()

### Community 7 - "bot_text.py"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 8 - "UtilityHandler"
Cohesion: 0.07
Nodes (39): metadata, Providers(), ActivityPage(), Backup, BackupsPage(), SettingsPage(), Worker, WorkersPage() (+31 more)

### Community 9 - "ProfileManager"
Cohesion: 0.08
Nodes (51): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+43 more)

### Community 11 - "run.py"
Cohesion: 0.08
Nodes (22): ChannelRefTests, ProfileTests, Path, FakeExecutor, WorkerApiTests, WorkerJobRequest, create_worker_app(), _error() (+14 more)

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.13
Nodes (17): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), build_profile_config(), build_profile_runtime(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs() (+9 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "TDLClient"
Cohesion: 0.10
Nodes (12): StateStoreTests, Any, Path, utc_now_iso(), write_json_atomic(), HttpStateStore, Any, Path (+4 more)

### Community 15 - "WorkerRegistry"
Cohesion: 0.40
Nodes (3): ExportJobResult, ExportService, ParsedTme3Url

### Community 16 - "StorageCatalog"
Cohesion: 0.05
Nodes (29): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, BackupCoordinator, BackupNodeJob, datetime (+21 more)

### Community 17 - "find_best_combination"
Cohesion: 0.14
Nodes (11): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, parse_tme3_url(), ValueError (+3 more)

### Community 18 - "config.py"
Cohesion: 0.19
Nodes (30): cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory(), entry_identity() (+22 more)

### Community 19 - "ProfileManager"
Cohesion: 0.07
Nodes (27): dom, dom.iterable, esnext, .next/dev/types/**/*.ts, next-env.d.ts, .next/types/**/*.ts, node_modules, **/*.ts (+19 more)

### Community 21 - "SerialPerKeyQueue"
Cohesion: 0.12
Nodes (15): aliases, components, hooks, lib, ui, utils, iconLibrary, rsc (+7 more)

### Community 22 - "ProfileTests"
Cohesion: 0.06
Nodes (26): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, ExportArtifactCatalogTests, SerialPerKeyQueueTests, ExportArtifactCatalog (+18 more)

### Community 24 - "DomainError"
Cohesion: 0.48
Nodes (3): LeaveResult, LeaveService, TDLCommandError

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 28 - "RunScriptTests"
Cohesion: 0.09
Nodes (66): BaseModel, StorageLinkTests, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _error(), event_dict() (+58 more)

### Community 29 - "Path"
Cohesion: 0.08
Nodes (25): @axe-core/playwright, jsdom, openapi-typescript, tailwindcss, @tailwindcss/postcss, @testing-library/jest-dom, @testing-library/react, @types/node (+17 more)

### Community 30 - "dependencies"
Cohesion: 0.09
Nodes (23): clsx, @hookform/resolvers, lucide-react, @radix-ui/react-dialog, @radix-ui/react-tabs, react, react-dom, react-hook-form (+15 more)

### Community 34 - "bff.ts"
Cohesion: 0.24
Nodes (13): POST(), POST(), proxy(), GET(), PUT(), backendFetch(), clearSession(), copyResponse() (+5 more)

### Community 36 - "composition.py"
Cohesion: 0.10
Nodes (15): FakeDispatcher, FakeProfiles, FakeWorkers, UtilitySettingsTests, ControlPlane, Application facade used by every frontend adapter., Application services and use cases., BackupScheduler (+7 more)

### Community 37 - "ExportService"
Cohesion: 0.10
Nodes (13): AuthServiceTests, Path, ControlPlaneTests, FakeDispatcher, FakeProfiles, Any, Job, _redact_secrets() (+5 more)

### Community 39 - "scripts"
Cohesion: 0.25
Nodes (8): scripts, build, dev, lint, openapi, start, test, test:e2e

### Community 40 - "package.json"
Cohesion: 0.40
Nodes (4): name, packageManager, private, version

### Community 52 - "SourceState"
Cohesion: 0.28
Nodes (6): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, build_telegram_message_url(), ExportResult

### Community 53 - "BatchDownloadService"
Cohesion: 0.09
Nodes (29): CallbackContext, AppMenuTests, PendingInput, Any, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Telegram presentation adapter and UI-only helpers. (+21 more)

### Community 56 - "request_json"
Cohesion: 0.09
Nodes (9): RunScriptTests, CompletedProcess, BackendApiClient, Any, Frontend adapters. They communicate with the backend only through JSON., JsonHttpError, Any, RuntimeError (+1 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.15
Nodes (11): str, AuthChallengeStatus, BotAuthService, _hash_secret(), _now(), Any, Connection, datetime (+3 more)

### Community 59 - "DomainError"
Cohesion: 0.12
Nodes (16): Enum, Protocol, JobStoreTests, Job, ActorResolver, JobRepository, Any, Job (+8 more)

### Community 72 - "tme3bot"
Cohesion: 0.05
Nodes (40): A1. Kirim source terbaru ke VPS besar, A2. Siapkan source di VPS besar, A3. Build base image satu kali, A. Kondisi pertama: membuat base image di VPS besar, Aturan dasar, B1. Di project lokal, B2. Ekstrak base image dengan aman di project lokal, B3. Kirim source ke VPS besar (+32 more)

## Knowledge Gaps
- **142 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `$schema`, `style` (+137 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AppConfig` connect `SerialPerKeyQueue` to `ProfileManager`, `composition.py`, `run.py`, `WorkerRegistry`, `StorageCatalog`, `SourceState`, `DownloadProgressTracker`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `BatchDownloadService` to `request_json`, `TDLClient`, `run.py`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `FakeProfiles`, `composition.py`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Are the 47 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 47 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `AppConfig` (e.g. with `BackupServiceTests` and `ChannelRefTests`) actually correct?**
  _`AppConfig` has 16 INFERRED edges - model-reasoned connections that need verification._