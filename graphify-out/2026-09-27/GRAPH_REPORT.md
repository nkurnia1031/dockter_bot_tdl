# Graph Report - dockter_bot_tdl  (2026-09-27)

## Corpus Check
- 183 files · ~140,588 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 2780 nodes · 6896 edges · 129 communities (102 shown, 24 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 492 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `82d872d9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- composition.py
- pindah4.py
- PanelManager
- tdl.py
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
- ProfileRegistry
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
- test_quick_export.py
- ExportArtifactCatalog
- BackendApiTests
- FakePublisher
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
- RcloneRunner
- ExportWorkspaceState
- DownloadProgressTracker
- register_jobs
- 12. Bootstrap VPS baru dan satu-command deployment
- .setUp
- SqliteAuthRepository
- ControlPlane
- test_worker_contract.py
- job-progress.ts
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- ExportService
- register_sources
- quick_export.py
- ProfileTests
- TME3Bot Deployment Runbook
- request_json
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
- tdl_output.py
- build.py
- .test_download_progress_callbacks_follow_the_download_lock_owner
- sign_storage_item
- JobEvent
- FakeProfiles
- ContainerBuildTests
- WorkerJobExecutor
- QuickThumbnailTests
- WorkerHttpDispatcher
- TDLClient
- control_plane.py
- migrate_images
- inspect_export_json
- pkg_resources.py
- RcloneRunnerTests
- WorkerEventPublisher
- register_utility
- bootstrap_python_dependencies
- QuickThumbnailBuilder
- pindah.py
- WorkspaceExecutorMixin
- register_downloads
- DomainError
- WorkerApiTests
- Arsitektur Sistem tme3bot
- routes/__init__.py
- FakeDispatcher
- ARSITEKTUR_SISTEM.md
- tme3bot
- FakeWorkers
- tests/__init__.py
- WorkspaceExplorer.svelte
- storage_item_dict
- Overview.svelte
- FakeStatusPanel
- D. Menambah worker remote baru
- Rekomendasi berikutnya
- Autentikasi GitHub dan GHCR
- Update berikutnya
- Context target per fitur dan Download global
- Rollback
- .test_subprocess_runner_freezes_and_resumes_current_process
- models.py

## God Nodes (most connected - your core abstractions)
1. `DomainError` - 130 edges
2. `StorageCatalog` - 86 edges
3. `create_backend_app()` - 84 edges
4. `TelegramFrontendApp` - 77 edges
5. `WorkerJobExecutor` - 69 edges
6. `SqliteJobRepository` - 68 edges
7. `ControlPlane` - 62 edges
8. `JobEvent` - 60 edges
9. `Job` - 55 edges
10. `BackendApiTests` - 52 edges

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

## Communities (129 total, 24 thin omitted)

### Community 0 - "composition.py"
Cohesion: 0.05
Nodes (27): BackupServiceTests, make_config(), Path, UtilitySettingsTests, configure_logging(), main(), BackupCoordinator, BackupNodeJob (+19 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "tdl.py"
Cohesion: 0.14
Nodes (20): has_downloadable_media(), is_image_message(), Any, BatchDownloadResult, BatchDownloadService, build_telegram_message_url(), _is_relative_to(), media_ids_in_export() (+12 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.08
Nodes (10): Protocol, Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job., Attach phase timing and event latency to this job's own event., ActorResolver, JobRepository, Any, StorageDelivery (+2 more)

### Community 6 - "WorkerRegistry"
Cohesion: 0.15
Nodes (7): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., Return workers that may receive new jobs. A disabled worker remains in…, WorkerRegistry

### Community 8 - "SubprocessRunner"
Cohesion: 0.11
Nodes (7): OutputCallback, ProgressCallback, Queue, CommandCallback, Any, Popen, SubprocessRunner

### Community 9 - "Path"
Cohesion: 0.19
Nodes (16): build_base_archive(), build_base_image(), deploy_web(), _download(), find_host_tdl(), _github_repository(), hmac_compare(), _install_static_release() (+8 more)

### Community 11 - "create_worker_app"
Cohesion: 0.09
Nodes (13): ContractWorkerExecutor, create_worker_app(), authorize(), capabilities(), domain_error(), job_log_snapshot(), tts_artifact(), unhandled_error() (+5 more)

### Community 12 - "Any"
Cohesion: 0.17
Nodes (10): Thread, PendingInput, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), loop() (+2 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.16
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "executor.py"
Cohesion: 0.06
Nodes (48): StorageWorkerPathTests, sha256_file(), bounded_output_tail(), Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Return only the newest output without splitting a line when possible., Redact obvious secret flags and values before persisting a command., sanitize_command() (+40 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (15): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, Connection, Path, Row, Insert a callback result, returning the existing item on retry. (+7 more)

### Community 17 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 18 - "tme3bot/utility.py"
Cohesion: 0.08
Nodes (21): UtilitySummaryTests, notify_command_completed(), notify_command_started(), pause_process_group(), ProcessStalledError, CommandCallback, Notify an observer without making telemetry a process dependency. New observers…, Notify completion, supporting both new and legacy command observers. (+13 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.17
Nodes (19): Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_picker_markup(), InlineKeyboardMarkup (+11 more)

### Community 21 - "StateStore"
Cohesion: 0.15
Nodes (9): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), StateStoreTests, Path, StateStore (+1 more)

### Community 22 - "QuickModeExecutorMixin"
Cohesion: 0.08
Nodes (30): ExportJobResult, Any, Path, QuickModeExecutorMixin, ensure_not_cancelled(), persist_uploaded_items(), phase_result(), save_manifest() (+22 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.16
Nodes (8): CallbackContext, Exception, Deliver durable TTS outbox entries using the Telegram process token., Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, help_text(), Update

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
Cohesion: 0.12
Nodes (43): BaseModel, register_storage(), ActorResponse, ApiResponse, ApproveChallengeRequest, BrowserChallengeResponse, BrowserProfileRequest, BrowserSessionResponse (+35 more)

### Community 29 - "package.json"
Cohesion: 0.04
Nodes (42): bits-ui, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit (+34 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (34): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+26 more)

### Community 34 - "test_quick_export.py"
Cohesion: 0.07
Nodes (5): QuickPipelineTests, download_export_to(), run(), DownloadedJsonResult, UtilityResult

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.14
Nodes (8): ExportArtifactCatalogTests, ExportArtifactCatalog, Any, Connection, Upsert an inventory batch in one SQLite transaction. Inventory can contain…, Mark catalog rows absent when a worker inventory completes., Remove a missing file from the runnable queue. The physical file is already…, utc_now()

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
Cohesion: 0.12
Nodes (11): Any, Path, utc_now_iso(), write_json_atomic(), HttpStateStore, normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case. Numeric Telegram… (+3 more)

### Community 44 - "api.ts"
Cohesion: 0.17
Nodes (11): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+3 more)

### Community 46 - "LabelStore"
Cohesion: 0.24
Nodes (6): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, slugify_label()

### Community 49 - "run.py"
Cohesion: 0.16
Nodes (26): add_profile(), capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), configured_service(), data_root_value() (+18 more)

### Community 50 - "create_backend_app"
Cohesion: 0.08
Nodes (31): create_backend_app(), browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile(), browser_refresh(), browser_session() (+23 more)

### Community 52 - "RcloneRunner"
Cohesion: 0.15
Nodes (12): Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Small, cancellable rclone adapter for files already in the workspace., Check remote/config access separately from per-file differences., RcloneError, RcloneRunner (+4 more)

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.09
Nodes (18): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref(), normalize_chat_ref() (+10 more)

### Community 54 - "DownloadProgressTracker"
Cohesion: 0.28
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 55 - "register_jobs"
Cohesion: 0.08
Nodes (38): verify_context(), verify_target(), event_dict(), job_dict(), _model_dict(), _newest_first_log_response(), _owned_job(), Any (+30 more)

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
Cohesion: 0.09
Nodes (16): ControlPlane, Any, Exception, Persist a worker's Quick Mode capacity and dispatch any new slots., Application facade used by every frontend adapter., Resume queued commands after backend restart or terminal events., Cancel jobs whose worker has stopped reporting progress. Worker cancellation is…, Restart an export attempt while preserving its stable job ID. (+8 more)

### Community 60 - "test_worker_contract.py"
Cohesion: 0.20
Nodes (9): patch, ContractWorkerRegistry, WorkerContractTests, Any, Versioned wire contract shared by the backend and worker processes., Return the non-secret version and feature set advertised by a worker., Reject workers whose advertised API cannot satisfy a backend operation., require_worker_contract() (+1 more)

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
Cohesion: 0.11
Nodes (7): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore, Text helpers owned by the Telegram presentation adapter., source_digest()

### Community 65 - "SqliteJobRepository"
Cohesion: 0.09
Nodes (16): _dump(), _elapsed_between(), _load(), Any, Connection, Path, Row, _quick_mode_sql() (+8 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 68 - "ExportService"
Cohesion: 0.18
Nodes (8): ParseTme3UrlTests, ExportService, Any, parse_tme3_url(), ParsedTme3Url, ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 69 - "register_sources"
Cohesion: 0.19
Nodes (10): register_sources(), add_label(), get_source(), update_source(), BatchSourcesRequest, ExportRequest, LabelRequest, SourceListResponse (+2 more)

### Community 70 - "quick_export.py"
Cohesion: 0.11
Nodes (26): _archive_files(), _chown_tree(), cleanup_quick_stage(), _clone_tree(), delete_quick_stage(), ensure_quick_stage_writable(), ensure_quick_tdl_client(), _json_media_stats() (+18 more)

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.11
Nodes (19): A. Langkah di komputer lokal, B. Build melalui GitHub Actions, Batas keamanan, Bootstrap VPS baru dengan `run.py`, C. Langkah di VPS gateway, Concurrency dan pesan status job, E. Update di setiap VPS worker remote, F. Deploy web static di VPS gateway (+11 more)

### Community 73 - "request_json"
Cohesion: 0.21
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

### Community 82 - ".upload"
Cohesion: 0.19
Nodes (12): _message_contains_caption(), visit(), _normalize_upload_caption(), CompletedProcess, Path, RuntimeError, Match captions across the different JSON shapes emitted by TDL., Upload one file and optionally force it to Telegram photo media. (+4 more)

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - "profiles.py"
Cohesion: 0.10
Nodes (21): AppConfig, Fail fast when a production role is missing its trust boundary., LeaveResult, LeaveService, CommandCallback, normalize_profile_name(), build_profile_config(), build_profile_runtime() (+13 more)

### Community 85 - "tdl_output.py"
Cohesion: 0.19
Nodes (16): _byte_multiplier(), clean_tdl_output_line(), _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), parse_elapsed_seconds(), parse_eta_seconds(), parse_file_name() (+8 more)

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - ".test_download_progress_callbacks_follow_the_download_lock_owner"
Cohesion: 0.53
Nodes (5): first_callback(), first_download(), second_callback(), second_download(), runtime()

### Community 88 - "sign_storage_item"
Cohesion: 0.22
Nodes (11): StorageLinkTests, _active_storage_item(), _deliver_storage_telegram(), delete_quick_mode_staging(), deliver_public_storage_deep_link(), deliver_storage_deep_link(), deliver_storage_item(), storage_deep_link() (+3 more)

### Community 89 - "JobEvent"
Cohesion: 0.09
Nodes (3): ControlPlaneTests, JobStoreTests, JobEvent

### Community 92 - "WorkerJobExecutor"
Cohesion: 0.07
Nodes (14): ExportMilestoneTests, export_from_url(), export_from_url(), Any, Exception, Bind the shared tracker callback only while owning its TDL lock., Executes domain jobs and publishes JSON events; no UI dependency., Make pre-manager Quick Mode staging visible after worker restart. (+6 more)

### Community 93 - "QuickThumbnailTests"
Cohesion: 0.11
Nodes (9): Path, QuickThumbnailTests, fake_run(), fake_run(), fake_run(), fake_run(), fake_run(), JobLogSnapshot (+1 more)

### Community 94 - "WorkerHttpDispatcher"
Cohesion: 0.29
Nodes (4): JsonHttpError, Any, RuntimeError, WorkerHttpDispatcher

### Community 95 - "TDLClient"
Cohesion: 0.19
Nodes (3): FakeRunner, TDLClientTests, TDLClient

### Community 96 - "control_plane.py"
Cohesion: 0.08
Nodes (11): FailingDispatcher, FakeDispatcher, FakeProfiles, IncompatibleDispatcher, _elapsed_since(), datetime, Application services and use cases., build_execution_plan() (+3 more)

### Community 97 - "migrate_images"
Cohesion: 0.20
Nodes (11): build_migration_archive(), configured_base_image(), ensure_base_image_available(), login_registry(), migrate_images(), Login to the image registry without exposing the PAT in process output., Build both split deployment images and package them for an offline load., Stop early when extracted base artifacts no longer match the source. (+3 more)

### Community 98 - "inspect_export_json"
Cohesion: 0.17
Nodes (10): discard_export_without_media(), inspect_export_json(), Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape., Remove an export JSON when its inspected media count is exactly zero. The…, DownloadExecutorMixin, progress_event() (+2 more)

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 101 - "WorkerEventPublisher"
Cohesion: 0.09
Nodes (8): CommandMilestoneRecorder, json_value(), Any, Persist bounded command results without allowing telemetry to fail work., Create the pending milestone before a subprocess begins work., Complete the pending milestone with bounded, sanitized output., Seed event numbering for a reused job ID., WorkerEventPublisher

### Community 102 - "register_utility"
Cohesion: 0.13
Nodes (13): register_backups(), start_backup(), register_utility(), utility_settings_meta(), utility_tree(), ItemListResponse, ObjectResponse, Typed object envelope for small mutation/settings responses. (+5 more)

### Community 103 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

### Community 104 - "QuickThumbnailBuilder"
Cohesion: 0.21
Nodes (7): CommandCallback, Popen, QuickThumbnailBuilder, probe_next_video(), skip_media(), watchdog(), Build a bounded, padded visual collage using ffmpeg/ffprobe. The process handle…

### Community 105 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 106 - "WorkspaceExecutorMixin"
Cohesion: 0.38
Nodes (4): Any, Path, Return a safe, shallow directory listing for the active workspace., WorkspaceExecutorMixin

### Community 107 - "register_downloads"
Cohesion: 0.21
Nodes (11): _profile_artifact(), register_downloads(), archive_artifact(), delete_artifact_file(), delete_artifacts_batch(), purge_artifact(), reconcile_artifacts(), restore_artifact() (+3 more)

### Community 108 - "DomainError"
Cohesion: 0.09
Nodes (24): _require_storage_folders_idle(), create_storage_folder(), purge_storage_entries(), purge_storage_folder(), purge_storage_item(), storage_browser(), trash_storage_entries(), trash_storage_folder() (+16 more)

### Community 110 - "Arsitektur Sistem tme3bot"
Cohesion: 0.18
Nodes (11): Alur job, Antrean dan kerja bersamaan, Arsitektur Sistem tme3bot, Bagian sistem, Data dan keamanan, Deployment dan source map, Komunikasi backend dan worker, Quick Mode dan folder staging (+3 more)

### Community 113 - "ARSITEKTUR_SISTEM.md"
Cohesion: 0.29
Nodes (4): Aktifkan satu worker untuk uji coba, Pemeriksaan uji coba, Persiapan, TTS Novel: konfigurasi dan rollout

### Community 114 - "tme3bot"
Cohesion: 0.22
Nodes (9): Arsitektur, Build Docker melalui GitHub Actions, Job dan progress, Login web melalui bot, Setup VPS utama, Storage dan backup, tme3bot, Verifikasi (+1 more)

### Community 117 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 118 - "storage_item_dict"
Cohesion: 0.28
Nodes (9): _storage_item(), delete_storage_item(), get_storage_item(), move_storage_entries(), restore_storage_entries(), restore_storage_item(), search_storage(), update_storage_item() (+1 more)

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

### Community 131 - ".test_subprocess_runner_freezes_and_resumes_current_process"
Cohesion: 0.40
Nodes (4): CompletedProcess, skipIf, output(), run()

### Community 137 - "models.py"
Cohesion: 0.18
Nodes (9): Enum, str, FakeTelegramBot, worker_event(), Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, JobStatus, datetime (+1 more)

## Knowledge Gaps
- **198 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+193 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 792 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **24 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DomainError` connect `DomainError` to `Job`, `models.py`, `create_worker_app`, `executor.py`, `QuickModeExecutorMixin`, `backend.py`, `test_quick_export.py`, `create_backend_app`, `register_jobs`, `.setUp`, `SqliteAuthRepository`, `ControlPlane`, `test_worker_contract.py`, `register_sources`, `sign_storage_item`, `JobEvent`, `WorkerJobExecutor`, `QuickThumbnailTests`, `control_plane.py`, `register_utility`, `register_downloads`, `storage_item_dict`?**
  _High betweenness centrality (0.108) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `composition.py`, `PanelManager`, `request_json`, `Any`, `format_job_status`, `telegram/app.py`, `FakeStatusPanel`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `composition.py`, `test_quick_export.py`, `tdl.py`, `inspect_export_json`, `WorkerEventPublisher`, `quick_export.py`, `QuickThumbnailBuilder`, `ControlPlane`, `TtsPipeline`, `WorkspaceExecutorMixin`, `DomainError`, `executor.py`, `tme3bot/utility.py`, `RcloneRunner`, `QuickModeExecutorMixin`, `.test_download_progress_callbacks_follow_the_download_lock_owner`, `ResourceAwareQueue`, `QuickThumbnailTests`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `create_backend_app()` (e.g. with `_active_storage_item()` and `current_actor()`) actually correct?**
  _`create_backend_app()` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `ExportStatusPollingTests`) actually correct?**
  _`TelegramFrontendApp` has 7 INFERRED edges - model-reasoned connections that need verification._