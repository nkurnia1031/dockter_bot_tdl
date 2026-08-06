# Graph Report - dockter_bot_tdl  (2026-08-07)

## Corpus Check
- 141 files · ~73,682 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1678 nodes · 4410 edges · 75 communities (60 shown, 15 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 419 edges (avg confidence: 0.53)
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
- Job
- WorkerRegistry
- SubprocessRunner
- BackendApiTests
- run.py
- compress.sh
- config.py
- edit_menu_message
- boltStorage
- ControlPlane
- request_json
- StorageCatalog
- BackupService
- utility.py
- compilerOptions
- telegram/app.py
- TDLClient
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
- ProfileRegistry
- tdl_output.py
- +layout.ts
- ProfileManager
- StateStore
- ProfileTests
- ControlPlaneTests
- RunScriptTests
- tdl.py
- executor.py
- test_pindah.py
- SqliteJobRepository
- ExportWorkspaceState
- .upload
- FakeStatusPanel
- write_json_atomic
- pindah.py
- SqliteAuthRepository
- composition.py
- WorkspaceExplorer.svelte
- job-progress.ts
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- models.py
- WorkerEventPublisher
- JobLogSnapshot
- Overview.svelte
- LabelStore
- .sync_profiles
- TME3Bot Deployment Runbook
- ../styles.css
- ArchitectureBoundaryTests
- infrastructure/__init__.py

## God Nodes (most connected - your core abstractions)
1. `StorageCatalog` - 93 edges
2. `TelegramFrontendApp` - 74 edges
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
- `AuthServiceTests` --uses--> `BotAuthService`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `AuthServiceTests` --uses--> `SqliteAuthRepository`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py

## Import Cycles
- None detected.

## Communities (75 total, 15 thin omitted)

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
Cohesion: 0.18
Nodes (15): AppConfig, Fail fast when a production role is missing its trust boundary., LeaveResult, LeaveService, build_profile_config(), build_profile_runtime(), chown_paths(), chown_tree() (+7 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.14
Nodes (10): Protocol, JobStoreTests, Update the latest telemetry without growing persistent event history., ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher (+2 more)

### Community 6 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 7 - "SubprocessRunner"
Cohesion: 0.20
Nodes (5): OutputCallback, Popen, ProgressCallback, Queue, SubprocessRunner

### Community 8 - "BackendApiTests"
Cohesion: 0.15
Nodes (5): BackendApiTests, StorageLinkTests, Compact, stable HMAC tokens for Telegram storage deep links., sign_storage_item(), verify_storage_item()

### Community 9 - "run.py"
Cohesion: 0.06
Nodes (70): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+62 more)

### Community 11 - "config.py"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`…, load_dotenv(), _parse_named_values()

### Community 12 - "edit_menu_message"
Cohesion: 0.22
Nodes (5): Thread, PendingInput, Any, main_menu_markup(), edit_menu_message()

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "ControlPlane"
Cohesion: 0.13
Nodes (12): AuthServiceTests, Path, ControlPlane, Any, Application facade used by every frontend adapter., _redact_secrets(), serializable(), Application services and use cases. (+4 more)

### Community 15 - "request_json"
Cohesion: 0.07
Nodes (19): FakeExecutor, WorkerApiTests, create_worker_app(), _error(), FastAPI, JSONResponse, Request, WorkerContext (+11 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (20): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+12 more)

### Community 17 - "BackupService"
Cohesion: 0.09
Nodes (15): BackupServiceTests, make_config(), Path, BackupCoordinator, BackupNodeJob, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup. (+7 more)

### Community 18 - "utility.py"
Cohesion: 0.11
Nodes (10): UtilitySummaryTests, Path, ValueError, Public metadata for clients; never contains a setting value or secret., utility_setting_specs(), UtilityPathError, UtilityResult, UtilityRunner (+2 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.18
Nodes (17): Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), InlineKeyboardMarkup, Inline keyboards used by the API-backed Telegram frontend. (+9 more)

### Community 21 - "TDLClient"
Cohesion: 0.22
Nodes (4): FakeRunner, TDLClientTests, decode_process_output(), TDLClient

### Community 22 - "WorkerJobExecutor"
Cohesion: 0.17
Nodes (7): json_value(), Any, Exception, Path, Return a safe, shallow directory listing for the active workspace., Executes domain jobs and publishes JSON events; no UI dependency., WorkerJobExecutor

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.20
Nodes (5): CallbackContext, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

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
Cohesion: 0.08
Nodes (71): BaseModel, _active_storage_item(), _add_internal_state_routes(), _add_management_routes(), BackendContext, _deliver_storage_telegram(), _error(), event_dict() (+63 more)

### Community 29 - "devDependencies"
Cohesion: 0.05
Nodes (43): bits-ui, jsdom, @lucide/svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss (+35 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (32): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+24 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.15
Nodes (10): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape. (+2 more)

### Community 36 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 37 - "tdl_output.py"
Cohesion: 0.18
Nodes (18): _byte_multiplier(), clean_tdl_output_line(), _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_elapsed_seconds(), parse_eta_seconds() (+10 more)

### Community 41 - "ProfileManager"
Cohesion: 0.23
Nodes (4): normalize_profile_name(), ProfileManager, Path, Metadata a worker can safely publish to the backend registry.

### Community 43 - "StateStore"
Cohesion: 0.05
Nodes (36): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, StateStoreTests, has_downloadable_media(), is_image_message(), Any (+28 more)

### Community 45 - "ControlPlaneTests"
Cohesion: 0.14
Nodes (3): ControlPlaneTests, FakeDispatcher, FakeProfiles

### Community 49 - "tdl.py"
Cohesion: 0.19
Nodes (11): _message_contains_caption(), _normalize_upload_caption(), CommandProgress, parse_terminal_size(), prepare_subprocess_command(), Any, RuntimeError, Match captions across the different JSON shapes emitted by TDL. (+3 more)

### Community 50 - "executor.py"
Cohesion: 0.24
Nodes (5): StorageWorkerPathTests, Return nested directories, including empty ones, as portable paths., storage_logical_folder(), storage_relative_folders(), Framework-independent worker execution adapter.

### Community 52 - "SqliteJobRepository"
Cohesion: 0.18
Nodes (7): _dump(), _load(), Connection, Path, Row, Keep only the newest high-frequency telemetry snapshot., SqliteJobRepository

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.12
Nodes (15): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), normalize_chat_ref(), Any (+7 more)

### Community 54 - ".upload"
Cohesion: 0.36
Nodes (4): CompletedProcess, Path, Upload exactly one file and return its Telegram channel message id., Resolve delayed TDL upload results by polling channel history. Some TDL…

### Community 55 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

### Community 56 - "write_json_atomic"
Cohesion: 0.24
Nodes (4): Any, Path, write_json_atomic(), ProfileSelectionStore

### Community 57 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.15
Nodes (9): BotAuthService, _hash_secret(), _now(), Any, Connection, datetime, Path, SqliteAuthRepository (+1 more)

### Community 59 - "composition.py"
Cohesion: 0.10
Nodes (15): FakeDispatcher, FakeProfiles, FakeTelegramBot, FakeWorkers, UtilitySettingsTests, create_backend_app(), BackupScheduler, build_backend_context() (+7 more)

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

### Community 65 - "models.py"
Cohesion: 0.28
Nodes (7): Enum, str, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, JobStatus, datetime, utc_now()

### Community 68 - "Overview.svelte"
Cohesion: 0.15
Nodes (4): describe(), error, icons, label()

### Community 69 - "LabelStore"
Cohesion: 0.14
Nodes (11): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, parse_tme3_url(), ValueError (+3 more)

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.07
Nodes (28): A. Langkah di komputer lokal, B. Langkah di VPS builder besar, Backend atau worker, Batas keamanan, C. Langkah di VPS gateway, D. Langkah di setiap VPS worker remote, E. Deploy web static di VPS gateway, F. Smoke test worker dan Download manager (+20 more)

## Knowledge Gaps
- **98 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+93 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `PanelManager`, `edit_menu_message`, `request_json`, `telegram/app.py`, `FakeStatusPanel`?**
  _High betweenness centrality (0.111) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `BackendApiTests`, `BackupService`, `composition.py`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `AppConfig` connect `AppConfig` to `ProfileManager`, `config.py`, `ProfileTests`, `StateStore`, `request_json`, `BackupService`, `write_json_atomic`, `composition.py`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `FakeClient`) actually correct?**
  _`TelegramFrontendApp` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 55 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 55 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `StateStore` (e.g. with `ProfileTests` and `FakeDownloadTDLClient`) actually correct?**
  _`StateStore` has 13 INFERRED edges - model-reasoned connections that need verification._