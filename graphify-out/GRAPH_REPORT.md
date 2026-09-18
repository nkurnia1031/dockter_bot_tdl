# Graph Report - dockter_bot_tdl  (2026-09-18)

## Corpus Check
- 153 files · ~105,925 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 2278 nodes · 5511 edges · 110 communities (85 shown, 21 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 300 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `69df8c15`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- profiles.py
- pindah4.py
- PanelManager
- ProfileManager
- organize_media_from_json.py
- Job
- WorkerRegistry
- BackendApiTests
- ProfileTests
- run.py
- compress.sh
- create_worker_app
- Any
- boltStorage
- format_job_status
- ServiceTests
- StorageCatalog
- create_backend_app
- UtilityRunner
- compilerOptions
- telegram/app.py
- BatchDownloadService
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
- executor.py
- ExportArtifactCatalog
- DownloadProgressTracker
- tdl_output.py
- main
- +layout.ts
- 8. Urutan implementasi
- RcloneRunner
- HttpStateStore
- api.ts
- RunScriptTests
- LabelStore
- vitest
- preflight_report
- .test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage
- test_pindah.py
- service.py
- ExportWorkspaceState
- SubprocessRunner
- TDLClient
- 12. Bootstrap VPS baru dan satu-command deployment
- _add_management_routes
- SqliteAuthRepository
- ControlPlane
- WorkspaceExplorer.svelte
- JobTable.svelte
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- FakeStatusPanel
- JobStatus
- .upload
- ._rclone_upload_files
- TME3Bot Deployment Runbook
- request_json
- ../styles.css
- ArchitectureBoundaryTests
- 5. Pesan status sementara untuk semua job
- AppConfig
- infrastructure/__init__.py
- 2. Temuan dari kode saat ini
- _error
- 6. Source picker Export Fokus
- BackupService
- 3. Keputusan desain
- .setUp
- job_dict
- build.py
- tdl.py
- WorkerHttpDispatcher
- JobEvent
- ProfileRegistry
- ContainerBuildTests
- StateStore
- QuickThumbnailBuilder
- storage_item_dict
- pindah.py
- devDependencies
- migrate_images
- ._storage_upload
- ProfileSelectionStore
- composition.py
- JobLogSnapshot
- utility_setting_specs
- WorkerEventPublisher
- ProgressReporter
- sign_storage_item
- client.py
- api/__init__.py
- .__init__

## God Nodes (most connected - your core abstractions)
1. `create_backend_app()` - 178 edges
2. `StorageCatalog` - 86 edges
3. `DomainError` - 83 edges
4. `TelegramFrontendApp` - 76 edges
5. `WorkerJobExecutor` - 64 edges
6. `SqliteJobRepository` - 48 edges
7. `ControlPlane` - 46 edges
8. `JobEvent` - 46 edges
9. `StateStore` - 45 edges
10. `Job` - 41 edges

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

### Community 0 - "profiles.py"
Cohesion: 0.15
Nodes (15): LeaveResult, LeaveService, Any, Path, utc_now_iso(), write_json_atomic(), build_profile_runtime(), chown_paths() (+7 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "ProfileManager"
Cohesion: 0.22
Nodes (5): normalize_profile_name(), get_profile_download_mode(), ProfileManager, Path, Metadata a worker can safely publish to the backend registry.

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.10
Nodes (7): Protocol, ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher, Job

### Community 6 - "WorkerRegistry"
Cohesion: 0.16
Nodes (7): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., Return workers that may receive new jobs. A disabled worker remains in…, WorkerRegistry

### Community 8 - "ProfileTests"
Cohesion: 0.37
Nodes (3): ProfileTests, Path, build_profile_config()

### Community 9 - "run.py"
Cohesion: 0.18
Nodes (25): active_env_file(), add_profile(), backend_management_request(), data_root_value(), deploy_web(), _download(), ensure_host_subdirs(), ensure_profile_root() (+17 more)

### Community 11 - "create_worker_app"
Cohesion: 0.09
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

### Community 15 - "ServiceTests"
Cohesion: 0.25
Nodes (6): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), ExportResult

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (19): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+11 more)

