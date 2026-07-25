# Graph Report - dockter_bot_tdl  (2026-07-25)

## Corpus Check
- 128 files · ~52,476 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1453 nodes · 3685 edges · 74 communities (49 shown, 25 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 373 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `6c3a89dc`
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
- ExportResult
- SerialPerKeyQueue
- boltStorage
- next
- WorkerRegistry
- StorageCatalog
- composition.py
- config.py
- ProfileManager
- DownloadProgressTracker
- SerialPerKeyQueue
- ProfileTests
- tme3bot-leave-helper
- ExportService
- tme3bot Agent Context
- build.py
- TDLCommandError
- RunScriptTests
- Path
- dependencies
- tme3bot/__init__.py
- pindah.sh script
- bff.ts
- ExportArtifactCatalog
- BackupCoordinator
- ExportService
- BackupService
- scripts
- package.json
- ProfileManager
- next-themes
- @playwright/test
- @radix-ui/react-dropdown-menu
- recharts
- tailwind-merge
- @types/react-dom
- next.config.ts
- next-env.d.ts
- models.py
- ControlPlaneTests
- BatchDownloadService
- request_json
- ControlPlane
- SqliteAuthRepository
- DomainError
- GET
- PATCH
- POST
- PUT
- WorkerRegistry
- BackendApiTests
- FakeProfiles
- pindah.py
- UtilityFolderStore
- FakeWorkers
- lucide-react
- tme3bot
- ArchitectureBoundaryTests
- infrastructure/__init__.py

## God Nodes (most connected - your core abstractions)
1. `BackendContext` - 59 edges
2. `TelegramFrontendApp` - 54 edges
3. `StorageCatalog` - 50 edges
4. `AppConfig` - 44 edges
5. `StateStore` - 42 edges
6. `SqliteJobRepository` - 39 edges
7. `ControlPlane` - 38 edges
8. `DomainError` - 37 edges
9. `create_backend_app()` - 36 edges
10. `TDLClient` - 36 edges

## Surprising Connections (you probably didn't know these)
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `BotAuthService`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `AuthServiceTests` --uses--> `SqliteAuthRepository`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `FakeProfiles` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py
- `FakeProfiles` --uses--> `ControlPlane`  [INFERRED]
  tests/test_backend_api.py → tme3bot/application/control_plane.py

## Import Cycles
- None detected.

## Communities (74 total, 25 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.10
Nodes (11): StateStoreTests, Any, Path, write_json_atomic(), HttpStateStore, Any, Path, StateStore-compatible client used by a worker without a local state file. (+3 more)

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.10
Nodes (11): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+3 more)

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.60
Nodes (3): LeaveResult, LeaveService, TDLCommandError

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.14
Nodes (16): Enum, Protocol, str, JobStoreTests, Job, ActorResolver, Any, StorageDelivery (+8 more)

### Community 6 - "LabelStore"
Cohesion: 0.14
Nodes (12): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, utc_now_iso(), parse_tme3_url() (+4 more)

### Community 7 - "bot_text.py"
Cohesion: 0.06
Nodes (39): OutputCallback, Popen, ProgressCallback, Queue, FakeRunner, TDLClientTests, has_downloadable_media(), is_image_message() (+31 more)

### Community 8 - "UtilityHandler"
Cohesion: 0.06
Nodes (46): metadata, Providers(), ActivityPage(), Backup, BackupsPage(), SettingsPage(), Worker, WorkersPage() (+38 more)

### Community 9 - "ProfileManager"
Cohesion: 0.08
Nodes (55): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+47 more)

