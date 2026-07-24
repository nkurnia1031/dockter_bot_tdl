# Graph Report - dockter_bot_tdl  (2026-07-25)

## Corpus Check
- 126 files · ~48,857 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1394 nodes · 3558 edges · 71 communities (47 shown, 24 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 364 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a0416b4d`
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
- telegram/app.py
- RunScriptTests
- Path
- dependencies
- tme3bot/__init__.py
- pindah.sh script
- bff.ts
- ExportArtifactCatalog
- composition.py
- ExportService
- edit_menu_message
- scripts
- package.json
- DomainError
- next-themes
- @playwright/test
- @radix-ui/react-dropdown-menu
- recharts
- tailwind-merge
- @types/react-dom
- next.config.ts
- next-env.d.ts
- PanelViewStore
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
- source_digest
- ProfileSelectionStore
- lucide-react
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
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `DomainError`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `BotAuthService`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `AuthServiceTests` --uses--> `SqliteAuthRepository`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `FakeProfiles` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py

## Import Cycles
- None detected.

## Communities (71 total, 24 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.30
Nodes (6): BatchDownloadResult, BatchDownloadService, Any, Path, Download selected opaque filenames after strict directory validation., unique_path()

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.14
Nodes (8): Message, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup, safe_edit_bot_message()

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.06
Nodes (34): Popen, ProgressCallback, Queue, FakeRunner, TDLClientTests, decode_process_output(), clean_tdl_output_line(), is_nonsemantic_tdl_output_line() (+26 more)

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.15
Nodes (28): HTMLParser, build_orphan_group_entry(), build_reply_group_entry(), build_root_catalog(), build_root_entries(), discover_html_files(), entry_sort_key(), first_text_line() (+20 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.20
Nodes (7): _dump(), _load(), Connection, Job, Path, Row, SqliteJobRepository

### Community 6 - "LabelStore"
Cohesion: 0.08
Nodes (17): BackupServiceTests, make_config(), Path, BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention. (+9 more)

### Community 7 - "bot_text.py"
Cohesion: 0.08
Nodes (18): FakeExecutor, WorkerApiTests, WorkerRegistryTests, create_worker_app(), _error(), FastAPI, JSONResponse, Request (+10 more)

### Community 8 - "UtilityHandler"
Cohesion: 0.07
Nodes (39): metadata, Providers(), ActivityPage(), Backup, BackupsPage(), SettingsPage(), Worker, WorkersPage() (+31 more)

### Community 9 - "ProfileManager"
Cohesion: 0.08
Nodes (53): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+45 more)

### Community 11 - "run.py"
Cohesion: 0.18
Nodes (9): ChannelRefTests, ProfileTests, Path, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., load_dotenv() (+1 more)

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.15
Nodes (17): build_backend_context(), _first_actor(), AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), build_profile_config(), build_profile_runtime(), chown_paths() (+9 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "TDLClient"
Cohesion: 0.12
Nodes (8): StateStoreTests, HttpStateStore, Any, Path, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot, StateStore

### Community 15 - "WorkerRegistry"
Cohesion: 0.53
Nodes (3): ExportJobResult, ExportService, ParsedTme3Url

### Community 16 - "StorageCatalog"
Cohesion: 0.11
Nodes (14): item_values(), StorageCatalogTests, build_storage_caption(), _caption_value(), Connection, Path, Row, Persistent catalog for the shared Telegram storage channel. (+6 more)

### Community 17 - "find_best_combination"
Cohesion: 0.07
Nodes (24): LabelStoreTests, ParseTme3UrlTests, UtilitySettingsTests, label_digest(), LabelStore, Path, SavedLabel, Any (+16 more)

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
Cohesion: 0.08
Nodes (17): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, Runs different keys concurrently while keeping each key serial., SerialPerKeyQueue (+9 more)

### Community 24 - "DomainError"
Cohesion: 0.18
Nodes (13): LeaveResult, LeaveService, has_downloadable_media(), is_image_message(), Any, build_telegram_message_url(), DownloadedJsonResult, media_ids_in_export() (+5 more)

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 27 - "telegram/app.py"
Cohesion: 0.26
Nodes (15): Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), InlineKeyboardMarkup, Inline keyboards used by the API-backed Telegram frontend., storage_delete_markup() (+7 more)

### Community 28 - "RunScriptTests"
Cohesion: 0.09
Nodes (67): BaseModel, StorageLinkTests, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _error(), event_dict() (+59 more)

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

### Community 36 - "composition.py"
Cohesion: 0.14
Nodes (3): BackendApiTests, FakeDispatcher, FakeWorkers

### Community 37 - "ExportService"
Cohesion: 0.11
Nodes (14): ControlPlaneTests, FakeDispatcher, FakeProfiles, ControlPlane, Any, Job, Application facade used by every frontend adapter., _redact_secrets() (+6 more)

### Community 38 - "edit_menu_message"
Cohesion: 0.21
Nodes (5): PendingInput, Any, main_menu_markup(), storage_menu_markup(), edit_menu_message()

### Community 39 - "scripts"
Cohesion: 0.25
Nodes (8): scripts, build, dev, lint, openapi, start, test, test:e2e

### Community 40 - "package.json"
Cohesion: 0.40
Nodes (4): name, packageManager, private, version

### Community 51 - "PanelViewStore"
Cohesion: 0.27
Nodes (3): PanelViewStoreTests, PanelViewStore, Tracks which asynchronous task currently owns a chat's panel view.

### Community 52 - "SourceState"
Cohesion: 0.32
Nodes (5): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, ExportResult

### Community 53 - "BatchDownloadService"
Cohesion: 0.21
Nodes (5): CallbackContext, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

### Community 56 - "request_json"
Cohesion: 0.09
Nodes (10): RunScriptTests, CompletedProcess, BackendApiClient, Any, Frontend adapters. They communicate with the backend only through JSON., JsonHttpError, Any, RuntimeError (+2 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.15
Nodes (10): AuthChallengeStatus, BotAuthService, _hash_secret(), _now(), Any, Connection, datetime, Path (+2 more)

### Community 59 - "DomainError"
Cohesion: 0.11
Nodes (17): Enum, Protocol, str, JobStoreTests, Job, ActorResolver, JobRepository, Any (+9 more)

### Community 65 - "source_digest"
Cohesion: 0.32
Nodes (4): AppMenuTests, help_text(), Text helpers owned by the Telegram presentation adapter., source_digest()

### Community 72 - "tme3bot"
Cohesion: 0.05
Nodes (41): A1. Kirim source terbaru ke VPS besar, A2. Siapkan source di VPS besar, A3. Build base image satu kali, A. Kondisi pertama: membuat base image di VPS besar, Aturan dasar, B1. Di project lokal, B2. Ekstrak base image dengan aman di project lokal, B3. Kirim source ke VPS besar (+33 more)

## Knowledge Gaps
- **143 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `$schema`, `style` (+138 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **24 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AppConfig` connect `SerialPerKeyQueue` to `ProfileManager`, `ProfileSelectionStore`, `LabelStore`, `bot_text.py`, `run.py`, `TDLClient`, `WorkerRegistry`, `SourceState`, `DownloadProgressTracker`, `DomainError`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `BatchDownloadService` to `source_digest`, `TDLClient`, `edit_menu_message`, `bot_text.py`, `request_json`, `telegram/app.py`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `FakeProfiles`, `composition.py`, `LabelStore`, `bot_text.py`, `SerialPerKeyQueue`, `DomainError`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Are the 47 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 47 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `AppConfig` (e.g. with `BackupServiceTests` and `ChannelRefTests`) actually correct?**
  _`AppConfig` has 16 INFERRED edges - model-reasoned connections that need verification._