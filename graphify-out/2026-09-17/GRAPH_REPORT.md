# Graph Report - dockter_bot_tdl  (2026-09-17)

## Corpus Check
- 151 files · ~104,054 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 2249 nodes · 5447 edges · 112 communities (83 shown, 26 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 290 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7fa8d731`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- browser_refresh
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
- ExportService
- StorageCatalog
- create_backend_app
- utility.py
- compilerOptions
- telegram/app.py
- service.py
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
- StateStore
- HttpStateStore
- api.ts
- RunScriptTests
- LabelStore
- vitest
- preflight_report
- .test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage
- test_pindah.py
- composition.py
- ExportWorkspaceState
- SubprocessRunner
- TDLClient
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
- request_json
- .upload
- ._backup
- TME3Bot Deployment Runbook
- parse_tme3_url
- ../styles.css
- ArchitectureBoundaryTests
- 5. Pesan status sementara untuk semua job
- config.py
- infrastructure/__init__.py
- 2. Temuan dari kode saat ini
- _error
- 6. Source picker Export Fokus
- BackupService
- 3. Keputusan desain
- test_backend_api.py
- DomainError
- build.py
- tdl.py
- WorkerHttpDispatcher
- JobEvent
- ProfileRegistry
- ContainerBuildTests
- profiles.py
- QuickThumbnailBuilder
- storage_item_dict
- pindah.py
- Overview.svelte
- migrate_images
- test-setup.ts
- write_json_atomic
- FakeWorkers
- client.py
- FakeProfiles
- FakeDispatcher
- WorkerEventPublisher
- ProgressReporter
- sign_storage_item
- FakePublisher
- FakeDispatcher
- JobLogSnapshot
- ._recover_legacy_quick_stages
- FakeProfiles

## God Nodes (most connected - your core abstractions)
1. `create_backend_app()` - 178 edges
2. `StorageCatalog` - 86 edges
3. `DomainError` - 83 edges
4. `TelegramFrontendApp` - 76 edges
5. `WorkerJobExecutor` - 62 edges
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

## Communities (112 total, 26 thin omitted)

### Community 0 - "browser_refresh"
Cohesion: 0.16
Nodes (15): browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_refresh(), browser_session(), _clear_cookie(), _clear_session() (+7 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "ProfileManager"
Cohesion: 0.24
Nodes (3): ProfileManager, Path, Metadata a worker can safely publish to the backend registry.

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.10
Nodes (7): Protocol, ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher, Job

### Community 6 - "WorkerRegistry"
Cohesion: 0.16
Nodes (7): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., Return workers that may receive new jobs. A disabled worker remains in…, WorkerRegistry

### Community 9 - "run.py"
Cohesion: 0.18
Nodes (25): active_env_file(), add_profile(), backend_management_request(), data_root_value(), deploy_web(), _download(), ensure_host_subdirs(), ensure_profile_root() (+17 more)

### Community 11 - "create_worker_app"
Cohesion: 0.09
Nodes (12): FakeExecutor, WorkerApiTests, create_worker_app(), authorize(), domain_error(), job_log_snapshot(), unhandled_error(), _error() (+4 more)

### Community 12 - "Any"
Cohesion: 0.17
Nodes (8): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), loop(), edit_menu_message()

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.16
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "ExportService"
Cohesion: 0.26
Nodes (7): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), ExportService, ExportResult

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (17): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+9 more)

### Community 17 - "create_backend_app"
Cohesion: 0.05
Nodes (38): create_backend_app(), archive_artifact(), archive_job(), cancel_job(), clear_failed(), create_telegram_notification(), delete_artifact_file(), delete_artifacts_batch() (+30 more)

### Community 18 - "utility.py"
Cohesion: 0.10
Nodes (12): UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, Remove the two intermediate JSON files produced by ``pindah``. ``pindah4.py``…, UtilityFolderStore, UtilityPathError, UtilityRunner (+4 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.11
Nodes (25): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_compact_markup() (+17 more)

### Community 21 - "service.py"
Cohesion: 0.19
Nodes (12): BatchDownloadResult, BatchDownloadService, DownloadedJsonResult, _is_relative_to(), media_ids_in_export(), Path, Download selected opaque filenames after strict directory validation., Download selected pending/failed JSON files from validated roots. (+4 more)

### Community 22 - "WorkerJobExecutor"
Cohesion: 0.11
Nodes (13): json_value(), Any, Exception, Path, Run the post-export Quick Mode stages while retaining staging on error., Executes domain jobs and publishes JSON events; no UI dependency., Return a safe, shallow directory listing for the active workspace., Return non-secret worker capabilities for backend target checks. (+5 more)

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
Nodes (33): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+25 more)

### Community 34 - "executor.py"
Cohesion: 0.09
Nodes (28): StorageWorkerPathTests, Return nested directories, including empty ones, as portable paths., storage_logical_folder(), storage_relative_folders(), _utility_progress_message(), ensure_not_cancelled(), save_manifest(), utility_progress() (+20 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.09
Nodes (18): ExportArtifactCatalogTests, discard_export_without_media(), ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical… (+10 more)

### Community 37 - "tdl_output.py"
Cohesion: 0.17
Nodes (18): _byte_multiplier(), clean_tdl_output_line(), CommandProgress, _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_elapsed_seconds() (+10 more)

### Community 38 - "main"
Cohesion: 0.15
Nodes (22): bootstrap_python_dependencies(), configured_service(), deploy_all(), deploy_application(), ensure_container_profile_dirs(), main(), _pip_supports_flag(), print_preflight_report() (+14 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "StateStore"
Cohesion: 0.24
Nodes (3): StateStoreTests, Path, StateStore

### Community 43 - "HttpStateStore"
Cohesion: 0.15
Nodes (8): utc_now_iso(), HttpStateStore, normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 44 - "api.ts"
Cohesion: 0.13
Nodes (6): api(), ApiError, csrf(), put(), remove(), async()

### Community 46 - "LabelStore"
Cohesion: 0.26
Nodes (6): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, slugify_label()

### Community 49 - "preflight_report"
Cohesion: 0.16
Nodes (18): capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), docker_image_exists(), docker_manifest_exists(), git_remote_revision() (+10 more)

### Community 50 - ".test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage"
Cohesion: 0.09
Nodes (8): ExportMilestoneTests, export_from_url(), export_from_url(), QuickPipelineTests, download_export_to(), run(), ExportJobResult, UtilityResult

### Community 52 - "composition.py"
Cohesion: 0.10
Nodes (11): configure_logging(), main(), BackupScheduler, build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, run_backend() (+3 more)

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.10
Nodes (16): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref(), normalize_chat_ref() (+8 more)

### Community 54 - "SubprocessRunner"
Cohesion: 0.14
Nodes (6): OutputCallback, Popen, ProgressCallback, LeaveResult, LeaveService, SubprocessRunner

### Community 55 - "TDLClient"
Cohesion: 0.22
Nodes (4): FakeRunner, CompletedProcess, TDLClientTests, TDLClient

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - ".setUp"
Cohesion: 0.11
Nodes (7): _add_internal_state_routes(), sync_profiles(), _add_management_routes(), management_start_backup(), BackendContext, FastAPI, FastAPI adapters for public and internal JSON contracts.

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.10
Nodes (14): str, AuthServiceTests, actor(), Path, AuthChallengeStatus, BotAuthService, _hash_secret(), _now() (+6 more)

### Community 59 - "ControlPlane"
Cohesion: 0.14
Nodes (9): ControlPlane, Any, Resume queued commands after backend restart or terminal events., Application facade used by every frontend adapter., Create a new export attempt while preserving the old record., Find the original TDL message range without reading the JSON file. New jobs…, _redact_secrets(), serializable() (+1 more)

### Community 60 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 61 - "job-progress.ts"
Cohesion: 0.39
Nodes (6): clampPercent(), formatDuration(), JobLike, NormalizedProgress, normalizeJobProgress(), number()

### Community 62 - "presentation.ts"
Cohesion: 0.42
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 63 - "session.svelte.ts"
Cohesion: 0.12
Nodes (10): challenge, contextRevision, current, loading, loadWorkers(), selectedWorkers(), session, SessionWorker (+2 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.14
Nodes (5): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore

### Community 65 - "SqliteJobRepository"
Cohesion: 0.12
Nodes (12): _dump(), _load(), Any, Connection, Path, Row, _quick_mode_sql(), Filter the compact JSON payload without requiring SQLite JSON1. (+4 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 68 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

### Community 69 - "request_json"
Cohesion: 0.31
Nodes (4): BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., request_json()

### Community 70 - ".upload"
Cohesion: 0.27
Nodes (7): CompletedProcess, Path, RuntimeError, Raised when TDL returns unusable or malformed export data., Upload one file and optionally force it to Telegram photo media., Resolve delayed TDL upload results by polling channel history. Some TDL…, TDLDataError

### Community 71 - "._backup"
Cohesion: 0.15
Nodes (7): _has_transfer_telemetry(), part_progress(), capture(), progress_event(), report_snapshot(), export_progress(), upload_progress()

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.04
Nodes (46): A. Langkah di komputer lokal, A. Login repository GitHub, Autentikasi GitHub dan GHCR, B. Langkah build lokal, B. Login GitHub Container Registry, Backend atau worker, Batas keamanan, Bootstrap VPS baru dengan `run.py` (+38 more)

### Community 73 - "parse_tme3_url"
Cohesion: 0.17
Nodes (7): ParseTme3UrlTests, build_telegram_message_url(), parse_tme3_url(), ParsedTme3Url, ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 76 - "5. Pesan status sementara untuk semua job"
Cohesion: 0.33
Nodes (6): 5.1 Komponen, 5.2 Jalur submit, 5.3 Subscription persisten, 5.4 Format message, 5.5 Polling, 5. Pesan status sementara untuk semua job

### Community 77 - "config.py"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`…, load_dotenv(), _parse_named_values()

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
Cohesion: 0.10
Nodes (16): BackupServiceTests, make_config(), Path, BackupCoordinator, BackupNodeJob, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup. (+8 more)

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - "test_backend_api.py"
Cohesion: 0.14
Nodes (11): Enum, FakeTelegramBot, Application services and use cases., build_execution_plan(), JobExecutionPlan, Any, Internal scheduling metadata shared by backend and worker., Framework-independent domain model for the tme3bot control plane. (+3 more)

### Community 85 - "DomainError"
Cohesion: 0.08
Nodes (31): _active_storage_item(), add_label(), browser_profile(), create_storage_folder(), deliver_public_storage_deep_link(), deliver_storage_deep_link(), deliver_storage_item(), get_source() (+23 more)

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - "tdl.py"
Cohesion: 0.22
Nodes (10): Queue, decode_process_output(), _message_contains_caption(), visit(), _normalize_upload_caption(), parse_terminal_size(), prepare_subprocess_command(), Any (+2 more)

### Community 88 - "WorkerHttpDispatcher"
Cohesion: 0.31
Nodes (4): JsonHttpError, Any, RuntimeError, WorkerHttpDispatcher

### Community 89 - "JobEvent"
Cohesion: 0.10
Nodes (5): ControlPlaneTests, JobStoreTests, worker_event(), Update the latest telemetry without growing persistent event history., JobEvent

### Community 90 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 92 - "profiles.py"
Cohesion: 0.23
Nodes (14): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), build_profile_config(), build_profile_runtime(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs() (+6 more)

### Community 93 - "QuickThumbnailBuilder"
Cohesion: 0.29
Nodes (7): Path, QuickThumbnailTests, fake_run(), fake_run(), fake_run(), QuickThumbnailBuilder, Build a bounded, padded visual collage using ffmpeg/ffprobe. The process handle…

### Community 94 - "storage_item_dict"
Cohesion: 0.28
Nodes (9): delete_storage_item(), get_storage_item(), move_storage_entries(), restore_storage_entries(), restore_storage_item(), search_storage(), update_storage_item(), _storage_item() (+1 more)

### Community 95 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 96 - "Overview.svelte"
Cohesion: 0.29
Nodes (4): describe(), error, icons, label()

### Community 97 - "migrate_images"
Cohesion: 0.18
Nodes (14): build_base_archive(), build_base_image(), build_migration_archive(), configured_base_image(), ensure_base_image_available(), find_host_tdl(), login_registry(), migrate_images() (+6 more)

### Community 99 - "write_json_atomic"
Cohesion: 0.24
Nodes (4): Any, Path, write_json_atomic(), ProfileSelectionStore

### Community 105 - "ProgressReporter"
Cohesion: 0.24
Nodes (7): _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed., utc_timestamp(), _without_none()

### Community 106 - "sign_storage_item"
Cohesion: 0.52
Nodes (4): StorageLinkTests, Compact, stable HMAC tokens for Telegram storage deep links., sign_storage_item(), verify_storage_item()

## Knowledge Gaps
- **176 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+171 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 607 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **26 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `create_backend_app()` connect `create_backend_app` to `browser_refresh`, `JobEvent`, `sign_storage_item`, `_error`, `StorageCatalog`, `test_backend_api.py`, `DomainError`, `composition.py`, `.setUp`, `ControlPlane`, `backend.py`, `storage_item_dict`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `executor.py`, `._backup`, `WorkerEventPublisher`, `ProgressReporter`, `JobLogSnapshot`, `._recover_legacy_quick_stages`, `.test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage`, `BackupService`, `composition.py`, `utility.py`, `SubprocessRunner`, `ResourceAwareQueue`, `QuickThumbnailBuilder`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `PanelManager`, `FakeStatusPanel`, `request_json`, `Any`, `format_job_status`, `telegram/app.py`, `composition.py`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `create_backend_app()` (e.g. with `require_internal()` and `require_management()`) actually correct?**
  _`create_backend_app()` has 49 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `ExportStatusPollingTests`) actually correct?**
  _`TelegramFrontendApp` has 7 INFERRED edges - model-reasoned connections that need verification._