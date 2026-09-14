# Graph Report - dockter_bot_tdl  (2026-09-15)

## Corpus Check
- 148 files · ~96,440 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 2157 nodes · 5187 edges · 95 communities (75 shown, 17 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 275 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e7918d0a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- FakeExecutor
- pindah4.py
- PanelManager
- profiles.py
- organize_media_from_json.py
- Job
- WorkerRegistry
- BatchDownloadService
- ProfileTests
- run.py
- compress.sh
- create_worker_app
- Any
- boltStorage
- format_job_status
- BackendApiTests
- StorageCatalog
- create_backend_app
- BackupService
- compilerOptions
- telegram/app.py
- ServiceTests
- WorkerJobExecutor
- tme3bot-leave-helper
- TelegramFrontendApp
- tme3bot Agent Context
- extract.py
- ResourceAwareQueue
- backend.py
- package.json
- StoragePage.svelte
- tme3bot/__init__.py
- pindah.sh script
- QuickThumbnailBuilder
- ExportArtifactCatalog
- BackupCoordinator
- TDLClient
- DomainError
- +layout.ts
- 8. Urutan implementasi
- ProgressReporter
- HttpStateStore
- api.ts
- request_json
- LabelStore
- vitest
- DownloadProgressTracker
- FakeWorkers
- test_pindah.py
- composition.py
- ExportWorkspaceState
- browser_refresh
- ProfileManager
- 12. Bootstrap VPS baru dan satu-command deployment
- .setUp
- SqliteAuthRepository
- ControlPlane
- WorkspaceExplorer.svelte
- job-progress.ts
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- FakeStatusPanel
- StateStore
- parse_tme3_url
- ._backup
- TME3Bot Deployment Runbook
- JobEvent
- ../styles.css
- ArchitectureBoundaryTests
- 5. Pesan status sementara untuk semua job
- config.py
- infrastructure/__init__.py
- 2. Temuan dari kode saat ini
- executor.py
- 6. Source picker Export Fokus
- write_json_atomic
- 3. Keputusan desain
- control_plane.py
- sign_storage_item
- ExportService
- StorageMaintenanceService
- ControlPlaneTests
- ProfileRegistry
- ContainerBuildTests
- Path
- storage_item_dict
- test_backend_api.py
- tme3bot/app.py

## God Nodes (most connected - your core abstractions)
1. `create_backend_app()` - 177 edges
2. `StorageCatalog` - 86 edges
3. `DomainError` - 82 edges
4. `TelegramFrontendApp` - 76 edges
5. `SqliteJobRepository` - 45 edges
6. `StateStore` - 44 edges
7. `WorkerJobExecutor` - 44 edges
8. `ControlPlane` - 40 edges
9. `JobEvent` - 37 edges
10. `AppConfig` - 36 edges

## Surprising Connections (you probably didn't know these)
- `AppMenuTests` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `DomainError`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `BackendApiTests` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py
- `BackendApiTests` --uses--> `ControlPlane`  [INFERRED]
  tests/test_backend_api.py → tme3bot/application/control_plane.py

## Import Cycles
- None detected.

## Communities (95 total, 17 thin omitted)

### Community 0 - "FakeExecutor"
Cohesion: 0.18
Nodes (3): FakeExecutor, WorkerApiTests, WorkerContext

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "profiles.py"
Cohesion: 0.23
Nodes (14): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), build_profile_config(), build_profile_runtime(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs() (+6 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.13
Nodes (8): Protocol, Update the latest telemetry without growing persistent event history., ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher, Job

### Community 6 - "WorkerRegistry"
Cohesion: 0.17
Nodes (7): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., Return workers that may receive new jobs. A disabled worker remains in…, WorkerRegistry

### Community 7 - "BatchDownloadService"
Cohesion: 0.19
Nodes (12): BatchDownloadResult, BatchDownloadService, build_telegram_message_url(), DownloadedJsonResult, _is_relative_to(), media_ids_in_export(), Path, Download selected opaque filenames after strict directory validation. (+4 more)

### Community 9 - "run.py"
Cohesion: 0.06
Nodes (93): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+85 more)

### Community 11 - "create_worker_app"
Cohesion: 0.15
Nodes (10): WorkerJobRequest, create_worker_app(), authorize(), domain_error(), job_log_snapshot(), unhandled_error(), _error(), FastAPI (+2 more)

### Community 12 - "Any"
Cohesion: 0.14
Nodes (10): Thread, PendingInput, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), loop() (+2 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.18
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (17): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+9 more)

### Community 17 - "create_backend_app"
Cohesion: 0.04
Nodes (39): create_backend_app(), archive_artifact(), archive_job(), cancel_job(), clear_failed(), create_telegram_notification(), delete_artifact_file(), delete_artifacts_batch() (+31 more)

### Community 18 - "BackupService"
Cohesion: 0.07
Nodes (21): BackupServiceTests, make_config(), Path, UtilitySettingsTests, UtilitySummaryTests, BackupArchive, BackupService, Path (+13 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.13
Nodes (23): Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_compact_markup(), _export_source_picker_markup() (+15 more)

### Community 21 - "ServiceTests"
Cohesion: 0.25
Nodes (6): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), ExportResult

