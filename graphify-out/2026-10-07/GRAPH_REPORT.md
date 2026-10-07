# Graph Report - dockter_bot_tdl  (2026-10-07)

## Corpus Check
- 277 files · ~254,512 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: (none) 6, .base 1, .resolver 1)

## Summary
- 4614 nodes · 11397 edges · 225 communities (169 shown, 49 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 774 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `282a5190`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ProfileRegistry
- pindah4.py
- PanelManager
- ProfileSyncClient
- organize_media_from_json.py
- Job
- config.py
- Any
- StateStore
- run.py
- compress.sh
- create_worker_app
- ControlPlane
- boltStorage
- format_job_status
- .capabilities
- ._db
- WorkerRuntimeSettings
- tme3bot/utility.py
- compilerOptions
- telegram/app.py
- .test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage
- QuickModeExecutorMixin
- tme3bot-leave-helper
- TelegramFrontendApp
- tme3bot Agent Context
- ProfileSessionManager
- ResourceAwareQueue
- schemas.py
- package.json
- StoragePage.svelte
- tme3bot/__init__.py
- pindah.sh script
- AppConfig
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
- create_backend_app
- test_pindah.py
- ProfileProvisioningStore
- ExportWorkspaceState
- quick_export.py
- register_jobs
- 12. Bootstrap VPS baru dan satu-command deployment
- SqliteSourceRepository
- SqliteAuthRepository
- register_runtime_settings
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
- WorkerEventPublisher
- executor_tts.py
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
- control_plane.py
- build.py
- WorkerHttpDispatcher
- backend.py
- BackupService
- Path
- ContainerBuildTests
- WorkerJobExecutor
- AesGcmSecretStore
- request_json
- TrustedDeviceError
- WorkerRegistry
- OperationTests
- normalize_profile_name
- pkg_resources.py
- BackendRuntimeSettings
- WorkerContext
- P0 — Akses production dari laptop tepercaya
- Rencana pemisahan backend, worker, dan Web
- WorkerCommandStore
- source_store.py
- 21 — Penyederhanaan ENV dan inventaris pemakaian
- ._capture_tdl_output
- executor.py
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
- TDLClient
- Pengaturan aplikasi dari Web
- _error
- 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress
- 03 — Operation persisten dan transactional outbox
- register_utility
- dependencies
- WorkerApiTests
- 04 — Redis privat dan proses RQ untuk orkestrasi
- TtsExecutorMixin
- OperationsService
- tts_helper.py
- safelink_resolver.py
- 05 — Penerimaan cepat dan kontrak dispatch berversi
- 06 — Alias peer dan serialisasi export lintas worker
- scripts
- 07 — Vault profil berversi dan kontrak tarik/ACK
- 08 — Konfigurasi terpusat, versi penerapan, dan rahasia
- 09 — Jurnal command worker dan outbox event persisten
- 10 — Tarik profil saat startup dan sinkronisasi manual
- 11 — Executor export memakai cursor bersama dan mengarsip state lokal
- WorkerCommandStoreTests
- tdl_output.py
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
- Overview.svelte
- .setUp
- WorkerContractTests
- DownloadExecutorMixin
- advance_command
- .check_worker_fast
- 00-OVERVIEW.md
- DeviceAuthService
- register_operations
- devDependencies
- HttpStateStore
- WorkerProfileAdmissionTests
- .test_tor_recovery_restarts_only_the_child_process
- WorkerProfileSyncTests
- models.py
- WorkspaceExplorer.svelte
- worker/__init__.py
- ._recover_legacy_quick_stages
- decrypt/+page.svelte
- svelte.config.js
- DeviceAuthTests
- tts_pipeline.py
- normalize_tdl_chat_ref
- pindah.py
- StorageCatalog
- _hash_secret
- Connection
- BackupCoordinator
- RcloneRunner
- ProfileSyncContractTests
- StorageItem
- JobTable.svelte
- extract_single_session
- ._worker_heartbeat_loop
- DesiredSettingsTests
- @tailwindcss/vite
- WorkerCommandRunner
- Any
- JobEvent
- .__init__
- test_worker_command_store.py
- ProfileTests
- composition.py
- .test_helper_state_imports_in_chrome_and_revoke_invalidates_it
- CommandMilestoneRecorder
- .test_operations_api_is_idempotent_private_and_actor_scoped
- build_base_image
- .setUp
- profiles.py
- AuthServiceTests
- SourceMigrationTests
- StorageMaintenanceService
- FakeProfiles
- bootstrap_python_dependencies
- storage_catalog.py
- .accept_durable_command
- ProfileSyncError
- ._failed
- _RejectRedirects

## God Nodes (most connected - your core abstractions)
1. `DomainError` - 260 edges
2. `create_backend_app()` - 114 edges
3. `WorkerJobExecutor` - 102 edges
4. `BackendApiTests` - 92 edges
5. `SqliteJobRepository` - 91 edges
6. `ControlPlane` - 89 edges
7. `StorageCatalog` - 86 edges
8. `TelegramFrontendApp` - 76 edges
9. `Job` - 72 edges
10. `JobEvent` - 71 edges

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

## Communities (225 total, 49 thin omitted)

### Community 0 - "ProfileRegistry"
Cohesion: 0.22
Nodes (6): ProfileRegistry, Path, One-way migration for installations created before the registry., Gateway-owned registry for profile metadata, separate from TDL sessions. A…, Apply backend vault identity as authoritative registry data., Accept only new legacy metadata; do not let a worker rewrite identity.

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "ProfileSyncClient"
Cohesion: 0.17
Nodes (13): _header(), hmac_compare(), _now(), _positive_int(), ProfileSyncClient, Any, Pull versioned TDL profiles from the backend vault into a worker., Synchronize inline for a durable profile.sync worker operation. (+5 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory(), entry_identity() (+50 more)

### Community 5 - "Job"
Cohesion: 0.05
Nodes (15): prepare(), prepare(), Restart an export attempt while preserving its stable job ID., Find the original TDL message range without reading the JSON file. New jobs…, ActorResolver, JobRepository, ProfileStateStore, Any (+7 more)

### Community 6 - "config.py"
Cohesion: 0.17
Nodes (10): ChannelRefTests, update_backup_settings(), Update fields read by the live backend services without replacing config., channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`… (+2 more)

### Community 7 - "Any"
Cohesion: 0.16
Nodes (8): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), main_menu_markup(), edit_menu_message()

### Community 8 - "StateStore"
Cohesion: 0.06
Nodes (28): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), StateStoreTests, ParseTme3UrlTests, DownloadProgressSnapshot (+20 more)

### Community 9 - "run.py"
Cohesion: 0.16
Nodes (27): active_env_file(), add_profile(), backend_management_request(), build_migration_archive(), configured_service(), data_root_value(), deploy_web(), _download() (+19 more)

### Community 11 - "create_worker_app"
Cohesion: 0.08
Nodes (18): create_worker_app(), authorize(), durable_command_status(), export_profile_bundle(), healthz(), install_profile_bundle(), job_log_snapshot(), profile_login_bundle() (+10 more)

### Community 12 - "ControlPlane"
Cohesion: 0.08
Nodes (16): ControlPlane, Any, Exception, Release only the Quick Mode export phase after durable completion., Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job., Attach phase timing and event latency to this job's own event., Persist a worker's Quick Mode capacity and dispatch any new slots. (+8 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.18
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - ".capabilities"
Cohesion: 0.15
Nodes (3): Path, Return non-secret worker capabilities for backend target checks., resolver_addon_ready()

### Community 17 - "WorkerRuntimeSettings"
Cohesion: 0.13
Nodes (7): Path, RuntimeProfileManager, WorkerRuntimeSettingsTests, Any, Path, Persistent allowlisted worker options that can be changed through Web., WorkerRuntimeSettings

### Community 18 - "tme3bot/utility.py"
Cohesion: 0.08
Nodes (21): run(), UtilitySettingsTests, UtilitySummaryTests, ProcessStalledError, Raised when a worker subprocess stops making meaningful progress., CommandCallback, Path, Popen (+13 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.15
Nodes (22): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_compact_markup() (+14 more)

### Community 22 - "QuickModeExecutorMixin"
Cohesion: 0.08
Nodes (30): ExportJobResult, Any, Path, QuickModeExecutorMixin, ensure_not_cancelled(), persist_uploaded_items(), phase_result(), save_manifest() (+22 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.18
Nodes (6): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.10
Nodes (19): Arsitektur, Catatan diagnosis produksi terakhir, Checklist memulai sesi baru, Deployment yang benar, Download Manager: aturan penting, graphify, Jebakan, Langkah operasional berikutnya (+11 more)

### Community 26 - "ProfileSessionManager"
Cohesion: 0.18
Nodes (6): _LoginProcess, ProfileSessionManager, Any, Path, Check identity and both private Bolt session trees without opening Bolt., Narrow TDL login bridge and safe profile session installer for workers.

### Community 27 - "ResourceAwareQueue"
Cohesion: 0.06
Nodes (17): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, ResourceAwareQueueTests, SerialPerKeyQueueTests, handle() (+9 more)

### Community 28 - "schemas.py"
Cohesion: 0.07
Nodes (57): register_workers(), remove_worker(), set_worker_enabled(), worker_settings(), ActorResponse, ApiResponse, ApproveChallengeRequest, BatchSourcesRequest (+49 more)

### Community 29 - "package.json"
Cohesion: 0.11
Nodes (18): bits-ui, crypto-js, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/kit (+10 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (34): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+26 more)

### Community 34 - "AppConfig"
Cohesion: 0.40
Nodes (7): configure_logging(), main(), run_backend(), run_queue(), run_worker(), AppConfig, Fail fast when a production role is missing its trust boundary.

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
Cohesion: 0.11
Nodes (6): SqliteSourceRepositoryTests, StateStore-compatible adapter that binds the shared repository to a profile., A source write was based on an outdated revision., SourceRevisionConflict, SqliteProfileStateStore, SourceState

### Community 44 - "api.ts"
Cohesion: 0.18
Nodes (10): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+2 more)

### Community 45 - "RunScriptTests"
Cohesion: 0.05
Nodes (4): call(), RunScriptTests, fake_docker(), register_queue()

### Community 46 - "LabelStore"
Cohesion: 0.25
Nodes (5): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel

### Community 48 - "vitest"
Cohesion: 0.18
Nodes (5): @testing-library/svelte, vitest, publicKey, { apiMock, postMock }, workerSettings

### Community 49 - "preflight_report"
Cohesion: 0.14
Nodes (20): capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), docker_image_exists(), docker_manifest_exists(), git_remote_revision() (+12 more)

### Community 50 - "create_backend_app"
Cohesion: 0.06
Nodes (43): create_backend_app(), adopt_profile(), advance_accepted_operation(), advance_background_job(), advance_cancel_operation(), advance_retry_operation(), browser_actor_dict(), browser_challenge() (+35 more)

### Community 52 - "ProfileProvisioningStore"
Cohesion: 0.10
Nodes (7): _now(), ProfileProvisioningStore, Any, Connection, Path, Persistent encrypted session vault and profile distribution state., Keep old worker identity reports as adoption candidates, never as vault data.

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.09
Nodes (18): ExportWorkspaceTests, delete_quick_mode_staging(), loop(), export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate() (+10 more)

### Community 54 - "quick_export.py"
Cohesion: 0.11
Nodes (31): slugify_label(), _archive_files(), _chown_tree(), cleanup_quick_stage(), _clone_tree(), delete_quick_stage(), ensure_quick_stage_writable(), ensure_quick_tdl_client() (+23 more)

### Community 55 - "register_jobs"
Cohesion: 0.08
Nodes (37): verify_context(), verify_target(), event_dict(), job_dict(), _model_dict(), _newest_first_log_response(), _owned_job(), Any (+29 more)

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - "SqliteSourceRepository"
Cohesion: 0.13
Nodes (9): normalize_peer_identity(), Normalize a TDL-resolved peer identity before it enters the alias map. A…, Connection, Row, Apply approved sources and ledger decisions atomically; return replay status., Keep cross-worker execution gated until workers implement the contract., Backend-owned, profile-scoped source state in the application database., SqliteSourceRepository (+1 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.13
Nodes (7): _now(), Any, Connection, datetime, Path, Run security-sensitive read/modify/write work under a SQLite write lock., SqliteAuthRepository

### Community 59 - "register_runtime_settings"
Cohesion: 0.15
Nodes (17): register_backups(), start_backup(), register_runtime_settings(), acknowledge_worker_settings(), desired_store(), get_runtime_settings(), put_runtime_settings(), runtime_settings_schema() (+9 more)

### Community 60 - "migrate_source_state.py"
Cohesion: 0.18
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

### Community 69 - "SqliteOperationStore"
Cohesion: 0.12
Nodes (13): OperationRepository, Operation, Any, _dump(), _load(), _now(), _parse_datetime(), Any (+5 more)

### Community 70 - "WorkerEventPublisher"
Cohesion: 0.11
Nodes (3): Enable durable event delivery while retaining legacy test adapters., Seed event numbering for a reused job ID., WorkerEventPublisher

### Community 71 - "executor_tts.py"
Cohesion: 0.12
Nodes (8): _Executor, _FakePipeline, _FakeTdl, TtsExecutorTests, request(), Build a portable audio filename from the user-visible TTS title., _truncate_utf8(), tts_delivery_filename()

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
Nodes (4): make_pipeline(), TtsPipelineTests, request_part(), request_part()

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - "SqliteSettingsStore"
Cohesion: 0.16
Nodes (14): _json(), _now(), Any, Connection, Row, ValueError, Import a legacy snapshot once; existing rows and tombstones always win., Import one online worker's local runtime JSON at most once. (+6 more)

### Community 85 - "control_plane.py"
Cohesion: 0.14
Nodes (9): FakeProfiles, _elapsed_since(), datetime, serializable(), Application services and use cases., build_execution_plan(), JobExecutionPlan, Any (+1 more)

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 88 - "backend.py"
Cohesion: 0.11
Nodes (37): StorageLinkTests, _active_storage_item(), BackendContext, _deliver_storage_telegram(), _require_storage_folders_idle(), _storage_item(), FastAPI adapters for public and internal JSON contracts., register_storage() (+29 more)

### Community 89 - "BackupService"
Cohesion: 0.21
Nodes (8): BackupServiceTests, make_config(), Path, BackupArchive, BackupService, Path, safe_node_name(), utc_now()

### Community 90 - "Path"
Cohesion: 0.04
Nodes (24): ExportMilestoneTests, export_from_url(), export_from_url(), Path, QuickPipelineTests, QuickThumbnailTests, fake_run(), first_callback() (+16 more)

### Community 92 - "WorkerJobExecutor"
Cohesion: 0.14
Nodes (3): Executes domain jobs and publishes JSON events; no UI dependency., Bind the shared tracker callback only while owning its TDL lock., WorkerJobExecutor

### Community 93 - "AesGcmSecretStore"
Cohesion: 0.18
Nodes (4): AesGcmSecretStore, Path, Encrypt setting values with a persistent owner-only AES-256 key., Path

### Community 94 - "request_json"
Cohesion: 0.24
Nodes (5): Any, RuntimeError, Send a durable command using a stable ID and reconcile lost ACKs., request_json(), current_receipt()

### Community 95 - "TrustedDeviceError"
Cohesion: 0.07
Nodes (32): FakeProtector, skipUnless, TrustedDeviceHelperTests, protect(), _browser_executable(), main(), open_trusted_context(), same_origin_only() (+24 more)

### Community 96 - "WorkerRegistry"
Cohesion: 0.18
Nodes (6): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 98 - "normalize_profile_name"
Cohesion: 0.14
Nodes (11): normalize_profile_name(), build_profile_config(), get_profile_download_mode(), ProfileManager, Path, Metadata a worker can safely publish to the backend registry., Return source state without constructing profile TDL clients., Refresh cached session paths after a locked install or rollback. (+3 more)

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - "BackendRuntimeSettings"
Cohesion: 0.36
Nodes (5): BackendRuntimeSettings, Any, Path, Persistent validated settings that can be applied to a live backend., Use the backend-owned SQLite registry after its one-time legacy import.

### Community 102 - "P0 — Akses production dari laptop tepercaya"
Cohesion: 0.11
Nodes (17): API perangkat milik actor, Cara verifikasi, Challenge dan signature, File yang disentuh, Helper Windows, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai (+9 more)

### Community 103 - "Rencana pemisahan backend, worker, dan Web"
Cohesion: 0.25
Nodes (8): Arsitektur target, Aturan agent pelaksana, Baseline audit — 2026-10-04, Asia/Jakarta, Cara memakai paket, Gerbang kompatibilitas dan migrasi, Keputusan dan kontrak bersama, Rencana pemisahan backend, worker, dan Web, Urutan dan ketergantungan

### Community 104 - "WorkerCommandStore"
Cohesion: 0.19
Nodes (7): _dump(), _now(), Any, Path, Row, SQLite journal kept on the worker's persistent data volume., WorkerCommandStore

### Community 105 - "source_store.py"
Cohesion: 0.07
Nodes (19): FailingCatalog, SharedExportCursorTests, current_actor(), Application service for verified peer aliases and shared export cursors., ExportCursorBusy, MigrationPlanConflict, PeerAliasConflict, PeerAliasCursorConflict (+11 more)

### Community 106 - "21 — Penyederhanaan ENV dan inventaris pemakaian"
Cohesion: 0.14
Nodes (13): 21 — Penyederhanaan ENV dan inventaris pemakaian, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Lampiran — inventaris ENV baseline, Penambahan yang direncanakan (+5 more)

### Community 108 - "executor.py"
Cohesion: 0.05
Nodes (52): StorageWorkerPathTests, Create encrypted, runtime-only per-node backup archives., sha256_file(), bounded_output_tail(), Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Return only the newest output without splitting a line when possible., Redact obvious secret flags and values before persisting a command. (+44 more)

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
Nodes (11): FakeProfileDispatcher, FakeProfileManager, FakeWorkerRegistry, make_config(), MutableWorkerRegistry, ProfileProvisioningTests, Path, single_session_zip() (+3 more)

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

### Community 127 - "TDLClient"
Cohesion: 0.04
Nodes (43): OutputCallback, ProgressCallback, Queue, FakeRunner, CompletedProcess, skipIf, TDLClientTests, output() (+35 more)

### Community 128 - "Pengaturan aplikasi dari Web"
Cohesion: 0.29
Nodes (6): Kontrak implementasi, Pengaturan aplikasi dari Web, Pengaturan deployment, Pengaturan yang sudah ada di Web, Pengelolaan rahasia, Status migrasi konfigurasi

### Community 129 - "_error"
Cohesion: 0.33
Nodes (6): domain_error(), request_validation_error(), unhandled_error(), _error(), JSONResponse, Request

### Community 130 - "02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress"
Cohesion: 0.17
Nodes (11): 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 131 - "03 — Operation persisten dan transactional outbox"
Cohesion: 0.17
Nodes (11): 03 — Operation persisten dan transactional outbox, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 132 - "register_utility"
Cohesion: 0.20
Nodes (8): register_utility(), utility_settings_meta(), utility_tree(), SettingRequest, UtilityFolderRequest, UtilityJobRequest, Public metadata for clients; never contains a setting value or secret., utility_setting_specs()

### Community 133 - "dependencies"
Cohesion: 0.33
Nodes (6): dependencies, bits-ui, crypto-js, flowbite-svelte, @lucide/svelte, svelte

### Community 135 - "04 — Redis privat dan proses RQ untuk orkestrasi"
Cohesion: 0.17
Nodes (11): 04 — Redis privat dan proses RQ untuk orkestrasi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 136 - "TtsExecutorMixin"
Cohesion: 0.24
Nodes (7): Any, Path, Keep the opaque artifact for retries, and upload a title-named copy., TtsExecutorMixin, RuntimeError, TtsCancelled, TtsError

### Community 137 - "OperationsService"
Cohesion: 0.15
Nodes (6): _canonical(), OperationHandler, OperationsService, Any, Protocol, Validates bounded actions and persists them without executing side effects.

### Community 138 - "tts_helper.py"
Cohesion: 0.24
Nodes (15): _bootstrap_percent(), diagnostics(), get, post, ready(), readyz(), recover_tor(), renew_tor_circuit() (+7 more)

### Community 139 - "safelink_resolver.py"
Cohesion: 0.05
Nodes (58): Client, Response, ResolverAddonTests, _livewire_page(), _public_dns(), ResolverHttpTests, handler(), client_factory() (+50 more)

### Community 140 - "05 — Penerimaan cepat dan kontrak dispatch berversi"
Cohesion: 0.17
Nodes (11): 05 — Penerimaan cepat dan kontrak dispatch berversi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 141 - "06 — Alias peer dan serialisasi export lintas worker"
Cohesion: 0.17
Nodes (11): 06 — Alias peer dan serialisasi export lintas worker, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 142 - "scripts"
Cohesion: 0.33
Nodes (6): scripts, build, check, dev, preview, test

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

### Community 149 - "tdl_output.py"
Cohesion: 0.10
Nodes (20): FakePublisher, ProgressReporterTests, _byte_multiplier(), clean_tdl_output_line(), CommandProgress, _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar() (+12 more)

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
Cohesion: 0.05
Nodes (59): _add_internal_state_routes(), acquire_export_cursor(), commit_export_cursor(), confirm_peer_alias(), heartbeat_export_cursor(), pending_peer_aliases(), require_cursor_service(), resolve_export_peer() (+51 more)

### Community 161 - "WorkspaceExecutorMixin"
Cohesion: 0.38
Nodes (4): Any, Path, Return a safe, shallow directory listing for the active workspace., WorkspaceExecutorMixin

### Community 162 - "Overview.svelte"
Cohesion: 0.40
Nodes (4): describe(), error, icons, label()

### Community 164 - "WorkerContractTests"
Cohesion: 0.25
Nodes (6): patch, ContractWorkerRegistry, WorkerContractTests, Any, Return the non-secret version and feature set advertised by a worker., worker_contract_metadata()

### Community 165 - "DownloadExecutorMixin"
Cohesion: 0.33
Nodes (4): DownloadExecutorMixin, progress_event(), report_snapshot(), Any

### Community 166 - "advance_command"
Cohesion: 0.40
Nodes (5): advance_command(), RuntimeError, QueueAdvanceRetry, A short backend wait; RQ applies the bounded retry policy., Ask the backend to claim and advance one durable command identifier.

### Community 167 - ".check_worker_fast"
Cohesion: 0.25
Nodes (5): profile_management(), HTTPRedirectHandler, Check worker availability without loading its full capabilities., Keep authenticated profile bundle transfers on the configured URL., _RejectRedirects

### Community 168 - "00-OVERVIEW.md"
Cohesion: 0.11
Nodes (15): File yang disentuh, Kontrak dan perilaku, Kriteria selesai, P1 — Diagnosis dan pemulihan kesiapan helper TTS, Prasyarat dan konteks, Prompt implementasi, Rollback, Tujuan (+7 more)

### Community 169 - "DeviceAuthService"
Cohesion: 0.20
Nodes (10): skipUnless, TrustedDevicePlaywrightHttpsE2ETests, _b64url(), _canonical_origin(), _decode_b64url(), DeviceAuthService, _now(), Any (+2 more)

### Community 170 - "register_operations"
Cohesion: 0.49
Nodes (10): register_operations(), api_capabilities(), cancel_operation(), get_operation(), list_operations(), _public(), _require_operations(), retry_operation() (+2 more)

### Community 171 - "devDependencies"
Cohesion: 0.15
Nodes (13): devDependencies, jsdom, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss, @tailwindcss/vite (+5 more)

### Community 172 - "HttpStateStore"
Cohesion: 0.16
Nodes (6): HttpStateStore, normalize_chat_ref(), Any, Canonical source key for usernames, links, phones, and numeric IDs., StateStore-compatible client used by a worker without a local state file., StateSnapshot

### Community 174 - ".test_tor_recovery_restarts_only_the_child_process"
Cohesion: 0.12
Nodes (3): skipIf, assert_release(), write_to_fp()

### Community 175 - "WorkerProfileSyncTests"
Cohesion: 0.18
Nodes (5): bundle_for(), FakeSessions, FakeTransport, manifest_row(), WorkerProfileSyncTests

### Community 176 - "models.py"
Cohesion: 0.11
Nodes (23): advance_profile_sync_cancel(), advance_profile_sync_command(), _complete_sync_operation(), prepare_profile_sync_operation(), Any, PreparedOperation, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus (+15 more)

### Community 177 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 180 - "decrypt/+page.svelte"
Cohesion: 0.09
Nodes (21): copied, decrypt(), encrypted, error, loadResolverJobs(), notice, plaintext, readEncryptedValue() (+13 more)

### Community 182 - "DeviceAuthTests"
Cohesion: 0.18
Nodes (3): DeviceAuthTests, actor(), challenge_payload()

### Community 183 - "tts_pipeline.py"
Cohesion: 0.25
Nodes (5): normalize_text(), Split normalized text into word-aware chunks no longer than 90 chars., Request a fresh Tor circuit without logging the control credential., split_text(), _tor_command()

### Community 184 - "normalize_tdl_chat_ref"
Cohesion: 0.08
Nodes (23): ChatReferenceTests, _profile_artifact(), register_downloads(), archive_artifact(), clear_failed(), delete_artifact_file(), list_artifacts(), purge_artifact() (+15 more)

### Community 186 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 187 - "StorageCatalog"
Cohesion: 0.20
Nodes (5): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, StorageCatalog

### Community 190 - "Connection"
Cohesion: 0.15
Nodes (4): Connection, Path, Insert a callback result, returning the existing item on retry., Create a consistent SQLite snapshot, including WAL contents.

### Community 193 - "BackupCoordinator"
Cohesion: 0.10
Nodes (8): BackendRuntimeSettingsTests, BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., Recheck enabled state or the schedule after a Web update.

### Community 195 - "RcloneRunner"
Cohesion: 0.11
Nodes (13): FakeSubprocessRunner, RcloneRunnerTests, CommandCallback, Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Small, cancellable rclone adapter for files already in the workspace. (+5 more)

### Community 198 - "JobTable.svelte"
Cohesion: 0.18
Nodes (4): normalizeBotApiChatRef(), normalizeTdlChatRef(), if(), length()

### Community 199 - "extract_single_session"
Cohesion: 0.22
Nodes (7): extract_single_session(), profile_bundle_identity(), Read the Telegram identity embedded in a validated bundle., Read a ZIP containing exactly one top-level .tdl directory., _safe_zip_entries(), validate_profile_bundle(), ZipInfo

### Community 207 - "JobEvent"
Cohesion: 0.05
Nodes (7): ControlPlaneTests, FailingDispatcher, FakeDispatcher, FakeExportCursorGate, IncompatibleDispatcher, JobStoreTests, JobEvent

### Community 212 - "ProfileTests"
Cohesion: 0.35
Nodes (3): ProfileTests, Path, build_profile_runtime()

### Community 213 - "composition.py"
Cohesion: 0.05
Nodes (19): _FakeConnection, _FakeJob, _FakeQueue, skipUnless, QueueTransportTests, build_backend_context(), ControlPlaneBackupRouter, _first_actor() (+11 more)

### Community 214 - ".test_helper_state_imports_in_chrome_and_revoke_invalidates_it"
Cohesion: 0.83
Nodes (3): make_test_certificates(), Path, prepare_state()

### Community 215 - "CommandMilestoneRecorder"
Cohesion: 0.20
Nodes (4): CommandMilestoneRecorder, Persist bounded command results without allowing telemetry to fail work., Create the pending milestone before a subprocess begins work., Complete the pending milestone with bounded, sanitized output.

### Community 217 - "build_base_image"
Cohesion: 0.25
Nodes (9): build_base_archive(), build_base_image(), configured_base_image(), ensure_base_image_available(), login_registry(), Login to the image registry without exposing the PAT in process output., Ensure Docker can resolve the immutable base image before Compose builds.…, Build and export the expensive immutable runtime/Go base image once. (+1 more)

### Community 219 - ".setUp"
Cohesion: 0.17
Nodes (3): FakeDispatcher, FakeProfiles, FakeUtilitySettings

### Community 221 - "profiles.py"
Cohesion: 0.13
Nodes (16): LeaveResult, LeaveService, CommandCallback, Any, Path, Atomically write JSON containing secrets with owner-only Unix mode., write_json_atomic(), write_json_atomic_private() (+8 more)

### Community 222 - "AuthServiceTests"
Cohesion: 0.46
Nodes (3): AuthServiceTests, actor(), Path

### Community 228 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

### Community 229 - "storage_catalog.py"
Cohesion: 0.47
Nodes (4): build_storage_caption(), _caption_value(), Persistent catalog for the shared Telegram storage channel., _slug()

### Community 233 - "ProfileSyncError"
Cohesion: 0.22
Nodes (4): ProfileSyncError, RuntimeError, An error safe to classify without retaining a response body or URL., Start one background pull on worker startup without blocking API boot.

## Knowledge Gaps
- **482 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+477 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1433 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **49 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DomainError` connect `DomainError` to `register_utility`, `Job`, `config.py`, `OperationsService`, `create_worker_app`, `ControlPlane`, `WorkerRuntimeSettings`, `WorkerCommandStoreTests`, `QuickModeExecutorMixin`, `schemas.py`, `WorkerContractTests`, `.check_worker_fast`, `DeviceAuthService`, `register_operations`, `models.py`, `create_backend_app`, `ExportWorkspaceState`, `DeviceAuthTests`, `quick_export.py`, `register_jobs`, `normalize_tdl_chat_ref`, `SqliteAuthRepository`, `register_runtime_settings`, `_hash_secret`, `DurableDispatchTests`, `ProfileSyncContractTests`, `SqliteOperationStore`, `Any`, `JobEvent`, `FakeExecutor`, `test_worker_command_store.py`, `control_plane.py`, `backend.py`, `Path`, `WorkerJobExecutor`, `AuthServiceTests`, `OperationTests`, `.accept_durable_command`, `source_store.py`, `WorkerCommandStore`, `executor.py`?**
  _High betweenness centrality (0.134) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `ProfileSyncClient`, `TtsExecutorMixin`, `safelink_resolver.py`, `.capabilities`, `WorkerRuntimeSettings`, `tme3bot/utility.py`, `QuickModeExecutorMixin`, `ProfileSessionManager`, `ResourceAwareQueue`, `DomainError`, `WorkspaceExecutorMixin`, `AppConfig`, `WorkerContractTests`, `DownloadExecutorMixin`, `WorkerProfileAdmissionTests`, `models.py`, `worker/__init__.py`, `._recover_legacy_quick_stages`, `quick_export.py`, `RcloneRunner`, `WorkerEventPublisher`, `executor_tts.py`, `._worker_heartbeat_loop`, `WorkerCommandRunner`, `Any`, `composition.py`, `CommandMilestoneRecorder`, `Path`, `normalize_profile_name`, `WorkerCommandStore`, `.accept_durable_command`, `._failed`, `._capture_tdl_output`, `executor.py`, `ProfileSyncError`, `ProfileProvisioningTests`, `TDLClient`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Why does `JsonHttpError` connect `JsonHttpError` to `WorkerContractTests`, `BackendApiTests`, `WorkerEventPublisher`, `.check_worker_fast`, `executor.py`, `models.py`, `telegram/app.py`, `WorkerHttpDispatcher`, `TelegramFrontendApp`, `schemas.py`, `request_json`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `create_backend_app()` (e.g. with `_active_storage_item()` and `advance_accepted_operation()`) actually correct?**
  _`create_backend_app()` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 26 inferred relationships involving `WorkerJobExecutor` (e.g. with `ProfileProvisioningTests` and `QuickThumbnailTests`) actually correct?**
  _`WorkerJobExecutor` has 26 INFERRED edges - model-reasoned connections that need verification._
- **Are the 22 inferred relationships involving `BackendApiTests` (e.g. with `BackendContext` and `ControlPlane`) actually correct?**
  _`BackendApiTests` has 22 INFERRED edges - model-reasoned connections that need verification._