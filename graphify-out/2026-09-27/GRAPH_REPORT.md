# Graph Report - dockter_bot_tdl  (2026-09-27)

## Corpus Check
- 176 files · ~132,177 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 2639 nodes · 6577 edges · 134 communities (104 shown, 27 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 462 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2f128845`
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
- SubprocessRunner
- Path
- compress.sh
- create_worker_app
- Any
- boltStorage
- format_job_status
- executor.py
- StorageCatalog
- write_json_atomic
- tme3bot/utility.py
- compilerOptions
- telegram/app.py
- ServiceTests
- QuickModeExecutorMixin
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
- .test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage
- ExportArtifactCatalog
- BackendApiTests
- ProgressReporter
- main
- +layout.ts
- 8. Urutan implementasi
- StateStore
- HttpStateStore
- api.ts
- RunScriptTests
- LabelStore
- vitest
- run.py
- create_backend_app
- test_pindah.py
- .patch
- ExportWorkspaceState
- DownloadProgressTracker
- register_jobs
- 12. Bootstrap VPS baru dan satu-command deployment
- _add_management_routes
- SqliteAuthRepository
- ControlPlane
- .verify_files
- job-progress.ts
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- parse_tme3_url
- DomainError
- composition.py
- ProfileTests
- TME3Bot Deployment Runbook
- BackendApiClient
- ../styles.css
- ArchitectureBoundaryTests
- 5. Pesan status sementara untuk semua job
- config.py
- infrastructure/__init__.py
- 2. Temuan dari kode saat ini
- FakeExecutor
- 6. Source picker Export Fokus
- .upload
- 3. Keputusan desain
- profiles.py
- tdl.py
- build.py
- .test_download_progress_callbacks_follow_the_download_lock_owner
- register_storage
- JobEvent
- .setUp
- ContainerBuildTests
- WorkerJobExecutor
- Path
- request_json
- TDLClient
- control_plane.py
- migrate_images
- inspect_export_json
- pkg_resources.py
- ExportService
- WorkerEventPublisher
- register_utility
- bootstrap_python_dependencies
- UtilitySettingsStore
- pindah.py
- .workspace_tree
- register_downloads
- quick_export.py
- ProfileManager
- JobStoreTests
- routes/__init__.py
- FakeDispatcher
- Arsitektur Sistem tme3bot
- tme3bot
- FakeWorkers
- tests/__init__.py
- WorkspaceExplorer.svelte
- Path
- CommandMilestoneRecorder
- FakeStatusPanel
- D. Menambah worker remote baru
- Rekomendasi perbaikan
- Autentikasi GitHub dan GHCR
- Update berikutnya
- Context target per fitur dan Download global
- Rollback
- WorkerApiTests
- ProfileSelectionStore
- validate_rclone_destination
- UtilityFolderStore
- .test_subprocess_runner_freezes_and_resumes_current_process
- Queue
- models.py

## God Nodes (most connected - your core abstractions)
1. `DomainError` - 109 edges
2. `StorageCatalog` - 86 edges
3. `create_backend_app()` - 83 edges
4. `TelegramFrontendApp` - 76 edges
5. `WorkerJobExecutor` - 67 edges
6. `JobEvent` - 58 edges
7. `ControlPlane` - 56 edges
8. `SqliteJobRepository` - 56 edges
9. `Job` - 52 edges
10. `BackendApiTests` - 48 edges

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

## Communities (134 total, 27 thin omitted)

### Community 0 - "BackupService"
Cohesion: 0.11
Nodes (12): BackupServiceTests, make_config(), Path, BackupCoordinator, BackupNodeJob, datetime, Worker-neutral command payload for one node backup., BackupArchive (+4 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "BatchDownloadService"
Cohesion: 0.21
Nodes (10): BatchDownloadResult, BatchDownloadService, _is_relative_to(), media_ids_in_export(), Path, Download selected opaque filenames after strict directory validation., Download selected pending/failed JSON files from validated roots., Download one export into a caller-owned staging directory. Quick Mode owns the… (+2 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.11
Nodes (7): Protocol, ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher, Job

### Community 6 - "WorkerRegistry"
Cohesion: 0.17
Nodes (7): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., Return workers that may receive new jobs. A disabled worker remains in…, WorkerRegistry

### Community 8 - "SubprocessRunner"
Cohesion: 0.13
Nodes (5): OutputCallback, ProgressCallback, CommandCallback, Popen, SubprocessRunner

### Community 9 - "Path"
Cohesion: 0.19
Nodes (16): build_base_archive(), build_base_image(), deploy_web(), _download(), find_host_tdl(), _github_repository(), hmac_compare(), _install_static_release() (+8 more)

### Community 11 - "create_worker_app"
Cohesion: 0.09
Nodes (19): ContractWorkerExecutor, WorkerJobRequest, create_worker_app(), authorize(), capabilities(), domain_error(), job_log_snapshot(), unhandled_error() (+11 more)

### Community 12 - "Any"
Cohesion: 0.16
Nodes (7): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), loop()

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.18
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "executor.py"
Cohesion: 0.07
Nodes (39): StorageWorkerPathTests, Gateway orchestration, channel upload, scheduling, and retention., Create encrypted, runtime-only per-node backup archives., sha256_file(), bounded_output_tail(), Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Return only the newest output without splitting a line when possible. (+31 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (19): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+11 more)

### Community 17 - "write_json_atomic"
Cohesion: 0.19
Nodes (8): Any, Path, utc_now_iso(), write_json_atomic(), ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 18 - "tme3bot/utility.py"
Cohesion: 0.09
Nodes (19): _message_contains_caption(), notify_command_completed(), notify_command_started(), pause_process_group(), ProcessStalledError, Any, CommandCallback, Notify an observer without making telemetry a process dependency. New observers… (+11 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.14
Nodes (26): PendingInput, backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_compact_markup(), _export_source_picker_markup() (+18 more)

### Community 21 - "ServiceTests"
Cohesion: 0.24
Nodes (6): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), ExportResult

### Community 22 - "QuickModeExecutorMixin"
Cohesion: 0.09
Nodes (27): ExportJobResult, Any, Path, QuickModeExecutorMixin, ensure_not_cancelled(), persist_uploaded_items(), phase_result(), save_manifest() (+19 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.16
Nodes (7): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Telegram presentation adapter and UI-only helpers., Update

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
Cohesion: 0.11
Nodes (49): BaseModel, ActorResponse, ApiResponse, ApproveChallengeRequest, BatchSourcesRequest, BrowserChallengeResponse, BrowserProfileRequest, BrowserSessionResponse (+41 more)

### Community 29 - "package.json"
Cohesion: 0.04
Nodes (42): bits-ui, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit (+34 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (34): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+26 more)

### Community 34 - ".test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage"
Cohesion: 0.07
Nodes (5): QuickPipelineTests, download_export_to(), run(), DownloadedJsonResult, UtilityResult

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.14
Nodes (8): ExportArtifactCatalogTests, ExportArtifactCatalog, Any, Connection, Upsert an inventory batch in one SQLite transaction. Inventory can contain…, Mark catalog rows absent when a worker inventory completes., Remove a missing file from the runnable queue. The physical file is already…, utc_now()

### Community 37 - "ProgressReporter"
Cohesion: 0.15
Nodes (9): FakePublisher, ProgressReporterTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed., utc_timestamp() (+1 more)

### Community 38 - "main"
Cohesion: 0.20
Nodes (20): active_env_file(), backend_management_request(), deploy_all(), deploy_application(), ensure_profile_root(), load_env_file(), main(), manage_backup() (+12 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "StateStore"
Cohesion: 0.24
Nodes (3): StateStoreTests, Path, StateStore

### Community 43 - "HttpStateStore"
Cohesion: 0.16
Nodes (7): HttpStateStore, normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 44 - "api.ts"
Cohesion: 0.12
Nodes (14): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+6 more)

### Community 46 - "LabelStore"
Cohesion: 0.24
Nodes (6): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, slugify_label()

### Community 49 - "run.py"
Cohesion: 0.16
Nodes (26): add_profile(), capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), configured_service(), data_root_value() (+18 more)

### Community 50 - "create_backend_app"
Cohesion: 0.09
Nodes (29): create_backend_app(), browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile(), browser_refresh(), browser_session() (+21 more)

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.10
Nodes (16): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref(), normalize_chat_ref() (+8 more)

### Community 55 - "register_jobs"
Cohesion: 0.09
Nodes (31): event_dict(), job_dict(), _newest_first_log_response(), _owned_job(), Any, Normalize current and legacy worker snapshots for the public API., start_backup(), clear_failed() (+23 more)

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - "_add_management_routes"
Cohesion: 0.13
Nodes (5): _add_internal_state_routes(), sync_profiles(), _add_management_routes(), management_start_backup(), FastAPI

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.11
Nodes (12): AuthServiceTests, actor(), Path, BotAuthService, _hash_secret(), _now(), Any, Connection (+4 more)

### Community 59 - "ControlPlane"
Cohesion: 0.11
Nodes (13): ControlPlane, Any, Exception, Persist a worker's Quick Mode capacity and dispatch any new slots., Application facade used by every frontend adapter., Resume queued commands after backend restart or terminal events., Cancel jobs whose worker has stopped reporting progress. Worker cancellation is…, Restart an export attempt while preserving its stable job ID. (+5 more)

### Community 60 - ".verify_files"
Cohesion: 0.26
Nodes (8): Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Check remote/config access separately from per-file differences., RcloneError, inventory_matches(), remote_inventory()

### Community 61 - "job-progress.ts"
Cohesion: 0.22
Nodes (10): eventLatency, phaseElapsedSeconds, phaseLabel(), stageId, clampPercent(), formatDuration(), JobLike, NormalizedProgress (+2 more)

### Community 62 - "presentation.ts"
Cohesion: 0.42
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 63 - "session.svelte.ts"
Cohesion: 0.09
Nodes (10): challenge, contextRevision, current, loading, loadWorkers(), selectedWorkers(), session, SessionWorker (+2 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.13
Nodes (5): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore

### Community 65 - "SqliteJobRepository"
Cohesion: 0.10
Nodes (16): _dump(), _elapsed_between(), _load(), Any, Connection, Path, Row, _quick_mode_sql() (+8 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 68 - "parse_tme3_url"
Cohesion: 0.30
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 69 - "DomainError"
Cohesion: 0.08
Nodes (26): require_internal(), require_management(), require_service(), verify_context(), verify_target(), _model_dict(), submit_download(), register_sources() (+18 more)

### Community 70 - "composition.py"
Cohesion: 0.13
Nodes (12): BackendContext, configure_logging(), main(), BackupScheduler, build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator (+4 more)

### Community 71 - "ProfileTests"
Cohesion: 0.37
Nodes (3): ProfileTests, Path, build_profile_config()

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.11
Nodes (19): A. Langkah di komputer lokal, B. Build melalui GitHub Actions, Batas keamanan, Bootstrap VPS baru dengan `run.py`, C. Langkah di VPS gateway, Concurrency dan pesan status job, E. Update di setiap VPS worker remote, F. Deploy web static di VPS gateway (+11 more)

### Community 73 - "BackendApiClient"
Cohesion: 0.21
Nodes (4): BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Frontend adapters. They communicate with the backend only through JSON.

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

### Community 82 - ".upload"
Cohesion: 0.23
Nodes (9): visit(), _normalize_upload_caption(), CompletedProcess, Path, Upload one file and optionally force it to Telegram photo media., Resolve delayed TDL upload results by polling channel history. Some TDL…, Raised when TDL returns unusable or malformed export data., TDLDataError (+1 more)

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - "profiles.py"
Cohesion: 0.16
Nodes (14): LeaveResult, LeaveService, CommandCallback, normalize_profile_name(), build_profile_runtime(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs() (+6 more)

### Community 85 - "tdl.py"
Cohesion: 0.11
Nodes (25): has_downloadable_media(), _byte_multiplier(), clean_tdl_output_line(), CommandProgress, _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), parse_elapsed_seconds() (+17 more)

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - ".test_download_progress_callbacks_follow_the_download_lock_owner"
Cohesion: 0.53
Nodes (5): first_callback(), first_download(), second_callback(), second_download(), runtime()

### Community 88 - "register_storage"
Cohesion: 0.12
Nodes (25): StorageLinkTests, _active_storage_item(), _deliver_storage_telegram(), _require_storage_folders_idle(), _storage_item(), register_storage(), delete_storage_item(), deliver_public_storage_deep_link() (+17 more)

### Community 89 - "JobEvent"
Cohesion: 0.09
Nodes (5): ControlPlaneTests, Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job., Attach phase timing and event latency to this job's own event., JobEvent

### Community 92 - "WorkerJobExecutor"
Cohesion: 0.06
Nodes (15): ExportMilestoneTests, export_from_url(), export_from_url(), Any, Exception, Executes domain jobs and publishes JSON events; no UI dependency., Make pre-manager Quick Mode staging visible after worker restart., Publish only profile metadata; .tdl files remain on this worker. (+7 more)

### Community 93 - "Path"
Cohesion: 0.08
Nodes (14): Path, QuickThumbnailTests, fake_run(), fake_run(), fake_run(), fake_run(), fake_run(), CommandCallback (+6 more)

### Community 94 - "request_json"
Cohesion: 0.35
Nodes (5): JsonHttpError, Any, RuntimeError, request_json(), WorkerHttpDispatcher

### Community 95 - "TDLClient"
Cohesion: 0.24
Nodes (3): FakeRunner, TDLClientTests, TDLClient

### Community 96 - "control_plane.py"
Cohesion: 0.09
Nodes (11): FailingDispatcher, FakeDispatcher, FakeProfiles, IncompatibleDispatcher, _elapsed_since(), datetime, Application services and use cases., build_execution_plan() (+3 more)

### Community 97 - "migrate_images"
Cohesion: 0.20
Nodes (11): build_migration_archive(), configured_base_image(), ensure_base_image_available(), login_registry(), migrate_images(), Login to the image registry without exposing the PAT in process output., Build both split deployment images and package them for an offline load., Stop early when extracted base artifacts no longer match the source. (+3 more)

### Community 98 - "inspect_export_json"
Cohesion: 0.16
Nodes (11): discard_export_without_media(), inspect_export_json(), Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape., Remove an export JSON when its inspected media count is exactly zero. The…, DownloadExecutorMixin, progress_event() (+3 more)

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - "ExportService"
Cohesion: 0.23
Nodes (6): is_image_message(), Any, build_telegram_message_url(), ExportService, Any, ParsedTme3Url

### Community 101 - "WorkerEventPublisher"
Cohesion: 0.13
Nodes (5): patch, ContractWorkerRegistry, WorkerContractTests, Seed event numbering for a reused job ID., WorkerEventPublisher

### Community 102 - "register_utility"
Cohesion: 0.16
Nodes (9): register_backups(), register_utility(), utility_settings_meta(), utility_tree(), ItemListResponse, ObjectResponse, Typed object envelope for small mutation/settings responses., Public metadata for clients; never contains a setting value or secret. (+1 more)

### Community 103 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

### Community 104 - "UtilitySettingsStore"
Cohesion: 0.21
Nodes (3): UtilitySettingsTests, UtilitySummaryTests, UtilitySettingsStore

### Community 105 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 106 - ".workspace_tree"
Cohesion: 0.50
Nodes (3): Any, Path, Return a safe, shallow directory listing for the active workspace.

### Community 107 - "register_downloads"
Cohesion: 0.24
Nodes (10): _profile_artifact(), register_downloads(), archive_artifact(), delete_artifact_file(), purge_artifact(), restore_artifact(), set_download_mode(), DownloadBatchRequest (+2 more)

### Community 108 - "quick_export.py"
Cohesion: 0.14
Nodes (28): _archive_files(), _chown_tree(), cleanup_quick_stage(), _clone_tree(), ensure_quick_stage_writable(), ensure_quick_tdl_client(), _json_media_stats(), migrate_legacy_quick_stage() (+20 more)

### Community 109 - "ProfileManager"
Cohesion: 0.24
Nodes (3): ProfileManager, Path, Metadata a worker can safely publish to the backend registry.

### Community 113 - "Arsitektur Sistem tme3bot"
Cohesion: 0.25
Nodes (6): Arsitektur Sistem tme3bot, Data, sesi, dan batas keamanan, Deployment dan pengembangan, Gambaran sistem, Komponen dan tanggung jawab, Peta source untuk mulai menelusuri

### Community 114 - "tme3bot"
Cohesion: 0.22
Nodes (9): Arsitektur, Build Docker melalui GitHub Actions, Job dan progress, Login web melalui bot, Setup VPS utama, Storage dan backup, tme3bot, Verifikasi (+1 more)

### Community 117 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 118 - "Path"
Cohesion: 0.29
Nodes (3): CommandCallback, Path, Remove the two intermediate JSON files produced by ``pindah``. ``pindah4.py``…

### Community 119 - "CommandMilestoneRecorder"
Cohesion: 0.20
Nodes (4): CommandMilestoneRecorder, Persist bounded command results without allowing telemetry to fail work., Create the pending milestone before a subprocess begins work., Complete the pending milestone with bounded, sanitized output.

### Community 120 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

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

### Community 129 - "validate_rclone_destination"
Cohesion: 0.36
Nodes (6): ValueError, Validate a remote destination before it reaches a worker command., UtilityPathError, _validate_password(), validate_rclone_destination(), _validate_size()

### Community 131 - ".test_subprocess_runner_freezes_and_resumes_current_process"
Cohesion: 0.40
Nodes (4): skipIf, CompletedProcess, output(), run()

### Community 137 - "models.py"
Cohesion: 0.17
Nodes (11): Enum, Event, str, worker_event(), Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, JobStatus, datetime (+3 more)

## Knowledge Gaps
- **191 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+186 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 749 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **27 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DomainError` connect `DomainError` to `control_plane.py`, `WorkerEventPublisher`, `register_utility`, `models.py`, `create_worker_app`, `register_downloads`, `JobStoreTests`, `create_backend_app`, `register_jobs`, `register_storage`, `JobEvent`, `SqliteAuthRepository`, `ControlPlane`, `backend.py`, `_add_management_routes`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `.test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage`, `inspect_export_json`, `ProgressReporter`, `composition.py`, `WorkerEventPublisher`, `models.py`, `quick_export.py`, `executor.py`, `tme3bot/utility.py`, `CommandMilestoneRecorder`, `tdl.py`, `QuickModeExecutorMixin`, `.test_download_progress_callbacks_follow_the_download_lock_owner`, `ResourceAwareQueue`, `Path`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `PanelManager`, `composition.py`, `BackendApiClient`, `Any`, `format_job_status`, `telegram/app.py`, `FakeStatusPanel`, `request_json`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `create_backend_app()` (e.g. with `_active_storage_item()` and `current_actor()`) actually correct?**
  _`create_backend_app()` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `ExportStatusPollingTests`) actually correct?**
  _`TelegramFrontendApp` has 7 INFERRED edges - model-reasoned connections that need verification._