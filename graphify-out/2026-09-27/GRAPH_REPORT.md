# Graph Report - dockter_bot_tdl  (2026-09-27)

## Corpus Check
- 194 files · ~150,131 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 2924 nodes · 7295 edges · 139 communities (107 shown, 28 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 508 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ad28a141`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- BackupService
- pindah4.py
- PanelManager
- BatchDownloadService
- organize_media_from_json.py
- Job
- config.py
- test-setup.ts
- SubprocessRunner
- Path
- compress.sh
- create_worker_app
- Any
- boltStorage
- format_job_status
- executor.py
- StorageCatalog
- profiles.py
- tme3bot/utility.py
- compilerOptions
- telegram/app.py
- StateStore
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
- TtsPipeline
- write_json_atomic
- api.ts
- RunScriptTests
- LabelStore
- vitest
- run.py
- create_backend_app
- test_pindah.py
- ._storage_upload
- ExportWorkspaceState
- DownloadProgressTracker
- register_jobs
- 12. Bootstrap VPS baru dan satu-command deployment
- _add_management_routes
- SqliteAuthRepository
- ControlPlane
- WorkerEventPublisher
- job-progress.ts
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- parse_tme3_url
- composition.py
- quick_export.py
- ProfileTests
- TME3Bot Deployment Runbook
- request_json
- ../styles.css
- ArchitectureBoundaryTests
- 5. Pesan status sementara untuk semua job
- tdl.py
- infrastructure/__init__.py
- 2. Temuan dari kode saat ini
- FakeExecutor
- 6. Source picker Export Fokus
- register_runtime_settings
- 3. Keputusan desain
- .make_executor
- FakeDispatcher
- build.py
- BackendRuntimeSettings
- register_storage
- JobEvent
- WorkerRegistry
- ContainerBuildTests
- WorkerJobExecutor
- Path
- WorkerHttpDispatcher
- TDLClient
- .upload
- migrate_images
- inspect_export_json
- pkg_resources.py
- QuickThumbnailBuilder
- register_workers
- register_utility
- normalize_tdl_chat_ref
- ProfileRegistry
- pindah.py
- WorkspaceExecutorMixin
- .patch
- DomainError
- WorkerApiTests
- Arsitektur Sistem tme3bot
- routes/__init__.py
- JsonHttpError
- ARSITEKTUR_SISTEM.md
- tme3bot
- BackupScheduler
- tests/__init__.py
- WorkspaceExplorer.svelte
- FakeWorkers
- Overview.svelte
- FakeStatusPanel
- D. Menambah worker remote baru
- Rekomendasi berikutnya
- Autentikasi GitHub dan GHCR
- Update berikutnya
- Context target per fitur dan Download global
- Rollback
- bootstrap_python_dependencies
- Pengaturan aplikasi dari Web
- test_worker_contract.py
- FakeProfiles
- .test_subprocess_runner_freezes_and_resumes_current_process
- JobTable.svelte
- LeaveService
- ._capture_tdl_output
- register_backups
- models.py
- .test_quickmode_verify_requires_channel_and_drive_before_cleanup

## God Nodes (most connected - your core abstractions)
1. `DomainError` - 146 edges
2. `StorageCatalog` - 86 edges
3. `create_backend_app()` - 85 edges
4. `TelegramFrontendApp` - 77 edges
5. `SqliteJobRepository` - 68 edges
6. `WorkerJobExecutor` - 68 edges
7. `ControlPlane` - 63 edges
8. `BackendApiTests` - 62 edges
9. `JobEvent` - 60 edges
10. `Job` - 55 edges

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

## Communities (139 total, 28 thin omitted)

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
Cohesion: 0.16
Nodes (11): BatchDownloadResult, BatchDownloadService, _is_relative_to(), media_ids_in_export(), Any, Path, Download selected opaque filenames after strict directory validation., Download selected pending/failed JSON files from validated roots. (+3 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.08
Nodes (10): Protocol, Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job., Attach phase timing and event latency to this job's own event., ActorResolver, JobRepository, Any, StorageDelivery (+2 more)

### Community 6 - "config.py"
Cohesion: 0.19
Nodes (10): ChannelRefTests, update_backup_settings(), Update fields read by the live backend services without replacing config., channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`… (+2 more)

### Community 8 - "SubprocessRunner"
Cohesion: 0.12
Nodes (6): OutputCallback, ProgressCallback, Queue, CommandCallback, Popen, SubprocessRunner

### Community 9 - "Path"
Cohesion: 0.19
Nodes (16): build_base_archive(), build_base_image(), deploy_web(), _download(), find_host_tdl(), _github_repository(), hmac_compare(), _install_static_release() (+8 more)

### Community 11 - "create_worker_app"
Cohesion: 0.09
Nodes (13): ContractWorkerExecutor, create_worker_app(), authorize(), domain_error(), job_log_snapshot(), request_validation_error(), tts_artifact(), unhandled_error() (+5 more)

### Community 12 - "Any"
Cohesion: 0.16
Nodes (8): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), main_menu_markup(), edit_menu_message()

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.18
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "executor.py"
Cohesion: 0.09
Nodes (46): ExportMilestoneTests, QuickPipelineTests, sha256_file(), bounded_output_tail(), Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Return only the newest output without splitting a line when possible., Redact obvious secret flags and values before persisting a command. (+38 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (19): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+11 more)

