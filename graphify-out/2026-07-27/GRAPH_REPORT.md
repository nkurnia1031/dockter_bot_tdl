# Graph Report - dockter_bot_tdl  (2026-07-27)

## Corpus Check
- 139 files · ~67,632 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1569 nodes · 4152 edges · 75 communities (60 shown, 15 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 416 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `4c430550`
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
- ProfileManager
- HttpStateStore
- @radix-ui/react-dropdown-menu
- DownloadProgressTracker
- tme3bot/app.py
- build_profile_runtime
- ProfileSelectionStore
- models.py
- ControlPlaneTests
- BatchDownloadService
- UtilityFolderStore
- BatchDownloadService
- request_json
- executor.py
- SqliteAuthRepository
- ControlPlaneTests
- WorkspaceExplorer.svelte
- job-progress.ts
- presentation.ts
- $lib/components/Shell.svelte
- TDLClient
- tme3bot/app.py
- pindah.py
- $lib/components/Overview.svelte
- .sync_profiles
- BatchDownloadService
- tme3bot
- ProfileTests
- ArchitectureBoundaryTests
- write_json_atomic
- infrastructure/__init__.py

## God Nodes (most connected - your core abstractions)
1. `StorageCatalog` - 92 edges
2. `BackendContext` - 66 edges
3. `TelegramFrontendApp` - 63 edges
4. `$lib/components/StoragePage.svelte` - 48 edges
5. `StateStore` - 47 edges
6. `AppConfig` - 44 edges
7. `SqliteJobRepository` - 41 edges
8. `ControlPlane` - 39 edges
9. `DomainError` - 39 edges
10. `create_backend_app()` - 38 edges

## Surprising Connections (you probably didn't know these)
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `FakeProfiles` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py
- `FakeProfiles` --uses--> `ControlPlane`  [INFERRED]
  tests/test_backend_api.py → tme3bot/application/control_plane.py
- `FakeProfiles` --uses--> `Actor`  [INFERRED]
  tests/test_backend_api.py → tme3bot/domain/models.py
- `FakeProfiles` --uses--> `BotAuthService`  [INFERRED]
  tests/test_backend_api.py → tme3bot/infrastructure/auth.py

## Import Cycles
- None detected.

## Communities (75 total, 15 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.32
Nodes (5): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, ExportResult

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.10
Nodes (11): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+3 more)

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.15
Nodes (8): JobStoreTests, _dump(), _load(), Connection, Path, Row, Keep only the newest high-frequency telemetry snapshot., SqliteJobRepository

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.15
Nodes (6): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup.

### Community 6 - "LabelStore"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 7 - "bot_text.py"
Cohesion: 0.21
Nodes (5): OutputCallback, Popen, ProgressCallback, Queue, SubprocessRunner

### Community 8 - "UtilityHandler"
Cohesion: 0.19
Nodes (12): $lib/api, api(), ApiError, csrf(), patch(), put(), remove(), $lib/components/SettingsPage.svelte (+4 more)

### Community 9 - "ProfileManager"
Cohesion: 0.07
Nodes (65): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+57 more)

### Community 11 - "ExportResult"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl.      Bot API uses `-100<peer i, load_dotenv(), _parse_named_values()

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.12
Nodes (20): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), Any, Path, write_json_atomic(), build_profile_config(), build_profile_runtime() (+12 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "next"
Cohesion: 0.15
Nodes (16): LeaveResult, LeaveService, has_downloadable_media(), is_image_message(), Any, build_telegram_message_url(), DownloadedJsonResult, ExportJobResult (+8 more)

### Community 15 - "WorkerRegistry"
Cohesion: 0.17
Nodes (8): FakeExecutor, WorkerApiTests, create_worker_app(), _error(), FastAPI, JSONResponse, Request, WorkerContext

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (17): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+9 more)

### Community 17 - "composition.py"
Cohesion: 0.19
Nodes (10): BackupServiceTests, make_config(), Path, BackupArchive, BackupService, Path, Create encrypted, runtime-only per-node backup archives., safe_node_name() (+2 more)

