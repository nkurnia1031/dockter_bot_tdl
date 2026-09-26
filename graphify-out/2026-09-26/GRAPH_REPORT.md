# Graph Report - dockter_bot_tdl  (2026-09-26)

## Corpus Check
- 159 files · ~127,920 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 2554 nodes · 6201 edges · 124 communities (99 shown, 22 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 347 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2f071913`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- BackupService
- pindah4.py
- PanelManager
- BatchDownloadService
- organize_media_from_json.py
- Job
- WorkerRegistry
- QuickModePage.svelte
- tdl_output.py
- Path
- compress.sh
- create_worker_app
- Any
- boltStorage
- format_job_status
- job_dict
- StorageCatalog
- ProfileRegistry
- UtilityRunner
- compilerOptions
- telegram/app.py
- StateStore
- ._write_quick_log_line
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
- ProgressReporter
- main
- +layout.ts
- 8. Urutan implementasi
- tdl.py
- HttpStateStore
- api.ts
- RunScriptTests
- write_json_atomic
- vitest
- run.py
- create_backend_app
- test_pindah.py
- RcloneRunner
- ExportWorkspaceState
- DownloadProgressTracker
- ExportService
- 12. Bootstrap VPS baru dan satu-command deployment
- .setUp
- SqliteAuthRepository
- ControlPlane
- CommandMilestoneRecorder
- job-progress.ts
- JobTable.svelte
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- FakeStatusPanel
- test_backend_api.py
- composition.py
- ProfileTests
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
- Overview.svelte
- 3. Keputusan desain
- profiles.py
- parse_tme3_url
- build.py
- .test_quickmode_verify_requires_channel_and_drive_before_cleanup
- sign_storage_item
- JobEvent
- ProfileManager
- ContainerBuildTests
- WorkerJobExecutor
- QuickThumbnailTests
- WorkerHttpDispatcher
- TDLClient
- control_plane.py
- migrate_images
- ._storage_upload
- pkg_resources.py
- .upload
- WorkerEventPublisher
- .verify_files
- bootstrap_python_dependencies
- ProfileSelectionStore
- pindah.py
- FakeDispatcher
- utility.py
- executor.py
- DomainError
- ._recover_legacy_quick_stages
- Arsitektur Sistem tme3bot
- tme3bot
- UtilitySummaryTests
- tests/__init__.py
- WorkspaceExplorer.svelte
- UtilityFolderStore
- FakeProfiles
- D. Menambah worker remote baru
- Rekomendasi perbaikan
- Autentikasi GitHub dan GHCR
- Update berikutnya
- Context target per fitur dan Download global
- Rollback

## God Nodes (most connected - your core abstractions)
1. `create_backend_app()` - 185 edges
2. `WorkerJobExecutor` - 96 edges
3. `DomainError` - 89 edges
4. `StorageCatalog` - 86 edges
5. `TelegramFrontendApp` - 76 edges
6. `JobEvent` - 56 edges
7. `SqliteJobRepository` - 55 edges
8. `ControlPlane` - 53 edges
9. `Job` - 50 edges
10. `BackendApiTests` - 46 edges

## Surprising Connections (you probably didn't know these)
- `_download()` --indirect_call--> `output()`  [INFERRED]
  run.py → tests/test_tdl.py
- `AppMenuTests` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `DomainError`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `BackendApiTests` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py

## Import Cycles
- None detected.

## Communities (124 total, 22 thin omitted)

### Community 0 - "BackupService"
Cohesion: 0.09
Nodes (17): BackupServiceTests, make_config(), Path, BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention. (+9 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "BatchDownloadService"
Cohesion: 0.14
Nodes (17): Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, has_downloadable_media(), is_image_message(), Any, BatchDownloadResult, BatchDownloadService, build_telegram_message_url(), DownloadedJsonResult (+9 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.10
Nodes (7): Protocol, ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher, Job

### Community 6 - "WorkerRegistry"
Cohesion: 0.16
Nodes (7): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., Return workers that may receive new jobs. A disabled worker remains in…, WorkerRegistry

### Community 8 - "tdl_output.py"
Cohesion: 0.15
Nodes (17): _byte_multiplier(), clean_tdl_output_line(), _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_elapsed_seconds(), parse_eta_seconds() (+9 more)

### Community 9 - "Path"
Cohesion: 0.19
Nodes (16): build_base_archive(), build_base_image(), deploy_web(), _download(), find_host_tdl(), _github_repository(), hmac_compare(), _install_static_release() (+8 more)

### Community 11 - "create_worker_app"
Cohesion: 0.06
Nodes (12): FakeExecutor, WorkerApiTests, create_worker_app(), authorize(), domain_error(), job_log_snapshot(), unhandled_error(), _error() (+4 more)

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
Cohesion: 0.07
Nodes (37): archive_job(), cancel_job(), clear_failed(), create_telegram_notification(), delete_artifacts_batch(), get_job(), get_job_events(), get_job_log_snapshot() (+29 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (19): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+11 more)

### Community 17 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 18 - "UtilityRunner"
Cohesion: 0.22
Nodes (7): CommandCallback, Path, Popen, Remove the two intermediate JSON files produced by ``pindah``. ``pindah4.py``…, UtilityRunner, consume_line(), watchdog()

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.20
Nodes (20): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_picker_markup() (+12 more)

### Community 21 - "StateStore"
Cohesion: 0.17
Nodes (9): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), StateStoreTests, Path, StateStore (+1 more)

### Community 22 - "._write_quick_log_line"
Cohesion: 0.21
Nodes (7): _is_named_progress_key(), jakarta_timestamp(), progress_line_key(), Remove stale progress redraws while retaining diagnostic lines., Return human-facing worker log timestamps in the project timezone., Return a stable key for a repeated TDL progress-bar line. TDL prints the same…, interrupt()

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.18
Nodes (7): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, help_text(), Update

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.11
Nodes (18): Arsitektur, Catatan diagnosis produksi terakhir, Checklist memulai sesi baru, Deployment yang benar, Download Manager: aturan penting, graphify, Jebakan, Langkah operasional berikutnya (+10 more)

### Community 26 - "extract.py"
Cohesion: 0.29
Nodes (11): cleanup_empty_directory(), emit_progress(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main() (+3 more)

### Community 27 - "ResourceAwareQueue"
Cohesion: 0.06
Nodes (17): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, ResourceAwareQueueTests, SerialPerKeyQueueTests, handle() (+9 more)

### Community 28 - "backend.py"
Cohesion: 0.09
Nodes (56): BaseModel, ActorResponse, ApiResponse, ApproveChallengeRequest, BatchSourcesRequest, BrowserChallengeResponse, BrowserProfileRequest, BrowserSessionResponse (+48 more)

### Community 29 - "package.json"
Cohesion: 0.04
Nodes (42): bits-ui, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit (+34 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (34): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+26 more)

### Community 34 - "test_quick_export.py"
Cohesion: 0.07
Nodes (8): ExportMilestoneTests, export_from_url(), export_from_url(), QuickPipelineTests, download_export_to(), run(), ExportJobResult, UtilityResult

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.12
Nodes (11): ExportArtifactCatalogTests, discard_export_without_media(), ExportArtifactCatalog, Any, Connection, Path, Upsert an inventory batch in one SQLite transaction. Inventory can contain…, Mark catalog rows absent when a worker inventory completes. (+3 more)

### Community 37 - "ProgressReporter"
Cohesion: 0.11
Nodes (9): FakePublisher, ProgressReporterTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed., utc_timestamp() (+1 more)

### Community 38 - "main"
Cohesion: 0.20
Nodes (20): active_env_file(), backend_management_request(), deploy_all(), deploy_application(), ensure_profile_root(), load_env_file(), main(), manage_backup() (+12 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "tdl.py"
Cohesion: 0.07
Nodes (21): OutputCallback, ProgressCallback, Queue, CommandCallback, _message_contains_caption(), visit(), _normalize_upload_caption(), notify_command_completed() (+13 more)

### Community 43 - "HttpStateStore"
Cohesion: 0.15
Nodes (7): HttpStateStore, normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 44 - "api.ts"
Cohesion: 0.23
Nodes (9): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+1 more)

### Community 46 - "write_json_atomic"
Cohesion: 0.18
Nodes (10): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, Any, Path, utc_now_iso() (+2 more)

### Community 49 - "run.py"
Cohesion: 0.16
Nodes (26): add_profile(), capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), configured_service(), data_root_value() (+18 more)

### Community 50 - "create_backend_app"
Cohesion: 0.05
Nodes (31): create_backend_app(), browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile(), browser_refresh(), browser_session() (+23 more)

### Community 52 - "RcloneRunner"
Cohesion: 0.17
Nodes (4): FakeSubprocessRunner, RcloneRunnerTests, Small, cancellable rclone adapter for files already in the workspace., RcloneRunner

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.10
Nodes (16): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref(), normalize_chat_ref() (+8 more)

### Community 54 - "DownloadProgressTracker"
Cohesion: 0.31
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 55 - "ExportService"
Cohesion: 0.35
Nodes (3): ExportService, Any, ParsedTme3Url

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - ".setUp"
Cohesion: 0.09
Nodes (12): _add_internal_state_routes(), sync_profiles(), _add_management_routes(), management_start_backup(), BackendContext, archive_artifact(), delete_artifact_file(), purge_artifact() (+4 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.11
Nodes (12): AuthServiceTests, actor(), Path, BotAuthService, _hash_secret(), _now(), Any, Connection (+4 more)

### Community 59 - "ControlPlane"
Cohesion: 0.10
Nodes (15): Event, ControlPlane, Any, Application facade used by every frontend adapter., Resume queued commands after backend restart or terminal events., Cancel jobs whose worker has stopped reporting progress. Worker cancellation is…, Restart an export attempt while preserving its stable job ID., Find the original TDL message range without reading the JSON file. New jobs… (+7 more)

### Community 60 - "CommandMilestoneRecorder"
Cohesion: 0.10
Nodes (12): Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Redact obvious secret flags and values before persisting a command., sanitize_command(), sanitize_text(), CommandMilestoneRecorder, Bind the shared tracker callback only while owning its TDL lock., Persist bounded command results without allowing telemetry to fail work. (+4 more)

### Community 61 - "job-progress.ts"
Cohesion: 0.39
Nodes (6): clampPercent(), formatDuration(), JobLike, NormalizedProgress, normalizeJobProgress(), number()

### Community 62 - "JobTable.svelte"
Cohesion: 0.15
Nodes (8): if(), formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 63 - "session.svelte.ts"
Cohesion: 0.12
Nodes (10): challenge, contextRevision, current, loading, loadWorkers(), selectedWorkers(), session, SessionWorker (+2 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.10
Nodes (9): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore, _export_source_compact_markup(), Render the default form without flooding it with source buttons. Source…, Text helpers owned by the Telegram presentation adapter. (+1 more)

### Community 65 - "SqliteJobRepository"
Cohesion: 0.09
Nodes (15): JobStoreTests, _dump(), _load(), Any, Connection, Path, Row, _quick_mode_sql() (+7 more)

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
Cohesion: 0.19
Nodes (7): Enum, str, FakeTelegramBot, worker_event(), Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, JobStatus

### Community 70 - "composition.py"
Cohesion: 0.19
Nodes (10): configure_logging(), main(), build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, run_backend(), run_worker() (+2 more)

### Community 71 - "ProfileTests"
Cohesion: 0.33
Nodes (4): ProfileTests, Path, build_profile_config(), build_profile_runtime()

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.11
Nodes (19): A. Langkah di komputer lokal, B. Build melalui GitHub Actions, Batas keamanan, Bootstrap VPS baru dengan `run.py`, C. Langkah di VPS gateway, Concurrency dan pesan status job, E. Update di setiap VPS worker remote, F. Deploy web static di VPS gateway (+11 more)

### Community 73 - "request_json"
Cohesion: 0.24
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

### Community 82 - "Overview.svelte"
Cohesion: 0.29
Nodes (4): describe(), error, icons, label()

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - "profiles.py"
Cohesion: 0.16
Nodes (13): LeaveResult, LeaveService, CommandCallback, normalize_profile_name(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs(), get_profile_download_mode() (+5 more)

### Community 85 - "parse_tme3_url"
Cohesion: 0.30
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - ".test_quickmode_verify_requires_channel_and_drive_before_cleanup"
Cohesion: 0.24
Nodes (5): first_callback(), first_download(), second_callback(), second_download(), runtime()

### Community 88 - "sign_storage_item"
Cohesion: 0.52
Nodes (4): StorageLinkTests, Compact, stable HMAC tokens for Telegram storage deep links., sign_storage_item(), verify_storage_item()

### Community 89 - "JobEvent"
Cohesion: 0.10
Nodes (4): ControlPlaneTests, Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job., JobEvent

### Community 90 - "ProfileManager"
Cohesion: 0.26
Nodes (3): ProfileManager, Path, Metadata a worker can safely publish to the backend registry.

### Community 92 - "WorkerJobExecutor"
Cohesion: 0.07
Nodes (24): json_value(), Any, Exception, Path, Return a per-stage TDL client, with a test/runtime fallback. Production profile…, Reconstruct Quick Mode metadata when the backend manifest is gone., Keep a recovery copy of the raw TDL export in Quick Mode staging., Create a temporary workspace-only input for the download service. (+16 more)

### Community 93 - "QuickThumbnailTests"
Cohesion: 0.07
Nodes (20): Path, QuickThumbnailTests, fake_run(), fake_run(), fake_run(), fake_run(), fake_run(), JobLogSnapshot (+12 more)

### Community 94 - "WorkerHttpDispatcher"
Cohesion: 0.25
Nodes (4): JsonHttpError, Any, RuntimeError, WorkerHttpDispatcher

### Community 95 - "TDLClient"
Cohesion: 0.14
Nodes (10): skipIf, FakeRunner, CompletedProcess, TDLClientTests, output(), run(), decode_process_output(), Raised when a TDL subprocess stops making semantic progress. (+2 more)

### Community 96 - "control_plane.py"
Cohesion: 0.11
Nodes (8): FailingDispatcher, FakeDispatcher, FakeProfiles, Application services and use cases., build_execution_plan(), JobExecutionPlan, Any, Internal scheduling metadata shared by backend and worker.

### Community 97 - "migrate_images"
Cohesion: 0.20
Nodes (11): build_migration_archive(), configured_base_image(), ensure_base_image_available(), login_registry(), migrate_images(), Login to the image registry without exposing the PAT in process output., Build both split deployment images and package them for an offline load., Stop early when extracted base artifacts no longer match the source. (+3 more)

### Community 98 - "._storage_upload"
Cohesion: 0.13
Nodes (9): StorageWorkerPathTests, _has_transfer_telemetry(), Return nested directories, including empty ones, as portable paths., storage_logical_folder(), storage_relative_folders(), part_progress(), capture(), export_progress() (+1 more)

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - ".upload"
Cohesion: 0.27
Nodes (7): CompletedProcess, Path, RuntimeError, Upload one file and optionally force it to Telegram photo media., Resolve delayed TDL upload results by polling channel history. Some TDL…, Raised when TDL returns unusable or malformed export data., TDLDataError

### Community 101 - "WorkerEventPublisher"
Cohesion: 0.17
Nodes (3): Remove a completed stage without racing heartbeat audit writes., Seed event numbering for a reused job ID., WorkerEventPublisher

### Community 102 - ".verify_files"
Cohesion: 0.21
Nodes (10): bounded_output_tail(), Return only the newest output without splitting a line when possible., Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Check remote/config access separately from per-file differences., RcloneError (+2 more)

### Community 103 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

### Community 105 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 107 - "utility.py"
Cohesion: 0.24
Nodes (8): UtilitySettingsTests, ValueError, Validate a remote destination before it reaches a worker command., UtilityPathError, UtilitySettingsStore, _validate_password(), validate_rclone_destination(), _validate_size()

### Community 108 - "executor.py"
Cohesion: 0.09
Nodes (41): inspect_export_json(), Return safe media statistics without assuming a single TDL JSON shape., ProcessStalledError, Raised when a worker subprocess stops making meaningful progress., _quick_message_matches(), Match a storage message without persisting or returning its contents., Verify completed Quick Mode uploads before deleting retained staging., _utility_progress_message() (+33 more)

### Community 109 - "DomainError"
Cohesion: 0.07
Nodes (39): _active_storage_item(), add_label(), create_storage_folder(), delete_storage_item(), deliver_public_storage_deep_link(), deliver_storage_deep_link(), deliver_storage_item(), get_source() (+31 more)

### Community 113 - "Arsitektur Sistem tme3bot"
Cohesion: 0.25
Nodes (6): Arsitektur Sistem tme3bot, Data, sesi, dan batas keamanan, Deployment dan pengembangan, Gambaran sistem, Komponen dan tanggung jawab, Peta source untuk mulai menelusuri

### Community 114 - "tme3bot"
Cohesion: 0.22
Nodes (9): Arsitektur, Build Docker melalui GitHub Actions, Job dan progress, Login web melalui bot, Setup VPS utama, Storage dan backup, tme3bot, Verifikasi (+1 more)

### Community 117 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 121 - "D. Menambah worker remote baru"
Cohesion: 0.40
Nodes (5): D.1 Siapkan VPS worker remote, D.2 Daftarkan worker pada VPS gateway, D.3 Verifikasi worker dan route legacy, D.4 Mengaktifkan atau menonaktifkan worker dari Web UI, D. Menambah worker remote baru

### Community 122 - "Rekomendasi perbaikan"
Cohesion: 0.40
Nodes (5): Prioritas 1 — Kendali concurrency Quick Mode, Prioritas 2 — Pecah modul orkestrasi besar, Prioritas 3 — Kontrak backend-worker, Prioritas 4 — Observabilitas antrean dan progress, Rekomendasi perbaikan

### Community 123 - "Autentikasi GitHub dan GHCR"
Cohesion: 0.50
Nodes (4): A. Login repository GitHub, Autentikasi GitHub dan GHCR, B. Login GitHub Container Registry, C. Token GitHub Release untuk static web

### Community 124 - "Update berikutnya"
Cohesion: 0.67
Nodes (3): Backend atau worker, Hanya web, Update berikutnya

### Community 125 - "Context target per fitur dan Download global"
Cohesion: 0.67
Nodes (3): Context target per fitur dan Download global, Download batch dan bulk action, Urutan rollout perubahan context

### Community 126 - "Rollback"
Cohesion: 0.67
Nodes (3): Rollback, Rollback backend dan worker, Rollback web saja

## Knowledge Gaps
- **188 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+183 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 729 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `create_backend_app()` connect `create_backend_app` to `JobEvent`, `test_backend_api.py`, `Job`, `composition.py`, `DomainError`, `job_dict`, `StorageCatalog`, `sign_storage_item`, `.setUp`, `ControlPlane`, `backend.py`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `BackupService`, `test_quick_export.py`, `._storage_upload`, `ProgressReporter`, `composition.py`, `WorkerEventPublisher`, `ControlPlane`, `executor.py`, `._recover_legacy_quick_stages`, `UtilityRunner`, `RcloneRunner`, `._write_quick_log_line`, `.test_quickmode_verify_requires_channel_and_drive_before_cleanup`, `ResourceAwareQueue`, `CommandMilestoneRecorder`, `QuickThumbnailTests`, `TDLClient`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `PanelManager`, `FakeStatusPanel`, `composition.py`, `request_json`, `Any`, `format_job_status`, `telegram/app.py`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `create_backend_app()` (e.g. with `require_internal()` and `require_management()`) actually correct?**
  _`create_backend_app()` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `WorkerJobExecutor` (e.g. with `ExportMilestoneTests` and `QuickPipelineTests`) actually correct?**
  _`WorkerJobExecutor` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._