### Community 22 - "WorkerJobExecutor"
Cohesion: 0.10
Nodes (11): JobLogSnapshot, json_value(), Any, Exception, Path, Executes domain jobs and publishes JSON events; no UI dependency., Return a safe, shallow directory listing for the active workspace., Publish only profile metadata; .tdl files remain on this worker. (+3 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.18
Nodes (6): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.12
Nodes (16): Arsitektur, Checklist memulai sesi baru, Deployment yang benar, Download Manager: aturan penting, graphify, Jebakan, Model target fitur saat ini, Operasional (+8 more)

### Community 26 - "extract.py"
Cohesion: 0.29
Nodes (11): cleanup_empty_directory(), emit_progress(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main() (+3 more)

### Community 27 - "ResourceAwareQueue"
Cohesion: 0.06
Nodes (26): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, Queue, ResourceAwareQueueTests, SerialPerKeyQueueTests (+18 more)

### Community 28 - "backend.py"
Cohesion: 0.10
Nodes (55): BaseModel, ActorResponse, ApiResponse, ApproveChallengeRequest, BatchSourcesRequest, BrowserChallengeResponse, BrowserProfileRequest, BrowserSessionResponse (+47 more)

### Community 29 - "package.json"
Cohesion: 0.04
Nodes (42): bits-ui, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit (+34 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (33): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+25 more)

### Community 34 - "QuickThumbnailBuilder"
Cohesion: 0.13
Nodes (16): Run the post-export Quick Mode stages while retaining staging on error., cleanup_quick_stage(), datetime, Path, RuntimeError, quick_folder_name(), quick_storage_caption(), quick_year() (+8 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.09
Nodes (18): ExportArtifactCatalogTests, discard_export_without_media(), ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical… (+10 more)

### Community 36 - "BackupCoordinator"
Cohesion: 0.14
Nodes (6): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup.

### Community 37 - "TDLClient"
Cohesion: 0.05
Nodes (46): OutputCallback, Popen, ProgressCallback, FakeRunner, CompletedProcess, TDLClientTests, LeaveResult, LeaveService (+38 more)

### Community 38 - "DomainError"
Cohesion: 0.08
Nodes (31): add_label(), create_storage_folder(), get_source(), purge_storage_entries(), purge_storage_folder(), purge_storage_item(), remove_worker(), require_internal() (+23 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "ProgressReporter"
Cohesion: 0.09
Nodes (13): FakePublisher, ProgressReporterTests, QuickPipelineTests, download_export_to(), _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events. (+5 more)

### Community 43 - "HttpStateStore"
Cohesion: 0.15
Nodes (7): HttpStateStore, normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 44 - "api.ts"
Cohesion: 0.16
Nodes (10): api(), ApiError, csrf(), put(), remove(), describe(), error, icons (+2 more)

### Community 45 - "request_json"
Cohesion: 0.06
Nodes (11): RunScriptTests, fake_docker(), BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Frontend adapters. They communicate with the backend only through JSON., JsonHttpError, Any (+3 more)

### Community 46 - "LabelStore"
Cohesion: 0.21
Nodes (7): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, utc_now_iso(), slugify_label()

### Community 52 - "composition.py"
Cohesion: 0.27
Nodes (4): build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.10
Nodes (16): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref(), normalize_chat_ref() (+8 more)

### Community 54 - "browser_refresh"
Cohesion: 0.15
Nodes (17): browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile(), browser_refresh(), browser_session(), _clear_cookie() (+9 more)

### Community 55 - "ProfileManager"
Cohesion: 0.26
Nodes (3): ProfileManager, Path, Metadata a worker can safely publish to the backend registry.

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - ".setUp"
Cohesion: 0.11
Nodes (7): _add_internal_state_routes(), sync_profiles(), _add_management_routes(), management_start_backup(), BackendContext, FastAPI, FastAPI adapters for public and internal JSON contracts.

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.11
Nodes (12): AuthServiceTests, actor(), Path, BotAuthService, _hash_secret(), _now(), Any, Connection (+4 more)

### Community 59 - "ControlPlane"
Cohesion: 0.19
Nodes (7): ControlPlane, Any, Application facade used by every frontend adapter., Resume queued commands after backend restart or terminal events., _redact_secrets(), serializable(), Actor

### Community 60 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 61 - "job-progress.ts"
Cohesion: 0.39
Nodes (6): clampPercent(), formatDuration(), JobLike, NormalizedProgress, normalizeJobProgress(), number()

### Community 62 - "presentation.ts"
Cohesion: 0.19
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 63 - "session.svelte.ts"
Cohesion: 0.11
Nodes (10): challenge, contextRevision, current, loading, loadWorkers(), selectedWorkers(), session, SessionWorker (+2 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.14
Nodes (5): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore

### Community 65 - "SqliteJobRepository"
Cohesion: 0.14
Nodes (9): _dump(), _load(), Any, Connection, Path, Row, Acquire all keys or return a deterministic queue position., Keep only the newest high-frequency telemetry snapshot. (+1 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 68 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

### Community 69 - "StateStore"
Cohesion: 0.27
Nodes (3): StateStoreTests, Path, StateStore

### Community 70 - "parse_tme3_url"
Cohesion: 0.30
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 71 - "._backup"
Cohesion: 0.15
Nodes (8): sha256_file(), _has_transfer_telemetry(), part_progress(), capture(), progress_event(), report_snapshot(), export_progress(), upload_progress()

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.04
Nodes (46): A. Langkah di komputer lokal, A. Login repository GitHub, Autentikasi GitHub dan GHCR, B. Langkah build lokal, B. Login GitHub Container Registry, Backend atau worker, Batas keamanan, Bootstrap VPS baru dengan `run.py` (+38 more)

### Community 73 - "JobEvent"
Cohesion: 0.18
Nodes (10): Enum, str, JobStoreTests, worker_event(), Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, JobEvent, JobStatus (+2 more)

### Community 76 - "5. Pesan status sementara untuk semua job"
Cohesion: 0.33
Nodes (6): 5.1 Komponen, 5.2 Jalur submit, 5.3 Subscription persisten, 5.4 Format message, 5.5 Polling, 5. Pesan status sementara untuk semua job

### Community 77 - "config.py"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`…, load_dotenv(), _parse_named_values()

### Community 79 - "2. Temuan dari kode saat ini"
Cohesion: 0.40
Nodes (5): 2.1 Akar masalah antrean, 2.2 Resource lock saat ini, 2.3 Notifikasi Telegram, 2.4 Source picker, 2. Temuan dari kode saat ini

### Community 80 - "executor.py"
Cohesion: 0.17
Nodes (8): StorageWorkerPathTests, Return nested directories, including empty ones, as portable paths., storage_logical_folder(), storage_relative_folders(), _utility_progress_message(), WorkerEventPublisher, utility_progress(), Framework-independent worker execution adapter.

### Community 81 - "6. Source picker Export Fokus"
Cohesion: 0.40
Nodes (5): 6.1 Inline picker searchable, 6.2 Search dan pagination, 6.3 Callback stabil, 6.4 Mini App fase berikutnya, 6. Source picker Export Fokus

### Community 82 - "write_json_atomic"
Cohesion: 0.24
Nodes (4): Any, Path, write_json_atomic(), ProfileSelectionStore

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - "control_plane.py"
Cohesion: 0.20
Nodes (6): FakeProfiles, Application services and use cases., build_execution_plan(), JobExecutionPlan, Any, Internal scheduling metadata shared by backend and worker.

### Community 85 - "sign_storage_item"
Cohesion: 0.24
Nodes (10): StorageLinkTests, _active_storage_item(), deliver_public_storage_deep_link(), deliver_storage_deep_link(), deliver_storage_item(), storage_deep_link(), _deliver_storage_telegram(), Compact, stable HMAC tokens for Telegram storage deep links. (+2 more)

### Community 89 - "ControlPlaneTests"
Cohesion: 0.11
Nodes (3): ControlPlaneTests, FailingDispatcher, FakeDispatcher

### Community 90 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 93 - "Path"
Cohesion: 0.44
Nodes (5): Path, run(), QuickThumbnailTests, fake_run(), fake_run()

### Community 94 - "storage_item_dict"
Cohesion: 0.28
Nodes (9): delete_storage_item(), get_storage_item(), move_storage_entries(), restore_storage_entries(), restore_storage_item(), search_storage(), update_storage_item(), _storage_item() (+1 more)

### Community 95 - "test_backend_api.py"
Cohesion: 0.12
Nodes (3): FakeDispatcher, FakeProfiles, FakeTelegramBot

### Community 97 - "tme3bot/app.py"
Cohesion: 0.60
Nodes (4): configure_logging(), main(), run_backend(), run_worker()

## Knowledge Gaps
- **176 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+171 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 575 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **17 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `create_backend_app()` connect `create_backend_app` to `tme3bot/app.py`, `DomainError`, `JobEvent`, `StorageCatalog`, `composition.py`, `sign_storage_item`, `browser_refresh`, `.setUp`, `ControlPlane`, `backend.py`, `storage_item_dict`, `test_backend_api.py`?**
  _High betweenness centrality (0.107) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `tme3bot/app.py`, `PanelManager`, `FakeStatusPanel`, `Any`, `request_json`, `format_job_status`, `telegram/app.py`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `BackendApiTests`, `BackupService`, `composition.py`, `.setUp`, `test_backend_api.py`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `create_backend_app()` (e.g. with `require_internal()` and `require_management()`) actually correct?**
  _`create_backend_app()` has 49 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `ExportStatusPollingTests`) actually correct?**
  _`TelegramFrontendApp` has 7 INFERRED edges - model-reasoned connections that need verification._