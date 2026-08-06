# Graph Report - dockter_bot_tdl  (2026-08-07)

## Corpus Check
- 141 files · ~73,373 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1673 nodes · 4392 edges · 77 communities (61 shown, 16 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 419 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `37aade97`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- TDLCommandError
- pindah4.py
- PanelManager
- AppConfig
- organize_media_from_json.py
- Job
- WorkerRegistry
- BackendContext
- BackendApiTests
- run.py
- compress.sh
- config.py
- edit_menu_message
- boltStorage
- ControlPlane
- WorkerContext
- StorageCatalog
- BackupService
- UtilitySettingsStore
- compilerOptions
- telegram/app.py
- BatchDownloadService
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
- TDLClient
- +layout.ts
- JobEvent
- StateStore
- ProfileTests
- DomainError
- RunScriptTests
- parse_tme3_url
- executor.py
- test_pindah.py
- SqliteJobRepository
- ExportWorkspaceState
- DownloadProgressTracker
- FakeStatusPanel
- request_json
- pindah.py
- SqliteAuthRepository
- test_backend_api.py
- WorkspaceExplorer.svelte
- job-progress.ts
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- models.py
- composition.py
- JsonHttpError
- Overview.svelte
- LabelStore
- StorageMaintenanceService
- sign_storage_item
- TME3Bot Deployment Runbook
- _error
- ../styles.css
- ArchitectureBoundaryTests
- infrastructure/__init__.py

## God Nodes (most connected - your core abstractions)
1. `StorageCatalog` - 93 edges
2. `TelegramFrontendApp` - 74 edges
3. `BackendContext` - 70 edges
4. `StateStore` - 46 edges
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

## Communities (77 total, 16 thin omitted)

### Community 0 - "TDLCommandError"
Cohesion: 0.21
Nodes (9): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, LeaveResult, LeaveService, build_telegram_message_url(), ExportResult (+1 more)

### Community 1 - "pindah4.py"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "AppConfig"
Cohesion: 0.10
Nodes (21): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), Any, Path, write_json_atomic(), build_profile_config(), build_profile_runtime() (+13 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.19
Nodes (7): Protocol, ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher, Job

### Community 6 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 7 - "BackendContext"
Cohesion: 0.13
Nodes (27): BackendContext, ActorResponse, ApiResponse, BrowserChallengeResponse, BrowserSessionResponse, ChallengeExchangeResponse, ChallengeResponse, ErrorBody (+19 more)

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
Cohesion: 0.11
Nodes (10): ControlPlaneTests, FakeDispatcher, FakeProfiles, ControlPlane, Any, Application facade used by every frontend adapter., _redact_secrets(), serializable() (+2 more)

### Community 15 - "WorkerContext"
Cohesion: 0.14
Nodes (9): FakeExecutor, WorkerApiTests, WorkerJobRequest, create_worker_app(), _error(), FastAPI, JSONResponse, Request (+1 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (17): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+9 more)

### Community 17 - "BackupService"
Cohesion: 0.09
Nodes (16): BackupServiceTests, make_config(), Path, BackupCoordinator, BackupNodeJob, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup. (+8 more)

### Community 18 - "UtilitySettingsStore"
Cohesion: 0.12
Nodes (11): UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, UtilityFolderStore, UtilityPathError, UtilityResult, UtilityRunner (+3 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.18
Nodes (17): Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), InlineKeyboardMarkup, Inline keyboards used by the API-backed Telegram frontend. (+9 more)

### Community 21 - "BatchDownloadService"
Cohesion: 0.15
Nodes (15): has_downloadable_media(), is_image_message(), Any, BatchDownloadResult, BatchDownloadService, DownloadedJsonResult, ExportJobResult, ExportService (+7 more)

### Community 22 - "WorkerJobExecutor"
Cohesion: 0.07
Nodes (23): FakePublisher, ProgressReporterTests, StorageWorkerPathTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed. (+15 more)

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
Cohesion: 0.20
Nodes (26): BaseModel, ApproveChallengeRequest, BatchSourcesRequest, BrowserProfileRequest, ChallengeTokenRequest, DownloadRequest, ExportRequest, LabelRequest (+18 more)

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

### Community 37 - "TDLClient"
Cohesion: 0.06
Nodes (41): OutputCallback, Popen, ProgressCallback, Queue, FakeRunner, TDLClientTests, decode_process_output(), _message_contains_caption() (+33 more)

### Community 41 - "JobEvent"
Cohesion: 0.25
Nodes (3): JobStoreTests, Update the latest telemetry without growing persistent event history., JobEvent

### Community 43 - "StateStore"
Cohesion: 0.11
Nodes (10): StateStoreTests, HttpStateStore, normalize_chat_ref(), Any, Path, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file., SourceState (+2 more)

### Community 45 - "DomainError"
Cohesion: 0.13
Nodes (17): _active_storage_item(), _add_internal_state_routes(), _add_management_routes(), create_backend_app(), _deliver_storage_telegram(), _owned_job(), _profile_artifact(), FastAPI (+9 more)

### Community 49 - "parse_tme3_url"
Cohesion: 0.30
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 52 - "SqliteJobRepository"
Cohesion: 0.17
Nodes (7): _dump(), _load(), Connection, Path, Row, Keep only the newest high-frequency telemetry snapshot., SqliteJobRepository

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.12
Nodes (15): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), normalize_chat_ref(), Any (+7 more)

