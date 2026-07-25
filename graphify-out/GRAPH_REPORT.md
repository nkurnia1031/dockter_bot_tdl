# Graph Report - dockter_bot_tdl  (2026-07-25)

## Corpus Check
- 129 files · ~54,160 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1483 nodes · 3792 edges · 89 communities (60 shown, 29 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 385 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `fc04114c`
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
- WorkerRegistry
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
- DownloadProgressTracker
- GET
- PATCH
- POST
- PUT
- TDLClient
- models.py
- FakeProfiles
- pindah.py
- BackendApiTests
- ProfileTests
- lucide-react
- SerialPerKeyQueue
- tme3bot
- request_json
- edit_menu_message
- ArchitectureBoundaryTests
- ControlPlaneBackupRouter
- BatchDownloadService
- infrastructure/__init__.py
- UtilityFolderStore
- parse_tme3_url
- _message_contains_caption
- .__init__
- next
- ControlPlaneTests
- JobRepository
- source_digest
- FakeDispatcher
- lucide-react

## God Nodes (most connected - your core abstractions)
1. `BackendContext` - 59 edges
2. `TelegramFrontendApp` - 54 edges
3. `StorageCatalog` - 50 edges
4. `StateStore` - 47 edges
5. `AppConfig` - 44 edges
6. `SqliteJobRepository` - 39 edges
7. `ControlPlane` - 38 edges
8. `DomainError` - 38 edges
9. `create_backend_app()` - 36 edges
10. `ProfileManager` - 36 edges

## Surprising Connections (you probably didn't know these)
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `DomainError`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `FakeProfiles` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py
- `FakeProfiles` --uses--> `ControlPlane`  [INFERRED]
  tests/test_backend_api.py → tme3bot/application/control_plane.py
- `FakeProfiles` --uses--> `Actor`  [INFERRED]
  tests/test_backend_api.py → tme3bot/domain/models.py

## Import Cycles
- None detected.

## Communities (89 total, 29 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.16
Nodes (5): normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case.      Numeric Telegram, SourceState, StateSnapshot

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.14
Nodes (8): Message, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup, safe_edit_bot_message()

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.26
Nodes (3): ProfileManager, Path, Metadata a worker can safely publish to the backend registry.

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.16
Nodes (9): FakeDispatcher, ControlPlane, Any, Job, JobEvent, Application facade used by every frontend adapter., _redact_secrets(), serializable() (+1 more)

### Community 6 - "LabelStore"
Cohesion: 0.18
Nodes (10): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, Any, Path, utc_now_iso() (+2 more)

### Community 8 - "UtilityHandler"
Cohesion: 0.06
Nodes (48): metadata, Providers(), ActivityPage(), Backup, BackupsPage(), SettingsPage(), Worker, WorkersPage() (+40 more)

### Community 9 - "ProfileManager"
Cohesion: 0.08
Nodes (55): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+47 more)

