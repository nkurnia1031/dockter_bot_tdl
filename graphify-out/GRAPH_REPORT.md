# Graph Report - dockter_bot_tdl  (2026-09-23)

## Corpus Check
- 158 files · ~121,693 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 2473 nodes · 6037 edges · 113 communities (91 shown, 19 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 331 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ece6424b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ProgressReporter
- pindah4.py
- PanelManager
- BatchDownloadService
- organize_media_from_json.py
- Job
- WorkerRegistry
- WorkspaceExplorer.svelte
- tdl_output.py
- Path
- compress.sh
- create_worker_app
- Any
- boltStorage
- format_job_status
- job_dict
- StorageCatalog
- write_json_atomic
- QuickThumbnailBuilder
- compilerOptions
- telegram/app.py
- StateStore
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
- test_quick_export.py
- ExportArtifactCatalog
- BackendApiTests
- BackupService
- main
- +layout.ts
- 8. Urutan implementasi
- tdl.py
- HttpStateStore
- api.ts
- RunScriptTests
- LabelStore
- vitest
- run.py
- create_backend_app
- test_pindah.py
- RcloneRunner
- ExportWorkspaceState
- SubprocessRunner
- BackupCoordinator
- 12. Bootstrap VPS baru dan satu-command deployment
- _add_management_routes
- SqliteAuthRepository
- ControlPlane
- CommandMilestoneRecorder
- job-progress.ts
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- FakeStatusPanel
- test_backend_api.py
- composition.py
- profiles.py
- TME3Bot Deployment Runbook
- request_json
- ../styles.css
- ArchitectureBoundaryTests
- 5. Pesan status sementara untuk semua job
- config.py
- infrastructure/__init__.py
- 2. Temuan dari kode saat ini
- FakeWorkers
- 6. Source picker Export Fokus
- DownloadProgressTracker
- 3. Keputusan desain
- WorkerApiTests
- _error
- build.py
- FakeProfiles
- .setUp
- JobEvent
- ProfileManager
- ContainerBuildTests
- ._recover_legacy_quick_stages
- QuickThumbnailTests
- WorkerHttpDispatcher
- TDLClient
- .setUp
- migrate_images
- ._backup
- pkg_resources.py
- .upload
- WorkerEventPublisher
- .verify_files
- bootstrap_python_dependencies
- pindah.py
- storage_item_dict
- FakeDispatcher
- storage_logical_folder
- executor.py
- DomainError
- test_backup_service.py
- _message_contains_caption
- tests/__init__.py

## God Nodes (most connected - your core abstractions)
1. `create_backend_app()` - 181 edges
2. `WorkerJobExecutor` - 88 edges
3. `DomainError` - 86 edges
4. `StorageCatalog` - 86 edges
5. `TelegramFrontendApp` - 76 edges
6. `JobEvent` - 51 edges
7. `ControlPlane` - 50 edges
8. `SqliteJobRepository` - 50 edges
9. `Job` - 46 edges
10. `StateStore` - 46 edges

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

## Communities (113 total, 19 thin omitted)

### Community 0 - "ProgressReporter"
Cohesion: 0.11
Nodes (9): FakePublisher, ProgressReporterTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed., utc_timestamp() (+1 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "BatchDownloadService"
Cohesion: 0.16
Nodes (11): BatchDownloadResult, BatchDownloadService, _is_relative_to(), media_ids_in_export(), Path, Download selected opaque filenames after strict directory validation., Download selected pending/failed JSON files from validated roots., Download one export into a caller-owned staging directory. Quick Mode owns the… (+3 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.09
Nodes (9): Protocol, Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job., ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher (+1 more)

### Community 6 - "WorkerRegistry"
Cohesion: 0.15
Nodes (7): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., Return workers that may receive new jobs. A disabled worker remains in…, WorkerRegistry

### Community 7 - "WorkspaceExplorer.svelte"
Cohesion: 0.13
Nodes (9): crumbs, error, folders, goUp(), load(), loading, openCrumb(), clear() (+1 more)

### Community 8 - "tdl_output.py"
Cohesion: 0.15
Nodes (17): _byte_multiplier(), clean_tdl_output_line(), _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_elapsed_seconds(), parse_eta_seconds() (+9 more)

### Community 9 - "Path"
Cohesion: 0.19
Nodes (16): build_base_archive(), build_base_image(), deploy_web(), _download(), find_host_tdl(), _github_repository(), hmac_compare(), _install_static_release() (+8 more)

### Community 11 - "create_worker_app"
Cohesion: 0.12
Nodes (14): quick_mode_staging(), recover_quick_mode(), create_worker_app(), authorize(), domain_error(), job_log_snapshot(), quickmode_scan(), quickmode_verify() (+6 more)

### Community 12 - "Any"
Cohesion: 0.13
Nodes (9): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), loop(), main_menu_markup() (+1 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.16
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "job_dict"
Cohesion: 0.10
Nodes (23): archive_job(), cancel_job(), clear_failed(), create_telegram_notification(), delete_artifacts_batch(), get_job(), get_job_events(), get_job_log_snapshot() (+15 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (19): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+11 more)

### Community 17 - "write_json_atomic"
Cohesion: 0.18
Nodes (8): Any, Path, utc_now_iso(), write_json_atomic(), ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 18 - "QuickThumbnailBuilder"
Cohesion: 0.16
Nodes (11): ensure_not_cancelled(), CommandCallback, Popen, RuntimeError, QuickModeError, QuickThumbnailBuilder, probe_next_video(), skip_media() (+3 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.20
Nodes (20): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_picker_markup() (+12 more)

### Community 21 - "StateStore"
Cohesion: 0.14
Nodes (11): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), StateStoreTests, build_telegram_message_url(), ExportService (+3 more)

### Community 22 - "WorkerJobExecutor"
Cohesion: 0.07
Nodes (24): json_value(), Any, Exception, Path, Return a per-stage TDL client, with a test/runtime fallback. Production profile…, Reconstruct Quick Mode metadata when the backend manifest is gone., Keep a recovery copy of the raw TDL export in Quick Mode staging., Create a temporary workspace-only input for the download service. (+16 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.18
Nodes (7): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, help_text(), Update

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.12
Nodes (16): Arsitektur, Checklist memulai sesi baru, Deployment yang benar, Download Manager: aturan penting, graphify, Jebakan, Model target fitur saat ini, Operasional (+8 more)

### Community 26 - "extract.py"
Cohesion: 0.29
Nodes (11): cleanup_empty_directory(), emit_progress(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main() (+3 more)

### Community 27 - "ResourceAwareQueue"
Cohesion: 0.07
Nodes (16): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, ResourceAwareQueueTests, SerialPerKeyQueueTests, handle() (+8 more)

### Community 28 - "backend.py"
Cohesion: 0.09
Nodes (56): BaseModel, ActorResponse, ApiResponse, ApproveChallengeRequest, BatchSourcesRequest, BrowserChallengeResponse, BrowserProfileRequest, BrowserSessionResponse (+48 more)

### Community 29 - "package.json"
Cohesion: 0.04
Nodes (42): bits-ui, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit (+34 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (35): patch(), post(), if(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName (+27 more)

### Community 34 - "test_quick_export.py"
Cohesion: 0.07
Nodes (9): ExportMilestoneTests, export_from_url(), export_from_url(), QuickPipelineTests, download_export_to(), run(), DownloadedJsonResult, ExportJobResult (+1 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.09
Nodes (16): ExportArtifactCatalogTests, discard_export_without_media(), ExportArtifactCatalog, Any, Connection, Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Upsert an inventory batch in one SQLite transaction. Inventory can contain… (+8 more)

### Community 36 - "BackendApiTests"
Cohesion: 0.05
Nodes (18): BackendApiTests, UtilitySettingsTests, UtilitySummaryTests, CommandCallback, Path, Popen, ValueError, Validate a remote destination before it reaches a worker command. (+10 more)

### Community 37 - "BackupService"
Cohesion: 0.24
Nodes (7): BackupArchive, BackupService, Path, Create encrypted, runtime-only per-node backup archives., safe_node_name(), utc_now(), parse_percent()

### Community 38 - "main"
Cohesion: 0.20
Nodes (20): active_env_file(), backend_management_request(), deploy_all(), deploy_application(), ensure_profile_root(), load_env_file(), main(), manage_backup() (+12 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "tdl.py"
Cohesion: 0.12
Nodes (19): OutputCallback, ProgressCallback, Queue, decode_process_output(), notify_command_completed(), notify_command_started(), parse_terminal_size(), prepare_subprocess_command() (+11 more)

### Community 43 - "HttpStateStore"
Cohesion: 0.16
Nodes (7): HttpStateStore, normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 44 - "api.ts"
Cohesion: 0.13
Nodes (13): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+5 more)

### Community 46 - "LabelStore"
Cohesion: 0.14
Nodes (11): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, parse_tme3_url(), ValueError (+3 more)

### Community 49 - "run.py"
Cohesion: 0.16
Nodes (26): add_profile(), capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), configured_service(), data_root_value() (+18 more)

### Community 50 - "create_backend_app"
Cohesion: 0.05
Nodes (26): create_backend_app(), archive_artifact(), browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile(), browser_refresh() (+18 more)

### Community 52 - "RcloneRunner"
Cohesion: 0.18
Nodes (5): FakeSubprocessRunner, RcloneRunnerTests, CommandCallback, Small, cancellable rclone adapter for files already in the workspace., RcloneRunner

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.10
Nodes (16): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref(), normalize_chat_ref() (+8 more)

### Community 54 - "SubprocessRunner"
Cohesion: 0.16
Nodes (5): LeaveResult, LeaveService, CommandCallback, Popen, SubprocessRunner

### Community 55 - "BackupCoordinator"
Cohesion: 0.14
Nodes (7): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., sha256_file()

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - "_add_management_routes"
Cohesion: 0.13
Nodes (5): _add_internal_state_routes(), sync_profiles(), _add_management_routes(), management_start_backup(), FastAPI

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.10
Nodes (14): str, AuthServiceTests, actor(), Path, AuthChallengeStatus, BotAuthService, _hash_secret(), _now() (+6 more)

### Community 59 - "ControlPlane"
Cohesion: 0.10
Nodes (15): Event, ControlPlane, Any, Application facade used by every frontend adapter., Resume queued commands after backend restart or terminal events., Cancel jobs whose worker has stopped reporting progress. Worker cancellation is…, Restart an export attempt while preserving its stable job ID., Find the original TDL message range without reading the JSON file. New jobs… (+7 more)

### Community 60 - "CommandMilestoneRecorder"
Cohesion: 0.07
Nodes (20): bounded_output_tail(), Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Return only the newest output without splitting a line when possible., Redact obvious secret flags and values before persisting a command., sanitize_command(), sanitize_text(), CommandMilestoneRecorder (+12 more)

### Community 61 - "job-progress.ts"
Cohesion: 0.33
Nodes (6): clampPercent(), formatDuration(), JobLike, NormalizedProgress, normalizeJobProgress(), number()

### Community 62 - "presentation.ts"
Cohesion: 0.31
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 63 - "session.svelte.ts"
Cohesion: 0.09
Nodes (10): challenge, contextRevision, current, loading, loadWorkers(), selectedWorkers(), session, SessionWorker (+2 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.10
Nodes (9): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore, _export_source_compact_markup(), Render the default form without flooding it with source buttons. Source…, Text helpers owned by the Telegram presentation adapter. (+1 more)

### Community 65 - "SqliteJobRepository"
Cohesion: 0.12
Nodes (13): _dump(), _load(), Any, Connection, Path, Row, _quick_mode_sql(), Reset a terminal row for a new attempt without changing its ID. The old… (+5 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 68 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

### Community 69 - "test_backend_api.py"
Cohesion: 0.14
Nodes (9): Enum, FakeTelegramBot, Application services and use cases., build_execution_plan(), JobExecutionPlan, Any, Internal scheduling metadata shared by backend and worker., Framework-independent domain model for the tme3bot control plane. (+1 more)

### Community 70 - "composition.py"
Cohesion: 0.20
Nodes (8): configure_logging(), main(), build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, run_backend(), run_worker()

### Community 71 - "profiles.py"
Cohesion: 0.17
Nodes (15): ProfileTests, Path, AppConfig, Fail fast when a production role is missing its trust boundary., build_profile_config(), build_profile_runtime(), chown_paths(), chown_tree() (+7 more)

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.04
Nodes (46): A. Langkah di komputer lokal, A. Login repository GitHub, Autentikasi GitHub dan GHCR, B. Build melalui GitHub Actions, B. Login GitHub Container Registry, Backend atau worker, Batas keamanan, Bootstrap VPS baru dengan `run.py` (+38 more)

### Community 73 - "request_json"
Cohesion: 0.25
Nodes (5): BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Frontend adapters. They communicate with the backend only through JSON., request_json()

### Community 76 - "5. Pesan status sementara untuk semua job"
Cohesion: 0.33
Nodes (6): 5.1 Komponen, 5.2 Jalur submit, 5.3 Subscription persisten, 5.4 Format message, 5.5 Polling, 5. Pesan status sementara untuk semua job

### Community 77 - "config.py"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`…, load_dotenv(), _parse_named_values()

### Community 79 - "2. Temuan dari kode saat ini"
Cohesion: 0.40
Nodes (5): 2.1 Akar masalah antrean, 2.2 Resource lock saat ini, 2.3 Notifikasi Telegram, 2.4 Source picker, 2. Temuan dari kode saat ini

### Community 81 - "6. Source picker Export Fokus"
Cohesion: 0.40
Nodes (5): 6.1 Inline picker searchable, 6.2 Search dan pagination, 6.3 Callback stabil, 6.4 Mini App fase berikutnya, 6. Source picker Export Fokus

### Community 82 - "DownloadProgressTracker"
Cohesion: 0.31
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 85 - "_error"
Cohesion: 0.20
Nodes (10): domain_error_handler(), exchange_challenge(), key_error_handler(), permission_error_handler(), unhandled_error_handler(), validation_error_handler(), value_error_handler(), _error() (+2 more)

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 88 - ".setUp"
Cohesion: 0.19
Nodes (12): StorageLinkTests, _active_storage_item(), BackendContext, deliver_public_storage_deep_link(), deliver_storage_deep_link(), deliver_storage_item(), storage_deep_link(), _deliver_storage_telegram() (+4 more)

### Community 89 - "JobEvent"
Cohesion: 0.11
Nodes (4): ControlPlaneTests, JobStoreTests, worker_event(), JobEvent

### Community 90 - "ProfileManager"
Cohesion: 0.15
Nodes (5): normalize_profile_name(), ProfileManager, ProfileSelectionStore, Path, Metadata a worker can safely publish to the backend registry.

### Community 93 - "QuickThumbnailTests"
Cohesion: 0.11
Nodes (9): Path, QuickThumbnailTests, fake_run(), fake_run(), fake_run(), fake_run(), fake_run(), JobLogSnapshot (+1 more)

### Community 94 - "WorkerHttpDispatcher"
Cohesion: 0.29
Nodes (4): JsonHttpError, Any, RuntimeError, WorkerHttpDispatcher

### Community 95 - "TDLClient"
Cohesion: 0.27
Nodes (4): FakeRunner, CompletedProcess, TDLClientTests, TDLClient

### Community 96 - ".setUp"
Cohesion: 0.17
Nodes (3): FailingDispatcher, FakeDispatcher, FakeProfiles

### Community 97 - "migrate_images"
Cohesion: 0.20
Nodes (11): build_migration_archive(), configured_base_image(), ensure_base_image_available(), login_registry(), migrate_images(), Login to the image registry without exposing the PAT in process output., Build both split deployment images and package them for an offline load., Stop early when extracted base artifacts no longer match the source. (+3 more)

### Community 98 - "._backup"
Cohesion: 0.29
Nodes (4): _has_transfer_telemetry(), part_progress(), export_progress(), upload_progress()

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - ".upload"
Cohesion: 0.32
Nodes (5): CompletedProcess, Path, Upload one file and optionally force it to Telegram photo media., Resolve delayed TDL upload results by polling channel history. Some TDL…, UploadResult

### Community 102 - ".verify_files"
Cohesion: 0.26
Nodes (8): Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Check remote/config access separately from per-file differences., RcloneError, inventory_matches(), remote_inventory()

### Community 103 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

### Community 104 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 105 - "storage_item_dict"
Cohesion: 0.28
Nodes (9): delete_storage_item(), get_storage_item(), move_storage_entries(), restore_storage_entries(), restore_storage_item(), search_storage(), update_storage_item(), _storage_item() (+1 more)

### Community 107 - "storage_logical_folder"
Cohesion: 0.43
Nodes (4): StorageWorkerPathTests, Return nested directories, including empty ones, as portable paths., storage_logical_folder(), storage_relative_folders()

### Community 108 - "executor.py"
Cohesion: 0.10
Nodes (39): inspect_export_json(), Return safe media statistics without assuming a single TDL JSON shape., _quick_message_matches(), Match a storage message without persisting or returning its contents., Verify completed Quick Mode uploads before deleting retained staging., _utility_progress_message(), verify_log(), utility_progress() (+31 more)

### Community 109 - "DomainError"
Cohesion: 0.08
Nodes (31): add_label(), create_storage_folder(), get_source(), purge_storage_entries(), purge_storage_folder(), purge_storage_item(), remove_worker(), require_internal() (+23 more)

### Community 110 - "test_backup_service.py"
Cohesion: 0.60
Nodes (3): BackupServiceTests, make_config(), Path

### Community 111 - "_message_contains_caption"
Cohesion: 0.40
Nodes (5): _message_contains_caption(), visit(), _normalize_upload_caption(), Any, Match captions across the different JSON shapes emitted by TDL.

## Knowledge Gaps
- **177 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+172 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 692 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **19 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `ProgressReporter`, `test_quick_export.py`, `._backup`, `BackendApiTests`, `BackupService`, `composition.py`, `WorkerEventPublisher`, `ControlPlane`, `tdl.py`, `executor.py`, `._recover_legacy_quick_stages`, `QuickThumbnailBuilder`, `RcloneRunner`, `ResourceAwareQueue`, `CommandMilestoneRecorder`, `QuickThumbnailTests`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `PanelManager`, `FakeStatusPanel`, `composition.py`, `request_json`, `Any`, `format_job_status`, `telegram/app.py`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `create_backend_app()` connect `create_backend_app` to `JobEvent`, `test_backend_api.py`, `Job`, `composition.py`, `storage_item_dict`, `create_worker_app`, `DomainError`, `job_dict`, `StorageCatalog`, `_error`, `.setUp`, `_add_management_routes`, `ControlPlane`, `backend.py`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `create_backend_app()` (e.g. with `require_internal()` and `require_management()`) actually correct?**
  _`create_backend_app()` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `WorkerJobExecutor` (e.g. with `ExportMilestoneTests` and `QuickPipelineTests`) actually correct?**
  _`WorkerJobExecutor` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._