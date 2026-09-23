# Graph Report - dockter_bot_tdl  (2026-09-23)

## Corpus Check
- 158 files · ~120,051 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 2450 nodes · 5977 edges · 110 communities (86 shown, 21 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 326 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `0677f54f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- TDLClient
- pindah4.py
- PanelManager
- BatchDownloadService
- organize_media_from_json.py
- Job
- WorkerRegistry
- WorkspaceExplorer.svelte
- ProfileTests
- Path
- compress.sh
- create_worker_app
- Any
- boltStorage
- format_job_status
- backup_service.py
- StorageCatalog
- ProfileRegistry
- .test_quickmode_verify_requires_channel_and_drive_before_cleanup
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
- utility.py
- ExportArtifactCatalog
- BackendApiTests
- tdl_output.py
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
- parse_tme3_url
- BackupCoordinator
- 12. Bootstrap VPS baru dan satu-command deployment
- .setUp
- SqliteAuthRepository
- ControlPlane
- executor.py
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
- ProfileManager
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
- BackupService
- 3. Keputusan desain
- FakeExecutor
- job_dict
- build.py
- FakeProfiles
- sign_storage_item
- JobEvent
- profiles.py
- ContainerBuildTests
- DownloadProgressTracker
- Path
- WorkerHttpDispatcher
- RcloneError
- FakeDispatcher
- migrate_images
- ._append_job_log
- pkg_resources.py
- tme3bot/app.py
- pindah.py
- test_backup_service.py
- bootstrap_python_dependencies
- FakeProfiles
- ProgressReporter
- FakeDispatcher
- quick_export.py
- DomainError
- tests/__init__.py

## God Nodes (most connected - your core abstractions)
1. `create_backend_app()` - 181 edges
2. `DomainError` - 86 edges
3. `StorageCatalog` - 86 edges
4. `WorkerJobExecutor` - 85 edges
5. `TelegramFrontendApp` - 76 edges
6. `JobEvent` - 50 edges
7. `SqliteJobRepository` - 50 edges
8. `ControlPlane` - 49 edges
9. `StateStore` - 46 edges
10. `Job` - 45 edges

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

## Communities (110 total, 21 thin omitted)

### Community 0 - "TDLClient"
Cohesion: 0.15
Nodes (11): FakeRunner, CompletedProcess, TDLClientTests, CompletedProcess, Path, RuntimeError, Raised when TDL returns unusable or malformed export data., Upload one file and optionally force it to Telegram photo media. (+3 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "BatchDownloadService"
Cohesion: 0.11
Nodes (18): download_export_to(), has_downloadable_media(), is_image_message(), Any, BatchDownloadResult, BatchDownloadService, build_telegram_message_url(), DownloadedJsonResult (+10 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.09
Nodes (8): Protocol, Update the latest telemetry without growing persistent event history., ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher, Job

### Community 6 - "WorkerRegistry"
Cohesion: 0.16
Nodes (7): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., Return workers that may receive new jobs. A disabled worker remains in…, WorkerRegistry

### Community 7 - "WorkspaceExplorer.svelte"
Cohesion: 0.13
Nodes (9): crumbs, error, folders, goUp(), load(), loading, openCrumb(), clear() (+1 more)

### Community 8 - "ProfileTests"
Cohesion: 0.30
Nodes (5): ProfileTests, Path, build_profile_config(), build_profile_runtime(), ProfileRuntime

### Community 9 - "Path"
Cohesion: 0.19
Nodes (16): build_base_archive(), build_base_image(), deploy_web(), _download(), find_host_tdl(), _github_repository(), hmac_compare(), _install_static_release() (+8 more)

### Community 11 - "create_worker_app"
Cohesion: 0.10
Nodes (11): WorkerApiTests, create_worker_app(), authorize(), domain_error(), job_log_snapshot(), unhandled_error(), _error(), FastAPI (+3 more)

### Community 12 - "Any"
Cohesion: 0.13
Nodes (9): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), loop(), main_menu_markup() (+1 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.16
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "backup_service.py"
Cohesion: 0.18
Nodes (9): BackupNodeJob, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., BackupArchive, Create encrypted, runtime-only per-node backup archives., safe_node_name(), sha256_file() (+1 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (19): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+11 more)

### Community 17 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 18 - ".test_quickmode_verify_requires_channel_and_drive_before_cleanup"
Cohesion: 0.25
Nodes (3): Persist non-secret phase metadata atomically for retry/recovery., _sanitize_manifest(), write_quick_manifest()

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.20
Nodes (20): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_picker_markup() (+12 more)

### Community 21 - "StateStore"
Cohesion: 0.17
Nodes (10): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), StateStoreTests, ExportService, Path (+2 more)

### Community 22 - "WorkerJobExecutor"
Cohesion: 0.06
Nodes (36): _has_transfer_telemetry(), Any, Exception, Path, _quick_message_matches(), Return a per-stage TDL client, with a test/runtime fallback. Production profile…, Reconstruct Quick Mode metadata when the backend manifest is gone., Keep a recovery copy of the raw TDL export in Quick Mode staging. (+28 more)

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

### Community 34 - "utility.py"
Cohesion: 0.07
Nodes (7): ExportMilestoneTests, export_from_url(), export_from_url(), QuickPipelineTests, run(), ExportJobResult, UtilityResult

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.11
Nodes (14): ExportArtifactCatalogTests, discard_export_without_media(), ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical… (+6 more)

### Community 36 - "BackendApiTests"
Cohesion: 0.05
Nodes (18): BackendApiTests, UtilitySettingsTests, UtilitySummaryTests, CommandCallback, Path, Popen, ValueError, Validate a remote destination before it reaches a worker command. (+10 more)

### Community 37 - "tdl_output.py"
Cohesion: 0.14
Nodes (18): _byte_multiplier(), clean_tdl_output_line(), _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_elapsed_seconds(), parse_eta_seconds() (+10 more)

### Community 38 - "main"
Cohesion: 0.20
Nodes (20): active_env_file(), backend_management_request(), deploy_all(), deploy_application(), ensure_profile_root(), load_env_file(), main(), manage_backup() (+12 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "tdl.py"
Cohesion: 0.08
Nodes (20): OutputCallback, ProgressCallback, Queue, LeaveResult, LeaveService, CommandCallback, decode_process_output(), _message_contains_caption() (+12 more)

### Community 43 - "HttpStateStore"
Cohesion: 0.15
Nodes (8): utc_now_iso(), HttpStateStore, normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 44 - "api.ts"
Cohesion: 0.13
Nodes (13): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+5 more)

### Community 46 - "LabelStore"
Cohesion: 0.24
Nodes (6): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, slugify_label()

### Community 49 - "run.py"
Cohesion: 0.16
Nodes (26): add_profile(), capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), configured_service(), data_root_value() (+18 more)

### Community 50 - "create_backend_app"
Cohesion: 0.05
Nodes (31): create_backend_app(), browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile(), browser_refresh(), browser_session() (+23 more)

### Community 52 - "RcloneRunner"
Cohesion: 0.20
Nodes (5): FakeSubprocessRunner, RcloneRunnerTests, CommandCallback, Small, cancellable rclone adapter for files already in the workspace., RcloneRunner

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.10
Nodes (16): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref(), normalize_chat_ref() (+8 more)

### Community 54 - "parse_tme3_url"
Cohesion: 0.30
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

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
Cohesion: 0.12
Nodes (11): ControlPlane, Any, Application facade used by every frontend adapter., Resume queued commands after backend restart or terminal events., Cancel jobs whose worker has stopped reporting progress. Worker cancellation is…, Restart an export attempt while preserving its stable job ID., Find the original TDL message range without reading the JSON file. New jobs…, _redact_secrets() (+3 more)

### Community 60 - "executor.py"
Cohesion: 0.08
Nodes (18): StorageWorkerPathTests, Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Redact obvious secret flags and values before persisting a command., sanitize_command(), sanitize_text(), CommandMilestoneRecorder, json_value() (+10 more)

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
Cohesion: 0.12
Nodes (15): Enum, Event, str, FakeTelegramBot, Application services and use cases., build_execution_plan(), JobExecutionPlan, Any (+7 more)

### Community 70 - "composition.py"
Cohesion: 0.17
Nodes (5): BackupScheduler, build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator

### Community 71 - "ProfileManager"
Cohesion: 0.16
Nodes (5): normalize_profile_name(), ProfileManager, ProfileSelectionStore, Path, Metadata a worker can safely publish to the backend registry.

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

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 85 - "job_dict"
Cohesion: 0.08
Nodes (35): archive_job(), cancel_job(), clear_failed(), create_telegram_notification(), delete_artifacts_batch(), get_job(), get_job_events(), get_job_log_snapshot() (+27 more)

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 88 - "sign_storage_item"
Cohesion: 0.52
Nodes (4): StorageLinkTests, Compact, stable HMAC tokens for Telegram storage deep links., sign_storage_item(), verify_storage_item()

### Community 89 - "JobEvent"
Cohesion: 0.11
Nodes (4): ControlPlaneTests, JobStoreTests, worker_event(), JobEvent

### Community 90 - "profiles.py"
Cohesion: 0.21
Nodes (13): AppConfig, Fail fast when a production role is missing its trust boundary., Any, Path, write_json_atomic(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs() (+5 more)

### Community 92 - "DownloadProgressTracker"
Cohesion: 0.28
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 93 - "Path"
Cohesion: 0.15
Nodes (9): Path, QuickThumbnailTests, fake_run(), fake_run(), fake_run(), fake_run(), fake_run(), JobLogSnapshot (+1 more)

### Community 94 - "WorkerHttpDispatcher"
Cohesion: 0.29
Nodes (4): JsonHttpError, Any, RuntimeError, WorkerHttpDispatcher

### Community 95 - "RcloneError"
Cohesion: 0.23
Nodes (8): bounded_output_tail(), Return only the newest output without splitting a line when possible., Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Check remote/config access separately from per-file differences., RcloneError

### Community 97 - "migrate_images"
Cohesion: 0.20
Nodes (11): build_migration_archive(), configured_base_image(), ensure_base_image_available(), login_registry(), migrate_images(), Login to the image registry without exposing the PAT in process output., Build both split deployment images and package them for an offline load., Stop early when extracted base artifacts no longer match the source. (+3 more)

### Community 98 - "._append_job_log"
Cohesion: 0.25
Nodes (5): jakarta_timestamp(), Return human-facing worker log timestamps in the project timezone., capture(), progress_event(), report_snapshot()

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - "tme3bot/app.py"
Cohesion: 0.60
Nodes (4): configure_logging(), main(), run_backend(), run_worker()

### Community 101 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 102 - "test_backup_service.py"
Cohesion: 0.60
Nodes (3): BackupServiceTests, make_config(), Path

### Community 103 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

### Community 105 - "ProgressReporter"
Cohesion: 0.11
Nodes (9): FakePublisher, ProgressReporterTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed., utc_timestamp() (+1 more)

### Community 108 - "quick_export.py"
Cohesion: 0.07
Nodes (41): notify_command_completed(), notify_command_started(), ProcessStalledError, CommandCallback, Notify completion, supporting both new and legacy command observers., Raised when a worker subprocess stops making meaningful progress., Notify an observer without making telemetry a process dependency. New observers…, Create the pending milestone before a subprocess begins work. (+33 more)

### Community 109 - "DomainError"
Cohesion: 0.07
Nodes (38): _active_storage_item(), add_label(), create_storage_folder(), delete_storage_item(), deliver_public_storage_deep_link(), deliver_storage_deep_link(), deliver_storage_item(), get_source() (+30 more)

## Knowledge Gaps
- **177 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+172 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 687 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `utility.py`, `._append_job_log`, `tme3bot/app.py`, `BackendApiTests`, `composition.py`, `test_backend_api.py`, `ProgressReporter`, `tdl.py`, `quick_export.py`, `.test_quickmode_verify_requires_channel_and_drive_before_cleanup`, `BackupService`, `RcloneRunner`, `ResourceAwareQueue`, `executor.py`, `Path`?**
  _High betweenness centrality (0.085) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `PanelManager`, `tme3bot/app.py`, `FakeStatusPanel`, `request_json`, `Any`, `format_job_status`, `telegram/app.py`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Why does `create_backend_app()` connect `create_backend_app` to `JobEvent`, `tme3bot/app.py`, `test_backend_api.py`, `Job`, `composition.py`, `DomainError`, `StorageCatalog`, `job_dict`, `sign_storage_item`, `.setUp`, `ControlPlane`, `backend.py`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `create_backend_app()` (e.g. with `require_internal()` and `require_management()`) actually correct?**
  _`create_backend_app()` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `WorkerJobExecutor` (e.g. with `ExportMilestoneTests` and `QuickPipelineTests`) actually correct?**
  _`WorkerJobExecutor` has 13 INFERRED edges - model-reasoned connections that need verification._