### Community 11 - "ExportResult"
Cohesion: 0.27
Nodes (7): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, build_telegram_message_url(), ExportService, ExportResult

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.18
Nodes (15): ProfileTests, Path, AppConfig, Fail fast when a production role is missing its trust boundary., build_profile_config(), build_profile_runtime(), chown_paths(), chown_tree() (+7 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "next"
Cohesion: 0.19
Nodes (8): _dump(), _load(), Connection, Job, JobEvent, Path, Row, SqliteJobRepository

### Community 15 - "WorkerRegistry"
Cohesion: 0.08
Nodes (21): ChannelRefTests, FakeExecutor, WorkerApiTests, WorkerJobRequest, create_worker_app(), _error(), FastAPI, JSONResponse (+13 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.09
Nodes (17): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, build_storage_caption(), _caption_value(), Connection (+9 more)

### Community 17 - "composition.py"
Cohesion: 0.16
Nodes (9): BackupScheduler, build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, JsonHttpError, WorkerHttpDispatcher, WorkerEventPublisher (+1 more)

### Community 18 - "config.py"
Cohesion: 0.15
Nodes (10): UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, UtilityPathError, UtilityResult, UtilityRunner, UtilitySettingsStore (+2 more)

### Community 19 - "ProfileManager"
Cohesion: 0.07
Nodes (27): dom, dom.iterable, esnext, .next/dev/types/**/*.ts, next-env.d.ts, .next/types/**/*.ts, node_modules, **/*.ts (+19 more)

### Community 20 - "DownloadProgressTracker"
Cohesion: 0.18
Nodes (9): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, Runs different keys concurrently while keeping each key serial., SerialPerKeyQueue (+1 more)

### Community 21 - "SerialPerKeyQueue"
Cohesion: 0.12
Nodes (15): aliases, components, hooks, lib, ui, utils, iconLibrary, rsc (+7 more)

### Community 22 - "ProfileTests"
Cohesion: 0.14
Nodes (9): JobLogSnapshot, json_value(), Any, Exception, Path, Executes domain jobs and publishes JSON events; no UI dependency., Bounded raw command output retained with the persistent job history., Return a safe, shallow directory listing for the active workspace. (+1 more)

### Community 24 - "ExportService"
Cohesion: 0.21
Nodes (9): BatchDownloadResult, BatchDownloadService, DownloadedJsonResult, ExportJobResult, media_ids_in_export(), Path, Download selected opaque filenames after strict directory validation., unique_path() (+1 more)

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 27 - "TDLCommandError"
Cohesion: 0.32
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 28 - "RunScriptTests"
Cohesion: 0.08
Nodes (69): BaseModel, StorageLinkTests, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _error(), event_dict() (+61 more)

### Community 29 - "Path"
Cohesion: 0.08
Nodes (25): @axe-core/playwright, jsdom, openapi-typescript, tailwindcss, @tailwindcss/postcss, @testing-library/jest-dom, @testing-library/react, @types/node (+17 more)

### Community 30 - "dependencies"
Cohesion: 0.09
Nodes (23): clsx, @hookform/resolvers, next, @radix-ui/react-dialog, @radix-ui/react-tabs, react, react-dom, react-hook-form (+15 more)

### Community 34 - "bff.ts"
Cohesion: 0.24
Nodes (13): POST(), POST(), proxy(), GET(), PUT(), backendFetch(), clearSession(), copyResponse() (+5 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.18
Nodes (9): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts.  The worker owns the physical J, Return safe media statistics without assuming a single TDL JSON shape. (+1 more)

### Community 36 - "BackupCoordinator"
Cohesion: 0.15
Nodes (6): BackupCoordinator, BackupNodeJob, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., sha256_file()

### Community 37 - "ExportService"
Cohesion: 0.33
Nodes (3): JobRepository, Job, JobEvent

### Community 38 - "BackupService"
Cohesion: 0.27
Nodes (6): BackupArchive, BackupService, Path, Create encrypted, runtime-only per-node backup archives., safe_node_name(), utc_now()

### Community 39 - "scripts"
Cohesion: 0.25
Nodes (8): scripts, build, dev, lint, openapi, start, test, test:e2e

### Community 40 - "package.json"
Cohesion: 0.40
Nodes (4): name, packageManager, private, version

### Community 41 - "ProfileManager"
Cohesion: 0.18
Nodes (3): ProfileManager, ProfileSelectionStore, Path

### Community 52 - "ControlPlaneTests"
Cohesion: 0.09
Nodes (13): FakeDispatcher, ControlPlaneTests, FakeDispatcher, FakeProfiles, ControlPlane, Any, Job, JobEvent (+5 more)

### Community 53 - "BatchDownloadService"
Cohesion: 0.09
Nodes (29): CallbackContext, AppMenuTests, PendingInput, Any, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Telegram presentation adapter and UI-only helpers. (+21 more)

### Community 56 - "request_json"
Cohesion: 0.09
Nodes (8): RunScriptTests, CompletedProcess, BackendApiClient, Any, Frontend adapters. They communicate with the backend only through JSON., Any, RuntimeError, request_json()

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.15
Nodes (9): BotAuthService, _hash_secret(), _now(), Any, Connection, datetime, Path, SqliteAuthRepository (+1 more)

### Community 59 - "DomainError"
Cohesion: 0.33
Nodes (5): AuthServiceTests, Path, DomainError, Any, RuntimeError

### Community 64 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 67 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 72 - "tme3bot"
Cohesion: 0.05
Nodes (41): A1. Kirim source terbaru ke VPS besar, A2. Siapkan source di VPS besar, A3. Build base image satu kali, A. Kondisi pertama: membuat base image di VPS besar, Aturan dasar, B1. Di project lokal, B2. Ekstrak base image dengan aman di project lokal, B3. Kirim source ke VPS besar (+33 more)

## Knowledge Gaps
- **146 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `$schema`, `style` (+141 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AppConfig` connect `SerialPerKeyQueue` to `ProfileManager`, `ProfileManager`, `ExportResult`, `WorkerRegistry`, `StorageCatalog`, `composition.py`, `ExportService`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `BatchDownloadService` to `request_json`, `composition.py`, `TDLClient`, `WorkerRegistry`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Why does `ProfileManager` connect `ProfileManager` to `ProfileManager`, `WorkerRegistry`, `SerialPerKeyQueue`, `bot_text.py`, `ExportResult`, `SerialPerKeyQueue`, `WorkerRegistry`, `composition.py`, `ExportService`, `TDLCommandError`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Are the 47 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 47 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `AppConfig` (e.g. with `BackupServiceTests` and `ChannelRefTests`) actually correct?**
  _`AppConfig` has 16 INFERRED edges - model-reasoned connections that need verification._