### Community 11 - "ExportResult"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl.      Bot API uses `-100<peer i, load_dotenv(), _parse_named_values()

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.20
Nodes (16): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), build_profile_config(), build_profile_runtime(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs() (+8 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "next"
Cohesion: 0.19
Nodes (8): _dump(), _load(), Connection, Job, JobEvent, Path, Row, SqliteJobRepository

### Community 15 - "WorkerRegistry"
Cohesion: 0.16
Nodes (9): FakeExecutor, WorkerApiTests, WorkerJobRequest, create_worker_app(), _error(), FastAPI, JSONResponse, Request (+1 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (25): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, BackupArchive, BackupService, Path (+17 more)

### Community 17 - "composition.py"
Cohesion: 0.11
Nodes (11): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., build_backend_context(), ControlPlaneBackupRouter (+3 more)

### Community 18 - "config.py"
Cohesion: 0.13
Nodes (11): UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, UtilityFolderStore, UtilityPathError, UtilityResult, UtilityRunner (+3 more)

### Community 19 - "ProfileManager"
Cohesion: 0.07
Nodes (27): dom, dom.iterable, esnext, .next/dev/types/**/*.ts, next-env.d.ts, .next/types/**/*.ts, node_modules, **/*.ts (+19 more)

### Community 20 - "DownloadProgressTracker"
Cohesion: 0.31
Nodes (6): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, ExportResult, TDLCommandError

### Community 21 - "SerialPerKeyQueue"
Cohesion: 0.12
Nodes (15): aliases, components, hooks, lib, ui, utils, iconLibrary, rsc (+7 more)

### Community 22 - "ProfileTests"
Cohesion: 0.13
Nodes (10): JobLogSnapshot, json_value(), Any, Exception, Path, Executes domain jobs and publishes JSON events; no UI dependency., Publish only profile metadata; .tdl files remain on this worker., Bounded raw command output retained with the persistent job history. (+2 more)

### Community 24 - "ExportService"
Cohesion: 0.60
Nodes (4): configure_logging(), main(), run_backend(), run_worker()

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 27 - "TDLCommandError"
Cohesion: 0.20
Nodes (10): has_downloadable_media(), is_image_message(), Any, build_telegram_message_url(), DownloadedJsonResult, ExportJobResult, ExportService, media_ids_in_export() (+2 more)

### Community 28 - "RunScriptTests"
Cohesion: 0.08
Nodes (71): BaseModel, StorageLinkTests, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _error(), event_dict() (+63 more)

### Community 29 - "Path"
Cohesion: 0.08
Nodes (25): @axe-core/playwright, jsdom, openapi-typescript, tailwindcss, @tailwindcss/postcss, @testing-library/jest-dom, @testing-library/react, @types/node (+17 more)

### Community 30 - "dependencies"
Cohesion: 0.09
Nodes (23): clsx, @hookform/resolvers, lucide-react, @radix-ui/react-dialog, @radix-ui/react-tabs, react, react-dom, react-hook-form (+15 more)

### Community 34 - "bff.ts"
Cohesion: 0.24
Nodes (13): POST(), POST(), proxy(), GET(), PUT(), backendFetch(), clearSession(), copyResponse() (+5 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.18
Nodes (9): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts.  The worker owns the physical J, Return safe media statistics without assuming a single TDL JSON shape. (+1 more)

### Community 37 - "ExportService"
Cohesion: 0.19
Nodes (16): clean_tdl_output_line(), CommandProgress, is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_file_name(), parse_fraction(), parse_message_id() (+8 more)

### Community 38 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 39 - "scripts"
Cohesion: 0.25
Nodes (8): scripts, build, dev, lint, openapi, start, test, test:e2e

### Community 40 - "package.json"
Cohesion: 0.40
Nodes (4): name, packageManager, private, version

### Community 41 - "ProfileManager"
Cohesion: 0.25
Nodes (8): _normalize_upload_caption(), CompletedProcess, Path, RuntimeError, Raised when TDL returns unusable or malformed export data., Upload exactly one file and return its Telegram channel message id., Resolve delayed TDL upload results by polling channel history.          Some TDL, TDLDataError

### Community 44 - "@radix-ui/react-dropdown-menu"
Cohesion: 0.25
Nodes (3): LeaveResult, LeaveService, ProfileSelectionStore

### Community 52 - "ControlPlaneTests"
Cohesion: 0.20
Nodes (9): Protocol, JobStoreTests, Job, ActorResolver, Any, StorageDelivery, WorkerDispatcher, Job (+1 more)

### Community 53 - "BatchDownloadService"
Cohesion: 0.21
Nodes (5): CallbackContext, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.09
Nodes (14): str, AuthServiceTests, Path, BackendApiTests, AuthChallengeStatus, BotAuthService, _hash_secret(), _now() (+6 more)

### Community 64 - "TDLClient"
Cohesion: 0.22
Nodes (4): FakeRunner, TDLClientTests, decode_process_output(), TDLClient

### Community 65 - "models.py"
Cohesion: 0.24
Nodes (6): Enum, Application services and use cases., Framework-independent domain model for the tme3bot control plane., JobStatus, datetime, utc_now()

### Community 67 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 68 - "BackendApiTests"
Cohesion: 0.19
Nodes (17): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), InlineKeyboardMarkup, Inline keyboards used by the API-backed Telegram frontend. (+9 more)

### Community 71 - "SerialPerKeyQueue"
Cohesion: 0.18
Nodes (9): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, Runs different keys concurrently while keeping each key serial., SerialPerKeyQueue (+1 more)

### Community 72 - "tme3bot"
Cohesion: 0.05
Nodes (41): A1. Kirim source terbaru ke VPS besar, A2. Siapkan source di VPS besar, A3. Build base image satu kali, A. Kondisi pertama: membuat base image di VPS besar, Aturan dasar, B1. Di project lokal, B2. Ekstrak base image dengan aman di project lokal, B3. Kirim source ke VPS besar (+33 more)

### Community 73 - "request_json"
Cohesion: 0.32
Nodes (4): BackendApiClient, Any, Frontend adapters. They communicate with the backend only through JSON., request_json()

### Community 74 - "edit_menu_message"
Cohesion: 0.31
Nodes (3): Any, main_menu_markup(), edit_menu_message()

### Community 76 - "ControlPlaneBackupRouter"
Cohesion: 0.18
Nodes (5): JsonHttpError, Any, RuntimeError, WorkerEventPublisher, Framework-independent worker execution adapter.

### Community 77 - "BatchDownloadService"
Cohesion: 0.36
Nodes (5): BatchDownloadResult, BatchDownloadService, Path, Download selected opaque filenames after strict directory validation., unique_path()

### Community 79 - "UtilityFolderStore"
Cohesion: 0.27
Nodes (3): StateStoreTests, Path, StateStore

### Community 80 - "parse_tme3_url"
Cohesion: 0.33
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 81 - "_message_contains_caption"
Cohesion: 0.22
Nodes (6): OutputCallback, ProgressCallback, Queue, _message_contains_caption(), Any, Match captions across the different JSON shapes emitted by TDL.

### Community 82 - ".__init__"
Cohesion: 0.27
Nodes (3): PanelViewStoreTests, PanelViewStore, Tracks which asynchronous task currently owns a chat's panel view.

### Community 83 - "next"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions.      A, One-way migration for installations created before the registry.

### Community 85 - "JobRepository"
Cohesion: 0.29
Nodes (3): JobRepository, Job, JobEvent

### Community 86 - "source_digest"
Cohesion: 0.32
Nodes (4): AppMenuTests, help_text(), Text helpers owned by the Telegram presentation adapter., source_digest()

## Knowledge Gaps
- **146 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `$schema`, `style` (+141 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **29 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AppConfig` connect `SerialPerKeyQueue` to `SerialPerKeyQueue`, `ProfileTests`, `DownloadProgressTracker`, `ExportResult`, `@radix-ui/react-dropdown-menu`, `BatchDownloadService`, `UtilityFolderStore`, `StorageCatalog`, `composition.py`, `DownloadProgressTracker`, `ExportService`, `TDLCommandError`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `BatchDownloadService` to `TDLClient`, `BackendApiTests`, `request_json`, `edit_menu_message`, `ControlPlaneBackupRouter`, `source_digest`, `ExportService`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `models.py`, `FakeProfiles`, `BackupCoordinator`, `composition.py`, `FakeDispatcher`, `SqliteAuthRepository`, `RunScriptTests`?**
  _High betweenness centrality (0.042) - this node is a cross-community bridge._
- **Are the 47 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 47 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `StateStore` (e.g. with `ProfileTests` and `.test_backend_runtime_never_uses_its_own_backend_api_url_for_state()`) actually correct?**
  _`StateStore` has 14 INFERRED edges - model-reasoned connections that need verification._