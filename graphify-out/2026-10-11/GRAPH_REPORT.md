# Graph Report - dockter_bot_tdl  (2026-10-11)

## Corpus Check
- 293 files · ~282,412 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: (none) 6, .base 1, .resolver 1)

## Summary
- 4986 nodes · 12296 edges · 228 communities (174 shown, 45 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 845 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `633456cf`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- normalize_profile_name
- pindah4.py
- PanelManager
- worker/profile_sync.py
- organize_media_from_json.py
- Job
- .patch
- Any
- StateStore
- Path
- compress.sh
- tdl.py
- JobEvent
- boltStorage
- format_job_status
- _add_internal_state_routes
- StorageCatalog
- WorkerRuntimeSettings
- UtilityRunner
- compilerOptions
- telegram/app.py
- ControlPlane
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
- test_backend_api.py
- ExportArtifactCatalog
- BackendApiTests
- ProfileProvisioningService
- main
- +layout.ts
- 8. Urutan implementasi
- TtsPipeline
- source_store.py
- api.ts
- RunScriptTests
- parse_tme3_url
- vitest
- run.py
- models.py
- test_pindah.py
- ProfileProvisioningStore
- ExportWorkspaceState
- executor.py
- register_jobs
- 12. Bootstrap VPS baru dan satu-command deployment
- SqliteSourceRepository
- SqliteAuthRepository
- verify_profile_backup
- migrate_source_state.py
- job-progress.ts
- WorkerHttpDispatcher
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- service.py
- SqliteOperationStore
- WorkerEventPublisher
- executor_tts.py
- TME3Bot Deployment Runbook
- request_json
- ../styles.css
- ArchitectureBoundaryTests
- 5. Pesan status sementara untuk semua job
- normalize_tdl_chat_ref
- infrastructure/__init__.py
- 2. Temuan dari kode saat ini
- FakeExecutor
- 6. Source picker Export Fokus
- TtsPipelineTests
- 3. Keputusan desain
- SqliteSettingsStore
- DeviceAuthService
- build.py
- WorkerProfileSyncTests
- .setUp
- ProfileSyncClient
- Path
- ContainerBuildTests
- compact_channel_ref
- SqliteProfileStateStore
- utc_now
- TrustedDeviceError
- inspect_export_json
- register_tts
- ProgressReporter
- pkg_resources.py
- register_workers
- test_worker_shared_cursor.py
- P0 — Akses production dari laptop tepercaya
- Rencana pemisahan backend, worker, dan Web
- WorkerCommandStore
- SharedExportCursorTests
- 21 — Penyederhanaan ENV dan inventaris pemakaian
- WorkerJobExecutor
- SqliteTdlAccessStore
- 22 — Uji kegagalan lintas komponen dan panduan cutover
- Arsitektur Sistem tme3bot
- routes/__init__.py
- JsonHttpError
- ARSITEKTUR_SISTEM.md
- tme3bot
- ProfileProvisioningTests
- tests/__init__.py
- test-setup.ts
- ExportCursorService
- 01 — Repository state backend dan pemisahan runtime profil
- FakeStatusPanel
- D. Menambah worker remote baru
- Rekomendasi berikutnya
- Autentikasi GitHub dan GHCR
- Update berikutnya
- Context target per fitur dan Download global
- Rollback
- ProfileRegistry
- Pengaturan aplikasi dari Web
- ControlPlaneTests
- 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress
- 03 — Operation persisten dan transactional outbox
- ProfileTests
- AppConfig
- composition.py
- 04 — Redis privat dan proses RQ untuk orkestrasi
- TtsExecutorMixin
- Perombakan Profil Lokal dan Vault
- tts_helper.py
- safelink_resolver.py
- 05 — Penerimaan cepat dan kontrak dispatch berversi
- 06 — Alias peer dan serialisasi export lintas worker
- TDLClient
- 07 — Vault profil berversi dan kontrak tarik/ACK
- 08 — Konfigurasi terpusat, versi penerapan, dan rahasia
- 09 — Jurnal command worker dan outbox event persisten
- 10 — Tarik profil saat startup dan sinkronisasi manual
- 11 — Executor export memakai cursor bersama dan mengarsip state lokal
- WorkerCommandStoreTests
- DeviceAuthTests
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
- FakeProfileProvisioner
- WorkspaceExecutorMixin
- DurableDispatchTests
- FakeWorkers
- WorkerContractTests
- BackendRuntimeSettings
- SourceMigrationTests
- .test_export_resolves_leases_and_commits_before_json_ready
- 00-OVERVIEW.md
- ._capture_tdl_output
- register_operations
- devDependencies
- HttpStateStore
- ProfileSyncContractTests
- .test_tor_recovery_restarts_only_the_child_process
- BotAuthService
- .test_download_progress_callbacks_follow_the_download_lock_owner
- WorkerProfileAdmissionTests
- UtilitySettingsStore
- QueueTransportTests
- decrypt/+page.svelte
- register_runtime_settings
- .setUp
- DownloadProgressTracker
- ._recover_legacy_quick_stages
- pindah.py
- http_client.py
- SqliteQueueState
- ProfilesPage.svelte
- AuthServiceTests
- BackupCoordinator
- QueueOutboxPublisher
- .dispatch_command
- .__init__
- AesGcmSecretStore
- backend_management_request
- presentation.ts
- test_profile_provisioning.py
- TtsError
- FakeDiagnosticStore
- worker/__init__.py
- WorkerCommandRunner
- deploy_web
- .__init__
- test_trusted_device_browser_e2e.py
- UtilityFolderStore
- Issue tracker: GitHub
- Overview.svelte
- register_queue
- Domain Docs
- triage-labels.md
- test_worker_command_store.py
- settings_store.py
- FakeProfiles
- Verifikasi sesi TDL dan arsip backup untuk canary
- Profil dan Sesi TDL
- dependencies
- scripts
- bootstrap_python_dependencies
- .test_build_base_builds_and_exports_only_the_base_image
- svelte.config.js
- @tailwindcss/vite

## God Nodes (most connected - your core abstractions)
1. `DomainError` - 277 edges
2. `WorkerJobExecutor` - 123 edges
3. `create_backend_app()` - 119 edges
4. `BackendApiTests` - 99 edges
5. `ControlPlane` - 99 edges
6. `SqliteJobRepository` - 91 edges
7. `StorageCatalog` - 86 edges
8. `ProfileProvisioningStore` - 79 edges
9. `TelegramFrontendApp` - 76 edges
10. `Job` - 73 edges

## Surprising Connections (you probably didn't know these)
- `AppMenuTests` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `DomainError`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `BotAuthService`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `AuthServiceTests` --uses--> `SqliteAuthRepository`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py

## Import Cycles
- None detected.

## Communities (228 total, 45 thin omitted)

### Community 0 - "normalize_profile_name"
Cohesion: 0.09
Nodes (20): normalize_profile_name(), build_profile_config(), ProfileManager, Path, Metadata a worker can safely publish to the backend registry., Return source state without constructing profile TDL clients., Return stable locks shared by every runtime and diagnostic for a profile., Resolve the actual TDL session paths without loading state or creating files. (+12 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "worker/profile_sync.py"
Cohesion: 0.13
Nodes (18): _header(), hmac_compare(), _positive_int(), _ProfileSyncCancelled, emit(), ProfileSyncError, Any, Exception (+10 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory(), entry_identity() (+50 more)

### Community 5 - "Job"
Cohesion: 0.05
Nodes (13): prepare(), prepare(), ActorResolver, JobRepository, ProfileStateStore, Any, Protocol, Profile-scoped source state used by export and metadata endpoints. (+5 more)

### Community 6 - ".patch"
Cohesion: 0.11
Nodes (13): FakeSubprocessRunner, RcloneRunnerTests, CommandCallback, Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Small, cancellable rclone adapter for files already in the workspace. (+5 more)

### Community 7 - "Any"
Cohesion: 0.16
Nodes (8): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), main_menu_markup(), edit_menu_message()

### Community 8 - "StateStore"
Cohesion: 0.16
Nodes (10): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), StateStoreTests, ExportService, Path (+2 more)

### Community 9 - "Path"
Cohesion: 0.16
Nodes (19): add_profile(), build_base_archive(), build_base_image(), build_migration_archive(), configured_base_image(), configured_service(), ensure_container_profile_dirs(), ensure_host_subdirs() (+11 more)

### Community 11 - "tdl.py"
Cohesion: 0.06
Nodes (33): OutputCallback, ProgressCallback, Queue, BackupArchive, Create encrypted, runtime-only per-node backup archives., safe_node_name(), utc_now(), notify_command_completed() (+25 more)

### Community 12 - "JobEvent"
Cohesion: 0.14
Nodes (6): JobStoreTests, Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job., Attach phase timing and event latency to this job's own event., Framework-independent domain model for the tme3bot control plane., JobEvent

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.18
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "_add_internal_state_routes"
Cohesion: 0.10
Nodes (14): _add_internal_state_routes(), acquire_export_cursor(), commit_export_cursor(), confirm_peer_alias(), heartbeat_export_cursor(), pending_peer_aliases(), require_cursor_service(), resolve_export_peer() (+6 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.05
Nodes (23): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, BackupService (+15 more)

### Community 17 - "WorkerRuntimeSettings"
Cohesion: 0.11
Nodes (7): Path, RuntimeProfileManager, WorkerRuntimeSettingsTests, Any, Path, Persistent allowlisted worker options that can be changed through Web., WorkerRuntimeSettings

### Community 18 - "UtilityRunner"
Cohesion: 0.11
Nodes (10): UtilitySummaryTests, pause_process_group(), CommandCallback, Path, Popen, Remove the two intermediate JSON files produced by ``pindah``. ``pindah4.py``…, UtilityPathError, UtilityRunner (+2 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.15
Nodes (22): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_compact_markup() (+14 more)

### Community 21 - "ControlPlane"
Cohesion: 0.08
Nodes (13): ControlPlane, Any, Exception, Resume queued commands after backend restart or terminal events., Cancel jobs whose worker has stopped reporting progress. Worker cancellation is…, Release only the Quick Mode export phase after durable completion., Restart an export attempt while preserving its stable job ID., Find the original TDL message range without reading the JSON file. New jobs… (+5 more)

### Community 22 - "QuickModeExecutorMixin"
Cohesion: 0.09
Nodes (23): ExportJobResult, Any, Path, QuickModeExecutorMixin, ensure_not_cancelled(), persist_uploaded_items(), phase_result(), save_manifest() (+15 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.18
Nodes (6): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.08
Nodes (23): Agent skills, Arsitektur, Catatan diagnosis produksi terakhir, Checklist memulai sesi baru, Deployment yang benar, Domain docs, Download Manager: aturan penting, graphify (+15 more)

### Community 26 - "ProfileSessionManager"
Cohesion: 0.08
Nodes (22): make_config(), ProfileTdlDiagnosticsTests, fake_run(), fake_run(), Path, _LoginProcess, ProfileSessionManager, Any (+14 more)

### Community 27 - "ResourceAwareQueue"
Cohesion: 0.06
Nodes (17): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, ResourceAwareQueueTests, SerialPerKeyQueueTests, handle() (+9 more)

### Community 28 - "backend.py"
Cohesion: 0.09
Nodes (57): register_storage(), create_storage_folder(), purge_storage_item(), storage_browser(), ActorResponse, ApiResponse, ApproveChallengeRequest, BatchSourcesRequest (+49 more)

### Community 29 - "package.json"
Cohesion: 0.11
Nodes (18): bits-ui, crypto-js, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/kit (+10 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.05
Nodes (43): patch(), post(), if(), accessIdempotencyKey(), chooseScope(), clearSelection(), createFolder(), createOpen (+35 more)

### Community 34 - "test_backend_api.py"
Cohesion: 0.07
Nodes (21): prepare(), OperationTests, _FakeConnection, _FakeJob, _FakeQueue, prepare_profile_sync_operation(), _canonical(), OperationHandler (+13 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.13
Nodes (9): ExportArtifactCatalogTests, ExportArtifactCatalog, Any, Connection, Idempotently record an export artifact before its shared cursor commits., Upsert an inventory batch in one SQLite transaction. Inventory can contain…, Mark catalog rows absent when a worker inventory completes., Remove a missing file from the runnable queue. The physical file is already… (+1 more)

### Community 38 - "main"
Cohesion: 0.18
Nodes (23): compose_files_for_target(), deploy_all(), deploy_application(), ensure_base_image_available(), ensure_profile_root(), login_registry(), main(), manage_backup() (+15 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "TtsPipeline"
Cohesion: 0.13
Nodes (6): Any, Event, Path, Return fixed-slot helper health without exposing configured URLs., Three-route gTTS pipeline with stable per-part checkpoints., TtsPipeline

### Community 43 - "source_store.py"
Cohesion: 0.15
Nodes (16): Application service for verified peer aliases and shared export cursors., normalize_peer_identity(), Normalize a TDL-resolved peer identity before it enters the alias map. A…, ExportCursorBusy, MigrationPlanConflict, PeerAliasConflict, PeerAliasCursorConflict, PeerAliasNotFound (+8 more)

### Community 44 - "api.ts"
Cohesion: 0.08
Nodes (20): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+12 more)

### Community 46 - "parse_tme3_url"
Cohesion: 0.13
Nodes (11): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, parse_tme3_url(), ValueError (+3 more)

### Community 48 - "vitest"
Cohesion: 0.19
Nodes (5): @testing-library/svelte, vitest, publicKey, { apiMock, postMock }, workerSettings

### Community 49 - "run.py"
Cohesion: 0.19
Nodes (21): capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), data_root_value(), docker_image_exists(), docker_manifest_exists() (+13 more)

### Community 50 - "models.py"
Cohesion: 0.03
Nodes (31): WorkerApiTests, ContractWorkerExecutor, WorkerJobRequest, create_worker_app(), accept_command(), authorize(), diagnose_profile_export(), diagnose_profile_tdl() (+23 more)

### Community 52 - "ProfileProvisioningStore"
Cohesion: 0.09
Nodes (8): _now(), ProfileProvisioningStore, Any, Connection, Path, Row, Persistent encrypted session vault and profile distribution state., Keep old worker identity reports as adoption candidates, never as vault data.

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.09
Nodes (18): ExportWorkspaceTests, delete_quick_mode_staging(), loop(), export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate() (+10 more)

### Community 54 - "executor.py"
Cohesion: 0.06
Nodes (69): StorageWorkerPathTests, bounded_output_tail(), Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Return only the newest output without splitting a line when possible., Redact obvious secret flags and values before persisting a command., sanitize_command(), sanitize_text() (+61 more)

### Community 55 - "register_jobs"
Cohesion: 0.07
Nodes (42): verify_context(), verify_target(), event_dict(), job_dict(), _model_dict(), _newest_first_log_response(), _owned_job(), Any (+34 more)

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - "SqliteSourceRepository"
Cohesion: 0.14
Nodes (8): Connection, Row, Apply approved sources and ledger decisions atomically; return replay status., Keep cross-worker execution gated until workers implement the contract., Backend-owned, profile-scoped source state in the application database., SqliteSourceRepository, utc_now_iso(), SourceState

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.13
Nodes (7): _now(), Any, Connection, datetime, Path, Run security-sensitive read/modify/write work under a SQLite write lock., SqliteAuthRepository

### Community 59 - "verify_profile_backup"
Cohesion: 0.07
Nodes (35): FakeArchive, ProfileBackupVerifierTests, factory(), Exception, skipUnless, WrongPasswordError, _archive_failure(), _archive_names() (+27 more)

### Community 60 - "migrate_source_state.py"
Cohesion: 0.18
Nodes (36): canonical_chat_key(), Canonicalize aliases for source state while preserving legacy keys., apply_plan(), build_plan(), _canonical_json(), _check_input_hashes(), _columns(), _coverage() (+28 more)

### Community 61 - "job-progress.ts"
Cohesion: 0.22
Nodes (10): eventLatency, phaseElapsedSeconds, phaseLabel(), stageId, clampPercent(), formatDuration(), JobLike, NormalizedProgress (+2 more)

### Community 62 - "WorkerHttpDispatcher"
Cohesion: 0.14
Nodes (5): worker_profile_sync_status(), Any, RuntimeError, Check worker availability without loading its full capabilities., WorkerHttpDispatcher

### Community 63 - "session.svelte.ts"
Cohesion: 0.10
Nodes (10): challenge, contextRevision, current, loading, loadWorkers(), selectedWorkers(), session, SessionWorker (+2 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.11
Nodes (8): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore, help_text(), Text helpers owned by the Telegram presentation adapter., source_digest()

### Community 65 - "SqliteJobRepository"
Cohesion: 0.08
Nodes (19): _dump(), _elapsed_between(), _load(), Any, Connection, Path, Row, _quick_mode_sql() (+11 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 68 - "service.py"
Cohesion: 0.10
Nodes (19): _FakeTdlClient, has_downloadable_media(), is_image_message(), Any, BatchDownloadResult, BatchDownloadService, build_telegram_message_url(), DownloadedJsonResult (+11 more)

### Community 69 - "SqliteOperationStore"
Cohesion: 0.12
Nodes (13): OperationRepository, Operation, Any, _dump(), _load(), _now(), _parse_datetime(), Any (+5 more)

### Community 70 - "WorkerEventPublisher"
Cohesion: 0.11
Nodes (3): Enable durable event delivery while retaining legacy test adapters., Seed event numbering for a reused job ID., WorkerEventPublisher

### Community 71 - "executor_tts.py"
Cohesion: 0.12
Nodes (7): _Executor, _FakePipeline, _FakeTdl, TtsExecutorTests, Build a portable audio filename from the user-visible TTS title., _truncate_utf8(), tts_delivery_filename()

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.10
Nodes (20): A. Langkah di komputer lokal, B. Build melalui GitHub Actions, Batas keamanan, Bootstrap VPS baru dengan `run.py`, Build dan pull image bertahap, C. Langkah di VPS gateway, Concurrency dan pesan status job, E. Update di setiap VPS worker remote (+12 more)

### Community 73 - "request_json"
Cohesion: 0.19
Nodes (6): BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Fetch Web-managed Telegram credentials during Telegram role startup., Frontend adapters. They communicate with the backend only through JSON., request_json()

### Community 76 - "5. Pesan status sementara untuk semua job"
Cohesion: 0.33
Nodes (6): 5.1 Komponen, 5.2 Jalur submit, 5.3 Subscription persisten, 5.4 Format message, 5.5 Polling, 5. Pesan status sementara untuk semua job

### Community 77 - "normalize_tdl_chat_ref"
Cohesion: 0.08
Nodes (23): ChatReferenceTests, _profile_artifact(), register_downloads(), archive_artifact(), clear_failed(), delete_artifact_file(), delete_artifacts_batch(), list_artifacts() (+15 more)

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

### Community 84 - "SqliteSettingsStore"
Cohesion: 0.15
Nodes (14): _json(), _now(), Any, Connection, Row, ValueError, Import a legacy snapshot once; existing rows and tombstones always win., Import one online worker's local runtime JSON at most once. (+6 more)

### Community 85 - "DeviceAuthService"
Cohesion: 0.25
Nodes (8): _b64url(), _canonical_origin(), _decode_b64url(), DeviceAuthService, _now(), Any, datetime, Approved public-key devices that can mint ordinary Web sessions.

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - "WorkerProfileSyncTests"
Cohesion: 0.16
Nodes (5): bundle_for(), FakeSessions, FakeTransport, manifest_row(), WorkerProfileSyncTests

### Community 88 - ".setUp"
Cohesion: 0.08
Nodes (27): FakeTelegramBot, StorageLinkTests, _active_storage_item(), BackendContext, _deliver_storage_telegram(), _require_storage_folders_idle(), _storage_item(), FastAPI adapters for public and internal JSON contracts. (+19 more)

### Community 89 - "ProfileSyncClient"
Cohesion: 0.13
Nodes (7): _now(), ProfileSyncClient, Start one background pull on worker startup without blocking API boot., Synchronize inline for a durable profile.sync worker operation., Cancel a queued sync, or ask an active sync to stop at a safe point., Fetch, verify, safely install, and ACK backend-owned profile revisions., Report a worker-side stage for a vault-initiated bundle install.

### Community 90 - "Path"
Cohesion: 0.03
Nodes (24): ExportMilestoneTests, export_from_url(), export_from_url(), Path, QuickPipelineTests, download_export_to(), run(), QuickThumbnailTests (+16 more)

### Community 92 - "compact_channel_ref"
Cohesion: 0.17
Nodes (10): ChannelRefTests, update_backup_settings(), Update fields read by the live backend services without replacing config., channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`… (+2 more)

### Community 93 - "SqliteProfileStateStore"
Cohesion: 0.10
Nodes (5): SqliteSourceRepositoryTests, StateStore-compatible adapter that binds the shared repository to a profile., A source write was based on an outdated revision., SourceRevisionConflict, SqliteProfileStateStore

### Community 94 - "utc_now"
Cohesion: 0.11
Nodes (5): datetime, utc_now(), Event, Exception, Keep backend liveness independent from noisy subprocess output. A Quick Mode…

### Community 95 - "TrustedDeviceError"
Cohesion: 0.07
Nodes (32): FakeProtector, skipUnless, TrustedDeviceHelperTests, protect(), _browser_executable(), main(), open_trusted_context(), same_origin_only() (+24 more)

### Community 96 - "inspect_export_json"
Cohesion: 0.16
Nodes (10): discard_export_without_media(), inspect_export_json(), Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape., Remove an export JSON when its inspected media count is exactly zero. The…, DownloadExecutorMixin, progress_event() (+2 more)

### Community 97 - "register_tts"
Cohesion: 0.15
Nodes (14): register_tts(), cancel_tts_delivery(), complete_tts_delivery(), complete_worker_tts_delivery(), list_tts_workers(), set_tts_telegram_readiness(), submit_tts(), tts_artifacts_ready() (+6 more)

### Community 98 - "ProgressReporter"
Cohesion: 0.05
Nodes (30): FakePublisher, ProgressReporterTests, TdlAccessWorkerTests, TdlWriteDenialTests, _VerifyExecutor, sha256_file(), _progress_percent(), ProgressReporter (+22 more)

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - "register_workers"
Cohesion: 0.15
Nodes (16): register_workers(), recover_worker_tts_helper(), remove_worker(), set_worker_enabled(), tts_worker_error(), update_worker(), update_worker_settings(), worker_settings() (+8 more)

### Community 101 - "test_worker_shared_cursor.py"
Cohesion: 0.18
Nodes (7): WorkerSharedCursorTests, __init__(), commit(), __init__(), RuntimeError, Sanitized error returned by the authenticated backend state client., StateApiError

### Community 102 - "P0 — Akses production dari laptop tepercaya"
Cohesion: 0.11
Nodes (17): API perangkat milik actor, Cara verifikasi, Challenge dan signature, File yang disentuh, Helper Windows, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai (+9 more)

### Community 103 - "Rencana pemisahan backend, worker, dan Web"
Cohesion: 0.25
Nodes (8): Arsitektur target, Aturan agent pelaksana, Baseline audit — 2026-10-04, Asia/Jakarta, Cara memakai paket, Gerbang kompatibilitas dan migrasi, Keputusan dan kontrak bersama, Rencana pemisahan backend, worker, dan Web, Urutan dan ketergantungan

### Community 104 - "WorkerCommandStore"
Cohesion: 0.21
Nodes (6): _dump(), _now(), Any, Row, SQLite journal kept on the worker's persistent data volume., WorkerCommandStore

### Community 105 - "SharedExportCursorTests"
Cohesion: 0.10
Nodes (5): FailingCatalog, SharedExportCursorTests, current_actor(), Path, Read source rows and migration ledger without opening unrelated tables.

### Community 106 - "21 — Penyederhanaan ENV dan inventaris pemakaian"
Cohesion: 0.14
Nodes (13): 21 — Penyederhanaan ENV dan inventaris pemakaian, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Lampiran — inventaris ENV baseline, Penambahan yang direncanakan (+5 more)

### Community 107 - "WorkerJobExecutor"
Cohesion: 0.09
Nodes (7): Any, Path, Executes domain jobs and publishes JSON events; no UI dependency., Bind the shared tracker callback only while owning its TDL lock., Open each configured TDL session read-only under its normal profile locks., Return non-secret worker capabilities for backend target checks., WorkerJobExecutor

### Community 108 - "SqliteTdlAccessStore"
Cohesion: 0.18
Nodes (7): TdlAccessStoreTests, Any, Connection, Path, Persist destination-specific sender checks and per-target rotation state., _safe_error_code(), SqliteTdlAccessStore

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
Cohesion: 0.10
Nodes (9): FakeProfileDispatcher, FakeProfileManager, FakeWorkerRegistry, make_config(), MutableWorkerRegistry, ProfileProvisioningTests, Path, single_session_zip() (+1 more)

### Community 118 - "ExportCursorService"
Cohesion: 0.15
Nodes (3): ExportCursorService, Any, Keep peer resolution, lease fencing, and artifact/cursor commit ordered. The…

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

### Community 127 - "ProfileRegistry"
Cohesion: 0.22
Nodes (6): ProfileRegistry, Path, One-way migration for installations created before the registry., Gateway-owned registry for profile metadata, separate from TDL sessions. A…, Apply backend vault identity as authoritative registry data., Accept only new legacy metadata; do not let a worker rewrite identity.

### Community 128 - "Pengaturan aplikasi dari Web"
Cohesion: 0.29
Nodes (6): Kontrak implementasi, Pengaturan aplikasi dari Web, Pengaturan deployment, Pengaturan yang sudah ada di Web, Pengelolaan rahasia, Status migrasi konfigurasi

### Community 129 - "ControlPlaneTests"
Cohesion: 0.03
Nodes (22): ControlPlaneTests, FailingDispatcher, FakeDispatcher, FakeExportCursorGate, FakeJobSecretStore, FakeProfiles, IncompatibleDispatcher, WorkerRegistryTests (+14 more)

### Community 130 - "02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress"
Cohesion: 0.17
Nodes (11): 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 131 - "03 — Operation persisten dan transactional outbox"
Cohesion: 0.17
Nodes (11): 03 — Operation persisten dan transactional outbox, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 133 - "AppConfig"
Cohesion: 0.17
Nodes (17): RLock, AppConfig, Fail fast when a production role is missing its trust boundary., LeaveResult, LeaveService, CommandCallback, write_json_atomic(), build_profile_runtime() (+9 more)

### Community 134 - "composition.py"
Cohesion: 0.11
Nodes (11): configure_logging(), main(), build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, run_backend(), run_queue() (+3 more)

### Community 135 - "04 — Redis privat dan proses RQ untuk orkestrasi"
Cohesion: 0.17
Nodes (11): 04 — Redis privat dan proses RQ untuk orkestrasi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 136 - "TtsExecutorMixin"
Cohesion: 0.26
Nodes (4): Any, Path, Keep the opaque artifact for retries, and upload a title-named copy., TtsExecutorMixin

### Community 137 - "Perombakan Profil Lokal dan Vault"
Cohesion: 0.12
Nodes (16): 1. Lindungi dan pulihkan profil lokal, 2. Adopsi dan distribusi sebagai kandidat vault, 3. Aktivasi, update, dan fallback, 4. Job, verifikasi, dan diagnosis, Arsitektur target, Cara menjalankan pekerjaan dengan skills, Diagnosis lokal awal — 2026-10-11, Kondisi berhenti (+8 more)

### Community 138 - "tts_helper.py"
Cohesion: 0.16
Nodes (16): get(), healthz(), _bootstrap_percent(), diagnostics(), post, ready(), readyz(), recover_tor() (+8 more)

### Community 139 - "safelink_resolver.py"
Cohesion: 0.05
Nodes (58): Client, Response, ResolverAddonTests, _livewire_page(), _public_dns(), ResolverHttpTests, handler(), handler() (+50 more)

### Community 140 - "05 — Penerimaan cepat dan kontrak dispatch berversi"
Cohesion: 0.17
Nodes (11): 05 — Penerimaan cepat dan kontrak dispatch berversi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 141 - "06 — Alias peer dan serialisasi export lintas worker"
Cohesion: 0.17
Nodes (11): 06 — Alias peer dan serialisasi export lintas worker, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 142 - "TDLClient"
Cohesion: 0.07
Nodes (19): FakeRunner, CompletedProcess, TDLClientTests, decode_process_output(), _message_contains_caption(), visit(), _normalize_upload_caption(), Any (+11 more)

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

### Community 149 - "DeviceAuthTests"
Cohesion: 0.18
Nodes (3): DeviceAuthTests, actor(), challenge_payload()

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
Cohesion: 0.04
Nodes (79): create_backend_app(), adopt_profile(), advance_accepted_operation(), advance_background_job(), advance_cancel_operation(), advance_retry_operation(), browser_actor_dict(), browser_challenge() (+71 more)

### Community 161 - "WorkspaceExecutorMixin"
Cohesion: 0.38
Nodes (4): Any, Path, Return a safe, shallow directory listing for the active workspace., WorkspaceExecutorMixin

### Community 164 - "WorkerContractTests"
Cohesion: 0.27
Nodes (5): patch, ContractWorkerRegistry, WorkerContractTests, Return the non-secret version and feature set advertised by a worker., worker_contract_metadata()

### Community 165 - "BackendRuntimeSettings"
Cohesion: 0.36
Nodes (5): BackendRuntimeSettings, Any, Path, Persistent validated settings that can be applied to a live backend., Use the backend-owned SQLite registry after its one-time legacy import.

### Community 168 - "00-OVERVIEW.md"
Cohesion: 0.11
Nodes (15): File yang disentuh, Kontrak dan perilaku, Kriteria selesai, P1 — Diagnosis dan pemulihan kesiapan helper TTS, Prasyarat dan konteks, Prompt implementasi, Rollback, Tujuan (+7 more)

### Community 170 - "register_operations"
Cohesion: 0.49
Nodes (10): register_operations(), api_capabilities(), cancel_operation(), get_operation(), list_operations(), _public(), _require_operations(), retry_operation() (+2 more)

### Community 171 - "devDependencies"
Cohesion: 0.15
Nodes (13): devDependencies, jsdom, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss, @tailwindcss/vite (+5 more)

### Community 172 - "HttpStateStore"
Cohesion: 0.14
Nodes (7): HttpStateStore, normalize_chat_ref(), Any, Canonical source key for usernames, links, phones, and numeric IDs., StateStore-compatible client used by a worker without a local state file., StateSnapshot, Advertise cursor support only when authenticated backend state is configured.

### Community 174 - ".test_tor_recovery_restarts_only_the_child_process"
Cohesion: 0.12
Nodes (3): skipIf, assert_release(), write_to_fp()

### Community 175 - "BotAuthService"
Cohesion: 0.25
Nodes (6): AuthChallengeStatus, Enum, str, BotAuthService, _hash_secret(), TokenPair

### Community 176 - ".test_download_progress_callbacks_follow_the_download_lock_owner"
Cohesion: 0.53
Nodes (5): first_callback(), first_download(), second_callback(), second_download(), runtime()

### Community 178 - "UtilitySettingsStore"
Cohesion: 0.14
Nodes (3): DesiredSettingsTests, UtilitySettingsTests, UtilitySettingsStore

### Community 179 - "QueueTransportTests"
Cohesion: 0.25
Nodes (3): QueueTransportTests, QueueCommandService, Claim and advance an outbox command without running work in a request.

### Community 180 - "decrypt/+page.svelte"
Cohesion: 0.08
Nodes (23): copied, decrypt(), encrypted, error, loadResolverJobs(), notice, plaintext, plaintextLink (+15 more)

### Community 182 - "register_runtime_settings"
Cohesion: 0.09
Nodes (28): register_backups(), register_runtime_settings(), acknowledge_worker_settings(), desired_store(), get_runtime_settings(), put_runtime_settings(), runtime_settings_schema(), update_runtime_secrets() (+20 more)

### Community 183 - ".setUp"
Cohesion: 0.14
Nodes (4): FakeDispatcher, FakeProfiles, FakeUtilitySettings, FakeWorkerRegistry

### Community 186 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 187 - "http_client.py"
Cohesion: 0.15
Nodes (11): Any, Reject workers whose advertised API cannot satisfy a backend operation., require_worker_contract(), HTTPRedirectHandler, Keep authenticated profile bundle transfers on the configured URL., _RejectRedirects, advance_command(), RuntimeError (+3 more)

### Community 188 - "SqliteQueueState"
Cohesion: 0.23
Nodes (6): _now(), Any, Connection, datetime, Queue-specific SQLite adapter over the durable operation outbox., SqliteQueueState

### Community 189 - "ProfilesPage.svelte"
Cohesion: 0.25
Nodes (7): load(), profileNeedsRepair(), refreshOperation(), submitUpload(), syncLogMessage(), syncOperationFor(), syncPhaseLabel()

### Community 190 - "AuthServiceTests"
Cohesion: 0.46
Nodes (3): AuthServiceTests, actor(), Path

### Community 191 - "BackupCoordinator"
Cohesion: 0.10
Nodes (8): BackendRuntimeSettingsTests, BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., Recheck enabled state or the schedule after a Web update.

### Community 192 - "QueueOutboxPublisher"
Cohesion: 0.24
Nodes (3): skipUnless, QueueOutboxPublisher, Moves SQLite outbox messages to RQ and repairs missing Redis jobs.

### Community 195 - "AesGcmSecretStore"
Cohesion: 0.18
Nodes (4): AesGcmSecretStore, Path, Encrypt setting values with a persistent owner-only AES-256 key., Path

### Community 196 - "backend_management_request"
Cohesion: 0.29
Nodes (7): active_env_file(), backend_management_request(), load_env_file(), manage_workers(), merge_env_file(), parse_env_line(), parse_env_value()

### Community 198 - "presentation.ts"
Cohesion: 0.42
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 199 - "test_profile_provisioning.py"
Cohesion: 0.21
Nodes (9): extract_single_session(), profile_bundle_identity(), profile_transfer_is_secure(), Read the Telegram identity embedded in a validated bundle., Allow HTTPS remote workers and explicit internal Compose service hosts., Read a ZIP containing exactly one top-level .tdl directory., _safe_zip_entries(), validate_profile_bundle() (+1 more)

### Community 200 - "TtsError"
Cohesion: 0.20
Nodes (9): request_part(), normalize_text(), RuntimeError, Split normalized text into word-aware chunks no longer than 90 chars., Request a fresh Tor circuit without logging the control credential., split_text(), _tor_command(), TtsCancelled (+1 more)

### Community 205 - "deploy_web"
Cohesion: 0.22
Nodes (9): deploy_web(), _download(), _github_repository(), hmac_compare(), Install a GitHub-built static UI without installing Node on the target., _safe_extract_tar(), skipIf, output() (+1 more)

### Community 209 - "test_trusted_device_browser_e2e.py"
Cohesion: 0.43
Nodes (5): make_test_certificates(), Path, skipUnless, TrustedDevicePlaywrightHttpsE2ETests, prepare_state()

### Community 211 - "Issue tracker: GitHub"
Cohesion: 0.33
Nodes (5): Conventions, Issue tracker: GitHub, Publishing and fetching, Pull requests as a triage surface, Wayfinding operations

### Community 212 - "Overview.svelte"
Cohesion: 0.25
Nodes (4): describe(), error, icons, label()

### Community 215 - "Domain Docs"
Cohesion: 0.50
Nodes (3): Before exploring, Domain Docs, Layout

### Community 219 - "settings_store.py"
Cohesion: 0.26
Nodes (9): Any, Path, Atomically write JSON containing secrets with owner-only Unix mode., write_json_atomic_private(), ValueError, Validate a remote destination before it reaches a worker command., _validate_password(), validate_rclone_destination() (+1 more)

### Community 221 - "Verifikasi sesi TDL dan arsip backup untuk canary"
Cohesion: 0.50
Nodes (3): Diagnosis sesi pada worker, Verifikasi arsip backup yang diunduh manual, Verifikasi sesi TDL dan arsip backup untuk canary

### Community 225 - "dependencies"
Cohesion: 0.33
Nodes (6): dependencies, bits-ui, crypto-js, flowbite-svelte, @lucide/svelte, svelte

### Community 227 - "scripts"
Cohesion: 0.33
Nodes (6): scripts, build, check, dev, preview, test

### Community 228 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

## Knowledge Gaps
- **517 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+512 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1566 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **45 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DomainError` connect `DomainError` to `ControlPlaneTests`, `Job`, `JobEvent`, `_add_internal_state_routes`, `WorkerRuntimeSettings`, `WorkerCommandStoreTests`, `DeviceAuthTests`, `ControlPlane`, `QuickModeExecutorMixin`, `backend.py`, `test_backend_api.py`, `DurableDispatchTests`, `WorkerContractTests`, `register_operations`, `source_store.py`, `ProfileSyncContractTests`, `BotAuthService`, `models.py`, `ExportWorkspaceState`, `executor.py`, `register_jobs`, `register_runtime_settings`, `SqliteAuthRepository`, `http_client.py`, `AuthServiceTests`, `WorkerHttpDispatcher`, `SqliteOperationStore`, `normalize_tdl_chat_ref`, `FakeExecutor`, `DeviceAuthService`, `.setUp`, `test_worker_command_store.py`, `Path`, `compact_channel_ref`, `register_tts`, `register_workers`, `WorkerCommandStore`, `SharedExportCursorTests`, `WorkerJobExecutor`?**
  _High betweenness centrality (0.104) - this node is a cross-community bridge._
- **Why does `JsonHttpError` connect `JsonHttpError` to `.dispatch_command`, `test_backend_api.py`, `register_workers`, `WorkerContractTests`, `BackendApiTests`, `WorkerEventPublisher`, `request_json`, `models.py`, `telegram/app.py`, `executor.py`, `TelegramFrontendApp`, `http_client.py`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `normalize_profile_name`, `worker/profile_sync.py`, `composition.py`, `.patch`, `TtsExecutorMixin`, `safelink_resolver.py`, `TDLClient`, `WorkerRuntimeSettings`, `UtilityRunner`, `QuickModeExecutorMixin`, `ProfileSessionManager`, `ResourceAwareQueue`, `DomainError`, `WorkspaceExecutorMixin`, `WorkerContractTests`, `._capture_tdl_output`, `HttpStateStore`, `WorkerProfileAdmissionTests`, `models.py`, `executor.py`, `._recover_legacy_quick_stages`, `WorkerEventPublisher`, `test_profile_provisioning.py`, `executor_tts.py`, `worker/__init__.py`, `.commit_profile_bundle`, `WorkerCommandRunner`, `ProfileSyncClient`, `Path`, `utc_now`, `inspect_export_json`, `ProgressReporter`, `test_worker_shared_cursor.py`, `WorkerCommandStore`, `ProfileProvisioningTests`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 32 inferred relationships involving `WorkerJobExecutor` (e.g. with `ProfileProvisioningTests` and `ProfileTdlDiagnosticsTests`) actually correct?**
  _`WorkerJobExecutor` has 32 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `create_backend_app()` (e.g. with `_active_storage_item()` and `advance_accepted_operation()`) actually correct?**
  _`create_backend_app()` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `BackendApiTests` (e.g. with `BackendContext` and `ControlPlane`) actually correct?**
  _`BackendApiTests` has 23 INFERRED edges - model-reasoned connections that need verification._