# Graph Report - dockter_bot_tdl  (2026-07-25)

## Corpus Check
- 127 files · ~51,045 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1422 nodes · 3630 edges · 72 communities (49 shown, 23 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 372 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `63f83f25`
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
- TDLClient
- WorkerRegistry
- StorageCatalog
- WorkerRegistry
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
- SerialPerKeyQueue
- scripts
- package.json
- test_backend_api.py
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
- parse_tme3_url
- BackendApiTests
- UtilityFolderStore
- pindah.py
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

## Communities (72 total, 23 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.19
Nodes (10): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, Any, Path, utc_now_iso() (+2 more)

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.10
Nodes (11): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+3 more)

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.07
Nodes (35): Popen, ProgressCallback, Queue, FakeRunner, TDLClientTests, decode_process_output(), _message_contains_caption(), _normalize_upload_caption() (+27 more)

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.15
Nodes (9): JobStoreTests, Job, _dump(), _load(), Connection, Job, Path, Row (+1 more)

### Community 6 - "LabelStore"
Cohesion: 0.12
Nodes (8): StateStoreTests, HttpStateStore, Any, Path, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot, StateStore

### Community 7 - "bot_text.py"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl.      Bot API uses `-100<peer i, load_dotenv(), _parse_named_values()

### Community 8 - "UtilityHandler"
Cohesion: 0.07
Nodes (43): metadata, Providers(), ActivityPage(), Backup, BackupsPage(), SettingsPage(), Worker, WorkersPage() (+35 more)

### Community 9 - "ProfileManager"
Cohesion: 0.08
Nodes (54): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+46 more)

### Community 11 - "ExportResult"
Cohesion: 0.31
Nodes (5): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, ExportResult

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.11
Nodes (19): ProfileTests, Path, AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), build_profile_config(), build_profile_runtime(), chown_paths() (+11 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "TDLClient"
Cohesion: 0.36
Nodes (5): BatchDownloadResult, BatchDownloadService, Path, Download selected opaque filenames after strict directory validation., unique_path()

### Community 15 - "WorkerRegistry"
Cohesion: 0.11
Nodes (16): FakeExecutor, WorkerApiTests, create_worker_app(), _error(), FastAPI, JSONResponse, Request, WorkerContext (+8 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (23): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, BackupArchive, BackupService, Path (+15 more)

### Community 17 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 18 - "config.py"
Cohesion: 0.16
Nodes (10): UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, UtilityPathError, UtilityResult, UtilityRunner, UtilitySettingsStore (+2 more)

### Community 19 - "ProfileManager"
Cohesion: 0.07
Nodes (27): dom, dom.iterable, esnext, .next/dev/types/**/*.ts, next-env.d.ts, .next/types/**/*.ts, node_modules, **/*.ts (+19 more)

### Community 21 - "SerialPerKeyQueue"
Cohesion: 0.12
Nodes (15): aliases, components, hooks, lib, ui, utils, iconLibrary, rsc (+7 more)

### Community 22 - "ProfileTests"
Cohesion: 0.13
Nodes (11): sha256_file(), JsonHttpError, json_value(), Any, Exception, Path, Return a safe, shallow directory listing for the active workspace., Executes domain jobs and publishes JSON events; no UI dependency. (+3 more)

### Community 24 - "ExportService"
Cohesion: 0.20
Nodes (10): has_downloadable_media(), is_image_message(), Any, build_telegram_message_url(), DownloadedJsonResult, ExportJobResult, ExportService, media_ids_in_export() (+2 more)

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 27 - "TDLCommandError"
Cohesion: 0.60
Nodes (3): LeaveResult, LeaveService, TDLCommandError

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
Nodes (6): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup.

### Community 37 - "ExportService"
Cohesion: 0.11
Nodes (16): Protocol, ControlPlane, Any, Job, Application facade used by every frontend adapter., _redact_secrets(), serializable(), Application services and use cases. (+8 more)

### Community 38 - "SerialPerKeyQueue"
Cohesion: 0.18
Nodes (9): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, Runs different keys concurrently while keeping each key serial., SerialPerKeyQueue (+1 more)

### Community 39 - "scripts"
Cohesion: 0.25
Nodes (8): scripts, build, dev, lint, openapi, start, test, test:e2e

### Community 40 - "package.json"
Cohesion: 0.40
Nodes (4): name, packageManager, private, version

### Community 41 - "test_backend_api.py"
Cohesion: 0.11
Nodes (3): FakeDispatcher, FakeProfiles, FakeWorkers

### Community 51 - "models.py"
Cohesion: 0.29
Nodes (8): Enum, str, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, Job, JobStatus, datetime, utc_now()

### Community 52 - "ControlPlaneTests"
Cohesion: 0.17
Nodes (3): ControlPlaneTests, FakeDispatcher, FakeProfiles

### Community 53 - "BatchDownloadService"
Cohesion: 0.09
Nodes (29): CallbackContext, AppMenuTests, PendingInput, Any, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Telegram presentation adapter and UI-only helpers. (+21 more)

### Community 56 - "request_json"
Cohesion: 0.09
Nodes (9): RunScriptTests, CompletedProcess, BackendApiClient, Any, Frontend adapters. They communicate with the backend only through JSON., Any, RuntimeError, request_json() (+1 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.15
Nodes (9): BotAuthService, _hash_secret(), _now(), Any, Connection, datetime, Path, SqliteAuthRepository (+1 more)

### Community 59 - "DomainError"
Cohesion: 0.33
Nodes (5): AuthServiceTests, Path, DomainError, Any, RuntimeError

### Community 64 - "parse_tme3_url"
Cohesion: 0.33
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 67 - "pindah.py"
Cohesion: 0.36
Nodes (7): find_best_combination(), find_best_combination_worker(), load_json(), main(), Membaca dan mengembalikan konten file JSON., Worker function to find the best combination within a given range of combination, Find the best combination of items to fill the space left using multiprocessing.

### Community 72 - "tme3bot"
Cohesion: 0.05
Nodes (41): A1. Kirim source terbaru ke VPS besar, A2. Siapkan source di VPS besar, A3. Build base image satu kali, A. Kondisi pertama: membuat base image di VPS besar, Aturan dasar, B1. Di project lokal, B2. Ekstrak base image dengan aman di project lokal, B3. Kirim source ke VPS besar (+33 more)

## Knowledge Gaps
- **145 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `$schema`, `style` (+140 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **23 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ProfileManager` connect `SerialPerKeyQueue` to `SerialPerKeyQueue`, `LabelStore`, `TDLClient`, `WorkerRegistry`, `WorkerRegistry`, `DownloadProgressTracker`, `ExportService`, `TDLCommandError`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Why does `AppConfig` connect `SerialPerKeyQueue` to `LabelStore`, `bot_text.py`, `ExportResult`, `TDLClient`, `WorkerRegistry`, `StorageCatalog`, `DownloadProgressTracker`, `ExportService`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `BatchDownloadService` to `request_json`, `TDLClient`, `ProfileTests`, `WorkerRegistry`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Are the 47 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 47 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `AppConfig` (e.g. with `BackupServiceTests` and `ChannelRefTests`) actually correct?**
  _`AppConfig` has 16 INFERRED edges - model-reasoned connections that need verification._