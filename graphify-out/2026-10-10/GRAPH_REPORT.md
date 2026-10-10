# Graph Report - dockter_bot_tdl  (2026-10-10)

## Corpus Check
- 285 files · ~274,847 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: (none) 6, .base 1, .resolver 1)

## Summary
- 4869 nodes · 12045 edges · 223 communities (183 shown, 31 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 829 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ce46e508`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ProfileManager
- pindah4.py
- PanelManager
- worker/profile_sync.py
- organize_media_from_json.py
- Job
- .patch
- Any
- StateStore
- run.py
- compress.sh
- tdl.py
- ControlPlane
- boltStorage
- format_job_status
- .test_export_resolves_leases_and_commits_before_json_ready
- StorageCatalog
- WorkerRuntimeSettings
- UtilityRunner
- compilerOptions
- telegram/app.py
- inspect_export_json
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
- composition.py
- ExportArtifactCatalog
- BackendApiTests
- ProfileProvisioningService
- main
- +layout.ts
- 8. Urutan implementasi
- TtsPipeline
- SourceState
- api.ts
- RunScriptTests
- LabelStore
- vitest
- preflight_report
- create_worker_app
- test_pindah.py
- ProfileProvisioningStore
- ExportWorkspaceState
- executor.py
- register_jobs
- 12. Bootstrap VPS baru dan satu-command deployment
- SqliteSourceRepository
- SqliteAuthRepository
- test_profile_sync_contract.py
- migrate_source_state.py
- JobTable.svelte
- WorkerHttpDispatcher
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- BatchDownloadService
- SqliteOperationStore
- WorkerEventPublisher
- _Executor
- TME3Bot Deployment Runbook
- BackendApiClient
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
- SqliteSettingsStore
- DeviceAuthService
- build.py
- JobEvent
- register_storage
- BackupService
- Path
- ContainerBuildTests
- config.py
- OperationsService
- SubprocessRunner
- TrustedDeviceError
- quick_export.py
- DomainError
- ProgressReporter
- pkg_resources.py
- register_downloads
- WorkerProfileSyncTests
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
- FakeDispatcher
- ARSITEKTUR_SISTEM.md
- tme3bot
- ProfileProvisioningTests
- tests/__init__.py
- QuickModePage.svelte
- ExportCursorService
- 01 — Repository state backend dan pemisahan runtime profil
- FakeStatusPanel
- D. Menambah worker remote baru
- Rekomendasi berikutnya
- Autentikasi GitHub dan GHCR
- Update berikutnya
- Context target per fitur dan Download global
- Rollback
- normalize_profile_name
- Pengaturan aplikasi dari Web
- WorkerRegistry
- 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress
- 03 — Operation persisten dan transactional outbox
- ProfileTests
- profiles.py
- QueueTransportTests
- 04 — Redis privat dan proses RQ untuk orkestrasi
- TtsExecutorMixin
- TDLClient
- tts_helper.py
- safelink_resolver.py
- 05 — Penerimaan cepat dan kontrak dispatch berversi
- 06 — Alias peer dan serialisasi export lintas worker
- .resolve_chat_peer
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
- create_backend_app
- FakeProfileProvisioner
- WorkspaceExecutorMixin
- DurableDispatchTests
- .setUp
- WorkerContractTests
- OperationTests
- WorkerApiTests
- ProfileSyncClient
- 00-OVERVIEW.md
- source_store.py
- register_operations
- devDependencies
- HttpStateStore
- ProfileSyncContractTests
- .test_tor_recovery_restarts_only_the_child_process
- BotAuthService
- AppConfig
- WorkspaceExplorer.svelte
- UtilitySettingsStore
- QueueOutboxPublisher
- decrypt/+page.svelte
- ObjectResponse
- register_runtime_settings
- .setUp
- DownloadProgressTracker
- ._validate
- pindah.py
- http_client.py
- TDLCommandError
- ProfilesPage.svelte
- AuthServiceTests
- BackendRuntimeSettings
- ProfileSyncError
- SourceMigrationTests
- normalize_tdl_chat_ref
- settings_store.py
- parse_tme3_url
- presentation.ts
- test_profile_provisioning.py
- executor_tts.py
- FakeDiagnosticStore
- test_worker_profile_sync.py
- WorkerSharedCursorTests
- WorkerCommandRunner
- .test_subprocess_runner_freezes_and_resumes_current_process
- ProfileRuntime
- _add_management_routes
- ProfileSelectionStore
- test_trusted_device_browser_e2e.py
- UtilityFolderStore
- Issue tracker: GitHub
- .test_download_progress_callbacks_follow_the_download_lock_owner
- FakeProfiles
- Domain Docs
- triage-labels.md
- build_base_image
- bootstrap_python_dependencies

## God Nodes (most connected - your core abstractions)
1. `DomainError` - 276 edges
2. `create_backend_app()` - 119 edges
3. `WorkerJobExecutor` - 119 edges
4. `BackendApiTests` - 99 edges
5. `ControlPlane` - 99 edges
6. `SqliteJobRepository` - 91 edges
7. `StorageCatalog` - 86 edges
8. `ProfileProvisioningStore` - 79 edges
9. `TelegramFrontendApp` - 76 edges
10. `Job` - 73 edges

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

## Communities (223 total, 31 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.12
Nodes (14): build_profile_config(), ProfileManager, Path, Metadata a worker can safely publish to the backend registry., Return source state without constructing profile TDL clients., Refresh cached session paths after a locked install or rollback., Resolve the session path, including a legacy default-profile location., Check an initialized local TDL session without creating runtime files. (+6 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "worker/profile_sync.py"
Cohesion: 0.20
Nodes (12): profile_bundle_identity(), Read the Telegram identity embedded in a validated bundle., _header(), hmac_compare(), _now(), _positive_int(), emit(), Any (+4 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory(), entry_identity() (+50 more)

### Community 5 - "Job"
Cohesion: 0.05
Nodes (16): prepare(), prepare(), Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job., Attach phase timing and event latency to this job's own event., ActorResolver, JobRepository, ProfileStateStore (+8 more)

### Community 6 - ".patch"
Cohesion: 0.09
Nodes (14): FakeSubprocessRunner, RcloneRunnerTests, TdlAccessWorkerTests, _VerifyExecutor, Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them. (+6 more)

### Community 7 - "Any"
Cohesion: 0.16
Nodes (8): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), main_menu_markup(), edit_menu_message()

### Community 8 - "StateStore"
Cohesion: 0.16
Nodes (10): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), StateStoreTests, ExportService, Path (+2 more)

### Community 9 - "run.py"
Cohesion: 0.16
Nodes (27): active_env_file(), add_profile(), backend_management_request(), build_migration_archive(), configured_service(), data_root_value(), deploy_web(), _download() (+19 more)

### Community 11 - "tdl.py"
Cohesion: 0.09
Nodes (29): Queue, has_downloadable_media(), is_image_message(), Any, media_ids_in_export(), Any, _byte_multiplier(), clean_tdl_output_line() (+21 more)

### Community 12 - "ControlPlane"
Cohesion: 0.08
Nodes (13): ControlPlane, Any, Exception, Resume queued commands after backend restart or terminal events., Cancel jobs whose worker has stopped reporting progress. Worker cancellation is…, Release only the Quick Mode export phase after durable completion., Restart an export attempt while preserving its stable job ID., Find the original TDL message range without reading the JSON file. New jobs… (+5 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.18
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (19): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+11 more)

### Community 17 - "WorkerRuntimeSettings"
Cohesion: 0.12
Nodes (7): Path, RuntimeProfileManager, WorkerRuntimeSettingsTests, Any, Path, Persistent allowlisted worker options that can be changed through Web., WorkerRuntimeSettings

### Community 18 - "UtilityRunner"
Cohesion: 0.13
Nodes (8): UtilitySummaryTests, CommandCallback, Path, Popen, Remove the two intermediate JSON files produced by ``pindah``. ``pindah4.py``…, UtilityRunner, consume_line(), watchdog()

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.15
Nodes (22): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_compact_markup() (+14 more)

### Community 21 - "inspect_export_json"
Cohesion: 0.18
Nodes (10): discard_export_without_media(), inspect_export_json(), Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape., Remove an export JSON when its inspected media count is exactly zero. The…, DownloadExecutorMixin, progress_event() (+2 more)

### Community 22 - "QuickModeExecutorMixin"
Cohesion: 0.08
Nodes (29): Any, Path, QuickModeExecutorMixin, ensure_not_cancelled(), persist_uploaded_items(), phase_result(), save_manifest(), verify_log() (+21 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.18
Nodes (6): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.08
Nodes (23): Agent skills, Arsitektur, Catatan diagnosis produksi terakhir, Checklist memulai sesi baru, Deployment yang benar, Domain docs, Download Manager: aturan penting, graphify (+15 more)

### Community 26 - "ProfileSessionManager"
Cohesion: 0.17
Nodes (7): _LoginProcess, ProfileSessionManager, Any, Path, Check whether a legacy profile can be exported without reading session contents., Check identity and both private Bolt session trees without opening Bolt., Narrow TDL login bridge and safe profile session installer for workers.

### Community 27 - "ResourceAwareQueue"
Cohesion: 0.06
Nodes (17): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, ResourceAwareQueueTests, SerialPerKeyQueueTests, handle() (+9 more)

### Community 28 - "backend.py"
Cohesion: 0.06
Nodes (73): StorageLinkTests, register_sources(), add_label(), get_source(), update_source(), register_workers(), remove_worker(), set_worker_enabled() (+65 more)

### Community 29 - "package.json"
Cohesion: 0.05
Nodes (33): bits-ui, crypto-js, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static (+25 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.05
Nodes (42): patch(), post(), accessIdempotencyKey(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName (+34 more)

### Community 34 - "composition.py"
Cohesion: 0.08
Nodes (28): prepare(), BackendContext, _elapsed_since(), datetime, serializable(), Application services and use cases., build_execution_plan(), JobExecutionPlan (+20 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.13
Nodes (9): ExportArtifactCatalogTests, ExportArtifactCatalog, Any, Connection, Idempotently record an export artifact before its shared cursor commits., Upsert an inventory batch in one SQLite transaction. Inventory can contain…, Mark catalog rows absent when a worker inventory completes., Remove a missing file from the runnable queue. The physical file is already… (+1 more)

### Community 38 - "main"
Cohesion: 0.22
Nodes (20): compose_files_for_target(), deploy_all(), deploy_application(), ensure_profile_root(), main(), manage_backup(), merge_env_file(), migrate_images() (+12 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "TtsPipeline"
Cohesion: 0.13
Nodes (6): Any, Event, Path, Return fixed-slot helper health without exposing configured URLs., Three-route gTTS pipeline with stable per-part checkpoints., TtsPipeline

### Community 43 - "SourceState"
Cohesion: 0.13
Nodes (4): SqliteSourceRepositoryTests, StateStore-compatible adapter that binds the shared repository to a profile., SqliteProfileStateStore, SourceState

### Community 44 - "api.ts"
Cohesion: 0.13
Nodes (14): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+6 more)

### Community 45 - "RunScriptTests"
Cohesion: 0.06
Nodes (3): call(), RunScriptTests, fake_docker()

### Community 46 - "LabelStore"
Cohesion: 0.25
Nodes (5): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel

### Community 48 - "vitest"
Cohesion: 0.18
Nodes (5): @testing-library/svelte, vitest, publicKey, { apiMock, postMock }, workerSettings

### Community 49 - "preflight_report"
Cohesion: 0.14
Nodes (20): capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), docker_image_exists(), docker_manifest_exists(), git_remote_revision() (+12 more)

### Community 50 - "create_worker_app"
Cohesion: 0.06
Nodes (26): WorkerJobRequest, create_worker_app(), accept_command(), authorize(), diagnose_profile_export(), domain_error(), durable_command_status(), export_profile_bundle() (+18 more)

### Community 52 - "ProfileProvisioningStore"
Cohesion: 0.09
Nodes (8): _now(), ProfileProvisioningStore, Any, Connection, Path, Row, Persistent encrypted session vault and profile distribution state., Keep old worker identity reports as adoption candidates, never as vault data.

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.09
Nodes (18): ExportWorkspaceTests, delete_quick_mode_staging(), loop(), export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate() (+10 more)

### Community 54 - "executor.py"
Cohesion: 0.07
Nodes (40): StorageWorkerPathTests, BackupArchive, Create encrypted, runtime-only per-node backup archives., safe_node_name(), sha256_file(), utc_now(), bounded_output_tail(), Safe, bounded command output helpers used by worker milestones. (+32 more)

### Community 55 - "register_jobs"
Cohesion: 0.07
Nodes (42): verify_context(), verify_target(), event_dict(), job_dict(), _model_dict(), _newest_first_log_response(), _owned_job(), Any (+34 more)

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - "SqliteSourceRepository"
Cohesion: 0.13
Nodes (9): normalize_peer_identity(), Normalize a TDL-resolved peer identity before it enters the alias map. A…, Connection, Row, Apply approved sources and ledger decisions atomically; return replay status., Keep cross-worker execution gated until workers implement the contract., Backend-owned, profile-scoped source state in the application database., SqliteSourceRepository (+1 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.13
Nodes (7): _now(), Any, Connection, datetime, Path, Run security-sensitive read/modify/write work under a SQLite write lock., SqliteAuthRepository

### Community 59 - "test_profile_sync_contract.py"
Cohesion: 0.12
Nodes (21): advance_accepted_operation(), advance_background_job(), advance_cancel_operation(), advance_retry_operation(), advance_profile_sync_cancel(), advance_profile_sync_command(), _complete_sync_operation(), prepare_profile_sync_operation() (+13 more)

### Community 60 - "migrate_source_state.py"
Cohesion: 0.18
Nodes (36): canonical_chat_key(), Canonicalize aliases for source state while preserving legacy keys., apply_plan(), build_plan(), _canonical_json(), _check_input_hashes(), _columns(), _coverage() (+28 more)

### Community 61 - "JobTable.svelte"
Cohesion: 0.17
Nodes (11): eventLatency, phaseElapsedSeconds, phaseLabel(), stageId, if(), clampPercent(), formatDuration(), JobLike (+3 more)

### Community 62 - "WorkerHttpDispatcher"
Cohesion: 0.14
Nodes (7): worker_profile_sync_status(), Any, RuntimeError, Send a durable command using a stable ID and reconcile lost ACKs., request_json(), WorkerHttpDispatcher, current_receipt()

### Community 63 - "session.svelte.ts"
Cohesion: 0.09
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

### Community 68 - "BatchDownloadService"
Cohesion: 0.14
Nodes (11): BatchDownloadResult, BatchDownloadService, build_telegram_message_url(), _is_relative_to(), Path, Download selected opaque filenames after strict directory validation., Download selected pending/failed JSON files from validated roots., Download one export into a caller-owned staging directory. Quick Mode owns the… (+3 more)

### Community 69 - "SqliteOperationStore"
Cohesion: 0.12
Nodes (13): OperationRepository, Operation, Any, _dump(), _load(), _now(), _parse_datetime(), Any (+5 more)

### Community 70 - "WorkerEventPublisher"
Cohesion: 0.06
Nodes (8): Admit durable worker commands into the existing resource-aware queue., Durable worker command journal and progress-event outbox., CommandMilestoneRecorder, Persist bounded command results without allowing telemetry to fail work., Create the pending milestone before a subprocess begins work., Enable durable event delivery while retaining legacy test adapters., Seed event numbering for a reused job ID., WorkerEventPublisher

### Community 71 - "_Executor"
Cohesion: 0.11
Nodes (7): _Executor, _FakePipeline, _FakeTdl, TtsExecutorTests, Build a portable audio filename from the user-visible TTS title., _truncate_utf8(), tts_delivery_filename()

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.10
Nodes (20): A. Langkah di komputer lokal, B. Build melalui GitHub Actions, Batas keamanan, Bootstrap VPS baru dengan `run.py`, Build dan pull image bertahap, C. Langkah di VPS gateway, Concurrency dan pesan status job, E. Update di setiap VPS worker remote (+12 more)

### Community 73 - "BackendApiClient"
Cohesion: 0.15
Nodes (5): BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Fetch Web-managed Telegram credentials during Telegram role startup., Frontend adapters. They communicate with the backend only through JSON.

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
Cohesion: 0.12
Nodes (3): make_pipeline(), TtsPipelineTests, request_part()

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - "SqliteSettingsStore"
Cohesion: 0.19
Nodes (11): _json(), _now(), Any, Connection, Row, Import a legacy snapshot once; existing rows and tombstones always win., Import one online worker's local runtime JSON at most once., Backend-owned desired settings, encrypted secrets, ACKs and audit metadata. (+3 more)

### Community 85 - "DeviceAuthService"
Cohesion: 0.25
Nodes (8): _b64url(), _canonical_origin(), _decode_b64url(), DeviceAuthService, _now(), Any, datetime, Approved public-key devices that can mint ordinary Web sessions.

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - "JobEvent"
Cohesion: 0.07
Nodes (4): ControlPlaneTests, FakeExportCursorGate, JobStoreTests, JobEvent

### Community 88 - "register_storage"
Cohesion: 0.13
Nodes (24): _active_storage_item(), _deliver_storage_telegram(), _require_storage_folders_idle(), _storage_item(), register_storage(), create_storage_folder(), delete_storage_item(), deliver_public_storage_deep_link() (+16 more)

### Community 89 - "BackupService"
Cohesion: 0.12
Nodes (11): BackupServiceTests, make_config(), Path, BackupCoordinator, BackupNodeJob, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup. (+3 more)

### Community 90 - "Path"
Cohesion: 0.04
Nodes (29): ExportMilestoneTests, export_from_url(), export_from_url(), Path, QuickPipelineTests, download_export_to(), run(), QuickThumbnailTests (+21 more)

### Community 92 - "config.py"
Cohesion: 0.17
Nodes (10): ChannelRefTests, update_backup_settings(), Update fields read by the live backend services without replacing config., channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`… (+2 more)

### Community 93 - "OperationsService"
Cohesion: 0.15
Nodes (6): _canonical(), OperationHandler, OperationsService, Any, Protocol, Validates bounded actions and persists them without executing side effects.

### Community 94 - "SubprocessRunner"
Cohesion: 0.12
Nodes (5): OutputCallback, ProgressCallback, CommandCallback, Popen, SubprocessRunner

### Community 95 - "TrustedDeviceError"
Cohesion: 0.07
Nodes (32): FakeProtector, skipUnless, TrustedDeviceHelperTests, protect(), _browser_executable(), main(), open_trusted_context(), same_origin_only() (+24 more)

### Community 96 - "quick_export.py"
Cohesion: 0.07
Nodes (33): notify_command_completed(), notify_command_started(), pause_process_group(), ProcessStalledError, CommandCallback, Notify an observer without making telemetry a process dependency. New observers…, Notify completion, supporting both new and legacy command observers., Raised when a worker subprocess stops making meaningful progress. (+25 more)

### Community 97 - "DomainError"
Cohesion: 0.07
Nodes (45): _add_internal_state_routes(), acquire_export_cursor(), commit_export_cursor(), confirm_peer_alias(), heartbeat_export_cursor(), pending_peer_aliases(), require_cursor_service(), resolve_export_peer() (+37 more)

### Community 98 - "ProgressReporter"
Cohesion: 0.08
Nodes (18): BaseException, FakePublisher, ProgressReporterTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed. (+10 more)

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - "register_downloads"
Cohesion: 0.17
Nodes (14): _profile_artifact(), register_downloads(), archive_artifact(), clear_failed(), delete_artifact_file(), delete_artifacts_batch(), list_artifacts(), purge_artifact() (+6 more)

### Community 101 - "WorkerProfileSyncTests"
Cohesion: 0.24
Nodes (3): bundle_for(), manifest_row(), WorkerProfileSyncTests

### Community 102 - "P0 — Akses production dari laptop tepercaya"
Cohesion: 0.11
Nodes (17): API perangkat milik actor, Cara verifikasi, Challenge dan signature, File yang disentuh, Helper Windows, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai (+9 more)

### Community 103 - "Rencana pemisahan backend, worker, dan Web"
Cohesion: 0.25
Nodes (8): Arsitektur target, Aturan agent pelaksana, Baseline audit — 2026-10-04, Asia/Jakarta, Cara memakai paket, Gerbang kompatibilitas dan migrasi, Keputusan dan kontrak bersama, Rencana pemisahan backend, worker, dan Web, Urutan dan ketergantungan

### Community 104 - "WorkerCommandStore"
Cohesion: 0.19
Nodes (7): _dump(), _now(), Any, Path, Row, SQLite journal kept on the worker's persistent data volume., WorkerCommandStore

### Community 105 - "SharedExportCursorTests"
Cohesion: 0.10
Nodes (5): FailingCatalog, SharedExportCursorTests, current_actor(), Path, Read source rows and migration ledger without opening unrelated tables.

### Community 106 - "21 — Penyederhanaan ENV dan inventaris pemakaian"
Cohesion: 0.14
Nodes (13): 21 — Penyederhanaan ENV dan inventaris pemakaian, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Lampiran — inventaris ENV baseline, Penambahan yang direncanakan (+5 more)

### Community 107 - "WorkerJobExecutor"
Cohesion: 0.04
Nodes (16): WorkerProfileAdmissionTests, Any, Event, Exception, Path, Executes domain jobs and publishes JSON events; no UI dependency., Keep backend liveness independent from noisy subprocess output. A Quick Mode…, Bind the shared tracker callback only while owning its TDL lock. (+8 more)

### Community 108 - "SqliteTdlAccessStore"
Cohesion: 0.19
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
Cohesion: 0.11
Nodes (9): FakeProfileDispatcher, FakeProfileManager, FakeWorkerRegistry, make_config(), MutableWorkerRegistry, ProfileProvisioningTests, Path, single_session_zip() (+1 more)

### Community 117 - "QuickModePage.svelte"
Cohesion: 0.16
Nodes (4): normalizeBotApiChatRef(), normalizeTdlChatRef(), clear(), length()

### Community 118 - "ExportCursorService"
Cohesion: 0.16
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

### Community 127 - "normalize_profile_name"
Cohesion: 0.20
Nodes (7): normalize_profile_name(), ProfileRegistry, Path, One-way migration for installations created before the registry., Gateway-owned registry for profile metadata, separate from TDL sessions. A…, Apply backend vault identity as authoritative registry data., Accept only new legacy metadata; do not let a worker rewrite identity.

### Community 128 - "Pengaturan aplikasi dari Web"
Cohesion: 0.29
Nodes (6): Kontrak implementasi, Pengaturan aplikasi dari Web, Pengaturan deployment, Pengaturan yang sudah ada di Web, Pengelolaan rahasia, Status migrasi konfigurasi

### Community 129 - "WorkerRegistry"
Cohesion: 0.07
Nodes (11): FailingDispatcher, FakeDispatcher, FakeJobSecretStore, IncompatibleDispatcher, WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path (+3 more)

### Community 130 - "02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress"
Cohesion: 0.17
Nodes (11): 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 131 - "03 — Operation persisten dan transactional outbox"
Cohesion: 0.17
Nodes (11): 03 — Operation persisten dan transactional outbox, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 132 - "ProfileTests"
Cohesion: 0.29
Nodes (4): ProfileTests, Path, build_profile_runtime(), set_profile_download_mode()

### Community 133 - "profiles.py"
Cohesion: 0.18
Nodes (12): Any, Path, Atomically write JSON containing secrets with owner-only Unix mode., write_json_atomic(), write_json_atomic_private(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs() (+4 more)

### Community 134 - "QueueTransportTests"
Cohesion: 0.09
Nodes (7): _FakeConnection, _FakeJob, _FakeQueue, QueueTransportTests, register_queue(), QueueCommandService, Claim and advance an outbox command without running work in a request.

### Community 135 - "04 — Redis privat dan proses RQ untuk orkestrasi"
Cohesion: 0.17
Nodes (11): 04 — Redis privat dan proses RQ untuk orkestrasi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 136 - "TtsExecutorMixin"
Cohesion: 0.26
Nodes (4): Any, Path, Keep the opaque artifact for retries, and upload a title-named copy., TtsExecutorMixin

### Community 137 - "TDLClient"
Cohesion: 0.15
Nodes (4): FakeRunner, TDLClientTests, decode_process_output(), TDLClient

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

### Community 142 - ".resolve_chat_peer"
Cohesion: 0.15
Nodes (14): _message_contains_caption(), visit(), _normalize_upload_caption(), Any, CompletedProcess, Path, RuntimeError, Raised when TDL returns unusable or malformed export data. (+6 more)

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

### Community 159 - "create_backend_app"
Cohesion: 0.06
Nodes (43): create_backend_app(), adopt_profile(), browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile(), browser_refresh() (+35 more)

### Community 161 - "WorkspaceExecutorMixin"
Cohesion: 0.38
Nodes (4): Any, Path, Return a safe, shallow directory listing for the active workspace., WorkspaceExecutorMixin

### Community 163 - ".setUp"
Cohesion: 0.10
Nodes (3): FakeProfiles, FakeTelegramBot, FakeWorkers

### Community 164 - "WorkerContractTests"
Cohesion: 0.15
Nodes (8): patch, ContractWorkerExecutor, ContractWorkerRegistry, WorkerContractTests, WorkerContext, Return the non-secret version and feature set advertised by a worker., worker_contract_metadata(), JsonHttpError

### Community 167 - "ProfileSyncClient"
Cohesion: 0.15
Nodes (6): ProfileSyncClient, Start one background pull on worker startup without blocking API boot., Synchronize inline for a durable profile.sync worker operation., Cancel a queued sync, or ask an active sync to stop at a safe point., Fetch, verify, safely install, and ACK backend-owned profile revisions., Report a worker-side stage for a vault-initiated bundle install.

### Community 168 - "00-OVERVIEW.md"
Cohesion: 0.11
Nodes (15): File yang disentuh, Kontrak dan perilaku, Kriteria selesai, P1 — Diagnosis dan pemulihan kesiapan helper TTS, Prasyarat dan konteks, Prompt implementasi, Rollback, Tujuan (+7 more)

### Community 169 - "source_store.py"
Cohesion: 0.15
Nodes (16): Application service for verified peer aliases and shared export cursors., ExportCursorBusy, MigrationPlanConflict, PeerAliasConflict, PeerAliasCursorConflict, PeerAliasNotFound, RuntimeError, A source write was based on an outdated revision. (+8 more)

### Community 170 - "register_operations"
Cohesion: 0.49
Nodes (10): register_operations(), api_capabilities(), cancel_operation(), get_operation(), list_operations(), _public(), _require_operations(), retry_operation() (+2 more)

### Community 171 - "devDependencies"
Cohesion: 0.15
Nodes (13): devDependencies, jsdom, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss, @tailwindcss/vite (+5 more)

### Community 172 - "HttpStateStore"
Cohesion: 0.12
Nodes (10): HttpStateStore, normalize_chat_ref(), Any, RuntimeError, Sanitized error returned by the authenticated backend state client., Canonical source key for usernames, links, phones, and numeric IDs., StateStore-compatible client used by a worker without a local state file., StateApiError (+2 more)

### Community 174 - ".test_tor_recovery_restarts_only_the_child_process"
Cohesion: 0.12
Nodes (3): skipIf, assert_release(), write_to_fp()

### Community 175 - "BotAuthService"
Cohesion: 0.32
Nodes (3): BotAuthService, _hash_secret(), TokenPair

### Community 176 - "AppConfig"
Cohesion: 0.40
Nodes (7): configure_logging(), main(), run_backend(), run_queue(), run_worker(), AppConfig, Fail fast when a production role is missing its trust boundary.

### Community 177 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 178 - "UtilitySettingsStore"
Cohesion: 0.13
Nodes (4): DesiredSettingsTests, UtilitySettingsTests, SettingsConflict, UtilitySettingsStore

### Community 179 - "QueueOutboxPublisher"
Cohesion: 0.12
Nodes (9): skipUnless, _now(), Any, Connection, datetime, QueueOutboxPublisher, Moves SQLite outbox messages to RQ and repairs missing Redis jobs., Queue-specific SQLite adapter over the durable operation outbox. (+1 more)

### Community 180 - "decrypt/+page.svelte"
Cohesion: 0.08
Nodes (23): copied, decrypt(), encrypted, error, loadResolverJobs(), notice, plaintext, plaintextLink (+15 more)

### Community 181 - "ObjectResponse"
Cohesion: 0.14
Nodes (13): register_backups(), register_utility(), utility_settings_meta(), utility_tree(), BackupRuntimeSettingsRequest, ItemListResponse, ObjectResponse, Typed object envelope for small mutation/settings responses. (+5 more)

### Community 182 - "register_runtime_settings"
Cohesion: 0.23
Nodes (13): register_runtime_settings(), acknowledge_worker_settings(), desired_store(), get_runtime_settings(), put_runtime_settings(), runtime_settings_schema(), update_runtime_secrets(), validate_target() (+5 more)

### Community 183 - ".setUp"
Cohesion: 0.14
Nodes (4): FakeDispatcher, FakeProfiles, FakeUtilitySettings, FakeWorkerRegistry

### Community 185 - "._validate"
Cohesion: 0.20
Nodes (8): ValueError, Encrypt a backend-only, job-pinned secret such as a TTS recipient., ValueError, Validate a remote destination before it reaches a worker command., UtilityPathError, _validate_password(), validate_rclone_destination(), _validate_size()

### Community 186 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 187 - "http_client.py"
Cohesion: 0.10
Nodes (15): profile_management(), Any, Reject workers whose advertised API cannot satisfy a backend operation., require_worker_contract(), HTTPRedirectHandler, Check worker availability without loading its full capabilities., Keep authenticated profile bundle transfers on the configured URL., _RejectRedirects (+7 more)

### Community 188 - "TDLCommandError"
Cohesion: 0.38
Nodes (3): _FakeTdlClient, TdlWriteDenialTests, TDLCommandError

### Community 189 - "ProfilesPage.svelte"
Cohesion: 0.25
Nodes (7): load(), profileNeedsRepair(), refreshOperation(), submitUpload(), syncLogMessage(), syncOperationFor(), syncPhaseLabel()

### Community 190 - "AuthServiceTests"
Cohesion: 0.46
Nodes (3): AuthServiceTests, actor(), Path

### Community 191 - "BackendRuntimeSettings"
Cohesion: 0.13
Nodes (8): BackendRuntimeSettingsTests, BackendRuntimeSettings, Any, Path, Persistent validated settings that can be applied to a live backend., Use the backend-owned SQLite registry after its one-time legacy import., BackupScheduler, Recheck enabled state or the schedule after a Web update.

### Community 192 - "ProfileSyncError"
Cohesion: 0.15
Nodes (6): ProfileSyncError, HTTPRedirectHandler, RuntimeError, An error safe to classify without retaining a response body or URL., _RejectRedirects, _secure_backend_url()

### Community 194 - "normalize_tdl_chat_ref"
Cohesion: 0.23
Nodes (7): ChatReferenceTests, submit_leave(), normalize_bot_api_chat_ref(), normalize_tdl_chat_ref(), Canonical chat references for TDL commands and Telegram Bot API targets., Return a canonical TDL peer selector or raise for unsupported input. TDL…, Return the Bot API chat_id representation for an ID or public username.

### Community 195 - "settings_store.py"
Cohesion: 0.18
Nodes (4): AesGcmSecretStore, Path, Encrypt setting values with a persistent owner-only AES-256 key., Path

### Community 196 - "parse_tme3_url"
Cohesion: 0.29
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 198 - "presentation.ts"
Cohesion: 0.31
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 199 - "test_profile_provisioning.py"
Cohesion: 0.44
Nodes (5): extract_single_session(), Read a ZIP containing exactly one top-level .tdl directory., _safe_zip_entries(), validate_profile_bundle(), ZipInfo

### Community 200 - "executor_tts.py"
Cohesion: 0.20
Nodes (9): request_part(), normalize_text(), RuntimeError, Split normalized text into word-aware chunks no longer than 90 chars., Request a fresh Tor circuit without logging the control credential., split_text(), _tor_command(), TtsCancelled (+1 more)

### Community 202 - "test_worker_profile_sync.py"
Cohesion: 0.18
Nodes (5): FakeSessions, FakeTransport, _ProfileSyncCancelled, Exception, Internal signal to stop a profile pull at a safe boundary.

### Community 203 - "WorkerSharedCursorTests"
Cohesion: 0.22
Nodes (4): WorkerSharedCursorTests, __init__(), commit(), __init__()

### Community 205 - ".test_subprocess_runner_freezes_and_resumes_current_process"
Cohesion: 0.40
Nodes (4): CompletedProcess, skipIf, output(), run()

### Community 206 - "ProfileRuntime"
Cohesion: 0.25
Nodes (5): LeaveResult, LeaveService, CommandCallback, ProfileRuntime, Return an already initialized runtime without creating profile files.

### Community 207 - "_add_management_routes"
Cohesion: 0.25
Nodes (3): _add_management_routes(), management_start_backup(), FastAPI

### Community 209 - "test_trusted_device_browser_e2e.py"
Cohesion: 0.43
Nodes (5): make_test_certificates(), Path, skipUnless, TrustedDevicePlaywrightHttpsE2ETests, prepare_state()

### Community 211 - "Issue tracker: GitHub"
Cohesion: 0.33
Nodes (5): Conventions, Issue tracker: GitHub, Publishing and fetching, Pull requests as a triage surface, Wayfinding operations

### Community 212 - ".test_download_progress_callbacks_follow_the_download_lock_owner"
Cohesion: 0.53
Nodes (5): first_callback(), first_download(), second_callback(), second_download(), runtime()

### Community 215 - "Domain Docs"
Cohesion: 0.50
Nodes (3): Before exploring, Domain Docs, Layout

### Community 217 - "build_base_image"
Cohesion: 0.25
Nodes (9): build_base_archive(), build_base_image(), configured_base_image(), ensure_base_image_available(), login_registry(), Login to the image registry without exposing the PAT in process output., Ensure Docker can resolve the immutable base image before Compose builds.…, Build and export the expensive immutable runtime/Go base image once. (+1 more)

### Community 228 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

## Knowledge Gaps
- **501 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+496 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1519 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **31 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DomainError` connect `DomainError` to `WorkerRegistry`, `Job`, `ControlPlane`, `WorkerRuntimeSettings`, `WorkerCommandStoreTests`, `DeviceAuthTests`, `QuickModeExecutorMixin`, `backend.py`, `create_backend_app`, `composition.py`, `DurableDispatchTests`, `WorkerContractTests`, `OperationTests`, `source_store.py`, `register_operations`, `ProfileSyncContractTests`, `BotAuthService`, `create_worker_app`, `ObjectResponse`, `ExportWorkspaceState`, `register_jobs`, `register_runtime_settings`, `executor.py`, `SqliteAuthRepository`, `test_profile_sync_contract.py`, `http_client.py`, `AuthServiceTests`, `WorkerHttpDispatcher`, `normalize_tdl_chat_ref`, `SqliteOperationStore`, `WorkerEventPublisher`, `_add_management_routes`, `FakeExecutor`, `DeviceAuthService`, `JobEvent`, `register_storage`, `Path`, `config.py`, `OperationsService`, `register_downloads`, `WorkerCommandStore`, `SharedExportCursorTests`, `WorkerJobExecutor`?**
  _High betweenness centrality (0.120) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `.patch`, `TtsExecutorMixin`, `TDLClient`, `tdl.py`, `safelink_resolver.py`, `WorkerRuntimeSettings`, `UtilityRunner`, `inspect_export_json`, `QuickModeExecutorMixin`, `ProfileSessionManager`, `ResourceAwareQueue`, `WorkspaceExecutorMixin`, `composition.py`, `WorkerContractTests`, `ProfileSyncClient`, `HttpStateStore`, `AppConfig`, `executor.py`, `ProfileSyncError`, `WorkerEventPublisher`, `_Executor`, `test_profile_provisioning.py`, `WorkerSharedCursorTests`, `WorkerCommandRunner`, `Path`, `quick_export.py`, `DomainError`, `ProgressReporter`, `WorkerCommandStore`, `ProfileProvisioningTests`?**
  _High betweenness centrality (0.088) - this node is a cross-community bridge._
- **Why does `JsonHttpError` connect `WorkerContractTests` to `composition.py`, `BackendApiTests`, `WorkerEventPublisher`, `FakeDispatcher`, `.__init__`, `telegram/app.py`, `executor.py`, `TelegramFrontendApp`, `http_client.py`, `backend.py`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `create_backend_app()` (e.g. with `_active_storage_item()` and `advance_accepted_operation()`) actually correct?**
  _`create_backend_app()` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `WorkerJobExecutor` (e.g. with `ProfileProvisioningTests` and `QuickThumbnailTests`) actually correct?**
  _`WorkerJobExecutor` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `BackendApiTests` (e.g. with `BackendContext` and `ControlPlane`) actually correct?**
  _`BackendApiTests` has 23 INFERRED edges - model-reasoned connections that need verification._