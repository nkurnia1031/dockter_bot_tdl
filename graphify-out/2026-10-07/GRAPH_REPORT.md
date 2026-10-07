# Graph Report - dockter_bot_tdl  (2026-10-07)

## Corpus Check
- 277 files · ~253,851 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 4668 nodes · 11463 edges · 224 communities (177 shown, 40 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 772 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8be1dc9b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- tdl_output.py
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
- TDLClient
- ._db
- WorkerRuntimeSettings
- tme3bot/utility.py
- compilerOptions
- telegram/app.py
- service.py
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
- composition.py
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
- FakePage
- register_jobs
- 12. Bootstrap VPS baru dan satu-command deployment
- SqliteSourceRepository
- SqliteAuthRepository
- WorkerRegistry
- migrate_source_state.py
- job-progress.ts
- DownloadProgressTracker
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
- SqliteSettingsStore
- resolve_shortlink
- build.py
- SqliteQueueState
- backend.py
- BackupService
- Path
- ContainerBuildTests
- WorkerJobExecutor
- settings_store.py
- WorkerHttpDispatcher
- TrustedDeviceError
- JobEvent
- StorageCatalog
- normalize_profile_name
- pkg_resources.py
- SqliteProfileStateStore
- normalize_tdl_chat_ref
- P0 — Akses production dari laptop tepercaya
- Rencana pemisahan backend, worker, dan Web
- WorkerCommandStore
- SharedExportCursorTests
- 21 — Penyederhanaan ENV dan inventaris pemakaian
- .patch
- executor.py
- 22 — Uji kegagalan lintas komponen dan panduan cutover
- Arsitektur Sistem tme3bot
- routes/__init__.py
- FakeDispatcher
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
- tdl.py
- Pengaturan aplikasi dari Web
- FakeLocator
- 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress
- 03 — Operation persisten dan transactional outbox
- ObjectResponse
- WorkerProfileSyncTests
- WorkerApiTests
- 04 — Redis privat dan proses RQ untuk orkestrasi
- TtsExecutorMixin
- OperationsService
- tts_helper.py
- SafelinkResolveError
- 05 — Penerimaan cepat dan kontrak dispatch berversi
- 06 — Alias peer dan serialisasi export lintas worker
- Connection
- 07 — Vault profil berversi dan kontrak tarik/ACK
- 08 — Konfigurasi terpusat, versi penerapan, dan rahasia
- 09 — Jurnal command worker dan outbox event persisten
- 10 — Tarik profil saat startup dan sinkronisasi manual
- 11 — Executor export memakai cursor bersama dan mengarsip state lokal
- WorkerCommandStoreTests
- inspect_export_json
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
- QueueTransportTests
- .setUp
- WorkerContractTests
- ProgressReporter
- FakeButton
- http_client.py
- 00-OVERVIEW.md
- DeviceAuthService
- register_operations
- devDependencies
- WorkerRuntimeSettingsTests
- SourceMigrationTests
- .test_tor_recovery_restarts_only_the_child_process
- FakeOverlayLocator
- models.py
- WorkspaceExplorer.svelte
- write_json_atomic_private
- BackendRuntimeSettings
- decrypt/+page.svelte
- bootstrap_python_dependencies
- DeviceAuthTests
- TtsError
- register_downloads
- build_storage_caption
- pindah.py
- register_device_routes
- resolver_addon.py
- BotAuthService
- parse_tme3_url
- test_safelink_resolver.py
- BackupCoordinator
- RcloneRunner
- ProfileSyncContractTests
- QueueOutboxPublisher
- JobTable.svelte
- test_profile_provisioning.py
- register_workers
- DesiredSettingsTests
- StorageMaintenanceService
- WorkerCommandRunner
- Any
- register_runtime_settings
- AppConfig
- .request_sync
- .test_internal_endpoint_requires_service_auth_and_valid_lease
- .browser
- test_worker_command_store.py
- ProfileManager
- .test_subprocess_runner_freezes_and_resumes_current_process
- test_trusted_device_browser_e2e.py
- CommandMilestoneRecorder
- .test_operations_api_is_idempotent_private_and_actor_scoped
- build_base_image
- .test_build_base_builds_and_exports_only_the_base_image
- .setUp
- TDLCommandError
- QuickThumbnailBuilder
- AuthServiceTests

## God Nodes (most connected - your core abstractions)
1. `DomainError` - 260 edges
2. `create_backend_app()` - 114 edges
3. `WorkerJobExecutor` - 101 edges
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

## Communities (224 total, 40 thin omitted)

### Community 0 - "tdl_output.py"
Cohesion: 0.15
Nodes (18): Create encrypted, runtime-only per-node backup archives., _byte_multiplier(), clean_tdl_output_line(), _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), parse_elapsed_seconds(), parse_eta_seconds() (+10 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "ProfileSyncClient"
Cohesion: 0.15
Nodes (15): _header(), hmac_compare(), _now(), _positive_int(), ProfileSyncClient, Any, HTTPRedirectHandler, Pull versioned TDL profiles from the backend vault into a worker. (+7 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

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
Cohesion: 0.16
Nodes (9): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), StateStoreTests, Path, StateStore (+1 more)

### Community 9 - "run.py"
Cohesion: 0.16
Nodes (27): active_env_file(), add_profile(), backend_management_request(), build_migration_archive(), configured_service(), data_root_value(), deploy_web(), _download() (+19 more)

### Community 11 - "create_worker_app"
Cohesion: 0.07
Nodes (24): create_worker_app(), authorize(), domain_error(), durable_command_status(), export_profile_bundle(), healthz(), install_profile_bundle(), job_log_snapshot() (+16 more)

### Community 12 - "ControlPlane"
Cohesion: 0.07
Nodes (17): actor(), actor(), ControlPlane, Any, Exception, Release only the Quick Mode export phase after durable completion., Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job. (+9 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.18
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "TDLClient"
Cohesion: 0.14
Nodes (11): FakeRunner, TDLClientTests, CompletedProcess, Path, RuntimeError, Upload one file and optionally force it to Telegram photo media., Resolve delayed TDL upload results by polling channel history. Some TDL…, Raised when TDL returns unusable or malformed export data. (+3 more)

### Community 17 - "WorkerRuntimeSettings"
Cohesion: 0.22
Nodes (4): Any, Path, Persistent allowlisted worker options that can be changed through Web., WorkerRuntimeSettings

### Community 18 - "tme3bot/utility.py"
Cohesion: 0.08
Nodes (19): UtilitySettingsTests, UtilitySummaryTests, ProcessStalledError, Raised when a worker subprocess stops making meaningful progress., CommandCallback, Path, Popen, ValueError (+11 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.15
Nodes (22): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_compact_markup() (+14 more)

### Community 21 - "service.py"
Cohesion: 0.14
Nodes (17): download_export_to(), has_downloadable_media(), is_image_message(), Any, BatchDownloadResult, BatchDownloadService, build_telegram_message_url(), DownloadedJsonResult (+9 more)

### Community 22 - "QuickModeExecutorMixin"
Cohesion: 0.10
Nodes (22): ExportJobResult, Any, Path, QuickModeExecutorMixin, ensure_not_cancelled(), persist_uploaded_items(), phase_result(), save_manifest() (+14 more)

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
Cohesion: 0.10
Nodes (40): ActorResponse, ApiResponse, ApproveChallengeRequest, BrowserChallengeResponse, BrowserProfileRequest, BrowserSessionResponse, ChallengeExchangeResponse, ChallengeResponse (+32 more)

### Community 29 - "package.json"
Cohesion: 0.05
Nodes (33): bits-ui, crypto-js, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static (+25 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (34): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+26 more)

### Community 34 - "composition.py"
Cohesion: 0.20
Nodes (9): configure_logging(), main(), build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, run_backend(), run_queue() (+1 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.15
Nodes (5): ExportArtifactCatalogTests, ExportArtifactCatalog, Connection, Mark catalog rows absent when a worker inventory completes., Remove a missing file from the runnable queue. The physical file is already…

### Community 38 - "main"
Cohesion: 0.22
Nodes (20): compose_files_for_target(), deploy_all(), deploy_application(), ensure_profile_root(), main(), manage_backup(), merge_env_file(), migrate_images() (+12 more)

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
Cohesion: 0.13
Nodes (14): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+6 more)

### Community 46 - "LabelStore"
Cohesion: 0.24
Nodes (6): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, slugify_label()

### Community 48 - "vitest"
Cohesion: 0.18
Nodes (5): @testing-library/svelte, vitest, publicKey, { apiMock, postMock }, workerSettings

### Community 49 - "preflight_report"
Cohesion: 0.14
Nodes (20): capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), docker_image_exists(), docker_manifest_exists(), git_remote_revision() (+12 more)

### Community 50 - "create_backend_app"
Cohesion: 0.06
Nodes (35): create_backend_app(), adopt_profile(), advance_accepted_operation(), advance_background_job(), advance_cancel_operation(), advance_retry_operation(), browser_challenge(), browser_logout() (+27 more)

### Community 52 - "ProfileProvisioningStore"
Cohesion: 0.11
Nodes (7): _now(), ProfileProvisioningStore, Any, Connection, Path, Persistent encrypted session vault and profile distribution state., Keep old worker identity reports as adoption candidates, never as vault data.

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.09
Nodes (18): ExportWorkspaceTests, delete_quick_mode_staging(), loop(), export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate() (+10 more)

### Community 54 - "FakePage"
Cohesion: 0.13
Nodes (9): AbstractContextManager, FakeBrowser, FakeClock, FakeContext, FakeOverlayPage, FakePage, FakePlaywrightFactory, _public_dns() (+1 more)

### Community 55 - "register_jobs"
Cohesion: 0.08
Nodes (38): verify_context(), verify_target(), event_dict(), job_dict(), _model_dict(), _newest_first_log_response(), _owned_job(), Any (+30 more)

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - "SqliteSourceRepository"
Cohesion: 0.10
Nodes (21): normalize_peer_identity(), Normalize a TDL-resolved peer identity before it enters the alias map. A…, ExportCursorBusy, PeerAliasConflict, PeerAliasCursorConflict, PeerAliasNotFound, Connection, Row (+13 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.13
Nodes (7): _now(), Any, Connection, datetime, Path, Run security-sensitive read/modify/write work under a SQLite write lock., SqliteAuthRepository

### Community 59 - "WorkerRegistry"
Cohesion: 0.18
Nodes (6): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 60 - "migrate_source_state.py"
Cohesion: 0.15
Nodes (40): canonical_chat_key(), Canonicalize aliases for source state while preserving legacy keys., MigrationPlanConflict, Path, Read source rows and migration ledger without opening unrelated tables., A migration plan or one of its optimistic revision checks is stale., apply_plan(), build_plan() (+32 more)

### Community 61 - "job-progress.ts"
Cohesion: 0.22
Nodes (10): eventLatency, phaseElapsedSeconds, phaseLabel(), stageId, clampPercent(), formatDuration(), JobLike, NormalizedProgress (+2 more)

### Community 62 - "DownloadProgressTracker"
Cohesion: 0.28
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

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
Cohesion: 0.07
Nodes (24): OperationTests, _FakeConnection, _FakeJob, _FakeQueue, PreparedOperation, OperationRepository, ensure_operation_transition(), Operation (+16 more)

### Community 70 - "WorkerEventPublisher"
Cohesion: 0.12
Nodes (3): Enable durable event delivery while retaining legacy test adapters., Seed event numbering for a reused job ID., WorkerEventPublisher

### Community 71 - "executor_tts.py"
Cohesion: 0.11
Nodes (8): _Executor, _FakePipeline, _FakeTdl, TtsExecutorTests, request(), Build a portable audio filename from the user-visible TTS title., _truncate_utf8(), tts_delivery_filename()

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

### Community 84 - "SqliteSettingsStore"
Cohesion: 0.17
Nodes (13): _json(), _now(), Any, Connection, Row, ValueError, Import a legacy snapshot once; existing rows and tombstones always win., Import one online worker's local runtime JSON at most once. (+5 more)

### Community 85 - "resolve_shortlink"
Cohesion: 0.16
Nodes (14): assert_public_http_url(), _captcha_present(), _choose_gate_action(), _close_ad_overlay(), decode_safelinkearn_url(), _guard_request(), _host_addresses(), Any (+6 more)

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - "SqliteQueueState"
Cohesion: 0.23
Nodes (6): _now(), Any, Connection, datetime, Queue-specific SQLite adapter over the durable operation outbox., SqliteQueueState

### Community 88 - "backend.py"
Cohesion: 0.08
Nodes (43): StorageLinkTests, _active_storage_item(), _add_management_routes(), management_start_backup(), BackendContext, _deliver_storage_telegram(), FastAPI, _require_storage_folders_idle() (+35 more)

### Community 89 - "BackupService"
Cohesion: 0.21
Nodes (8): BackupServiceTests, make_config(), Path, BackupArchive, BackupService, Path, safe_node_name(), utc_now()

### Community 90 - "Path"
Cohesion: 0.04
Nodes (21): ExportMilestoneTests, export_from_url(), export_from_url(), Path, QuickPipelineTests, run(), QuickThumbnailTests, fake_run() (+13 more)

### Community 92 - "WorkerJobExecutor"
Cohesion: 0.04
Nodes (17): WorkerProfileAdmissionTests, accept_command(), capabilities(), Any, Event, Exception, Path, Executes domain jobs and publishes JSON events; no UI dependency. (+9 more)

### Community 93 - "settings_store.py"
Cohesion: 0.17
Nodes (5): AesGcmSecretStore, Path, Encrypt setting values with a persistent owner-only AES-256 key., Path, SettingsConflict

### Community 94 - "WorkerHttpDispatcher"
Cohesion: 0.12
Nodes (7): profile_management(), Any, RuntimeError, Check worker availability without loading its full capabilities., Send a durable command using a stable ID and reconcile lost ACKs., WorkerHttpDispatcher, current_receipt()

### Community 95 - "TrustedDeviceError"
Cohesion: 0.07
Nodes (32): FakeProtector, skipUnless, TrustedDeviceHelperTests, protect(), _browser_executable(), main(), open_trusted_context(), same_origin_only() (+24 more)

### Community 96 - "JobEvent"
Cohesion: 0.05
Nodes (7): ControlPlaneTests, FailingDispatcher, FakeDispatcher, FakeExportCursorGate, FakeProfiles, JobStoreTests, JobEvent

### Community 97 - "StorageCatalog"
Cohesion: 0.20
Nodes (5): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, StorageCatalog

### Community 98 - "normalize_profile_name"
Cohesion: 0.09
Nodes (18): Application service for verified peer aliases and shared export cursors., normalize_profile_name(), write_json_atomic(), ProfileRegistry, Path, One-way migration for installations created before the registry., Gateway-owned registry for profile metadata, separate from TDL sessions. A…, Apply backend vault identity as authoritative registry data. (+10 more)

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - "SqliteProfileStateStore"
Cohesion: 0.09
Nodes (5): SqliteSourceRepositoryTests, StateStore-compatible adapter that binds the shared repository to a profile., A source write was based on an outdated revision., SourceRevisionConflict, SqliteProfileStateStore

### Community 101 - "normalize_tdl_chat_ref"
Cohesion: 0.11
Nodes (16): ChatReferenceTests, list_artifacts(), register_sources(), add_label(), get_source(), submit_leave(), update_source(), BatchSourcesRequest (+8 more)

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
Cohesion: 0.11
Nodes (3): FailingCatalog, SharedExportCursorTests, current_actor()

### Community 106 - "21 — Penyederhanaan ENV dan inventaris pemakaian"
Cohesion: 0.14
Nodes (13): 21 — Penyederhanaan ENV dan inventaris pemakaian, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Lampiran — inventaris ENV baseline, Penambahan yang direncanakan (+5 more)

### Community 108 - "executor.py"
Cohesion: 0.07
Nodes (61): StorageWorkerPathTests, bounded_output_tail(), Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Return only the newest output without splitting a line when possible., Redact obvious secret flags and values before persisting a command., sanitize_command(), sanitize_text() (+53 more)

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

### Community 118 - "ExportCursorService"
Cohesion: 0.17
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

### Community 127 - "tdl.py"
Cohesion: 0.07
Nodes (22): OutputCallback, ProgressCallback, Queue, decode_process_output(), _message_contains_caption(), visit(), _normalize_upload_caption(), notify_command_completed() (+14 more)

### Community 128 - "Pengaturan aplikasi dari Web"
Cohesion: 0.29
Nodes (6): Kontrak implementasi, Pengaturan aplikasi dari Web, Pengaturan deployment, Pengaturan yang sudah ada di Web, Pengelolaan rahasia, Status migrasi konfigurasi

### Community 130 - "02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress"
Cohesion: 0.17
Nodes (11): 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 131 - "03 — Operation persisten dan transactional outbox"
Cohesion: 0.17
Nodes (11): 03 — Operation persisten dan transactional outbox, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 132 - "ObjectResponse"
Cohesion: 0.13
Nodes (14): register_backups(), start_backup(), register_utility(), utility_settings_meta(), utility_tree(), BackupRuntimeSettingsRequest, ItemListResponse, ObjectResponse (+6 more)

### Community 133 - "WorkerProfileSyncTests"
Cohesion: 0.12
Nodes (7): bundle_for(), FakeSessions, FakeTransport, manifest_row(), WorkerProfileSyncTests, ProfileSyncError, An error safe to classify without retaining a response body or URL.

### Community 135 - "04 — Redis privat dan proses RQ untuk orkestrasi"
Cohesion: 0.17
Nodes (11): 04 — Redis privat dan proses RQ untuk orkestrasi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 136 - "TtsExecutorMixin"
Cohesion: 0.26
Nodes (4): Any, Path, Keep the opaque artifact for retries, and upload a title-named copy., TtsExecutorMixin

### Community 137 - "OperationsService"
Cohesion: 0.15
Nodes (6): _canonical(), OperationHandler, OperationsService, Any, Protocol, Validates bounded actions and persists them without executing side effects.

### Community 138 - "tts_helper.py"
Cohesion: 0.24
Nodes (15): _bootstrap_percent(), diagnostics(), get, post, ready(), readyz(), recover_tor(), renew_tor_circuit() (+7 more)

### Community 139 - "SafelinkResolveError"
Cohesion: 0.14
Nodes (11): ResolverAddonTests, Any, Any, Worker-side client for the private resolver addon service., resolve_with_addon(), RuntimeError, A safe, user-facing resolver failure with no untrusted URL attached., Raised when the persisted job receives a cancellation request. (+3 more)

### Community 140 - "05 — Penerimaan cepat dan kontrak dispatch berversi"
Cohesion: 0.17
Nodes (11): 05 — Penerimaan cepat dan kontrak dispatch berversi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 141 - "06 — Alias peer dan serialisasi export lintas worker"
Cohesion: 0.17
Nodes (11): 06 — Alias peer dan serialisasi export lintas worker, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 142 - "Connection"
Cohesion: 0.15
Nodes (4): Connection, Path, Insert a callback result, returning the existing item on retry., Create a consistent SQLite snapshot, including WAL contents.

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

### Community 149 - "inspect_export_json"
Cohesion: 0.18
Nodes (10): discard_export_without_media(), inspect_export_json(), Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape., Remove an export JSON when its inspected media count is exactly zero. The…, DownloadExecutorMixin, progress_event() (+2 more)

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
Cohesion: 0.06
Nodes (52): IncompatibleDispatcher, _add_internal_state_routes(), acquire_export_cursor(), commit_export_cursor(), confirm_peer_alias(), heartbeat_export_cursor(), pending_peer_aliases(), require_cursor_service() (+44 more)

### Community 161 - "WorkspaceExecutorMixin"
Cohesion: 0.38
Nodes (4): Any, Path, Return a safe, shallow directory listing for the active workspace., WorkspaceExecutorMixin

### Community 162 - "QueueTransportTests"
Cohesion: 0.25
Nodes (3): QueueTransportTests, QueueCommandService, Claim and advance an outbox command without running work in a request.

### Community 163 - ".setUp"
Cohesion: 0.10
Nodes (3): FakeProfiles, FakeTelegramBot, FakeWorkers

### Community 164 - "WorkerContractTests"
Cohesion: 0.15
Nodes (8): patch, ContractWorkerExecutor, ContractWorkerRegistry, WorkerContractTests, WorkerContext, Return the non-secret version and feature set advertised by a worker., worker_contract_metadata(), JsonHttpError

### Community 165 - "ProgressReporter"
Cohesion: 0.07
Nodes (24): FakePublisher, ProgressReporterTests, sha256_file(), _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed. (+16 more)

### Community 167 - "http_client.py"
Cohesion: 0.13
Nodes (13): Any, Reject workers whose advertised API cannot satisfy a backend operation., require_worker_contract(), HTTPRedirectHandler, Keep authenticated profile bundle transfers on the configured URL., _RejectRedirects, profile_transfer_is_secure(), Allow HTTPS remote workers and explicit internal Compose service hosts. (+5 more)

### Community 168 - "00-OVERVIEW.md"
Cohesion: 0.11
Nodes (15): File yang disentuh, Kontrak dan perilaku, Kriteria selesai, P1 — Diagnosis dan pemulihan kesiapan helper TTS, Prasyarat dan konteks, Prompt implementasi, Rollback, Tujuan (+7 more)

### Community 169 - "DeviceAuthService"
Cohesion: 0.25
Nodes (8): _b64url(), _canonical_origin(), _decode_b64url(), DeviceAuthService, _now(), Any, datetime, Approved public-key devices that can mint ordinary Web sessions.

### Community 170 - "register_operations"
Cohesion: 0.49
Nodes (10): register_operations(), api_capabilities(), cancel_operation(), get_operation(), list_operations(), _public(), _require_operations(), retry_operation() (+2 more)

### Community 171 - "devDependencies"
Cohesion: 0.15
Nodes (13): devDependencies, jsdom, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss, @tailwindcss/vite (+5 more)

### Community 172 - "WorkerRuntimeSettingsTests"
Cohesion: 0.26
Nodes (3): Path, RuntimeProfileManager, WorkerRuntimeSettingsTests

### Community 174 - ".test_tor_recovery_restarts_only_the_child_process"
Cohesion: 0.12
Nodes (3): skipIf, assert_release(), write_to_fp()

### Community 176 - "models.py"
Cohesion: 0.11
Nodes (18): worker_event(), _elapsed_since(), datetime, serializable(), Application services and use cases., build_execution_plan(), JobExecutionPlan, Any (+10 more)

### Community 177 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 178 - "write_json_atomic_private"
Cohesion: 0.33
Nodes (4): Any, Path, Atomically write JSON containing secrets with owner-only Unix mode., write_json_atomic_private()

### Community 179 - "BackendRuntimeSettings"
Cohesion: 0.27
Nodes (7): BackendRuntimeSettings, Any, Path, Persistent validated settings that can be applied to a live backend., Use the backend-owned SQLite registry after its one-time legacy import., normalize_bot_api_chat_ref(), Return the Bot API chat_id representation for an ID or public username.

### Community 180 - "decrypt/+page.svelte"
Cohesion: 0.09
Nodes (21): copied, decrypt(), encrypted, error, loadResolverJobs(), notice, plaintext, readEncryptedValue() (+13 more)

### Community 181 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

### Community 183 - "TtsError"
Cohesion: 0.20
Nodes (9): request_part(), normalize_text(), RuntimeError, Split normalized text into word-aware chunks no longer than 90 chars., Request a fresh Tor circuit without logging the control credential., split_text(), _tor_command(), TtsCancelled (+1 more)

### Community 184 - "register_downloads"
Cohesion: 0.17
Nodes (14): _profile_artifact(), register_downloads(), archive_artifact(), clear_failed(), delete_artifact_file(), delete_artifacts_batch(), purge_artifact(), reconcile_artifacts() (+6 more)

### Community 185 - "build_storage_caption"
Cohesion: 0.19
Nodes (5): build_storage_caption(), _caption_value(), Row, _slug(), StorageItem

### Community 186 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 187 - "register_device_routes"
Cohesion: 0.60
Nodes (6): register_device_routes(), list_devices(), register_device(), rename_device(), require_browser_actor(), revoke_device()

### Community 188 - "resolver_addon.py"
Cohesion: 0.16
Nodes (14): _browser_ready(), healthz(), lifespan(), _line(), Any, BaseModel, FastAPI, get (+6 more)

### Community 189 - "BotAuthService"
Cohesion: 0.40
Nodes (3): BotAuthService, _hash_secret(), TokenPair

### Community 190 - "parse_tme3_url"
Cohesion: 0.28
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 191 - "test_safelink_resolver.py"
Cohesion: 0.15
Nodes (5): FakePlaywright, FakeRoute, normalize_shortlink_url(), Input validation shared by the Safelink API and resolver addon., Validate and normalize a supported HTTP(S) shortlink without I/O.

### Community 193 - "BackupCoordinator"
Cohesion: 0.10
Nodes (8): BackendRuntimeSettingsTests, BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., Recheck enabled state or the schedule after a Web update.

### Community 195 - "RcloneRunner"
Cohesion: 0.15
Nodes (11): CommandCallback, Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Small, cancellable rclone adapter for files already in the workspace., Check remote/config access separately from per-file differences., RcloneError (+3 more)

### Community 197 - "QueueOutboxPublisher"
Cohesion: 0.24
Nodes (3): skipUnless, QueueOutboxPublisher, Moves SQLite outbox messages to RQ and repairs missing Redis jobs.

### Community 198 - "JobTable.svelte"
Cohesion: 0.12
Nodes (11): normalizeBotApiChatRef(), normalizeTdlChatRef(), if(), formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem (+3 more)

### Community 199 - "test_profile_provisioning.py"
Cohesion: 0.28
Nodes (7): extract_single_session(), profile_bundle_identity(), Read the Telegram identity embedded in a validated bundle., Read a ZIP containing exactly one top-level .tdl directory., _safe_zip_entries(), validate_profile_bundle(), ZipInfo

### Community 201 - "register_workers"
Cohesion: 0.15
Nodes (17): register_workers(), recover_worker_tts_helper(), remove_worker(), set_worker_enabled(), tts_worker_error(), update_worker(), update_worker_settings(), worker_settings() (+9 more)

### Community 205 - "Any"
Cohesion: 0.32
Nodes (4): Any, Idempotently record an export artifact before its shared cursor commits., Upsert an inventory batch in one SQLite transaction. Inventory can contain…, utc_now()

### Community 206 - "register_runtime_settings"
Cohesion: 0.32
Nodes (10): register_runtime_settings(), acknowledge_worker_settings(), desired_store(), get_runtime_settings(), put_runtime_settings(), runtime_settings_schema(), update_runtime_secrets(), validate_target() (+2 more)

### Community 207 - "AppConfig"
Cohesion: 0.27
Nodes (4): AppConfig, Fail fast when a production role is missing its trust boundary., ExportService, ParsedTme3Url

### Community 212 - "ProfileManager"
Cohesion: 0.12
Nodes (11): ProfileTests, Path, build_profile_config(), ProfileManager, Path, Metadata a worker can safely publish to the backend registry., Return source state without constructing profile TDL clients., Refresh cached session paths after a locked install or rollback. (+3 more)

### Community 213 - ".test_subprocess_runner_freezes_and_resumes_current_process"
Cohesion: 0.40
Nodes (4): CompletedProcess, skipIf, output(), run()

### Community 214 - "test_trusted_device_browser_e2e.py"
Cohesion: 0.43
Nodes (5): make_test_certificates(), Path, skipUnless, TrustedDevicePlaywrightHttpsE2ETests, prepare_state()

### Community 215 - "CommandMilestoneRecorder"
Cohesion: 0.20
Nodes (4): CommandMilestoneRecorder, Persist bounded command results without allowing telemetry to fail work., Create the pending milestone before a subprocess begins work., Complete the pending milestone with bounded, sanitized output.

### Community 217 - "build_base_image"
Cohesion: 0.25
Nodes (9): build_base_archive(), build_base_image(), configured_base_image(), ensure_base_image_available(), login_registry(), Login to the image registry without exposing the PAT in process output., Ensure Docker can resolve the immutable base image before Compose builds.…, Build and export the expensive immutable runtime/Go base image once. (+1 more)

### Community 219 - ".setUp"
Cohesion: 0.17
Nodes (3): FakeDispatcher, FakeProfiles, FakeUtilitySettings

### Community 220 - "TDLCommandError"
Cohesion: 0.33
Nodes (6): LeaveResult, LeaveService, CommandCallback, build_profile_runtime(), ProfileRuntime, TDLCommandError

### Community 221 - "QuickThumbnailBuilder"
Cohesion: 0.21
Nodes (7): CommandCallback, Popen, QuickThumbnailBuilder, probe_next_video(), skip_media(), watchdog(), Build a bounded, padded visual collage using ffmpeg/ffprobe. The process handle…

## Knowledge Gaps
- **481 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+476 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1474 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **40 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DomainError` connect `DomainError` to `ObjectResponse`, `Job`, `config.py`, `OperationsService`, `create_worker_app`, `ControlPlane`, `WorkerCommandStoreTests`, `QuickModeExecutorMixin`, `schemas.py`, `WorkerContractTests`, `http_client.py`, `DeviceAuthService`, `register_operations`, `WorkerRuntimeSettingsTests`, `models.py`, `create_backend_app`, `ExportWorkspaceState`, `DeviceAuthTests`, `register_jobs`, `register_downloads`, `SqliteAuthRepository`, `register_device_routes`, `BotAuthService`, `DurableDispatchTests`, `SqliteOperationStore`, `ProfileSyncContractTests`, `register_workers`, `register_runtime_settings`, `FakeExecutor`, `test_worker_command_store.py`, `backend.py`, `Path`, `WorkerJobExecutor`, `WorkerHttpDispatcher`, `AuthServiceTests`, `JobEvent`, `normalize_tdl_chat_ref`, `WorkerCommandStore`, `SharedExportCursorTests`, `executor.py`?**
  _High betweenness centrality (0.138) - this node is a cross-community bridge._
- **Why does `JsonHttpError` connect `WorkerContractTests` to `BackendApiTests`, `WorkerEventPublisher`, `http_client.py`, `register_workers`, `request_json`, `executor.py`, `models.py`, `FakeDispatcher`, `telegram/app.py`, `TelegramFrontendApp`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `ProfileSyncClient`, `WorkerProfileSyncTests`, `TtsExecutorMixin`, `WorkerRuntimeSettings`, `tme3bot/utility.py`, `inspect_export_json`, `QuickModeExecutorMixin`, `ProfileSessionManager`, `ResourceAwareQueue`, `DomainError`, `WorkspaceExecutorMixin`, `composition.py`, `WorkerContractTests`, `ProgressReporter`, `WorkerRuntimeSettingsTests`, `RcloneRunner`, `WorkerEventPublisher`, `executor_tts.py`, `test_profile_provisioning.py`, `WorkerCommandRunner`, `ProfileManager`, `CommandMilestoneRecorder`, `Path`, `QuickThumbnailBuilder`, `WorkerCommandStore`, `executor.py`, `ProfileProvisioningTests`, `tdl.py`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `create_backend_app()` (e.g. with `_active_storage_item()` and `advance_accepted_operation()`) actually correct?**
  _`create_backend_app()` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `WorkerJobExecutor` (e.g. with `ProfileProvisioningTests` and `QuickThumbnailTests`) actually correct?**
  _`WorkerJobExecutor` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 22 inferred relationships involving `BackendApiTests` (e.g. with `BackendContext` and `ControlPlane`) actually correct?**
  _`BackendApiTests` has 22 INFERRED edges - model-reasoned connections that need verification._