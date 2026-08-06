# Graph Report - dockter_bot_tdl  (2026-08-07)

## Corpus Check
- 141 files · ~73,966 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1683 nodes · 4425 edges · 73 communities (57 shown, 16 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 419 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `0dbb45db`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ProgressReporter
- pindah4.py
- PanelManager
- AppConfig
- organize_media_from_json.py
- SqliteJobRepository
- WorkerRegistry
- BatchDownloadService
- BackendApiTests
- run.py
- compress.sh
- config.py
- edit_menu_message
- boltStorage
- AuthServiceTests
- request_json
- StorageCatalog
- BackupCoordinator
- UtilitySettingsStore
- compilerOptions
- telegram/app.py
- ExportService
- WorkerJobExecutor
- tme3bot-leave-helper
- TelegramFrontendApp
- tme3bot Agent Context
- extract.py
- SerialPerKeyQueue
- backend.py
- devDependencies
- StoragePage.svelte
- tme3bot/__init__.py
- pindah.sh script
- svelte.config.js
- ExportArtifactCatalog
- composition.py
- TDLClient
- +layout.ts
- ProfileManager
- StateStore
- ProfileTests
- BackupService
- FakeProfiles
- DownloadProgressTracker
- executor.py
- test_pindah.py
- test_backup_service.py
- ExportWorkspaceState
- tme3bot/app.py
- FakeStatusPanel
- Path
- pindah.py
- SqliteAuthRepository
- test_backend_api.py
- WorkspaceExplorer.svelte
- job-progress.ts
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- WorkerEventPublisher
- JobLogSnapshot
- Overview.svelte
- LabelStore
- TME3Bot Deployment Runbook
- ../styles.css
- ArchitectureBoundaryTests
- infrastructure/__init__.py

## God Nodes (most connected - your core abstractions)
1. `StorageCatalog` - 93 edges
2. `TelegramFrontendApp` - 76 edges
3. `BackendContext` - 70 edges
4. `StateStore` - 47 edges
5. `AppConfig` - 44 edges
6. `SqliteJobRepository` - 42 edges
7. `ControlPlane` - 40 edges
8. `WorkerJobExecutor` - 39 edges
9. `DomainError` - 37 edges
10. `Job` - 36 edges

## Surprising Connections (you probably didn't know these)
- `FakePanel` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `FakeClient` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `AppMenuTests` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `DomainError`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py

## Import Cycles
- None detected.

## Communities (73 total, 16 thin omitted)

### Community 0 - "ProgressReporter"
Cohesion: 0.17
Nodes (9): FakePublisher, ProgressReporterTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed., utc_timestamp() (+1 more)

### Community 1 - "pindah4.py"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "AppConfig"
Cohesion: 0.12
Nodes (18): AppConfig, Fail fast when a production role is missing its trust boundary., Any, Path, utc_now_iso(), write_json_atomic(), ProfileRegistry, Gateway-owned registry for profile metadata, separate from TDL sessions. A… (+10 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "SqliteJobRepository"
Cohesion: 0.05
Nodes (33): Enum, Protocol, str, ControlPlaneTests, FakeDispatcher, FakeProfiles, JobStoreTests, ControlPlane (+25 more)

### Community 6 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 7 - "BatchDownloadService"
Cohesion: 0.14
Nodes (16): LeaveResult, LeaveService, BatchDownloadResult, BatchDownloadService, DownloadedJsonResult, ExportJobResult, media_ids_in_export(), Any (+8 more)

### Community 9 - "run.py"
Cohesion: 0.06
Nodes (70): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+62 more)

### Community 11 - "config.py"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`…, load_dotenv(), _parse_named_values()

### Community 12 - "edit_menu_message"
Cohesion: 0.17
Nodes (5): Thread, PendingInput, Any, main_menu_markup(), edit_menu_message()

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 15 - "request_json"
Cohesion: 0.08
Nodes (11): RunScriptTests, CompletedProcess, BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Frontend adapters. They communicate with the backend only through JSON., JsonHttpError, Any (+3 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (19): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+11 more)

### Community 17 - "BackupCoordinator"
Cohesion: 0.14
Nodes (7): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., sha256_file()

### Community 18 - "UtilitySettingsStore"
Cohesion: 0.14
Nodes (10): UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, UtilityPathError, UtilityResult, UtilityRunner, UtilitySettingsStore (+2 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.21
Nodes (17): Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), InlineKeyboardMarkup, Inline keyboards used by the API-backed Telegram frontend. (+9 more)

### Community 21 - "ExportService"
Cohesion: 0.20
Nodes (10): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, has_downloadable_media(), is_image_message(), Any, build_telegram_message_url() (+2 more)

### Community 22 - "WorkerJobExecutor"
Cohesion: 0.15
Nodes (6): json_value(), Any, Exception, Executes domain jobs and publishes JSON events; no UI dependency., Publish only profile metadata; .tdl files remain on this worker., WorkerJobExecutor

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.20
Nodes (6): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "extract.py"
Cohesion: 0.33
Nodes (11): cleanup_empty_directory(), emit_progress(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main() (+3 more)

### Community 27 - "SerialPerKeyQueue"
Cohesion: 0.18
Nodes (9): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, Runs different keys concurrently while keeping each key serial., SerialPerKeyQueue (+1 more)

### Community 28 - "backend.py"
Cohesion: 0.07
Nodes (82): BaseModel, StorageLinkTests, _active_storage_item(), _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _deliver_storage_telegram() (+74 more)

### Community 29 - "devDependencies"
Cohesion: 0.05
Nodes (43): bits-ui, jsdom, @lucide/svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss (+35 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (32): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+24 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.15
Nodes (10): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape. (+2 more)

### Community 36 - "composition.py"
Cohesion: 0.11
Nodes (11): FakeExecutor, WorkerApiTests, create_worker_app(), _error(), FastAPI, JSONResponse, Request, WorkerContext (+3 more)

### Community 37 - "TDLClient"
Cohesion: 0.06
Nodes (41): OutputCallback, Popen, ProgressCallback, Queue, FakeRunner, TDLClientTests, decode_process_output(), _message_contains_caption() (+33 more)

### Community 41 - "ProfileManager"
Cohesion: 0.13
Nodes (9): build_backend_context(), _first_actor(), normalize_profile_name(), Path, get_profile_download_mode(), ProfileManager, ProfileSelectionStore, Path (+1 more)

### Community 43 - "StateStore"
Cohesion: 0.12
Nodes (10): StateStoreTests, HttpStateStore, normalize_chat_ref(), Any, Path, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file., SourceState (+2 more)

### Community 44 - "ProfileTests"
Cohesion: 0.40
Nodes (3): ProfileTests, Path, build_profile_config()

### Community 45 - "BackupService"
Cohesion: 0.26
Nodes (6): BackupArchive, BackupService, Path, Create encrypted, runtime-only per-node backup archives., safe_node_name(), utc_now()

### Community 49 - "DownloadProgressTracker"
Cohesion: 0.29
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 50 - "executor.py"
Cohesion: 0.24
Nodes (5): StorageWorkerPathTests, Return nested directories, including empty ones, as portable paths., storage_logical_folder(), storage_relative_folders(), Framework-independent worker execution adapter.

### Community 52 - "test_backup_service.py"
Cohesion: 0.60
Nodes (3): BackupServiceTests, make_config(), Path

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.12
Nodes (15): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), normalize_chat_ref(), Any (+7 more)

### Community 54 - "tme3bot/app.py"
Cohesion: 0.70
Nodes (3): configure_logging(), main(), run_backend()

### Community 55 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

### Community 57 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.15
Nodes (10): AuthChallengeStatus, BotAuthService, _hash_secret(), _now(), Any, Connection, datetime, Path (+2 more)

### Community 59 - "test_backend_api.py"
Cohesion: 0.15
Nodes (4): FakeDispatcher, FakeTelegramBot, FakeWorkers, UtilityFolderStore

### Community 60 - "WorkspaceExplorer.svelte"
Cohesion: 0.24
Nodes (5): async(), crumbs, goUp(), load(), openCrumb()

### Community 61 - "job-progress.ts"
Cohesion: 0.39
Nodes (6): clampPercent(), formatDuration(), JobLike, NormalizedProgress, normalizeJobProgress(), number()

### Community 62 - "presentation.ts"
Cohesion: 0.16
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 63 - "session.svelte.ts"
Cohesion: 0.13
Nodes (15): api(), ApiError, csrf(), put(), remove(), challenge, contextRevision, current (+7 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.12
Nodes (8): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore, help_text(), Text helpers owned by the Telegram presentation adapter., source_digest()

### Community 68 - "Overview.svelte"
Cohesion: 0.15
Nodes (4): describe(), error, icons, label()

### Community 69 - "LabelStore"
Cohesion: 0.13
Nodes (10): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, parse_tme3_url(), ValueError (+2 more)

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.07
Nodes (28): A. Langkah di komputer lokal, B. Langkah di VPS builder besar, Backend atau worker, Batas keamanan, C. Langkah di VPS gateway, D. Langkah di setiap VPS worker remote, E. Deploy web static di VPS gateway, F. Smoke test worker dan Download manager (+20 more)

## Knowledge Gaps
- **98 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+93 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `PanelManager`, `edit_menu_message`, `request_json`, `telegram/app.py`, `tme3bot/app.py`, `FakeStatusPanel`?**
  _High betweenness centrality (0.120) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `composition.py`, `BackendApiTests`, `ProfileManager`, `BackupService`, `FakeProfiles`, `test_backup_service.py`, `test_backend_api.py`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Why does `JsonHttpError` connect `request_json` to `WorkerEventPublisher`, `JobLogSnapshot`, `edit_menu_message`, `executor.py`, `telegram/app.py`, `WorkerJobExecutor`, `TelegramFrontendApp`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `FakeClient`) actually correct?**
  _`TelegramFrontendApp` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 55 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 55 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `StateStore` (e.g. with `ProfileTests` and `FakeDownloadTDLClient`) actually correct?**
  _`StateStore` has 13 INFERRED edges - model-reasoned connections that need verification._