### Community 55 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

### Community 56 - "request_json"
Cohesion: 0.26
Nodes (5): BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Frontend adapters. They communicate with the backend only through JSON., request_json()

### Community 57 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.13
Nodes (11): AuthServiceTests, Path, BotAuthService, _hash_secret(), _now(), Any, Connection, datetime (+3 more)

### Community 59 - "test_backend_api.py"
Cohesion: 0.10
Nodes (4): FakeDispatcher, FakeProfiles, FakeTelegramBot, FakeWorkers

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
Cohesion: 0.29
Nodes (7): Enum, str, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, JobStatus, datetime, utc_now()

### Community 66 - "composition.py"
Cohesion: 0.18
Nodes (10): configure_logging(), main(), BackupScheduler, build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, run_backend() (+2 more)

### Community 67 - "JsonHttpError"
Cohesion: 0.33
Nodes (4): JsonHttpError, Any, RuntimeError, WorkerHttpDispatcher

### Community 68 - "Overview.svelte"
Cohesion: 0.15
Nodes (4): describe(), error, icons, label()

### Community 69 - "LabelStore"
Cohesion: 0.24
Nodes (7): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, utc_now_iso(), slugify_label()

### Community 71 - "sign_storage_item"
Cohesion: 0.52
Nodes (4): StorageLinkTests, Compact, stable HMAC tokens for Telegram storage deep links., sign_storage_item(), verify_storage_item()

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.07
Nodes (27): A. Langkah di komputer lokal, B. Langkah di VPS builder besar, Backend atau worker, Batas keamanan, C. Langkah di VPS gateway, D. Langkah di setiap VPS worker remote, E. Deploy web static di VPS gateway, F. Smoke test worker dan Download manager (+19 more)

### Community 73 - "_error"
Cohesion: 0.29
Nodes (7): _error(), event_dict(), job_dict(), _model_dict(), Any, JSONResponse, Request

## Knowledge Gaps
- **98 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+93 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `composition.py`, `PanelManager`, `JsonHttpError`, `edit_menu_message`, `telegram/app.py`, `FakeStatusPanel`, `request_json`?**
  _High betweenness centrality (0.111) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `composition.py`, `BackendApiTests`, `DomainError`, `BackupService`, `test_backend_api.py`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Why does `AppConfig` connect `AppConfig` to `TDLCommandError`, `composition.py`, `config.py`, `ProfileTests`, `StateStore`, `BackupService`, `BatchDownloadService`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `FakeClient`) actually correct?**
  _`TelegramFrontendApp` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 55 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 55 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `StateStore` (e.g. with `ProfileTests` and `FakeDownloadTDLClient`) actually correct?**
  _`StateStore` has 13 INFERRED edges - model-reasoned connections that need verification._