### Community 17 - "create_backend_app"
Cohesion: 0.05
Nodes (45): create_backend_app(), add_label(), archive_artifact(), browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile() (+37 more)

### Community 18 - "UtilityRunner"
Cohesion: 0.10
Nodes (12): UtilitySummaryTests, Path, ValueError, Validate a remote destination before it reaches a worker command., Remove the two intermediate JSON files produced by ``pindah``. ``pindah4.py``…, UtilityFolderStore, UtilityPathError, UtilityRunner (+4 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.20
Nodes (20): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_picker_markup() (+12 more)

### Community 21 - "BatchDownloadService"
Cohesion: 0.20
Nodes (12): BatchDownloadResult, BatchDownloadService, DownloadedJsonResult, _is_relative_to(), media_ids_in_export(), Path, Download selected opaque filenames after strict directory validation., Download selected pending/failed JSON files from validated roots. (+4 more)

### Community 22 - "WorkerJobExecutor"
Cohesion: 0.11
Nodes (14): ExportMilestoneTests, export_from_url(), QuickPipelineTests, ExportJobResult, json_value(), Any, Exception, Path (+6 more)

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
Cohesion: 0.06
Nodes (30): bits-ui, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit (+22 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (34): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+26 more)

### Community 34 - "executor.py"
Cohesion: 0.10
Nodes (28): UtilityResult, Run the post-export Quick Mode stages while retaining staging on error., Read the last persisted Quick phase for failed/cancelled retries., _utility_progress_message(), ensure_not_cancelled(), save_manifest(), utility_progress(), Framework-independent worker execution adapter. (+20 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.11
Nodes (14): ExportArtifactCatalogTests, discard_export_without_media(), ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical… (+6 more)

### Community 37 - "tdl_output.py"
Cohesion: 0.15
Nodes (18): _byte_multiplier(), clean_tdl_output_line(), _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_elapsed_seconds(), parse_eta_seconds() (+10 more)

### Community 38 - "main"
Cohesion: 0.15
Nodes (22): bootstrap_python_dependencies(), configured_service(), deploy_all(), deploy_application(), ensure_container_profile_dirs(), main(), _pip_supports_flag(), print_preflight_report() (+14 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "RcloneRunner"
Cohesion: 0.15
Nodes (8): FakeSubprocessRunner, RcloneRunnerTests, Path, RuntimeError, Raised when an rclone transfer cannot be completed., Small, cancellable rclone adapter for files already in the workspace., RcloneError, RcloneRunner

### Community 43 - "HttpStateStore"
Cohesion: 0.15
Nodes (7): HttpStateStore, normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 44 - "api.ts"
Cohesion: 0.13
Nodes (10): api(), ApiError, csrf(), put(), remove(), describe(), error, icons (+2 more)

### Community 46 - "LabelStore"
Cohesion: 0.14
Nodes (11): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, parse_tme3_url(), ValueError (+3 more)

### Community 49 - "preflight_report"
Cohesion: 0.16
Nodes (18): capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), docker_image_exists(), docker_manifest_exists(), git_remote_revision() (+10 more)

### Community 52 - "service.py"
Cohesion: 0.21
Nodes (7): has_downloadable_media(), is_image_message(), Any, build_telegram_message_url(), ExportService, Any, ParsedTme3Url

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.10
Nodes (16): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref(), normalize_chat_ref() (+8 more)

### Community 54 - "SubprocessRunner"
Cohesion: 0.18
Nodes (4): OutputCallback, Popen, ProgressCallback, SubprocessRunner

### Community 55 - "TDLClient"
Cohesion: 0.26
Nodes (4): FakeRunner, CompletedProcess, TDLClientTests, TDLClient

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
Cohesion: 0.14
Nodes (10): ControlPlane, Any, Resume queued commands after backend restart or terminal events., Application facade used by every frontend adapter., Create a new export attempt while preserving the old record., Find the original TDL message range without reading the JSON file. New jobs…, _redact_secrets(), serializable() (+2 more)

### Community 60 - "WorkspaceExplorer.svelte"
Cohesion: 0.13
Nodes (9): crumbs, error, folders, goUp(), load(), loading, openCrumb(), clear() (+1 more)

### Community 61 - "JobTable.svelte"
Cohesion: 0.27
Nodes (6): clampPercent(), formatDuration(), JobLike, NormalizedProgress, normalizeJobProgress(), number()

### Community 62 - "presentation.ts"
Cohesion: 0.31
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 63 - "session.svelte.ts"
Cohesion: 0.10
Nodes (10): challenge, contextRevision, current, loading, loadWorkers(), selectedWorkers(), session, SessionWorker (+2 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.10
Nodes (9): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore, _export_source_compact_markup(), Render the default form without flooding it with source buttons. Source…, Text helpers owned by the Telegram presentation adapter. (+1 more)

### Community 65 - "SqliteJobRepository"
Cohesion: 0.13
Nodes (10): _dump(), _load(), Any, Connection, Path, Row, Acquire all keys or return a deterministic queue position., Atomically replace an active job's lease set. Quick Mode uses this at… (+2 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 68 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

### Community 69 - "JobStatus"
Cohesion: 0.13
Nodes (15): Enum, str, worker_event(), Application services and use cases., build_execution_plan(), JobExecutionPlan, Any, Internal scheduling metadata shared by backend and worker. (+7 more)

### Community 70 - ".upload"
Cohesion: 0.27
Nodes (7): CompletedProcess, Path, RuntimeError, Raised when TDL returns unusable or malformed export data., Upload one file and optionally force it to Telegram photo media., Resolve delayed TDL upload results by polling channel history. Some TDL…, TDLDataError

### Community 71 - "._rclone_upload_files"
Cohesion: 0.22
Nodes (3): Upload workspace files through the worker-local rclone config., Make pre-manager Quick Mode staging visible after worker restart., Publish only profile metadata; .tdl files remain on this worker.

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.04
Nodes (46): A. Langkah di komputer lokal, A. Login repository GitHub, Autentikasi GitHub dan GHCR, B. Build melalui GitHub Actions, B. Login GitHub Container Registry, Backend atau worker, Batas keamanan, Bootstrap VPS baru dengan `run.py` (+38 more)

### Community 73 - "request_json"
Cohesion: 0.31
Nodes (4): BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., request_json()

### Community 76 - "5. Pesan status sementara untuk semua job"
Cohesion: 0.33
Nodes (6): 5.1 Komponen, 5.2 Jalur submit, 5.3 Subscription persisten, 5.4 Format message, 5.5 Polling, 5. Pesan status sementara untuk semua job

### Community 77 - "AppConfig"
Cohesion: 0.16
Nodes (14): ChannelRefTests, configure_logging(), main(), channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`… (+6 more)

### Community 79 - "2. Temuan dari kode saat ini"
Cohesion: 0.40
Nodes (5): 2.1 Akar masalah antrean, 2.2 Resource lock saat ini, 2.3 Notifikasi Telegram, 2.4 Source picker, 2. Temuan dari kode saat ini

### Community 80 - "_error"
Cohesion: 0.20
Nodes (10): domain_error_handler(), exchange_challenge(), key_error_handler(), permission_error_handler(), unhandled_error_handler(), validation_error_handler(), value_error_handler(), _error() (+2 more)

### Community 81 - "6. Source picker Export Fokus"
Cohesion: 0.40
Nodes (5): 6.1 Inline picker searchable, 6.2 Search dan pagination, 6.3 Callback stabil, 6.4 Mini App fase berikutnya, 6. Source picker Export Fokus

### Community 82 - "BackupService"
Cohesion: 0.09
Nodes (16): BackupServiceTests, make_config(), Path, BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention. (+8 more)

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - ".setUp"
Cohesion: 0.17
Nodes (3): FailingDispatcher, FakeDispatcher, FakeProfiles

### Community 85 - "job_dict"
Cohesion: 0.09
Nodes (29): archive_job(), cancel_job(), clear_failed(), create_telegram_notification(), delete_artifacts_batch(), get_job(), get_job_events(), get_job_log_snapshot() (+21 more)

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - "tdl.py"
Cohesion: 0.20
Nodes (11): Queue, decode_process_output(), _message_contains_caption(), visit(), _normalize_upload_caption(), CommandProgress, parse_terminal_size(), prepare_subprocess_command() (+3 more)

### Community 88 - "WorkerHttpDispatcher"
Cohesion: 0.31
Nodes (4): JsonHttpError, Any, RuntimeError, WorkerHttpDispatcher

### Community 89 - "JobEvent"
Cohesion: 0.11
Nodes (4): ControlPlaneTests, JobStoreTests, Update the latest telemetry without growing persistent event history., JobEvent

### Community 90 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 92 - "StateStore"
Cohesion: 0.27
Nodes (3): StateStoreTests, Path, StateStore

### Community 93 - "QuickThumbnailBuilder"
Cohesion: 0.20
Nodes (8): export_from_url(), Path, QuickThumbnailTests, fake_run(), fake_run(), fake_run(), QuickThumbnailBuilder, Build a bounded, padded visual collage using ffmpeg/ffprobe. The process handle…

### Community 94 - "storage_item_dict"
Cohesion: 0.28
Nodes (9): delete_storage_item(), get_storage_item(), move_storage_entries(), restore_storage_entries(), restore_storage_item(), search_storage(), update_storage_item(), _storage_item() (+1 more)

### Community 95 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 96 - "devDependencies"
Cohesion: 0.17
Nodes (12): devDependencies, jsdom, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss, @tailwindcss/vite (+4 more)

### Community 97 - "migrate_images"
Cohesion: 0.18
Nodes (14): build_base_archive(), build_base_image(), build_migration_archive(), configured_base_image(), ensure_base_image_available(), find_host_tdl(), login_registry(), migrate_images() (+6 more)

### Community 98 - "._storage_upload"
Cohesion: 0.11
Nodes (11): StorageWorkerPathTests, _has_transfer_telemetry(), Return nested directories, including empty ones, as portable paths., storage_logical_folder(), storage_relative_folders(), part_progress(), capture(), progress_event() (+3 more)

### Community 100 - "composition.py"
Cohesion: 0.06
Nodes (11): FakeDispatcher, FakeProfiles, FakeTelegramBot, FakeWorkers, UtilitySettingsTests, BackendContext, build_backend_context(), ControlPlaneBackupRouter (+3 more)

### Community 103 - "utility_setting_specs"
Cohesion: 0.67
Nodes (3): utility_settings_meta(), Public metadata for clients; never contains a setting value or secret., utility_setting_specs()

### Community 105 - "ProgressReporter"
Cohesion: 0.16
Nodes (9): FakePublisher, ProgressReporterTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed., utc_timestamp() (+1 more)

### Community 106 - "sign_storage_item"
Cohesion: 0.24
Nodes (10): StorageLinkTests, _active_storage_item(), deliver_public_storage_deep_link(), deliver_storage_deep_link(), deliver_storage_item(), storage_deep_link(), _deliver_storage_telegram(), Compact, stable HMAC tokens for Telegram storage deep links. (+2 more)

## Knowledge Gaps
- **177 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+172 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 621 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `create_backend_app()` connect `create_backend_app` to `JobEvent`, `composition.py`, `JobStatus`, `utility_setting_specs`, `sign_storage_item`, `api/__init__.py`, `AppConfig`, `_error`, `StorageCatalog`, `job_dict`, `_add_management_routes`, `ControlPlane`, `backend.py`, `storage_item_dict`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `executor.py`, `._storage_upload`, `composition.py`, `JobLogSnapshot`, `.test_quick_cancel_is_best_effort_when_some_runtimes_are_already_gone`, `._rclone_upload_files`, `WorkerEventPublisher`, `ProgressReporter`, `RcloneRunner`, `AppConfig`, `.test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage`, `BackupService`, `UtilityRunner`, `SubprocessRunner`, `ResourceAwareQueue`, `QuickThumbnailBuilder`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `PanelManager`, `FakeStatusPanel`, `request_json`, `Any`, `AppConfig`, `format_job_status`, `telegram/app.py`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `create_backend_app()` (e.g. with `require_internal()` and `require_management()`) actually correct?**
  _`create_backend_app()` has 49 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `ExportStatusPollingTests`) actually correct?**
  _`TelegramFrontendApp` has 7 INFERRED edges - model-reasoned connections that need verification._