### Community 18 - "config.py"
Cohesion: 0.12
Nodes (11): UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, UtilityFolderStore, UtilityPathError, UtilityResult, UtilityRunner (+3 more)

### Community 19 - "ProfileManager"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 22 - "ProfileTests"
Cohesion: 0.14
Nodes (10): sha256_file(), JsonHttpError, JobLogSnapshot, json_value(), Any, Exception, Executes domain jobs and publishes JSON events; no UI dependency., Publish only profile metadata; .tdl files remain on this worker. (+2 more)

### Community 24 - "ExportService"
Cohesion: 0.17
Nodes (9): FakePublisher, ProgressReporterTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed., utc_timestamp() (+1 more)

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.33
Nodes (11): cleanup_empty_directory(), emit_progress(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main() (+3 more)

### Community 27 - "TDLCommandError"
Cohesion: 0.18
Nodes (9): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, Runs different keys concurrently while keeping each key serial., SerialPerKeyQueue (+1 more)

### Community 28 - "RunScriptTests"
Cohesion: 0.08
Nodes (76): BaseModel, StorageLinkTests, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _error(), event_dict() (+68 more)

### Community 29 - "Path"
Cohesion: 0.05
Nodes (43): bits-ui, jsdom, @lucide/svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss (+35 more)

### Community 30 - "dependencies"
Cohesion: 0.07
Nodes (16): $lib/components/StoragePage.svelte, createOpen, currentName, displayName, editKeywords, emptyTrash(), isTrash, keywords (+8 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.18
Nodes (9): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts.  The worker owns the physical J, Return safe media statistics without assuming a single TDL JSON shape. (+1 more)

### Community 36 - "BackupCoordinator"
Cohesion: 0.12
Nodes (6): FakeDispatcher, FakeWorkers, ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions.      A, One-way migration for installations created before the registry.

### Community 37 - "ExportService"
Cohesion: 0.16
Nodes (17): _byte_multiplier(), clean_tdl_output_line(), _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_elapsed_seconds(), parse_eta_seconds() (+9 more)

### Community 41 - "ProfileManager"
Cohesion: 0.25
Nodes (8): _normalize_upload_caption(), CompletedProcess, Path, RuntimeError, Raised when TDL returns unusable or malformed export data., Upload exactly one file and return its Telegram channel message id., Resolve delayed TDL upload results by polling channel history.          Some TDL, TDLDataError

### Community 43 - "HttpStateStore"
Cohesion: 0.11
Nodes (10): StateStoreTests, HttpStateStore, normalize_chat_ref(), Any, Path, Canonical source key: usernames ignore @ and letter case.      Numeric Telegram, StateStore-compatible client used by a worker without a local state file., SourceState (+2 more)

### Community 44 - "@radix-ui/react-dropdown-menu"
Cohesion: 0.27
Nodes (4): BackendApiClient, Any, Frontend adapters. They communicate with the backend only through JSON., request_json()

### Community 45 - "DownloadProgressTracker"
Cohesion: 0.23
Nodes (6): build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, WorkerHttpDispatcher, WorkerEventPublisher

### Community 49 - "build_profile_runtime"
Cohesion: 0.23
Nodes (14): post(), chooseScope(), clearSelection(), createFolder(), deliver(), dropOnFolder(), load(), moveSelection() (+6 more)

### Community 52 - "ControlPlaneTests"
Cohesion: 0.11
Nodes (14): Enum, Protocol, Update the latest telemetry without growing persistent event history., ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher (+6 more)

### Community 53 - "BatchDownloadService"
Cohesion: 0.06
Nodes (42): CallbackContext, AppMenuTests, ExportWorkspaceTests, PendingInput, Any, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp (+34 more)

### Community 54 - "UtilityFolderStore"
Cohesion: 0.26
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 55 - "BatchDownloadService"
Cohesion: 0.67
Nodes (3): _message_contains_caption(), Any, Match captions across the different JSON shapes emitted by TDL.

### Community 57 - "executor.py"
Cohesion: 0.16
Nodes (7): StorageWorkerPathTests, Path, Return a safe, shallow directory listing for the active workspace., Return nested directories, including empty ones, as portable paths., storage_logical_folder(), storage_relative_folders(), Framework-independent worker execution adapter.

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.12
Nodes (16): str, AuthServiceTests, Path, AuthChallengeStatus, DomainError, Any, RuntimeError, BotAuthService (+8 more)

### Community 59 - "ControlPlaneTests"
Cohesion: 0.11
Nodes (10): ControlPlaneTests, FakeDispatcher, FakeProfiles, ControlPlane, Any, Application facade used by every frontend adapter., _redact_secrets(), serializable() (+2 more)

### Community 60 - "WorkspaceExplorer.svelte"
Cohesion: 0.38
Nodes (4): crumbs, goUp(), load(), openCrumb()

### Community 61 - "job-progress.ts"
Cohesion: 0.39
Nodes (6): clampPercent(), formatDuration(), JobLike, NormalizedProgress, normalizeJobProgress(), number()

### Community 62 - "presentation.ts"
Cohesion: 0.15
Nodes (10): $lib/components/BackupsPage.svelte, ./JobProgressCard.svelte, $lib/components/JobTable.svelte, formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem (+2 more)

### Community 63 - "$lib/components/Shell.svelte"
Cohesion: 0.15
Nodes (8): ../styles.css, ./Login.svelte, $lib/components/Shell.svelte, $lib/components/WorkersPage.svelte, challenge, current, loading, Session

### Community 64 - "TDLClient"
Cohesion: 0.30
Nodes (4): FakeRunner, TDLClientTests, decode_process_output(), TDLClient

### Community 65 - "tme3bot/app.py"
Cohesion: 0.60
Nodes (4): configure_logging(), main(), run_backend(), run_worker()

### Community 67 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 68 - "$lib/components/Overview.svelte"
Cohesion: 0.40
Nodes (5): $lib/components/Overview.svelte, describe(), error, icons, label()

### Community 69 - ".sync_profiles"
Cohesion: 0.14
Nodes (12): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, utc_now_iso(), parse_tme3_url() (+4 more)

### Community 71 - "BatchDownloadService"
Cohesion: 0.36
Nodes (5): BatchDownloadResult, BatchDownloadService, Path, Download selected opaque filenames after strict directory validation., unique_path()

### Community 72 - "tme3bot"
Cohesion: 0.07
Nodes (26): A. Langkah di komputer lokal, B. Langkah di VPS builder besar, Backend atau worker, Batas keamanan, C. Langkah di VPS gateway, D. Langkah di setiap VPS worker remote, E. Deploy web static di VPS gateway, F. Smoke test telemetry progress (+18 more)

## Knowledge Gaps
- **93 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+88 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AppConfig` connect `SerialPerKeyQueue` to `ProfileManager`, `tme3bot/app.py`, `BatchDownloadService`, `ProfileTests`, `ExportResult`, `HttpStateStore`, `DownloadProgressTracker`, `next`, `write_json_atomic`, `composition.py`, `UtilityFolderStore`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `BackupCoordinator`, `DownloadProgressTracker`, `tme3bot/app.py`, `composition.py`, `DownloadProgressTracker`, `ControlPlaneTests`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `BatchDownloadService` to `tme3bot/app.py`, `TDLClient`, `@radix-ui/react-dropdown-menu`, `ProfileTests`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **Are the 12 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 53 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 53 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `ExportWorkspaceStore`) actually correct?**
  _`TelegramFrontendApp` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `$lib/components/StoragePage.svelte` (e.g. with `clearSelection()` and `emptyTrash()`) actually correct?**
  _`$lib/components/StoragePage.svelte` has 4 INFERRED edges - model-reasoned connections that need verification._