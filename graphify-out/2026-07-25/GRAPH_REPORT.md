# Graph Report - dockter_bot_tdl  (2026-07-25)

## Corpus Check
- 128 files · ~52,150 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1450 nodes · 3684 edges · 65 communities (43 shown, 22 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 377 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c74ea98f`
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
- WorkerRegistry
- StorageCatalog
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
- lucide-react
- pindah.py
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
9. `create_backend_app()` - 36 edges
10. `TDLClient` - 36 edges

## Surprising Connections (you probably didn't know these)
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `DomainError`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `BotAuthService`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `AuthServiceTests` --uses--> `SqliteAuthRepository`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `FakeProfiles` --uses--> `ControlPlane`  [INFERRED]
  tests/test_backend_api.py → tme3bot/application/control_plane.py

## Import Cycles
- None detected.

## Communities (65 total, 22 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.07
Nodes (20): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, Any, Path (+12 more)

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.10
Nodes (11): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+3 more)

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.23
Nodes (7): FakeRunner, TDLClientTests, LeaveResult, DownloadedJsonResult, decode_process_output(), TDLClient, TDLCommandError

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.09
Nodes (23): Enum, Protocol, str, JobStoreTests, Job, ActorResolver, Any, StorageDelivery (+15 more)

### Community 6 - "LabelStore"
Cohesion: 0.17
Nodes (13): Queue, has_downloadable_media(), is_image_message(), Any, media_ids_in_export(), Any, _message_contains_caption(), _normalize_upload_caption() (+5 more)

### Community 7 - "bot_text.py"
Cohesion: 0.14
Nodes (11): OutputCallback, Popen, ProgressCallback, CompletedProcess, Path, RuntimeError, Raised when TDL returns unusable or malformed export data., Upload exactly one file and return its Telegram channel message id. (+3 more)

### Community 8 - "UtilityHandler"
Cohesion: 0.06
Nodes (46): metadata, Providers(), ActivityPage(), Backup, BackupsPage(), SettingsPage(), Worker, WorkersPage() (+38 more)

### Community 9 - "ProfileManager"
Cohesion: 0.08
Nodes (54): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+46 more)

### Community 11 - "ExportResult"
Cohesion: 0.19
Nodes (10): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, StateStoreTests, build_telegram_message_url(), ExportService, Path (+2 more)

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.06
Nodes (37): ChannelRefTests, ProfileTests, Path, WorkerRegistryTests, configure_logging(), main(), channel_chat_id(), channel_tdl_ref() (+29 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 15 - "WorkerRegistry"
Cohesion: 0.16
Nodes (9): FakeExecutor, WorkerApiTests, WorkerJobRequest, create_worker_app(), _error(), FastAPI, JSONResponse, Request (+1 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (25): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, BackupArchive, BackupService, Path (+17 more)

### Community 18 - "config.py"
Cohesion: 0.08
Nodes (13): BackendApiTests, FakeWorkers, UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, UtilityFolderStore, UtilityPathError (+5 more)

### Community 19 - "ProfileManager"
Cohesion: 0.07
Nodes (27): dom, dom.iterable, esnext, .next/dev/types/**/*.ts, next-env.d.ts, .next/types/**/*.ts, node_modules, **/*.ts (+19 more)

### Community 20 - "DownloadProgressTracker"
Cohesion: 0.18
Nodes (12): clean_tdl_output_line(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_file_name(), parse_fraction(), parse_message_id(), parse_percent() (+4 more)

### Community 21 - "SerialPerKeyQueue"
Cohesion: 0.12
Nodes (15): aliases, components, hooks, lib, ui, utils, iconLibrary, rsc (+7 more)

### Community 22 - "ProfileTests"
Cohesion: 0.08
Nodes (18): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, Runs different keys concurrently while keeping each key serial., SerialPerKeyQueue (+10 more)

### Community 24 - "ExportService"
Cohesion: 0.21
Nodes (7): BatchDownloadResult, BatchDownloadService, ExportJobResult, Path, Download selected opaque filenames after strict directory validation., unique_path(), ParsedTme3Url

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 27 - "TDLCommandError"
Cohesion: 0.26
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 28 - "RunScriptTests"
Cohesion: 0.07
Nodes (71): BaseModel, FakeDispatcher, FakeProfiles, StorageLinkTests, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app() (+63 more)

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
Cohesion: 0.11
Nodes (12): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., build_backend_context(), ControlPlaneBackupRouter (+4 more)

### Community 37 - "ExportService"
Cohesion: 0.33
Nodes (3): JobRepository, Job, JobEvent

### Community 39 - "scripts"
Cohesion: 0.25
Nodes (8): scripts, build, dev, lint, openapi, start, test, test:e2e

### Community 40 - "package.json"
Cohesion: 0.40
Nodes (4): name, packageManager, private, version

### Community 52 - "ControlPlaneTests"
Cohesion: 0.11
Nodes (15): ControlPlaneTests, FakeDispatcher, FakeProfiles, ControlPlane, Any, Job, JobEvent, Application facade used by every frontend adapter. (+7 more)

### Community 53 - "BatchDownloadService"
Cohesion: 0.08
Nodes (30): CallbackContext, AppMenuTests, PendingInput, Any, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Telegram presentation adapter and UI-only helpers. (+22 more)

### Community 56 - "request_json"
Cohesion: 0.09
Nodes (8): RunScriptTests, CompletedProcess, BackendApiClient, Any, Frontend adapters. They communicate with the backend only through JSON., Any, RuntimeError, request_json()

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.15
Nodes (10): AuthChallengeStatus, BotAuthService, _hash_secret(), _now(), Any, Connection, datetime, Path (+2 more)

### Community 67 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 72 - "tme3bot"
Cohesion: 0.05
Nodes (41): A1. Kirim source terbaru ke VPS besar, A2. Siapkan source di VPS besar, A3. Build base image satu kali, A. Kondisi pertama: membuat base image di VPS besar, Aturan dasar, B1. Di project lokal, B2. Ekstrak base image dengan aman di project lokal, B3. Kirim source ke VPS besar (+33 more)

## Knowledge Gaps
- **146 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `$schema`, `style` (+141 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ProfileManager` connect `SerialPerKeyQueue` to `ProfileManager`, `SerialPerKeyQueue`, `BackupCoordinator`, `ExportResult`, `ExportService`, `TDLCommandError`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Why does `AppConfig` connect `SerialPerKeyQueue` to `SerialPerKeyQueue`, `BackupCoordinator`, `LabelStore`, `ExportResult`, `StorageCatalog`, `ExportService`, `TDLCommandError`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `BatchDownloadService` to `request_json`, `TDLClient`, `SerialPerKeyQueue`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Are the 47 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 47 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `AppConfig` (e.g. with `BackupServiceTests` and `ChannelRefTests`) actually correct?**
  _`AppConfig` has 16 INFERRED edges - model-reasoned connections that need verification._