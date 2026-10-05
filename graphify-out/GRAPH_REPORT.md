# Graph Report - dockter_bot_tdl  (2026-10-05)

## Corpus Check
- 255 files · ~224,570 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 4068 nodes · 9907 edges · 198 communities (161 shown, 33 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 658 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f8195b71`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- QueueTransportTests
- pindah4.py
- PanelManager
- BatchDownloadService
- organize_media_from_json.py
- JobRepository
- BackendRuntimeSettings
- Any
- SubprocessRunner
- run.py
- compress.sh
- create_worker_app
- ControlPlane
- boltStorage
- format_job_status
- executor.py
- StorageCatalog
- ._storage_upload
- tme3bot/utility.py
- compilerOptions
- telegram/app.py
- ExportService
- QuickModeExecutorMixin
- tme3bot-leave-helper
- TelegramFrontendApp
- tme3bot Agent Context
- ProfileSessionManager
- ResourceAwareQueue
- backend.py
- package.json
- StoragePage.svelte
- tme3bot/__init__.py
- pindah.sh script
- OperationsService
- ExportArtifactCatalog
- BackendApiTests
- ProfileProvisioningService
- main
- +layout.ts
- 8. Urutan implementasi
- TtsPipeline
- HttpStateStore
- api.ts
- RunScriptTests
- LabelStore
- vitest
- preflight_report
- create_backend_app
- test_pindah.py
- ProfileProvisioningStore
- ExportWorkspaceState
- DownloadProgressTracker
- register_jobs
- 12. Bootstrap VPS baru dan satu-command deployment
- _add_management_routes
- SqliteAuthRepository
- JobEvent
- migrate_source_state.py
- job-progress.ts
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- DurableDispatchTests
- SqliteOperationStore
- profiles.py
- test_tts_executor.py
- TME3Bot Deployment Runbook
- request_json
- ../styles.css
- ArchitectureBoundaryTests
- 5. Pesan status sementara untuk semua job
- extract.py
- infrastructure/__init__.py
- 2. Temuan dari kode saat ini
- FakeExecutor
- 6. Source picker Export Fokus
- TtsPipelineTests
- 3. Keputusan desain
- DeviceAuthService
- .setUp
- build.py
- QuickThumbnailBuilder
- register_storage
- BackupService
- Path
- ContainerBuildTests
- WorkerJobExecutor
- ProgressReporter
- WorkerHttpDispatcher
- TrustedDeviceError
- SqliteSourceRepository
- migrate_images
- ProfileTests
- pkg_resources.py
- SourceState
- register_utility
- P0 — Akses production dari laptop tepercaya
- Rencana pemisahan backend, worker, dan Web
- WorkerRegistry
- DeviceAuthTests
- 21 — Penyederhanaan ENV dan inventaris pemakaian
- RcloneRunner
- JsonHttpError
- 22 — Uji kegagalan lintas komponen dan panduan cutover
- Arsitektur Sistem tme3bot
- routes/__init__.py
- FakeDispatcher
- ARSITEKTUR_SISTEM.md
- tme3bot
- ProfileProvisioningTests
- tests/__init__.py
- QuickModePage.svelte
- StateStore
- 01 — Repository state backend dan pemisahan runtime profil
- FakeStatusPanel
- D. Menambah worker remote baru
- Rekomendasi berikutnya
- Autentikasi GitHub dan GHCR
- Update berikutnya
- Context target per fitur dan Download global
- Rollback
- AppConfig
- Pengaturan aplikasi dari Web
- Any
- 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress
- 03 — Operation persisten dan transactional outbox
- JobTable.svelte
- .update_worker_settings
- _hash_secret
- 04 — Redis privat dan proses RQ untuk orkestrasi
- TtsExecutorMixin
- ._capture_tdl_output
- tts_helper.py
- QueueOutboxPublisher
- 05 — Penerimaan cepat dan kontrak dispatch berversi
- 06 — Alias peer dan serialisasi export lintas worker
- test_profile_provisioning.py
- 07 — Vault profil berversi dan kontrak tarik/ACK
- 08 — Konfigurasi terpusat, versi penerapan, dan rahasia
- 09 — Jurnal command worker dan outbox event persisten
- 10 — Tarik profil saat startup dan sinkronisasi manual
- 11 — Executor export memakai cursor bersama dan mengarsip state lokal
- TDLClient
- advance_command
- 12 — Supervisor login TDL yang tidak bergantung pada browser
- 13 — Workflow profil upload, login, adopsi, dan distribusi
- PROGRESS.md
- 15 — Bootstrap persisten dan reload client layanan
- 16 — Aksi Quick Mode sebagai operation background
- 17 — Pemeriksaan Storage, Utility, dan target melalui antrean
- 18 — Halaman Profil pulih setelah ditutup
- 19 — Monitor progress terpusat dan refresh berdasarkan aksi
- 20 — Pengaturan Web dengan desired/applied status
- DomainError
- TtsError
- WorkspaceExecutorMixin
- SqliteQueueState
- composition.py
- WorkerContractTests
- register_backups
- parse_tme3_url
- SourceMigrationTests
- 00-OVERVIEW.md
- register_runtime_settings
- register_operations
- devDependencies
- Job
- .__init__
- .test_tor_recovery_restarts_only_the_child_process
- LeaveService
- WorkerEventPublisher
- WorkspaceExplorer.svelte
- AuthServiceTests
- JobLogSnapshot
- decrypt/+page.svelte
- .setUp
- ProfileRegistry
- ._recover_legacy_quick_stages
- .export_from_url
- pindah.py
- inspect_export_json
- .test_helper_state_imports_in_chrome_and_revoke_invalidates_it
- .test_download_progress_callbacks_follow_the_download_lock_owner
- dependencies
- scripts
- .test_build_base_builds_and_exports_only_the_base_image
- svelte.config.js
- register_queue
- .dispatch_command
- @tailwindcss/vite
- ._worker_heartbeat_loop

## God Nodes (most connected - your core abstractions)
1. `DomainError` - 213 edges
2. `create_backend_app()` - 102 edges
3. `StorageCatalog` - 86 edges
4. `SqliteJobRepository` - 85 edges
5. `BackendApiTests` - 83 edges
6. `WorkerJobExecutor` - 83 edges
7. `TelegramFrontendApp` - 76 edges
8. `ControlPlane` - 73 edges
9. `JobEvent` - 69 edges
10. `Job` - 67 edges

## Surprising Connections (you probably didn't know these)
- `_download()` --indirect_call--> `output()`  [INFERRED]
  run.py → tests/test_tdl.py
- `AppMenuTests` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `DomainError`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `BotAuthService`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py

## Import Cycles
- None detected.

## Communities (198 total, 33 thin omitted)

### Community 0 - "QueueTransportTests"
Cohesion: 0.25
Nodes (3): QueueTransportTests, QueueCommandService, Claim and advance an outbox command without running work in a request.

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "BatchDownloadService"
Cohesion: 0.20
Nodes (10): BatchDownloadResult, BatchDownloadService, _is_relative_to(), media_ids_in_export(), Path, Download selected opaque filenames after strict directory validation., Download selected pending/failed JSON files from validated roots., Download one export into a caller-owned staging directory. Quick Mode owns the… (+2 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "JobRepository"
Cohesion: 0.05
Nodes (10): ActorResolver, JobRepository, ProfileStateStore, Any, Protocol, Profile-scoped source state used by export and metadata endpoints., Backend-owned source records with atomic revision-checked commits., SourceRepository (+2 more)

### Community 6 - "BackendRuntimeSettings"
Cohesion: 0.08
Nodes (19): BackendRuntimeSettingsTests, ChannelRefTests, update_backup_settings(), BackendRuntimeSettings, Any, Path, Update fields read by the live backend services without replacing config., Persistent validated settings that can be applied to a live backend. (+11 more)

### Community 7 - "Any"
Cohesion: 0.16
Nodes (7): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), loop()

### Community 8 - "SubprocessRunner"
Cohesion: 0.08
Nodes (14): OutputCallback, ProgressCallback, Queue, notify_command_completed(), notify_command_started(), pause_process_group(), Any, CommandCallback (+6 more)

### Community 9 - "run.py"
Cohesion: 0.18
Nodes (25): active_env_file(), add_profile(), backend_management_request(), data_root_value(), deploy_web(), _download(), ensure_host_subdirs(), ensure_profile_root() (+17 more)

### Community 11 - "create_worker_app"
Cohesion: 0.07
Nodes (23): quick_mode_staging(), create_worker_app(), authorize(), capabilities(), domain_error(), export_profile_bundle(), install_profile_bundle(), job_log_snapshot() (+15 more)

### Community 12 - "ControlPlane"
Cohesion: 0.08
Nodes (19): ControlPlane, Any, Exception, Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job., Attach phase timing and event latency to this job's own event., Restart an export attempt while preserving its stable job ID., Find the original TDL message range without reading the JSON file. New jobs… (+11 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.18
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "executor.py"
Cohesion: 0.08
Nodes (60): bounded_output_tail(), Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Return only the newest output without splitting a line when possible., Redact obvious secret flags and values before persisting a command., sanitize_command(), sanitize_text(), is_tdl_telemetry_line() (+52 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (19): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+11 more)

### Community 17 - "._storage_upload"
Cohesion: 0.16
Nodes (10): StorageWorkerPathTests, Any, Path, Upload workspace files through the worker-local rclone config., StorageExecutorMixin, progress(), Path, Return nested directories, including empty ones, as portable paths. (+2 more)

### Community 18 - "tme3bot/utility.py"
Cohesion: 0.08
Nodes (19): run(), UtilitySettingsTests, UtilitySummaryTests, CommandCallback, Path, Popen, ValueError, Validate a remote destination before it reaches a worker command. (+11 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.14
Nodes (26): PendingInput, backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_compact_markup(), _export_source_picker_markup() (+18 more)

### Community 21 - "ExportService"
Cohesion: 0.25
Nodes (7): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), ExportService, ExportResult

### Community 22 - "QuickModeExecutorMixin"
Cohesion: 0.10
Nodes (22): ExportJobResult, Any, Path, QuickModeExecutorMixin, ensure_not_cancelled(), persist_uploaded_items(), phase_result(), save_manifest() (+14 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.16
Nodes (7): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Telegram presentation adapter and UI-only helpers., Update

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.10
Nodes (19): Arsitektur, Catatan diagnosis produksi terakhir, Checklist memulai sesi baru, Deployment yang benar, Download Manager: aturan penting, graphify, Jebakan, Langkah operasional berikutnya (+11 more)

### Community 26 - "ProfileSessionManager"
Cohesion: 0.19
Nodes (6): build_profile_config(), _LoginProcess, ProfileSessionManager, Any, Path, Narrow TDL login bridge and safe profile session installer for workers.

### Community 27 - "ResourceAwareQueue"
Cohesion: 0.06
Nodes (17): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, ResourceAwareQueueTests, SerialPerKeyQueueTests, handle() (+9 more)

### Community 28 - "backend.py"
Cohesion: 0.08
Nodes (63): BaseModel, register_workers(), remove_worker(), set_worker_enabled(), worker_settings(), ActorResponse, ApiResponse, ApproveChallengeRequest (+55 more)

### Community 29 - "package.json"
Cohesion: 0.11
Nodes (18): bits-ui, crypto-js, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/kit (+10 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (34): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+26 more)

### Community 34 - "OperationsService"
Cohesion: 0.11
Nodes (9): _canonical(), OperationHandler, OperationsService, Any, Protocol, Validates bounded actions and persists them without executing side effects., OperationRepository, Operation (+1 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.14
Nodes (8): ExportArtifactCatalogTests, ExportArtifactCatalog, Any, Connection, Upsert an inventory batch in one SQLite transaction. Inventory can contain…, Mark catalog rows absent when a worker inventory completes., Remove a missing file from the runnable queue. The physical file is already…, utc_now()

### Community 36 - "BackendApiTests"
Cohesion: 0.05
Nodes (3): BackendApiTests, prepare(), FakeProfileProvisioner

### Community 38 - "main"
Cohesion: 0.15
Nodes (22): bootstrap_python_dependencies(), configured_service(), deploy_all(), deploy_application(), ensure_container_profile_dirs(), main(), _pip_supports_flag(), print_preflight_report() (+14 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "TtsPipeline"
Cohesion: 0.13
Nodes (6): Any, Event, Path, Return fixed-slot helper health without exposing configured URLs., Three-route gTTS pipeline with stable per-part checkpoints., TtsPipeline

### Community 43 - "HttpStateStore"
Cohesion: 0.14
Nodes (6): HttpStateStore, normalize_chat_ref(), Any, Canonical source key for usernames, links, phones, and numeric IDs., StateStore-compatible client used by a worker without a local state file., StateSnapshot

### Community 44 - "api.ts"
Cohesion: 0.18
Nodes (10): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+2 more)

### Community 46 - "LabelStore"
Cohesion: 0.25
Nodes (5): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel

### Community 48 - "vitest"
Cohesion: 0.19
Nodes (5): @testing-library/svelte, vitest, publicKey, { apiMock, postMock }, workerSettings

### Community 49 - "preflight_report"
Cohesion: 0.16
Nodes (18): capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), docker_image_exists(), docker_manifest_exists(), git_remote_revision() (+10 more)

### Community 50 - "create_backend_app"
Cohesion: 0.06
Nodes (41): create_backend_app(), adopt_profile(), browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile(), browser_refresh() (+33 more)

### Community 52 - "ProfileProvisioningStore"
Cohesion: 0.15
Nodes (6): _now(), ProfileProvisioningStore, Any, Connection, Path, Persistent encrypted session vault and profile distribution state.

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.10
Nodes (16): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref(), normalize_chat_ref() (+8 more)

### Community 55 - "register_jobs"
Cohesion: 0.06
Nodes (53): ChatReferenceTests, verify_context(), verify_target(), event_dict(), job_dict(), _model_dict(), _newest_first_log_response(), _owned_job() (+45 more)

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - "_add_management_routes"
Cohesion: 0.13
Nodes (5): _add_internal_state_routes(), sync_profiles(), _add_management_routes(), management_start_backup(), FastAPI

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.13
Nodes (7): _now(), Any, Connection, datetime, Path, Run security-sensitive read/modify/write work under a SQLite write lock., SqliteAuthRepository

### Community 59 - "JobEvent"
Cohesion: 0.05
Nodes (11): ControlPlaneTests, FailingDispatcher, FakeDispatcher, FakeProfiles, IncompatibleDispatcher, worker_event(), build_execution_plan(), JobExecutionPlan (+3 more)

### Community 60 - "migrate_source_state.py"
Cohesion: 0.19
Nodes (36): canonical_chat_key(), Canonicalize aliases for source state while preserving legacy keys., apply_plan(), build_plan(), _canonical_json(), _check_input_hashes(), _columns(), _coverage() (+28 more)

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
Cohesion: 0.13
Nodes (5): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore

### Community 65 - "SqliteJobRepository"
Cohesion: 0.07
Nodes (18): JobStoreTests, _dump(), _elapsed_between(), _load(), Any, Connection, datetime, Path (+10 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 69 - "SqliteOperationStore"
Cohesion: 0.12
Nodes (11): OperationTests, _dump(), _load(), _now(), _parse_datetime(), Any, Connection, datetime (+3 more)

### Community 70 - "profiles.py"
Cohesion: 0.11
Nodes (18): normalize_profile_name(), write_json_atomic(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs(), get_profile_download_mode(), profile_settings_path(), ProfileManager (+10 more)

### Community 71 - "test_tts_executor.py"
Cohesion: 0.11
Nodes (7): _Executor, _FakePipeline, _FakeTdl, TtsExecutorTests, Build a portable audio filename from the user-visible TTS title., _truncate_utf8(), tts_delivery_filename()

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.11
Nodes (19): A. Langkah di komputer lokal, B. Build melalui GitHub Actions, Batas keamanan, Bootstrap VPS baru dengan `run.py`, C. Langkah di VPS gateway, Concurrency dan pesan status job, E. Update di setiap VPS worker remote, F. Deploy web static di VPS gateway (+11 more)

### Community 73 - "request_json"
Cohesion: 0.19
Nodes (6): BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Fetch Web-managed Telegram credentials during Telegram role startup., Frontend adapters. They communicate with the backend only through JSON., request_json()

### Community 76 - "5. Pesan status sementara untuk semua job"
Cohesion: 0.33
Nodes (6): 5.1 Komponen, 5.2 Jalur submit, 5.3 Subscription persisten, 5.4 Format message, 5.5 Polling, 5. Pesan status sementara untuk semua job

### Community 77 - "extract.py"
Cohesion: 0.29
Nodes (11): cleanup_empty_directory(), emit_progress(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main() (+3 more)

### Community 79 - "2. Temuan dari kode saat ini"
Cohesion: 0.40
Nodes (5): 2.1 Akar masalah antrean, 2.2 Resource lock saat ini, 2.3 Notifikasi Telegram, 2.4 Source picker, 2. Temuan dari kode saat ini

### Community 81 - "6. Source picker Export Fokus"
Cohesion: 0.40
Nodes (5): 6.1 Inline picker searchable, 6.2 Search dan pagination, 6.3 Callback stabil, 6.4 Mini App fase berikutnya, 6. Source picker Export Fokus

### Community 82 - "TtsPipelineTests"
Cohesion: 0.13
Nodes (3): make_pipeline(), TtsPipelineTests, request_part()

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - "DeviceAuthService"
Cohesion: 0.20
Nodes (10): skipUnless, TrustedDevicePlaywrightHttpsE2ETests, _b64url(), _canonical_origin(), _decode_b64url(), DeviceAuthService, _now(), Any (+2 more)

### Community 85 - ".setUp"
Cohesion: 0.18
Nodes (3): _FakeConnection, _FakeJob, _FakeQueue

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - "QuickThumbnailBuilder"
Cohesion: 0.18
Nodes (9): ProcessStalledError, Raised when a worker subprocess stops making meaningful progress., CommandCallback, Popen, QuickThumbnailBuilder, probe_next_video(), skip_media(), watchdog() (+1 more)

### Community 88 - "register_storage"
Cohesion: 0.11
Nodes (28): StorageLinkTests, _active_storage_item(), _deliver_storage_telegram(), _require_storage_folders_idle(), _storage_item(), register_storage(), create_storage_folder(), delete_storage_item() (+20 more)

### Community 89 - "BackupService"
Cohesion: 0.11
Nodes (12): BackupServiceTests, make_config(), Path, BackupCoordinator, BackupNodeJob, datetime, Worker-neutral command payload for one node backup., BackupArchive (+4 more)

### Community 90 - "Path"
Cohesion: 0.04
Nodes (14): ExportMilestoneTests, export_from_url(), export_from_url(), Path, QuickPipelineTests, download_export_to(), QuickThumbnailTests, fake_run() (+6 more)

### Community 92 - "WorkerJobExecutor"
Cohesion: 0.13
Nodes (4): Executes domain jobs and publishes JSON events; no UI dependency., Bind the shared tracker callback only while owning its TDL lock., WorkerJobExecutor, Framework-independent worker execution adapter.

### Community 93 - "ProgressReporter"
Cohesion: 0.09
Nodes (17): FakePublisher, ProgressReporterTests, Gateway orchestration, channel upload, scheduling, and retention., sha256_file(), _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events. (+9 more)

### Community 94 - "WorkerHttpDispatcher"
Cohesion: 0.17
Nodes (3): Any, RuntimeError, WorkerHttpDispatcher

### Community 95 - "TrustedDeviceError"
Cohesion: 0.07
Nodes (32): FakeProtector, skipUnless, TrustedDeviceHelperTests, protect(), _browser_executable(), main(), open_trusted_context(), same_origin_only() (+24 more)

### Community 96 - "SqliteSourceRepository"
Cohesion: 0.18
Nodes (8): Connection, Path, Row, Read source rows and migration ledger without opening unrelated tables., Apply approved sources and ledger decisions atomically; return replay status., Backend-owned, profile-scoped source state in the application database., SqliteSourceRepository, utc_now_iso()

### Community 97 - "migrate_images"
Cohesion: 0.18
Nodes (14): build_base_archive(), build_base_image(), build_migration_archive(), configured_base_image(), ensure_base_image_available(), find_host_tdl(), login_registry(), migrate_images() (+6 more)

### Community 98 - "ProfileTests"
Cohesion: 0.35
Nodes (3): ProfileTests, Path, build_profile_runtime()

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - "SourceState"
Cohesion: 0.09
Nodes (10): SqliteSourceRepositoryTests, Canonical chat references for TDL commands and Telegram Bot API targets., MigrationPlanConflict, RuntimeError, A source write was based on an outdated revision., A migration plan or one of its optimistic revision checks is stale., StateStore-compatible adapter that binds the shared repository to a profile., SourceRevisionConflict (+2 more)

### Community 101 - "register_utility"
Cohesion: 0.20
Nodes (8): register_utility(), utility_settings_meta(), utility_tree(), SettingRequest, UtilityFolderRequest, UtilityJobRequest, Public metadata for clients; never contains a setting value or secret., utility_setting_specs()

### Community 102 - "P0 — Akses production dari laptop tepercaya"
Cohesion: 0.11
Nodes (17): API perangkat milik actor, Cara verifikasi, Challenge dan signature, File yang disentuh, Helper Windows, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai (+9 more)

### Community 103 - "Rencana pemisahan backend, worker, dan Web"
Cohesion: 0.25
Nodes (8): Arsitektur target, Aturan agent pelaksana, Baseline audit — 2026-10-04, Asia/Jakarta, Cara memakai paket, Gerbang kompatibilitas dan migrasi, Keputusan dan kontrak bersama, Rencana pemisahan backend, worker, dan Web, Urutan dan ketergantungan

### Community 104 - "WorkerRegistry"
Cohesion: 0.06
Nodes (18): WorkerRegistryTests, Path, RuntimeProfileManager, WorkerRuntimeSettingsTests, Any, Path, Atomically write JSON containing secrets with owner-only Unix mode., write_json_atomic_private() (+10 more)

### Community 105 - "DeviceAuthTests"
Cohesion: 0.18
Nodes (3): DeviceAuthTests, actor(), challenge_payload()

### Community 106 - "21 — Penyederhanaan ENV dan inventaris pemakaian"
Cohesion: 0.14
Nodes (13): 21 — Penyederhanaan ENV dan inventaris pemakaian, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Lampiran — inventaris ENV baseline, Penambahan yang direncanakan (+5 more)

### Community 107 - "RcloneRunner"
Cohesion: 0.09
Nodes (13): FakeSubprocessRunner, RcloneRunnerTests, CommandCallback, Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Small, cancellable rclone adapter for files already in the workspace. (+5 more)

### Community 108 - "JsonHttpError"
Cohesion: 0.16
Nodes (8): HTTPRedirectHandler, Any, Reject workers whose advertised API cannot satisfy a backend operation., require_worker_contract(), JsonHttpError, Check worker availability without loading its full capabilities., Keep authenticated profile bundle transfers on the configured URL., _RejectRedirects

### Community 109 - "22 — Uji kegagalan lintas komponen dan panduan cutover"
Cohesion: 0.17
Nodes (11): 22 — Uji kegagalan lintas komponen dan panduan cutover, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 110 - "Arsitektur Sistem tme3bot"
Cohesion: 0.18
Nodes (11): Alur job, Antrean dan kerja bersamaan, Arsitektur Sistem tme3bot, Bagian sistem, Data dan keamanan, Deployment dan source map, Komunikasi backend dan worker, Quick Mode dan folder staging (+3 more)

### Community 113 - "ARSITEKTUR_SISTEM.md"
Cohesion: 0.29
Nodes (4): Aktifkan satu worker untuk uji coba, Pemeriksaan uji coba, Persiapan, TTS Novel: konfigurasi dan rollout

### Community 114 - "tme3bot"
Cohesion: 0.22
Nodes (9): Arsitektur, Build Docker melalui GitHub Actions, Job dan progress, Login web melalui bot, Setup VPS utama, Storage dan backup, tme3bot, Verifikasi (+1 more)

### Community 115 - "ProfileProvisioningTests"
Cohesion: 0.12
Nodes (9): FakeProfileDispatcher, FakeProfileManager, FakeWorkerRegistry, make_config(), MutableWorkerRegistry, ProfileProvisioningTests, Path, single_session_zip() (+1 more)

### Community 118 - "StateStore"
Cohesion: 0.23
Nodes (3): StateStoreTests, Path, StateStore

### Community 119 - "01 — Repository state backend dan pemisahan runtime profil"
Cohesion: 0.17
Nodes (11): 01 — Repository state backend dan pemisahan runtime profil, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

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

### Community 127 - "AppConfig"
Cohesion: 0.40
Nodes (7): configure_logging(), main(), run_backend(), run_queue(), run_worker(), AppConfig, Fail fast when a production role is missing its trust boundary.

### Community 128 - "Pengaturan aplikasi dari Web"
Cohesion: 0.29
Nodes (6): Kontrak implementasi, Pengaturan aplikasi dari Web, Pengaturan deployment, Pengaturan yang sudah ada di Web, Pengelolaan rahasia, Status migrasi konfigurasi

### Community 130 - "02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress"
Cohesion: 0.17
Nodes (11): 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 131 - "03 — Operation persisten dan transactional outbox"
Cohesion: 0.17
Nodes (11): 03 — Operation persisten dan transactional outbox, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 132 - "JobTable.svelte"
Cohesion: 0.15
Nodes (7): normalizeBotApiChatRef(), normalizeTdlChatRef(), if(), describe(), error, icons, label()

### Community 135 - "04 — Redis privat dan proses RQ untuk orkestrasi"
Cohesion: 0.17
Nodes (11): 04 — Redis privat dan proses RQ untuk orkestrasi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 136 - "TtsExecutorMixin"
Cohesion: 0.29
Nodes (4): Any, Path, Keep the opaque artifact for retries, and upload a title-named copy., TtsExecutorMixin

### Community 138 - "tts_helper.py"
Cohesion: 0.24
Nodes (15): get, post, _bootstrap_percent(), diagnostics(), ready(), readyz(), recover_tor(), renew_tor_circuit() (+7 more)

### Community 139 - "QueueOutboxPublisher"
Cohesion: 0.22
Nodes (3): skipUnless, QueueOutboxPublisher, Moves SQLite outbox messages to RQ and repairs missing Redis jobs.

### Community 140 - "05 — Penerimaan cepat dan kontrak dispatch berversi"
Cohesion: 0.17
Nodes (11): 05 — Penerimaan cepat dan kontrak dispatch berversi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 141 - "06 — Alias peer dan serialisasi export lintas worker"
Cohesion: 0.17
Nodes (11): 06 — Alias peer dan serialisasi export lintas worker, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 142 - "test_profile_provisioning.py"
Cohesion: 0.24
Nodes (9): extract_single_session(), profile_bundle_identity(), profile_transfer_is_secure(), Read the Telegram identity embedded in a validated bundle., Allow HTTPS remote workers and explicit internal deployment hosts., Read a ZIP containing exactly one top-level .tdl directory., _safe_zip_entries(), validate_profile_bundle() (+1 more)

### Community 143 - "07 — Vault profil berversi dan kontrak tarik/ACK"
Cohesion: 0.17
Nodes (11): 07 — Vault profil berversi dan kontrak tarik/ACK, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 144 - "08 — Konfigurasi terpusat, versi penerapan, dan rahasia"
Cohesion: 0.17
Nodes (11): 08 — Konfigurasi terpusat, versi penerapan, dan rahasia, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 145 - "09 — Jurnal command worker dan outbox event persisten"
Cohesion: 0.17
Nodes (11): 09 — Jurnal command worker dan outbox event persisten, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 146 - "10 — Tarik profil saat startup dan sinkronisasi manual"
Cohesion: 0.17
Nodes (11): 10 — Tarik profil saat startup dan sinkronisasi manual, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 147 - "11 — Executor export memakai cursor bersama dan mengarsip state lokal"
Cohesion: 0.17
Nodes (11): 11 — Executor export memakai cursor bersama dan mengarsip state lokal, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 148 - "TDLClient"
Cohesion: 0.06
Nodes (40): FakeRunner, TDLClientTests, Create encrypted, runtime-only per-node backup archives., decode_process_output(), _message_contains_caption(), visit(), _normalize_upload_caption(), _byte_multiplier() (+32 more)

### Community 149 - "advance_command"
Cohesion: 0.40
Nodes (5): advance_command(), RuntimeError, QueueAdvanceRetry, A short backend wait; RQ applies the bounded retry policy., Ask the backend to claim and advance one durable command identifier.

### Community 150 - "12 — Supervisor login TDL yang tidak bergantung pada browser"
Cohesion: 0.17
Nodes (11): 12 — Supervisor login TDL yang tidak bergantung pada browser, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 151 - "13 — Workflow profil upload, login, adopsi, dan distribusi"
Cohesion: 0.17
Nodes (11): 13 — Workflow profil upload, login, adopsi, dan distribusi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 152 - "PROGRESS.md"
Cohesion: 0.14
Nodes (12): 14 — Penerapan konfigurasi worker saat aman, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+4 more)

### Community 153 - "15 — Bootstrap persisten dan reload client layanan"
Cohesion: 0.17
Nodes (11): 15 — Bootstrap persisten dan reload client layanan, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 154 - "16 — Aksi Quick Mode sebagai operation background"
Cohesion: 0.17
Nodes (11): 16 — Aksi Quick Mode sebagai operation background, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 155 - "17 — Pemeriksaan Storage, Utility, dan target melalui antrean"
Cohesion: 0.17
Nodes (11): 17 — Pemeriksaan Storage, Utility, dan target melalui antrean, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 156 - "18 — Halaman Profil pulih setelah ditutup"
Cohesion: 0.17
Nodes (11): 18 — Halaman Profil pulih setelah ditutup, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 157 - "19 — Monitor progress terpusat dan refresh berdasarkan aksi"
Cohesion: 0.17
Nodes (11): 19 — Monitor progress terpusat dan refresh berdasarkan aksi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 158 - "20 — Pengaturan Web dengan desired/applied status"
Cohesion: 0.17
Nodes (11): 20 — Pengaturan Web dengan desired/applied status, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 159 - "DomainError"
Cohesion: 0.08
Nodes (37): register_device_routes(), device_challenge(), device_exchange(), list_devices(), register_device(), remote_key(), rename_device(), require_browser_actor() (+29 more)

### Community 160 - "TtsError"
Cohesion: 0.20
Nodes (9): request_part(), normalize_text(), RuntimeError, Split normalized text into word-aware chunks no longer than 90 chars., Request a fresh Tor circuit without logging the control credential., split_text(), _tor_command(), TtsCancelled (+1 more)

### Community 161 - "WorkspaceExecutorMixin"
Cohesion: 0.38
Nodes (4): Any, Path, Return a safe, shallow directory listing for the active workspace., WorkspaceExecutorMixin

### Community 162 - "SqliteQueueState"
Cohesion: 0.26
Nodes (6): _now(), Any, Connection, datetime, Queue-specific SQLite adapter over the durable operation outbox., SqliteQueueState

### Community 163 - "composition.py"
Cohesion: 0.07
Nodes (9): FakeProfiles, FakeTelegramBot, FakeWorkers, BackendContext, WorkerContext, build_backend_context(), ControlPlaneBackupRouter, _first_actor() (+1 more)

### Community 164 - "WorkerContractTests"
Cohesion: 0.19
Nodes (6): patch, ContractWorkerExecutor, ContractWorkerRegistry, WorkerContractTests, Return the non-secret version and feature set advertised by a worker., worker_contract_metadata()

### Community 165 - "register_backups"
Cohesion: 0.40
Nodes (3): register_backups(), start_backup(), BackupRuntimeSettingsRequest

### Community 166 - "parse_tme3_url"
Cohesion: 0.28
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 168 - "00-OVERVIEW.md"
Cohesion: 0.11
Nodes (15): File yang disentuh, Kontrak dan perilaku, Kriteria selesai, P1 — Diagnosis dan pemulihan kesiapan helper TTS, Prasyarat dan konteks, Prompt implementasi, Rollback, Tujuan (+7 more)

### Community 169 - "register_runtime_settings"
Cohesion: 0.40
Nodes (3): register_runtime_settings(), update_runtime_secrets(), RuntimeSecretsRequest

### Community 170 - "register_operations"
Cohesion: 0.49
Nodes (10): register_operations(), api_capabilities(), cancel_operation(), get_operation(), list_operations(), _public(), _require_operations(), retry_operation() (+2 more)

### Community 171 - "devDependencies"
Cohesion: 0.15
Nodes (13): devDependencies, jsdom, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss, @tailwindcss/vite (+5 more)

### Community 172 - "Job"
Cohesion: 0.11
Nodes (22): prepare(), prepare(), _elapsed_since(), datetime, PreparedOperation, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, Job (+14 more)

### Community 174 - ".test_tor_recovery_restarts_only_the_child_process"
Cohesion: 0.12
Nodes (3): skipIf, assert_release(), write_to_fp()

### Community 175 - "LeaveService"
Cohesion: 0.50
Nodes (3): LeaveResult, LeaveService, CommandCallback

### Community 177 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 178 - "AuthServiceTests"
Cohesion: 0.46
Nodes (3): AuthServiceTests, actor(), Path

### Community 179 - "JobLogSnapshot"
Cohesion: 0.20
Nodes (4): CommandMilestoneRecorder, JobLogSnapshot, Bounded raw command output retained with the persistent job history., Persist bounded command results without allowing telemetry to fail work.

### Community 180 - "decrypt/+page.svelte"
Cohesion: 0.20
Nodes (7): copied, decrypt(), encrypted, error, notice, plaintext, readEncryptedValue()

### Community 181 - ".setUp"
Cohesion: 0.17
Nodes (3): FakeDispatcher, FakeProfiles, FakeUtilitySettings

### Community 182 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 185 - ".export_from_url"
Cohesion: 0.21
Nodes (5): is_image_message(), Any, build_telegram_message_url(), Any, ParsedTme3Url

### Community 186 - "pindah.py"
Cohesion: 0.15
Nodes (14): CompletedProcess, skipIf, output(), run(), find_best_combination(), find_best_combination_worker(), load_json(), main() (+6 more)

### Community 187 - "inspect_export_json"
Cohesion: 0.16
Nodes (11): discard_export_without_media(), inspect_export_json(), Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape., Remove an export JSON when its inspected media count is exactly zero. The…, has_downloadable_media(), DownloadExecutorMixin (+3 more)

### Community 188 - ".test_helper_state_imports_in_chrome_and_revoke_invalidates_it"
Cohesion: 0.83
Nodes (3): make_test_certificates(), Path, prepare_state()

### Community 189 - ".test_download_progress_callbacks_follow_the_download_lock_owner"
Cohesion: 0.53
Nodes (5): first_callback(), first_download(), second_callback(), second_download(), runtime()

### Community 190 - "dependencies"
Cohesion: 0.33
Nodes (6): dependencies, bits-ui, crypto-js, flowbite-svelte, @lucide/svelte, svelte

### Community 191 - "scripts"
Cohesion: 0.33
Nodes (6): scripts, build, check, dev, preview, test

## Knowledge Gaps
- **471 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+466 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1284 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **33 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DomainError` connect `DomainError` to `Any`, `.update_worker_settings`, `BackendRuntimeSettings`, `_hash_secret`, `create_worker_app`, `ControlPlane`, `executor.py`, `QuickModeExecutorMixin`, `backend.py`, `OperationsService`, `composition.py`, `WorkerContractTests`, `register_backups`, `register_runtime_settings`, `register_operations`, `Job`, `AuthServiceTests`, `create_backend_app`, `register_jobs`, `_add_management_routes`, `SqliteAuthRepository`, `JobEvent`, `SqliteJobRepository`, `DurableDispatchTests`, `SqliteOperationStore`, `FakeExecutor`, `DeviceAuthService`, `register_storage`, `Path`, `WorkerJobExecutor`, `register_utility`, `WorkerRegistry`, `DeviceAuthTests`, `JsonHttpError`?**
  _High betweenness centrality (0.133) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `Any`, `.update_worker_settings`, `TtsExecutorMixin`, `._capture_tdl_output`, `test_profile_provisioning.py`, `executor.py`, `._storage_upload`, `tme3bot/utility.py`, `TDLClient`, `QuickModeExecutorMixin`, `ProfileSessionManager`, `ResourceAwareQueue`, `DomainError`, `WorkspaceExecutorMixin`, `composition.py`, `WorkerEventPublisher`, `JobLogSnapshot`, `._recover_legacy_quick_stages`, `inspect_export_json`, `._worker_heartbeat_loop`, `test_tts_executor.py`, `QuickThumbnailBuilder`, `Path`, `ProgressReporter`, `WorkerRegistry`, `RcloneRunner`, `ProfileProvisioningTests`, `AppConfig`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `JsonHttpError` connect `JsonHttpError` to `.dispatch_command`, `WorkerContractTests`, `BackendApiTests`, `request_json`, `Job`, `executor.py`, `FakeDispatcher`, `WorkerEventPublisher`, `telegram/app.py`, `TelegramFrontendApp`, `backend.py`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Are the 18 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 35 inferred relationships involving `create_backend_app()` (e.g. with `_active_storage_item()` and `advance_background_job()`) actually correct?**
  _`create_backend_app()` has 35 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `SqliteJobRepository` (e.g. with `BackendApiTests` and `ControlPlaneTests`) actually correct?**
  _`SqliteJobRepository` has 10 INFERRED edges - model-reasoned connections that need verification._