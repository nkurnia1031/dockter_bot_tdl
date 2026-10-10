# Graph Report - dockter_bot_tdl  (2026-10-10)

## Corpus Check
- 282 files · ~269,264 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: (none) 6, .base 1, .resolver 1)

## Summary
- 4823 nodes · 11960 edges · 216 communities (177 shown, 35 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 821 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d37f2919`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ProfileManager
- pindah4.py
- PanelManager
- ProfileSyncClient
- organize_media_from_json.py
- JobRepository
- .patch
- Any
- StateStore
- run.py
- compress.sh
- profiles.py
- ControlPlane
- boltStorage
- format_job_status
- ExportJobResult
- StorageCatalog
- WorkerRuntimeSettings
- UtilityRunner
- compilerOptions
- telegram/app.py
- DownloadExecutorMixin
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
- normalize_tdl_chat_ref
- test_pindah.py
- ProfileProvisioningStore
- ExportWorkspaceState
- executor.py
- register_jobs
- 12. Bootstrap VPS baru dan satu-command deployment
- SqliteSourceRepository
- SqliteAuthRepository
- OperationsService
- migrate_source_state.py
- job-progress.ts
- WorkerHttpDispatcher
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- quick_export.py
- SqliteOperationStore
- WorkerEventPublisher
- _Executor
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
- BotAuthService
- build.py
- WorkerJobExecutor
- register_storage
- BackupService
- Path
- ContainerBuildTests
- ._storage_upload
- settings_store.py
- SubprocessRunner
- TrustedDeviceError
- register_workers
- DomainError
- tdl.py
- pkg_resources.py
- config.py
- register_runtime_settings
- P0 — Akses production dari laptop tepercaya
- Rencana pemisahan backend, worker, dan Web
- WorkerCommandStore
- SharedExportCursorTests
- 21 — Penyederhanaan ENV dan inventaris pemakaian
- utc_now
- ProfileStateStore
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
- normalize_profile_name
- Pengaturan aplikasi dari Web
- JobEvent
- 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress
- 03 — Operation persisten dan transactional outbox
- ProfileTests
- QueueTransportTests
- SqliteQueueState
- 04 — Redis privat dan proses RQ untuk orkestrasi
- TtsExecutorMixin
- TDLClient
- tts_helper.py
- safelink_resolver.py
- 05 — Penerimaan cepat dan kontrak dispatch berversi
- 06 — Alias peer dan serialisasi export lintas worker
- .upload
- 07 — Vault profil berversi dan kontrak tarik/ACK
- 08 — Konfigurasi terpusat, versi penerapan, dan rahasia
- 09 — Jurnal command worker dan outbox event persisten
- 10 — Tarik profil saat startup dan sinkronisasi manual
- 11 — Executor export memakai cursor bersama dan mengarsip state lokal
- WorkerCommandStoreTests
- ProfileRuntime
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
- advance_command
- 00-OVERVIEW.md
- register_device_routes
- register_operations
- devDependencies
- normalize_chat_ref
- ProfileSyncContractTests
- .test_tor_recovery_restarts_only_the_child_process
- QueueOutboxPublisher
- build_backend_context
- WorkspaceExplorer.svelte
- .setUp
- UtilityFolderStore
- decrypt/+page.svelte
- register_utility
- .capabilities
- CommandMilestoneRecorder
- .cancel
- FakePublisher
- Queue
- .check_worker_fast
- TDLCommandError
- ProfilesPage.svelte
- parse_tme3_url
- BackendRuntimeSettings
- SourceMigrationTests
- .resolve_chat_peer
- test_trusted_device_browser_e2e.py
- ._export
- register_queue
- JobTable.svelte
- profile_provisioning.py
- executor_tts.py
- .test_download_progress_callbacks_follow_the_download_lock_owner
- UtilitySettingsStore
- WorkerProfileAdmissionTests
- WorkerCommandRunner
- .test_subprocess_runner_freezes_and_resumes_current_process
- service.py
- .test_build_base_builds_and_exports_only_the_base_image
- HttpStateStore
- ._recover_legacy_quick_stages
- .dispatch_command
- _message_contains_caption
- .__init__
- write_json_atomic_private
- build_base_image
- bootstrap_python_dependencies

## God Nodes (most connected - your core abstractions)
1. `DomainError` - 273 edges
2. `create_backend_app()` - 119 edges
3. `WorkerJobExecutor` - 119 edges
4. `BackendApiTests` - 99 edges
5. `ControlPlane` - 99 edges
6. `SqliteJobRepository` - 91 edges
7. `StorageCatalog` - 86 edges
8. `TelegramFrontendApp` - 76 edges
9. `ProfileProvisioningStore` - 76 edges
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
- `AuthServiceTests` --uses--> `SqliteAuthRepository`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py

## Import Cycles
- None detected.

## Communities (216 total, 35 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.15
Nodes (10): build_profile_config(), ProfileManager, Path, Metadata a worker can safely publish to the backend registry., Return source state without constructing profile TDL clients., Refresh cached session paths after a locked install or rollback., Resolve the session path, including a legacy default-profile location., Check an initialized local TDL session without creating runtime files. (+2 more)

### Community 1 - "pindah4.py"
Cohesion: 0.70
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "ProfileSyncClient"
Cohesion: 0.06
Nodes (28): bundle_for(), FakeSessions, FakeTransport, manifest_row(), WorkerProfileSyncTests, _header(), hmac_compare(), _now() (+20 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory(), entry_identity() (+50 more)

### Community 5 - "JobRepository"
Cohesion: 0.07
Nodes (8): ActorResolver, JobRepository, Any, Protocol, Backend-owned source records with atomic revision-checked commits., SourceRepository, StorageDelivery, WorkerDispatcher

### Community 6 - ".patch"
Cohesion: 0.09
Nodes (14): FakeSubprocessRunner, RcloneRunnerTests, Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Small, cancellable rclone adapter for files already in the workspace., Check remote/config access separately from per-file differences. (+6 more)

### Community 7 - "Any"
Cohesion: 0.16
Nodes (8): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), main_menu_markup(), edit_menu_message()

### Community 8 - "StateStore"
Cohesion: 0.06
Nodes (26): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), StateStoreTests, DownloadProgressSnapshot, DownloadProgressTracker (+18 more)

### Community 9 - "run.py"
Cohesion: 0.16
Nodes (27): active_env_file(), add_profile(), backend_management_request(), build_migration_archive(), configured_service(), data_root_value(), deploy_web(), _download() (+19 more)

### Community 11 - "profiles.py"
Cohesion: 0.19
Nodes (15): configure_logging(), main(), run_backend(), run_queue(), AppConfig, Fail fast when a production role is missing its trust boundary., write_json_atomic(), chown_paths() (+7 more)

### Community 12 - "ControlPlane"
Cohesion: 0.07
Nodes (18): current_actor(), ControlPlane, Any, Exception, Resume queued commands after backend restart or terminal events., Cancel jobs whose worker has stopped reporting progress. Worker cancellation is…, Release only the Quick Mode export phase after durable completion., Update the latest telemetry without growing persistent event history. (+10 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.18
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "ExportJobResult"
Cohesion: 0.09
Nodes (9): WorkerSharedCursorTests, export_from_url(), validate_url(), __init__(), commit(), __init__(), ExportJobResult, Sanitized error returned by the authenticated backend state client. (+1 more)

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

### Community 21 - "DownloadExecutorMixin"
Cohesion: 0.33
Nodes (4): DownloadExecutorMixin, progress_event(), report_snapshot(), Any

### Community 22 - "QuickModeExecutorMixin"
Cohesion: 0.08
Nodes (29): Any, Path, QuickModeExecutorMixin, ensure_not_cancelled(), persist_uploaded_items(), phase_result(), save_manifest(), verify_log() (+21 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.18
Nodes (6): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.10
Nodes (19): Arsitektur, Catatan diagnosis produksi terakhir, Checklist memulai sesi baru, Deployment yang benar, Download Manager: aturan penting, graphify, Jebakan, Langkah operasional berikutnya (+11 more)

### Community 26 - "ProfileSessionManager"
Cohesion: 0.17
Nodes (7): _LoginProcess, ProfileSessionManager, Any, Path, Check whether a legacy profile can be exported without reading session contents., Check identity and both private Bolt session trees without opening Bolt., Narrow TDL login bridge and safe profile session installer for workers.

### Community 27 - "ResourceAwareQueue"
Cohesion: 0.06
Nodes (17): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, ResourceAwareQueueTests, SerialPerKeyQueueTests, handle() (+9 more)

### Community 28 - "backend.py"
Cohesion: 0.07
Nodes (70): register_backups(), register_tdl_access(), get_tdl_access_target(), submit_tdl_access_verification(), ActorResponse, ApiResponse, ApproveChallengeRequest, BackupRuntimeSettingsRequest (+62 more)

### Community 29 - "package.json"
Cohesion: 0.05
Nodes (33): bits-ui, crypto-js, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static (+25 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.05
Nodes (40): patch(), post(), accessIdempotencyKey(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName (+32 more)

### Community 34 - "composition.py"
Cohesion: 0.08
Nodes (28): prepare(), advance_cancel_operation(), advance_profile_sync_cancel(), _complete_sync_operation(), prepare_profile_sync_operation(), Any, cancel_profile_sync(), _elapsed_since() (+20 more)

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
Cohesion: 0.09
Nodes (11): SqliteSourceRepositoryTests, MigrationPlanConflict, PeerAliasNotFound, RuntimeError, StateStore-compatible adapter that binds the shared repository to a profile., A source write was based on an outdated revision., A migration plan or one of its optimistic revision checks is stale., A chat reference has not been resolved by an authenticated TDL worker. (+3 more)

### Community 44 - "api.ts"
Cohesion: 0.13
Nodes (14): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+6 more)

### Community 46 - "LabelStore"
Cohesion: 0.25
Nodes (5): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel

### Community 48 - "vitest"
Cohesion: 0.18
Nodes (5): @testing-library/svelte, vitest, publicKey, { apiMock, postMock }, workerSettings

### Community 49 - "preflight_report"
Cohesion: 0.14
Nodes (20): capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), docker_image_exists(), docker_manifest_exists(), git_remote_revision() (+12 more)

### Community 50 - "normalize_tdl_chat_ref"
Cohesion: 0.24
Nodes (6): ChatReferenceTests, normalize_bot_api_chat_ref(), normalize_tdl_chat_ref(), Canonical chat references for TDL commands and Telegram Bot API targets., Return a canonical TDL peer selector or raise for unsupported input. TDL…, Return the Bot API chat_id representation for an ID or public username.

### Community 52 - "ProfileProvisioningStore"
Cohesion: 0.09
Nodes (8): _now(), ProfileProvisioningStore, Any, Connection, Path, Row, Persistent encrypted session vault and profile distribution state., Keep old worker identity reports as adoption candidates, never as vault data.

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.09
Nodes (18): ExportWorkspaceTests, delete_quick_mode_staging(), loop(), export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate() (+10 more)

### Community 54 - "executor.py"
Cohesion: 0.08
Nodes (40): sha256_file(), bounded_output_tail(), Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Return only the newest output without splitting a line when possible., Redact obvious secret flags and values before persisting a command., sanitize_command(), sanitize_text() (+32 more)

### Community 55 - "register_jobs"
Cohesion: 0.05
Nodes (56): verify_context(), verify_target(), event_dict(), job_dict(), _model_dict(), _newest_first_log_response(), _owned_job(), _profile_artifact() (+48 more)

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - "SqliteSourceRepository"
Cohesion: 0.13
Nodes (11): normalize_peer_identity(), Normalize a TDL-resolved peer identity before it enters the alias map. A…, Connection, Row, Apply approved sources and ledger decisions atomically; return replay status., Keep cross-worker execution gated until workers implement the contract., A lease owner, attempt, or fencing generation is no longer current., Backend-owned, profile-scoped source state in the application database. (+3 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.09
Nodes (8): DeviceAuthTests, _now(), Any, Connection, datetime, Path, Run security-sensitive read/modify/write work under a SQLite write lock., SqliteAuthRepository

### Community 59 - "OperationsService"
Cohesion: 0.09
Nodes (9): _FakeConnection, _FakeJob, _FakeQueue, _canonical(), OperationHandler, OperationsService, Any, Protocol (+1 more)

### Community 60 - "migrate_source_state.py"
Cohesion: 0.18
Nodes (36): canonical_chat_key(), Canonicalize aliases for source state while preserving legacy keys., apply_plan(), build_plan(), _canonical_json(), _check_input_hashes(), _columns(), _coverage() (+28 more)

### Community 61 - "job-progress.ts"
Cohesion: 0.22
Nodes (10): eventLatency, phaseElapsedSeconds, phaseLabel(), stageId, clampPercent(), formatDuration(), JobLike, NormalizedProgress (+2 more)

### Community 62 - "WorkerHttpDispatcher"
Cohesion: 0.15
Nodes (3): Any, RuntimeError, WorkerHttpDispatcher

### Community 63 - "session.svelte.ts"
Cohesion: 0.10
Nodes (10): challenge, contextRevision, current, loading, loadWorkers(), selectedWorkers(), session, SessionWorker (+2 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.11
Nodes (8): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore, help_text(), Text helpers owned by the Telegram presentation adapter., source_digest()

### Community 65 - "SqliteJobRepository"
Cohesion: 0.06
Nodes (21): JobStoreTests, _dump(), _elapsed_between(), _load(), Any, Connection, datetime, Path (+13 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 68 - "quick_export.py"
Cohesion: 0.19
Nodes (18): _archive_files(), _chown_tree(), cleanup_quick_stage(), _clone_tree(), ensure_quick_stage_writable(), ensure_quick_tdl_client(), _json_media_stats(), datetime (+10 more)

### Community 69 - "SqliteOperationStore"
Cohesion: 0.12
Nodes (13): OperationRepository, Operation, Any, _dump(), _load(), _now(), _parse_datetime(), Any (+5 more)

### Community 70 - "WorkerEventPublisher"
Cohesion: 0.11
Nodes (3): Enable durable event delivery while retaining legacy test adapters., Seed event numbering for a reused job ID., WorkerEventPublisher

### Community 71 - "_Executor"
Cohesion: 0.11
Nodes (8): _Executor, _FakePipeline, _FakeTdl, TtsExecutorTests, request(), Build a portable audio filename from the user-visible TTS title., _truncate_utf8(), tts_delivery_filename()

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.10
Nodes (20): A. Langkah di komputer lokal, B. Build melalui GitHub Actions, Batas keamanan, Bootstrap VPS baru dengan `run.py`, Build dan pull image bertahap, C. Langkah di VPS gateway, Concurrency dan pesan status job, E. Update di setiap VPS worker remote (+12 more)

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
Cohesion: 0.16
Nodes (13): _json(), _now(), Any, Connection, Row, ValueError, Import a legacy snapshot once; existing rows and tombstones always win., Import one online worker's local runtime JSON at most once. (+5 more)

### Community 85 - "BotAuthService"
Cohesion: 0.10
Nodes (16): AuthServiceTests, actor(), Path, actor(), BotAuthService, _hash_secret(), TokenPair, _b64url() (+8 more)

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - "WorkerJobExecutor"
Cohesion: 0.10
Nodes (4): Any, Executes domain jobs and publishes JSON events; no UI dependency., Bind the shared tracker callback only while owning its TDL lock., WorkerJobExecutor

### Community 88 - "register_storage"
Cohesion: 0.10
Nodes (30): StorageLinkTests, _active_storage_item(), BackendContext, _deliver_storage_telegram(), _require_storage_folders_idle(), _storage_item(), FastAPI adapters for public and internal JSON contracts., register_storage() (+22 more)

### Community 89 - "BackupService"
Cohesion: 0.11
Nodes (13): BackupServiceTests, make_config(), Path, BackupCoordinator, BackupNodeJob, datetime, Worker-neutral command payload for one node backup., BackupArchive (+5 more)

### Community 90 - "Path"
Cohesion: 0.05
Nodes (30): ExportMilestoneTests, export_from_url(), export_from_url(), Path, QuickThumbnailTests, fake_run(), fake_run(), fake_run() (+22 more)

### Community 92 - "._storage_upload"
Cohesion: 0.15
Nodes (10): StorageWorkerPathTests, Any, Path, Upload workspace files through the worker-local rclone config., StorageExecutorMixin, upload_progress(), Path, Return nested directories, including empty ones, as portable paths. (+2 more)

### Community 93 - "settings_store.py"
Cohesion: 0.17
Nodes (5): AesGcmSecretStore, Path, Encrypt setting values with a persistent owner-only AES-256 key., Path, SettingsConflict

### Community 94 - "SubprocessRunner"
Cohesion: 0.14
Nodes (3): CommandCallback, Popen, SubprocessRunner

### Community 95 - "TrustedDeviceError"
Cohesion: 0.07
Nodes (32): FakeProtector, skipUnless, TrustedDeviceHelperTests, protect(), _browser_executable(), main(), open_trusted_context(), same_origin_only() (+24 more)

### Community 96 - "register_workers"
Cohesion: 0.18
Nodes (10): register_workers(), recover_worker_tts_helper(), remove_worker(), set_worker_enabled(), tts_worker_error(), update_worker(), update_worker_settings(), worker_profile_sync_status() (+2 more)

### Community 97 - "DomainError"
Cohesion: 0.03
Nodes (71): ContractWorkerExecutor, _add_internal_state_routes(), acquire_export_cursor(), commit_export_cursor(), confirm_peer_alias(), heartbeat_export_cursor(), pending_peer_aliases(), require_cursor_service() (+63 more)

### Community 98 - "tdl.py"
Cohesion: 0.07
Nodes (33): OutputCallback, ProgressCallback, Gateway orchestration, channel upload, scheduling, and retention., Create encrypted, runtime-only per-node backup archives., notify_command_completed(), notify_command_started(), _byte_multiplier(), clean_tdl_output_line() (+25 more)

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 100 - "config.py"
Cohesion: 0.17
Nodes (10): ChannelRefTests, update_backup_settings(), Update fields read by the live backend services without replacing config., channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`… (+2 more)

### Community 101 - "register_runtime_settings"
Cohesion: 0.23
Nodes (13): register_runtime_settings(), acknowledge_worker_settings(), desired_store(), get_runtime_settings(), put_runtime_settings(), runtime_settings_schema(), update_runtime_secrets(), validate_target() (+5 more)

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
Nodes (10): FailingCatalog, SharedExportCursorTests, ExportCursorBusy, PeerAliasConflict, PeerAliasCursorConflict, Path, Read source rows and migration ledger without opening unrelated tables., A verified alias already points at a different Telegram peer. (+2 more)

### Community 106 - "21 — Penyederhanaan ENV dan inventaris pemakaian"
Cohesion: 0.14
Nodes (13): 21 — Penyederhanaan ENV dan inventaris pemakaian, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Lampiran — inventaris ENV baseline, Penambahan yang direncanakan (+5 more)

### Community 107 - "utc_now"
Cohesion: 0.13
Nodes (5): datetime, utc_now(), Event, Exception, Keep backend liveness independent from noisy subprocess output. A Quick Mode…

### Community 108 - "ProfileStateStore"
Cohesion: 0.15
Nodes (3): ProfileStateStore, Profile-scoped source state used by export and metadata endpoints., ProfileSelectionStore

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
Cohesion: 0.13
Nodes (4): ExportCursorService, Any, Application service for verified peer aliases and shared export cursors., Keep peer resolution, lease fencing, and artifact/cursor commit ordered. The…

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
Cohesion: 0.18
Nodes (7): normalize_profile_name(), ProfileRegistry, Path, One-way migration for installations created before the registry., Gateway-owned registry for profile metadata, separate from TDL sessions. A…, Apply backend vault identity as authoritative registry data., Accept only new legacy metadata; do not let a worker rewrite identity.

### Community 128 - "Pengaturan aplikasi dari Web"
Cohesion: 0.29
Nodes (6): Kontrak implementasi, Pengaturan aplikasi dari Web, Pengaturan deployment, Pengaturan yang sudah ada di Web, Pengelolaan rahasia, Status migrasi konfigurasi

### Community 129 - "JobEvent"
Cohesion: 0.04
Nodes (16): ControlPlaneTests, FailingDispatcher, FakeDispatcher, FakeExportCursorGate, FakeJobSecretStore, FakeProfiles, IncompatibleDispatcher, WorkerRegistryTests (+8 more)

### Community 130 - "02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress"
Cohesion: 0.17
Nodes (11): 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 131 - "03 — Operation persisten dan transactional outbox"
Cohesion: 0.17
Nodes (11): 03 — Operation persisten dan transactional outbox, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 132 - "ProfileTests"
Cohesion: 0.35
Nodes (3): ProfileTests, Path, build_profile_runtime()

### Community 133 - "QueueTransportTests"
Cohesion: 0.25
Nodes (3): QueueTransportTests, QueueCommandService, Claim and advance an outbox command without running work in a request.

### Community 134 - "SqliteQueueState"
Cohesion: 0.21
Nodes (6): _now(), Any, Connection, datetime, Queue-specific SQLite adapter over the durable operation outbox., SqliteQueueState

### Community 135 - "04 — Redis privat dan proses RQ untuk orkestrasi"
Cohesion: 0.17
Nodes (11): 04 — Redis privat dan proses RQ untuk orkestrasi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 136 - "TtsExecutorMixin"
Cohesion: 0.26
Nodes (4): Any, Path, Keep the opaque artifact for retries, and upload a title-named copy., TtsExecutorMixin

### Community 137 - "TDLClient"
Cohesion: 0.18
Nodes (3): FakeRunner, TDLClientTests, TDLClient

### Community 138 - "tts_helper.py"
Cohesion: 0.22
Nodes (16): get(), healthz(), _bootstrap_percent(), diagnostics(), post, ready(), readyz(), recover_tor() (+8 more)

### Community 139 - "safelink_resolver.py"
Cohesion: 0.05
Nodes (57): Client, Response, ResolverAddonTests, _livewire_page(), _public_dns(), ResolverHttpTests, handler(), handler() (+49 more)

### Community 140 - "05 — Penerimaan cepat dan kontrak dispatch berversi"
Cohesion: 0.17
Nodes (11): 05 — Penerimaan cepat dan kontrak dispatch berversi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 141 - "06 — Alias peer dan serialisasi export lintas worker"
Cohesion: 0.17
Nodes (11): 06 — Alias peer dan serialisasi export lintas worker, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 142 - ".upload"
Cohesion: 0.32
Nodes (5): CompletedProcess, Path, Upload one file and optionally force it to Telegram photo media., Resolve delayed TDL upload results by polling channel history. Some TDL…, UploadResult

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

### Community 149 - "ProfileRuntime"
Cohesion: 0.29
Nodes (5): LeaveResult, LeaveService, CommandCallback, ProfileRuntime, Return an already initialized runtime without creating profile files.

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
Cohesion: 0.05
Nodes (49): _add_management_routes(), management_start_backup(), create_backend_app(), adopt_profile(), advance_accepted_operation(), advance_background_job(), advance_retry_operation(), browser_actor_dict() (+41 more)

### Community 161 - "WorkspaceExecutorMixin"
Cohesion: 0.38
Nodes (4): Any, Path, Return a safe, shallow directory listing for the active workspace., WorkspaceExecutorMixin

### Community 162 - "DurableDispatchTests"
Cohesion: 0.10
Nodes (9): DurableDispatchTests, FakeArtifactCatalog, TdlAccessStoreTests, Any, Connection, Path, Persist destination-specific sender checks and per-target rotation state., _safe_error_code() (+1 more)

### Community 163 - ".setUp"
Cohesion: 0.10
Nodes (3): FakeProfiles, FakeTelegramBot, FakeWorkers

### Community 164 - "WorkerContractTests"
Cohesion: 0.27
Nodes (5): patch, ContractWorkerRegistry, WorkerContractTests, Return the non-secret version and feature set advertised by a worker., worker_contract_metadata()

### Community 165 - "OperationTests"
Cohesion: 0.23
Nodes (3): OperationTests, prepare(), prepare()

### Community 167 - "advance_command"
Cohesion: 0.40
Nodes (5): advance_command(), RuntimeError, QueueAdvanceRetry, A short backend wait; RQ applies the bounded retry policy., Ask the backend to claim and advance one durable command identifier.

### Community 168 - "00-OVERVIEW.md"
Cohesion: 0.11
Nodes (15): File yang disentuh, Kontrak dan perilaku, Kriteria selesai, P1 — Diagnosis dan pemulihan kesiapan helper TTS, Prasyarat dan konteks, Prompt implementasi, Rollback, Tujuan (+7 more)

### Community 169 - "register_device_routes"
Cohesion: 0.25
Nodes (14): register_device_routes(), device_challenge(), device_exchange(), list_devices(), register_device(), remote_key(), rename_device(), require_browser_actor() (+6 more)

### Community 170 - "register_operations"
Cohesion: 0.49
Nodes (10): register_operations(), api_capabilities(), cancel_operation(), get_operation(), list_operations(), _public(), _require_operations(), retry_operation() (+2 more)

### Community 171 - "devDependencies"
Cohesion: 0.15
Nodes (13): devDependencies, jsdom, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss, @tailwindcss/vite (+5 more)

### Community 172 - "normalize_chat_ref"
Cohesion: 0.13
Nodes (7): capabilities(), normalize_chat_ref(), Any, RuntimeError, Canonical source key for usernames, links, phones, and numeric IDs., StateSnapshot, Advertise cursor support only when authenticated backend state is configured.

### Community 174 - ".test_tor_recovery_restarts_only_the_child_process"
Cohesion: 0.12
Nodes (3): skipIf, assert_release(), write_to_fp()

### Community 175 - "QueueOutboxPublisher"
Cohesion: 0.26
Nodes (3): skipUnless, QueueOutboxPublisher, Moves SQLite outbox messages to RQ and repairs missing Redis jobs.

### Community 176 - "build_backend_context"
Cohesion: 0.20
Nodes (4): build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator

### Community 177 - "WorkspaceExplorer.svelte"
Cohesion: 0.28
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 178 - ".setUp"
Cohesion: 0.14
Nodes (4): FakeDispatcher, FakeProfiles, FakeUtilitySettings, FakeWorkerRegistry

### Community 180 - "decrypt/+page.svelte"
Cohesion: 0.08
Nodes (23): copied, decrypt(), encrypted, error, loadResolverJobs(), notice, plaintext, plaintextLink (+15 more)

### Community 181 - "register_utility"
Cohesion: 0.22
Nodes (5): register_utility(), utility_settings_meta(), utility_tree(), Public metadata for clients; never contains a setting value or secret., utility_setting_specs()

### Community 182 - ".capabilities"
Cohesion: 0.22
Nodes (3): Return locally initialized sessions; vault ACK state is diagnostic only., Path, Return non-secret worker capabilities for backend target checks.

### Community 183 - "CommandMilestoneRecorder"
Cohesion: 0.20
Nodes (4): CommandMilestoneRecorder, Persist bounded command results without allowing telemetry to fail work., Create the pending milestone before a subprocess begins work., Complete the pending milestone with bounded, sanitized output.

### Community 186 - "Queue"
Cohesion: 0.18
Nodes (12): Queue, decode_process_output(), find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size() (+4 more)

### Community 187 - ".check_worker_fast"
Cohesion: 0.25
Nodes (5): profile_management(), HTTPRedirectHandler, Check worker availability without loading its full capabilities., Keep authenticated profile bundle transfers on the configured URL., _RejectRedirects

### Community 188 - "TDLCommandError"
Cohesion: 0.16
Nodes (9): BaseException, _FakeTdlClient, TdlAccessWorkerTests, TdlWriteDenialTests, _VerifyExecutor, Return a Telegram error code only for an explicit send-permission denial., tdl_write_denial_code(), TDLCommandError (+1 more)

### Community 189 - "ProfilesPage.svelte"
Cohesion: 0.48
Nodes (5): cancelOperation(), load(), refreshOperation(), sendLoginInput(), submitUpload()

### Community 190 - "parse_tme3_url"
Cohesion: 0.28
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 191 - "BackendRuntimeSettings"
Cohesion: 0.13
Nodes (8): BackendRuntimeSettingsTests, BackendRuntimeSettings, Any, Path, Persistent validated settings that can be applied to a live backend., Use the backend-owned SQLite registry after its one-time legacy import., BackupScheduler, Recheck enabled state or the schedule after a Web update.

### Community 194 - ".resolve_chat_peer"
Cohesion: 0.39
Nodes (4): Any, Raised when TDL returns unusable or malformed export data., Resolve a selector using this authenticated TDL session. The chat listing…, TDLDataError

### Community 195 - "test_trusted_device_browser_e2e.py"
Cohesion: 0.43
Nodes (5): make_test_certificates(), Path, skipUnless, TrustedDevicePlaywrightHttpsE2ETests, prepare_state()

### Community 198 - "JobTable.svelte"
Cohesion: 0.12
Nodes (11): normalizeBotApiChatRef(), normalizeTdlChatRef(), if(), formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem (+3 more)

### Community 199 - "profile_provisioning.py"
Cohesion: 0.23
Nodes (9): extract_single_session(), profile_bundle_identity(), profile_transfer_is_secure(), Read the Telegram identity embedded in a validated bundle., Allow HTTPS remote workers and explicit internal Compose service hosts., Read a ZIP containing exactly one top-level .tdl directory., _safe_zip_entries(), validate_profile_bundle() (+1 more)

### Community 200 - "executor_tts.py"
Cohesion: 0.20
Nodes (9): request_part(), normalize_text(), RuntimeError, Split normalized text into word-aware chunks no longer than 90 chars., Request a fresh Tor circuit without logging the control credential., split_text(), _tor_command(), TtsCancelled (+1 more)

### Community 201 - ".test_download_progress_callbacks_follow_the_download_lock_owner"
Cohesion: 0.53
Nodes (5): first_callback(), first_download(), second_callback(), second_download(), runtime()

### Community 202 - "UtilitySettingsStore"
Cohesion: 0.14
Nodes (3): DesiredSettingsTests, UtilitySettingsTests, UtilitySettingsStore

### Community 205 - ".test_subprocess_runner_freezes_and_resumes_current_process"
Cohesion: 0.40
Nodes (4): CompletedProcess, skipIf, output(), run()

### Community 206 - "service.py"
Cohesion: 0.06
Nodes (9): QuickPipelineTests, download_export_to(), run(), has_downloadable_media(), is_image_message(), Any, DownloadedJsonResult, slugify_label() (+1 more)

### Community 211 - "_message_contains_caption"
Cohesion: 0.67
Nodes (4): _message_contains_caption(), visit(), _normalize_upload_caption(), Match captions across the different JSON shapes emitted by TDL.

### Community 214 - "write_json_atomic_private"
Cohesion: 0.21
Nodes (10): Any, Path, Atomically write JSON containing secrets with owner-only Unix mode., write_json_atomic_private(), ValueError, Validate a remote destination before it reaches a worker command., UtilityPathError, _validate_password() (+2 more)

### Community 217 - "build_base_image"
Cohesion: 0.25
Nodes (9): build_base_archive(), build_base_image(), configured_base_image(), ensure_base_image_available(), login_registry(), Login to the image registry without exposing the PAT in process output., Ensure Docker can resolve the immutable base image before Compose builds.…, Build and export the expensive immutable runtime/Go base image once. (+1 more)

### Community 228 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

## Knowledge Gaps
- **489 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+484 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1499 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **35 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DomainError` connect `DomainError` to `JobEvent`, `ControlPlane`, `WorkerRuntimeSettings`, `WorkerCommandStoreTests`, `QuickModeExecutorMixin`, `backend.py`, `create_backend_app`, `DurableDispatchTests`, `composition.py`, `WorkerContractTests`, `OperationTests`, `register_device_routes`, `register_operations`, `ProfileSyncContractTests`, `ExportWorkspaceState`, `register_utility`, `register_jobs`, `executor.py`, `SqliteAuthRepository`, `.check_worker_fast`, `OperationsService`, `SqliteJobRepository`, `SqliteOperationStore`, `FakeExecutor`, `BotAuthService`, `WorkerJobExecutor`, `register_storage`, `Path`, `register_workers`, `config.py`, `register_runtime_settings`, `WorkerCommandStore`, `SharedExportCursorTests`?**
  _High betweenness centrality (0.149) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `ProfileSyncClient`, `.patch`, `TtsExecutorMixin`, `TDLClient`, `safelink_resolver.py`, `ExportJobResult`, `WorkerRuntimeSettings`, `UtilityRunner`, `DownloadExecutorMixin`, `QuickModeExecutorMixin`, `ProfileSessionManager`, `ResourceAwareQueue`, `WorkspaceExecutorMixin`, `composition.py`, `WorkerContractTests`, `normalize_chat_ref`, `executor.py`, `CommandMilestoneRecorder`, `.capabilities`, `.cancel`, `TDLCommandError`, `._export`, `WorkerEventPublisher`, `_Executor`, `WorkerProfileAdmissionTests`, `WorkerCommandRunner`, `HttpStateStore`, `._recover_legacy_quick_stages`, `Path`, `._storage_upload`, `DomainError`, `tdl.py`, `WorkerCommandStore`, `utc_now`, `ProfileProvisioningTests`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Why does `JsonHttpError` connect `JsonHttpError` to `register_workers`, `composition.py`, `WorkerContractTests`, `BackendApiTests`, `WorkerEventPublisher`, `request_json`, `.dispatch_command`, `telegram/app.py`, `executor.py`, `TelegramFrontendApp`, `.check_worker_fast`, `backend.py`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 38 inferred relationships involving `create_backend_app()` (e.g. with `_active_storage_item()` and `advance_accepted_operation()`) actually correct?**
  _`create_backend_app()` has 38 INFERRED edges - model-reasoned connections that need verification._
- **Are the 31 inferred relationships involving `WorkerJobExecutor` (e.g. with `ProfileProvisioningTests` and `QuickThumbnailTests`) actually correct?**
  _`WorkerJobExecutor` has 31 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `BackendApiTests` (e.g. with `BackendContext` and `ControlPlane`) actually correct?**
  _`BackendApiTests` has 23 INFERRED edges - model-reasoned connections that need verification._