### Community 17 - "profiles.py"
Cohesion: 0.12
Nodes (18): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), build_profile_config(), build_profile_runtime(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs() (+10 more)

### Community 18 - "tme3bot/utility.py"
Cohesion: 0.06
Nodes (26): UtilitySettingsTests, UtilitySummaryTests, Path, Verify exact remote files without downloading or mutating them., Check remote/config access separately from per-file differences., inventory_matches(), remote_inventory(), ProcessStalledError (+18 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.13
Nodes (25): canonical_chat_key(), Canonical chat references for TDL commands and Telegram Bot API targets., Canonicalize aliases for source state while preserving legacy keys., PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup() (+17 more)

### Community 21 - "StateStore"
Cohesion: 0.14
Nodes (11): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), StateStoreTests, build_telegram_message_url(), ExportService (+3 more)

### Community 22 - "QuickModeExecutorMixin"
Cohesion: 0.09
Nodes (27): Any, Path, QuickModeExecutorMixin, ensure_not_cancelled(), persist_uploaded_items(), phase_result(), save_manifest(), verify_log() (+19 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.16
Nodes (7): CallbackContext, Exception, Deliver durable TTS outbox entries using the Telegram process token., Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

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
Nodes (52): BaseModel, ActorResponse, ApiResponse, ApproveChallengeRequest, BackupRuntimeSettingsRequest, BatchSourcesRequest, BrowserChallengeResponse, BrowserProfileRequest (+44 more)

### Community 29 - "package.json"
Cohesion: 0.04
Nodes (42): bits-ui, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit (+34 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (34): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+26 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.14
Nodes (8): ExportArtifactCatalogTests, ExportArtifactCatalog, Any, Connection, Upsert an inventory batch in one SQLite transaction. Inventory can contain…, Mark catalog rows absent when a worker inventory completes., Remove a missing file from the runnable queue. The physical file is already…, utc_now()

### Community 37 - "ProgressReporter"
Cohesion: 0.09
Nodes (14): FakePublisher, ProgressReporterTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed., utc_timestamp() (+6 more)

### Community 38 - "main"
Cohesion: 0.20
Nodes (20): active_env_file(), backend_management_request(), deploy_all(), deploy_application(), ensure_profile_root(), load_env_file(), main(), manage_backup() (+12 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "TtsPipeline"
Cohesion: 0.05
Nodes (29): get, post, make_pipeline(), skipIf, TtsPipelineTests, request_part(), request_part(), Any (+21 more)

### Community 43 - "write_json_atomic"
Cohesion: 0.14
Nodes (9): utc_now_iso(), write_json_atomic(), HttpStateStore, normalize_chat_ref(), Any, Canonical source key for usernames, links, phones, and numeric IDs., StateStore-compatible client used by a worker without a local state file., SourceState (+1 more)

### Community 44 - "api.ts"
Cohesion: 0.32
Nodes (10): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+2 more)

### Community 46 - "LabelStore"
Cohesion: 0.25
Nodes (5): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel

### Community 49 - "run.py"
Cohesion: 0.16
Nodes (26): add_profile(), capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), configured_service(), data_root_value() (+18 more)

### Community 50 - "create_backend_app"
Cohesion: 0.08
Nodes (31): create_backend_app(), browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile(), browser_refresh(), browser_session() (+23 more)

### Community 52 - "._storage_upload"
Cohesion: 0.16
Nodes (10): StorageWorkerPathTests, Any, Path, Upload workspace files through the worker-local rclone config., StorageExecutorMixin, upload_progress(), Path, Return nested directories, including empty ones, as portable paths. (+2 more)

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.09
Nodes (17): ExportWorkspaceTests, loop(), export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref() (+9 more)

### Community 55 - "register_jobs"
Cohesion: 0.08
Nodes (39): event_dict(), job_dict(), _newest_first_log_response(), _owned_job(), _profile_artifact(), Any, Normalize current and legacy worker snapshots for the public API., register_downloads() (+31 more)

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
Nodes (13): ControlPlane, Any, Exception, Persist a worker's Quick Mode capacity and dispatch any new slots., Application facade used by every frontend adapter., Resume queued commands after backend restart or terminal events., Cancel jobs whose worker has stopped reporting progress. Worker cancellation is…, Restart an export attempt while preserving its stable job ID. (+5 more)

### Community 61 - "job-progress.ts"
Cohesion: 0.22
Nodes (10): eventLatency, phaseElapsedSeconds, phaseLabel(), stageId, clampPercent(), formatDuration(), JobLike, NormalizedProgress (+2 more)

### Community 62 - "presentation.ts"
Cohesion: 0.31
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 63 - "session.svelte.ts"
Cohesion: 0.09
Nodes (10): challenge, contextRevision, current, loading, loadWorkers(), selectedWorkers(), session, SessionWorker (+2 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.11
Nodes (8): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore, help_text(), Text helpers owned by the Telegram presentation adapter., source_digest()

### Community 65 - "SqliteJobRepository"
Cohesion: 0.09
Nodes (16): _dump(), _elapsed_between(), _load(), Any, Connection, Path, Row, _quick_mode_sql() (+8 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 68 - "parse_tme3_url"
Cohesion: 0.25
Nodes (6): ParseTme3UrlTests, parse_tme3_url(), ParsedTme3Url, ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 69 - "composition.py"
Cohesion: 0.20
Nodes (8): configure_logging(), main(), build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, run_backend(), run_worker()

### Community 70 - "quick_export.py"
Cohesion: 0.18
Nodes (19): _archive_files(), _chown_tree(), cleanup_quick_stage(), _clone_tree(), delete_quick_stage(), ensure_quick_stage_writable(), ensure_quick_tdl_client(), _json_media_stats() (+11 more)

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.11
Nodes (19): A. Langkah di komputer lokal, B. Build melalui GitHub Actions, Batas keamanan, Bootstrap VPS baru dengan `run.py`, C. Langkah di VPS gateway, Concurrency dan pesan status job, E. Update di setiap VPS worker remote, F. Deploy web static di VPS gateway (+11 more)

### Community 73 - "request_json"
Cohesion: 0.19
Nodes (6): BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Fetch Web-managed Telegram credentials during Telegram role startup., Frontend adapters. They communicate with the backend only through JSON., request_json()

### Community 76 - "5. Pesan status sementara untuk semua job"
Cohesion: 0.33
Nodes (6): 5.1 Komponen, 5.2 Jalur submit, 5.3 Subscription persisten, 5.4 Format message, 5.5 Polling, 5. Pesan status sementara untuk semua job

### Community 77 - "tdl.py"
Cohesion: 0.08
Nodes (29): Gateway orchestration, channel upload, scheduling, and retention., Create encrypted, runtime-only per-node backup archives., _message_contains_caption(), visit(), _normalize_upload_caption(), _byte_multiplier(), clean_tdl_output_line(), CommandProgress (+21 more)

### Community 79 - "2. Temuan dari kode saat ini"
Cohesion: 0.40
Nodes (5): 2.1 Akar masalah antrean, 2.2 Resource lock saat ini, 2.3 Notifikasi Telegram, 2.4 Source picker, 2. Temuan dari kode saat ini

### Community 81 - "6. Source picker Export Fokus"
Cohesion: 0.40
Nodes (5): 6.1 Inline picker searchable, 6.2 Search dan pagination, 6.3 Callback stabil, 6.4 Mini App fase berikutnya, 6. Source picker Export Fokus

### Community 82 - "register_runtime_settings"
Cohesion: 0.40
Nodes (3): register_runtime_settings(), update_runtime_secrets(), RuntimeSecretsRequest

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - ".make_executor"
Cohesion: 0.10
Nodes (3): export_from_url(), export_from_url(), WorkerExecutorTestCase

### Community 85 - "FakeDispatcher"
Cohesion: 0.13
Nodes (3): FailingDispatcher, FakeDispatcher, IncompatibleDispatcher

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - "BackendRuntimeSettings"
Cohesion: 0.44
Nodes (4): BackendRuntimeSettings, Any, Path, Persistent validated settings that can be applied to a live backend.

### Community 88 - "register_storage"
Cohesion: 0.09
Nodes (31): StorageLinkTests, _active_storage_item(), BackendContext, _deliver_storage_telegram(), _require_storage_folders_idle(), _storage_item(), FastAPI adapters for public and internal JSON contracts., delete_quick_mode_staging() (+23 more)

### Community 89 - "JobEvent"
Cohesion: 0.09
Nodes (3): ControlPlaneTests, JobStoreTests, JobEvent

### Community 90 - "WorkerRegistry"
Cohesion: 0.06
Nodes (18): WorkerRegistryTests, Path, RuntimeProfileManager, WorkerRuntimeSettingsTests, Any, Path, Atomically write JSON containing secrets with owner-only Unix mode., write_json_atomic_private() (+10 more)

### Community 92 - "WorkerJobExecutor"
Cohesion: 0.07
Nodes (13): Any, Event, Exception, Keep backend liveness independent from noisy subprocess output. A Quick Mode…, Executes domain jobs and publishes JSON events; no UI dependency., Bind the shared tracker callback only while owning its TDL lock., Make pre-manager Quick Mode staging visible after worker restart., Publish only profile metadata; .tdl files remain on this worker. (+5 more)

### Community 93 - "Path"
Cohesion: 0.14
Nodes (7): Path, QuickThumbnailTests, fake_run(), fake_run(), fake_run(), fake_run(), fake_run()

### Community 94 - "WorkerHttpDispatcher"
Cohesion: 0.27
Nodes (3): Any, RuntimeError, WorkerHttpDispatcher

### Community 95 - "TDLClient"
Cohesion: 0.21
Nodes (4): FakeRunner, TDLClientTests, decode_process_output(), TDLClient

### Community 96 - ".upload"
Cohesion: 0.27
Nodes (7): CompletedProcess, Path, Upload one file and optionally force it to Telegram photo media., Resolve delayed TDL upload results by polling channel history. Some TDL…, Raised when TDL returns unusable or malformed export data., TDLDataError, UploadResult

### Community 97 - "migrate_images"
Cohesion: 0.20
Nodes (11): build_migration_archive(), configured_base_image(), ensure_base_image_available(), login_registry(), migrate_images(), Login to the image registry without exposing the PAT in process output., Build both split deployment images and package them for an offline load., Stop early when extracted base artifacts no longer match the source. (+3 more)

### Community 98 - "inspect_export_json"
Cohesion: 0.13
Nodes (14): discard_export_without_media(), inspect_export_json(), Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape., Remove an export JSON when its inspected media count is exactly zero. The…, has_downloadable_media(), is_image_message() (+6 more)

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - "QuickThumbnailBuilder"
Cohesion: 0.10
Nodes (16): notify_command_completed(), notify_command_started(), CommandCallback, Notify an observer without making telemetry a process dependency. New observers…, Notify completion, supporting both new and legacy command observers., CommandMilestoneRecorder, Persist bounded command results without allowing telemetry to fail work., Create the pending milestone before a subprocess begins work. (+8 more)

### Community 101 - "register_workers"
Cohesion: 0.18
Nodes (12): register_workers(), remove_worker(), set_worker_enabled(), update_worker(), update_worker_settings(), worker_settings(), WorkerEnabledRequest, WorkerListResponse (+4 more)

### Community 102 - "register_utility"
Cohesion: 0.22
Nodes (5): register_utility(), utility_settings_meta(), utility_tree(), Public metadata for clients; never contains a setting value or secret., utility_setting_specs()

### Community 103 - "normalize_tdl_chat_ref"
Cohesion: 0.33
Nodes (5): ChatReferenceTests, normalize_bot_api_chat_ref(), normalize_tdl_chat_ref(), Return a canonical TDL peer selector or raise for unsupported input. TDL…, Return the Bot API chat_id representation for an ID or public username.

### Community 104 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 105 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 106 - "WorkspaceExecutorMixin"
Cohesion: 0.38
Nodes (4): Any, Path, Return a safe, shallow directory listing for the active workspace., WorkspaceExecutorMixin

### Community 108 - "DomainError"
Cohesion: 0.10
Nodes (25): verify_context(), verify_target(), _model_dict(), submit_download(), register_sources(), add_label(), get_source(), submit_export() (+17 more)

### Community 110 - "Arsitektur Sistem tme3bot"
Cohesion: 0.18
Nodes (11): Alur job, Antrean dan kerja bersamaan, Arsitektur Sistem tme3bot, Bagian sistem, Data dan keamanan, Deployment dan source map, Komunikasi backend dan worker, Quick Mode dan folder staging (+3 more)

### Community 113 - "ARSITEKTUR_SISTEM.md"
Cohesion: 0.29
Nodes (4): Aktifkan satu worker untuk uji coba, Pemeriksaan uji coba, Persiapan, TTS Novel: konfigurasi dan rollout

### Community 114 - "tme3bot"
Cohesion: 0.22
Nodes (9): Arsitektur, Build Docker melalui GitHub Actions, Job dan progress, Login web melalui bot, Setup VPS utama, Storage dan backup, tme3bot, Verifikasi (+1 more)

### Community 115 - "BackupScheduler"
Cohesion: 0.16
Nodes (3): BackendRuntimeSettingsTests, BackupScheduler, Recheck enabled state or the schedule after a Web update.

### Community 117 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 119 - "Overview.svelte"
Cohesion: 0.29
Nodes (4): describe(), error, icons, label()

### Community 120 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

### Community 121 - "D. Menambah worker remote baru"
Cohesion: 0.40
Nodes (5): D.1 Siapkan VPS worker remote, D.2 Daftarkan worker pada VPS gateway, D.3 Verifikasi worker dan route legacy, D.4 Mengaktifkan atau menonaktifkan worker dari Web UI, D. Menambah worker remote baru

### Community 122 - "Rekomendasi berikutnya"
Cohesion: 0.50
Nodes (4): 1. Simpan audit penghapusan staging, 2. Perkuat recovery setelah worker restart, 3. Pantau kapasitas worker dan staging, Rekomendasi berikutnya

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

### Community 127 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

### Community 128 - "Pengaturan aplikasi dari Web"
Cohesion: 0.29
Nodes (6): Kontrak implementasi, Pengaturan aplikasi dari Web, Pengaturan deployment, Pengaturan yang sudah ada di Web, Pengelolaan rahasia, Status migrasi konfigurasi

### Community 129 - "test_worker_contract.py"
Cohesion: 0.18
Nodes (10): patch, ContractWorkerRegistry, WorkerContractTests, capabilities(), Any, Versioned wire contract shared by the backend and worker processes., Return the non-secret version and feature set advertised by a worker., Reject workers whose advertised API cannot satisfy a backend operation. (+2 more)

### Community 131 - ".test_subprocess_runner_freezes_and_resumes_current_process"
Cohesion: 0.40
Nodes (4): CompletedProcess, skipIf, output(), run()

### Community 132 - "JobTable.svelte"
Cohesion: 0.17
Nodes (4): normalizeBotApiChatRef(), normalizeTdlChatRef(), if(), length()

### Community 133 - "LeaveService"
Cohesion: 0.40
Nodes (3): LeaveResult, LeaveService, CommandCallback

### Community 137 - "models.py"
Cohesion: 0.10
Nodes (16): Enum, FakeTelegramBot, FakeProfiles, worker_event(), _elapsed_since(), datetime, Application services and use cases., build_execution_plan() (+8 more)

### Community 144 - ".test_quickmode_verify_requires_channel_and_drive_before_cleanup"
Cohesion: 0.24
Nodes (5): first_callback(), first_download(), second_callback(), second_download(), runtime()

## Knowledge Gaps
- **203 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+198 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 827 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **28 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DomainError` connect `DomainError` to `test_worker_contract.py`, `Job`, `config.py`, `register_backups`, `models.py`, `create_worker_app`, `executor.py`, `QuickModeExecutorMixin`, `backend.py`, `create_backend_app`, `register_jobs`, `_add_management_routes`, `SqliteAuthRepository`, `ControlPlane`, `FakeExecutor`, `register_runtime_settings`, `FakeDispatcher`, `register_storage`, `JobEvent`, `WorkerRegistry`, `WorkerJobExecutor`, `Path`, `register_workers`, `register_utility`?**
  _High betweenness centrality (0.136) - this node is a cross-community bridge._
- **Why does `JsonHttpError` connect `JsonHttpError` to `test_worker_contract.py`, `register_workers`, `models.py`, `request_json`, `executor.py`, `telegram/app.py`, `TelegramFrontendApp`, `WorkerEventPublisher`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `PanelManager`, `composition.py`, `request_json`, `Any`, `format_job_status`, `JsonHttpError`, `telegram/app.py`, `ExportWorkspaceState`, `FakeStatusPanel`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Are the 12 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `create_backend_app()` (e.g. with `_active_storage_item()` and `current_actor()`) actually correct?**
  _`create_backend_app()` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `ExportStatusPollingTests`) actually correct?**
  _`TelegramFrontendApp` has 7 INFERRED edges - model-reasoned connections that need verification._