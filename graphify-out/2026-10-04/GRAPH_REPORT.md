# Graph Report - dockter_bot_tdl  (2026-10-04)

## Corpus Check
- 236 files · ~198,879 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 9 file(s) not represented in the graph (top: (none) 6, .base 1, .conf 1)

## Summary
- 3593 nodes · 8560 edges · 163 communities (137 shown, 22 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 548 edges (avg confidence: 0.91)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c5c76b3b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- BackupService
- pindah4.py
- PanelManager
- BatchDownloadService
- organize_media_from_json.py
- Job
- normalize_tdl_chat_ref
- ProfileProvisioningTests
- TDLClient
- Path
- compress.sh
- create_worker_app
- Any
- boltStorage
- format_job_status
- executor.py
- StorageCatalog
- normalize_profile_name
- tme3bot/utility.py
- compilerOptions
- telegram/app.py
- ServiceTests
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
- FakeDispatcher
- ExportArtifactCatalog
- BackendApiTests
- ProgressReporter
- main
- +layout.ts
- 8. Urutan implementasi
- TtsPipeline
- state.py
- api.ts
- RunScriptTests
- LabelStore
- vitest
- run.py
- create_backend_app
- test_pindah.py
- ProfileProvisioningStore
- ExportWorkspaceState
- DownloadProgressTracker
- register_jobs
- 12. Bootstrap VPS baru dan satu-command deployment
- BackendContext
- SqliteAuthRepository
- ControlPlane
- tdl_output.py
- job-progress.ts
- presentation.ts
- session.svelte.ts
- ExportWorkspaceStore
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- register_workers
- composition.py
- ProfileTests
- .test_tts_uploads_each_part_with_active_profile_tdl_session
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
- ProfileRegistry
- WorkerApiTests
- build.py
- WorkerRuntimeSettings
- register_storage
- JobEvent
- .test_download_progress_callbacks_follow_the_download_lock_owner
- ContainerBuildTests
- WorkerJobExecutor
- Path
- WorkerHttpDispatcher
- TrustedDeviceStore
- WorkerRegistry
- migrate_images
- profiles.py
- pkg_resources.py
- register_utility
- P0 — Akses production dari laptop tepercaya
- 00-OVERVIEW.md
- ._storage_upload
- pindah.py
- 21 — Penyederhanaan ENV dan inventaris pemakaian
- RcloneRunner
- DomainError
- PROGRESS.md
- Arsitektur Sistem tme3bot
- routes/__init__.py
- JsonHttpError
- ARSITEKTUR_SISTEM.md
- tme3bot
- ExportService
- tests/__init__.py
- WorkspaceExplorer.svelte
- StateStore
- 01 — Repository state backend dan pemisahan runtime profil
- FakeStatusPanel
- D. Menambah worker remote baru
- Rekomendasi berikutnya
- Autentikasi GitHub dan GHCR
- Update berikutnya
- Context target per fitur dan Download global
- Rollback
- bootstrap_python_dependencies
- Pengaturan aplikasi dari Web
- WorkerEventPublisher
- 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress
- 03 — Operation persisten dan transactional outbox
- JobTable.svelte
- split_text
- .setUp
- 04 — Redis privat dan proses RQ untuk orkestrasi
- TtsExecutorMixin
- test_backend_api.py
- tts_helper.py
- ProfileProvisioningService
- 05 — Penerimaan cepat dan kontrak dispatch berversi
- 06 — Alias peer dan serialisasi export lintas worker
- test_profile_provisioning.py
- 07 — Vault profil berversi dan kontrak tarik/ACK
- 08 — Konfigurasi terpusat, versi penerapan, dan rahasia
- 09 — Jurnal command worker dan outbox event persisten
- 10 — Tarik profil saat startup dan sinkronisasi manual
- 11 — Executor export memakai cursor bersama dan mengarsip state lokal
- .test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage
- http_client.py
- 12 — Supervisor login TDL yang tidak bergantung pada browser
- 13 — Workflow profil upload, login, adopsi, dan distribusi
- 14 — Penerapan konfigurasi worker saat aman
- 15 — Bootstrap persisten dan reload client layanan
- 16 — Aksi Quick Mode sebagai operation background
- 17 — Pemeriksaan Storage, Utility, dan target melalui antrean
- 18 — Halaman Profil pulih setelah ditutup
- 19 — Monitor progress terpusat dan refresh berdasarkan aksi
- 20 — Pengaturan Web dengan desired/applied status
- .verify_files
- .test_subprocess_runner_freezes_and_resumes_current_process
- .test_build_base_builds_and_exports_only_the_base_image
- _FakeTdl

## God Nodes (most connected - your core abstractions)
1. `DomainError` - 183 edges
2. `create_backend_app()` - 95 edges
3. `StorageCatalog` - 86 edges
4. `WorkerJobExecutor` - 81 edges
5. `TelegramFrontendApp` - 76 edges
6. `BackendApiTests` - 69 edges
7. `SqliteJobRepository` - 68 edges
8. `ControlPlane` - 64 edges
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

## Communities (163 total, 22 thin omitted)

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
Cohesion: 0.21
Nodes (10): BatchDownloadResult, BatchDownloadService, _is_relative_to(), media_ids_in_export(), Path, Download selected opaque filenames after strict directory validation., Download selected pending/failed JSON files from validated roots., Download one export into a caller-owned staging directory. Quick Mode owns the… (+2 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.08
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.08
Nodes (10): Protocol, Update the latest telemetry without growing persistent event history., Return whether a transient worker snapshot advanced the job., Attach phase timing and event latency to this job's own event., ActorResolver, JobRepository, Any, StorageDelivery (+2 more)

### Community 6 - "normalize_tdl_chat_ref"
Cohesion: 0.06
Nodes (29): BackendRuntimeSettingsTests, ChannelRefTests, ChatReferenceTests, ParseTme3UrlTests, update_backup_settings(), submit_leave(), BackendRuntimeSettings, Any (+21 more)

### Community 7 - "ProfileProvisioningTests"
Cohesion: 0.12
Nodes (9): FakeProfileDispatcher, FakeProfileManager, FakeWorkerRegistry, make_config(), MutableWorkerRegistry, ProfileProvisioningTests, Path, single_session_zip() (+1 more)

### Community 8 - "TDLClient"
Cohesion: 0.06
Nodes (32): OutputCallback, ProgressCallback, Queue, FakeRunner, TDLClientTests, has_downloadable_media(), is_image_message(), Any (+24 more)

### Community 9 - "Path"
Cohesion: 0.19
Nodes (16): build_base_archive(), build_base_image(), deploy_web(), _download(), find_host_tdl(), _github_repository(), hmac_compare(), _install_static_release() (+8 more)

### Community 11 - "create_worker_app"
Cohesion: 0.08
Nodes (18): create_worker_app(), authorize(), domain_error(), export_profile_bundle(), install_profile_bundle(), job_log_snapshot(), profile_login_bundle(), profile_login_input() (+10 more)

### Community 12 - "Any"
Cohesion: 0.14
Nodes (9): Thread, Any, Recover subscriptions after the Telegram container restarts., expire(), expire(), loop(), loop(), main_menu_markup() (+1 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): context.Context, github.com/gotd/td/telegram/peers.Manager, github.com/gotd/td/tg.Client, go.etcd.io/bbolt.DB, boltStorage, fail(), leave(), main() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.18
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "executor.py"
Cohesion: 0.08
Nodes (62): bounded_output_tail(), Safe, bounded command output helpers used by worker milestones., Remove known and obvious secret values from command output., Return only the newest output without splitting a line when possible., Redact obvious secret flags and values before persisting a command., sanitize_command(), sanitize_text(), discard_export_without_media() (+54 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (19): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+11 more)

### Community 17 - "normalize_profile_name"
Cohesion: 0.14
Nodes (8): normalize_profile_name(), ProfileManager, ProfileSelectionStore, Path, Metadata a worker can safely publish to the backend registry., Resolve the session path, including a legacy default-profile location., Return whether TDL initialized its Bolt database in this session root., _tdl_session_database_ready()

### Community 18 - "tme3bot/utility.py"
Cohesion: 0.08
Nodes (16): UtilitySummaryTests, notify_command_completed(), notify_command_started(), pause_process_group(), ProcessStalledError, Notify an observer without making telemetry a process dependency. New observers…, Notify completion, supporting both new and legacy command observers., Raised when a worker subprocess stops making meaningful progress. (+8 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.16
Nodes (24): canonical_chat_key(), Canonicalize aliases for source state while preserving legacy keys., PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup() (+16 more)

### Community 21 - "ServiceTests"
Cohesion: 0.24
Nodes (6): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, download(), ExportResult

### Community 22 - "QuickModeExecutorMixin"
Cohesion: 0.09
Nodes (23): ExportJobResult, Any, Path, QuickModeExecutorMixin, ensure_not_cancelled(), persist_uploaded_items(), phase_result(), save_manifest() (+15 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.18
Nodes (6): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

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
Nodes (52): register_backups(), start_backup(), register_runtime_settings(), update_runtime_secrets(), register_sources(), add_label(), get_source(), update_source() (+44 more)

### Community 29 - "package.json"
Cohesion: 0.04
Nodes (42): bits-ui, flowbite-svelte, jsdom, @lucide/svelte, svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit (+34 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (35): patch(), post(), if(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName (+27 more)

### Community 34 - "FakeDispatcher"
Cohesion: 0.10
Nodes (4): FailingDispatcher, FakeDispatcher, FakeProfiles, IncompatibleDispatcher

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.14
Nodes (8): ExportArtifactCatalogTests, ExportArtifactCatalog, Any, Connection, Upsert an inventory batch in one SQLite transaction. Inventory can contain…, Mark catalog rows absent when a worker inventory completes., Remove a missing file from the runnable queue. The physical file is already…, utc_now()

### Community 37 - "ProgressReporter"
Cohesion: 0.06
Nodes (24): FakePublisher, ProgressReporterTests, Gateway orchestration, channel upload, scheduling, and retention., sha256_file(), _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events. (+16 more)

### Community 38 - "main"
Cohesion: 0.20
Nodes (20): active_env_file(), backend_management_request(), deploy_all(), deploy_application(), ensure_profile_root(), load_env_file(), main(), manage_backup() (+12 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 42 - "TtsPipeline"
Cohesion: 0.15
Nodes (5): Any, Event, Path, Three-route gTTS pipeline with stable per-part checkpoints., TtsPipeline

### Community 43 - "state.py"
Cohesion: 0.15
Nodes (8): utc_now_iso(), HttpStateStore, normalize_chat_ref(), Any, Canonical source key for usernames, links, phones, and numeric IDs., StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 44 - "api.ts"
Cohesion: 0.16
Nodes (14): api(), ApiError, beginRequest(), csrf(), emitRequestEvent(), endRequest(), put(), remove() (+6 more)

### Community 46 - "LabelStore"
Cohesion: 0.25
Nodes (5): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel

### Community 48 - "vitest"
Cohesion: 0.22
Nodes (3): @testing-library/svelte, vitest, publicKey

### Community 49 - "run.py"
Cohesion: 0.16
Nodes (26): add_profile(), capture_compose(), _command_available(), _compose_available(), compose_base_command(), compose_env(), configured_service(), data_root_value() (+18 more)

### Community 50 - "create_backend_app"
Cohesion: 0.07
Nodes (38): create_backend_app(), adopt_profile(), browser_actor_dict(), browser_challenge(), browser_challenge_status(), browser_logout(), browser_profile(), browser_refresh() (+30 more)

### Community 52 - "ProfileProvisioningStore"
Cohesion: 0.15
Nodes (6): _now(), ProfileProvisioningStore, Any, Connection, Path, Persistent encrypted session vault and profile distribution state.

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.09
Nodes (16): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), is_numeric_chat_ref(), normalize_chat_ref() (+8 more)

### Community 55 - "register_jobs"
Cohesion: 0.06
Nodes (48): verify_context(), verify_target(), event_dict(), job_dict(), _model_dict(), _newest_first_log_response(), _owned_job(), _profile_artifact() (+40 more)

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - "BackendContext"
Cohesion: 0.12
Nodes (7): _add_internal_state_routes(), sync_profiles(), _add_management_routes(), management_start_backup(), BackendContext, FastAPI, FastAPI adapters for public and internal JSON contracts.

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.05
Nodes (27): Enum, str, AuthServiceTests, actor(), Path, DeviceAuthTests, actor(), AuthChallengeStatus (+19 more)

### Community 59 - "ControlPlane"
Cohesion: 0.11
Nodes (12): ControlPlane, Any, Exception, Persist a worker's Quick Mode capacity and dispatch any new slots., Application facade used by every frontend adapter., Resume queued commands after backend restart or terminal events., Cancel jobs whose worker has stopped reporting progress. Worker cancellation is…, Restart an export attempt while preserving its stable job ID. (+4 more)

### Community 60 - "tdl_output.py"
Cohesion: 0.13
Nodes (19): Create encrypted, runtime-only per-node backup archives., _byte_multiplier(), clean_tdl_output_line(), CommandProgress, _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), parse_elapsed_seconds() (+11 more)

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

### Community 68 - "register_workers"
Cohesion: 0.19
Nodes (11): register_workers(), remove_worker(), set_worker_enabled(), update_worker(), update_worker_settings(), worker_settings(), WorkerEnabledRequest, WorkerRequest (+3 more)

### Community 69 - "composition.py"
Cohesion: 0.19
Nodes (10): configure_logging(), main(), build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, run_backend(), run_worker() (+2 more)

### Community 70 - "ProfileTests"
Cohesion: 0.32
Nodes (4): ProfileTests, Path, build_profile_runtime(), set_profile_download_mode()

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
Cohesion: 0.15
Nodes (4): make_pipeline(), TtsPipelineTests, request_part(), request_part()

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 84 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 85 - "WorkerApiTests"
Cohesion: 0.09
Nodes (3): WorkerApiTests, ContractWorkerExecutor, WorkerContext

### Community 86 - "build.py"
Cohesion: 0.28
Nodes (14): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+6 more)

### Community 87 - "WorkerRuntimeSettings"
Cohesion: 0.06
Nodes (23): UtilitySettingsTests, Path, RuntimeProfileManager, WorkerRuntimeSettingsTests, Any, Path, Atomically write JSON containing secrets with owner-only Unix mode., write_json_atomic_private() (+15 more)

### Community 88 - "register_storage"
Cohesion: 0.08
Nodes (39): BaseModel, StorageLinkTests, _active_storage_item(), _deliver_storage_telegram(), _require_storage_folders_idle(), _storage_item(), delete_quick_mode_staging(), register_storage() (+31 more)

### Community 89 - "JobEvent"
Cohesion: 0.09
Nodes (3): ControlPlaneTests, JobStoreTests, JobEvent

### Community 90 - ".test_download_progress_callbacks_follow_the_download_lock_owner"
Cohesion: 0.53
Nodes (5): first_callback(), first_download(), second_callback(), second_download(), runtime()

### Community 92 - "WorkerJobExecutor"
Cohesion: 0.05
Nodes (19): datetime, utc_now(), Any, Event, Exception, Path, Keep backend liveness independent from noisy subprocess output. A Quick Mode…, Executes domain jobs and publishes JSON events; no UI dependency. (+11 more)

### Community 93 - "Path"
Cohesion: 0.05
Nodes (20): ExportMilestoneTests, export_from_url(), export_from_url(), Path, QuickThumbnailTests, fake_run(), fake_run(), fake_run() (+12 more)

### Community 94 - "WorkerHttpDispatcher"
Cohesion: 0.15
Nodes (5): profile_management(), Any, RuntimeError, Check worker availability without loading its full capabilities., WorkerHttpDispatcher

### Community 95 - "TrustedDeviceStore"
Cohesion: 0.08
Nodes (24): ArgumentParser, skipUnless, FakeProtector, TrustedDeviceHelperTests, protect(), browser_state(), build_parser(), canonical_payload() (+16 more)

### Community 96 - "WorkerRegistry"
Cohesion: 0.17
Nodes (7): WorkerRegistryTests, _as_enabled(), normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., Return workers that may receive new jobs. A disabled worker remains in…, WorkerRegistry

### Community 97 - "migrate_images"
Cohesion: 0.20
Nodes (11): build_migration_archive(), configured_base_image(), ensure_base_image_available(), login_registry(), migrate_images(), Login to the image registry without exposing the PAT in process output., Build both split deployment images and package them for an offline load., Stop early when extracted base artifacts no longer match the source. (+3 more)

### Community 98 - "profiles.py"
Cohesion: 0.17
Nodes (12): LeaveResult, LeaveService, CommandCallback, write_json_atomic(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs(), get_profile_download_mode() (+4 more)

### Community 99 - "pkg_resources.py"
Cohesion: 0.29
Nodes (7): PackageNotFoundError, DistributionNotFound, get_distribution(), iter_entry_points(), Small importlib-backed compatibility shim for legacy APScheduler. python-…, Compatibility name used by APScheduler 3.x., Return importlib entry points with the old pkg_resources API shape.

### Community 101 - "register_utility"
Cohesion: 0.22
Nodes (5): register_utility(), utility_settings_meta(), utility_tree(), Public metadata for clients; never contains a setting value or secret., utility_setting_specs()

### Community 102 - "P0 — Akses production dari laptop tepercaya"
Cohesion: 0.11
Nodes (17): API perangkat milik actor, Cara verifikasi, Challenge dan signature, File yang disentuh, Helper Windows, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai (+9 more)

### Community 103 - "00-OVERVIEW.md"
Cohesion: 0.12
Nodes (14): Arsitektur target, Aturan agent pelaksana, Baseline audit — 2026-10-04, Asia/Jakarta, Cara memakai paket, Gerbang kompatibilitas dan migrasi, Keputusan dan kontrak bersama, Rencana pemisahan backend, worker, dan Web, Urutan dan ketergantungan (+6 more)

### Community 104 - "._storage_upload"
Cohesion: 0.18
Nodes (8): StorageWorkerPathTests, Any, Path, Upload workspace files through the worker-local rclone config., Path, Return nested directories, including empty ones, as portable paths., storage_logical_folder(), storage_relative_folders()

### Community 105 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 106 - "21 — Penyederhanaan ENV dan inventaris pemakaian"
Cohesion: 0.14
Nodes (13): 21 — Penyederhanaan ENV dan inventaris pemakaian, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Lampiran — inventaris ENV baseline, Penambahan yang direncanakan (+5 more)

### Community 107 - "RcloneRunner"
Cohesion: 0.14
Nodes (5): FakeSubprocessRunner, RcloneRunnerTests, CommandCallback, Small, cancellable rclone adapter for files already in the workspace., RcloneRunner

### Community 108 - "DomainError"
Cohesion: 0.12
Nodes (29): register_device_routes(), device_challenge(), device_exchange(), list_devices(), register_device(), remote_key(), rename_device(), require_browser_actor() (+21 more)

### Community 109 - "PROGRESS.md"
Cohesion: 0.14
Nodes (12): 22 — Uji kegagalan lintas komponen dan panduan cutover, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+4 more)

### Community 110 - "Arsitektur Sistem tme3bot"
Cohesion: 0.18
Nodes (11): Alur job, Antrean dan kerja bersamaan, Arsitektur Sistem tme3bot, Bagian sistem, Data dan keamanan, Deployment dan source map, Komunikasi backend dan worker, Quick Mode dan folder staging (+3 more)

### Community 113 - "ARSITEKTUR_SISTEM.md"
Cohesion: 0.29
Nodes (4): Aktifkan satu worker untuk uji coba, Pemeriksaan uji coba, Persiapan, TTS Novel: konfigurasi dan rollout

### Community 114 - "tme3bot"
Cohesion: 0.22
Nodes (9): Arsitektur, Build Docker melalui GitHub Actions, Job dan progress, Login web melalui bot, Setup VPS utama, Storage dan backup, tme3bot, Verifikasi (+1 more)

### Community 115 - "ExportService"
Cohesion: 0.27
Nodes (4): build_telegram_message_url(), ExportService, Any, ParsedTme3Url

### Community 117 - "WorkspaceExplorer.svelte"
Cohesion: 0.13
Nodes (9): crumbs, error, folders, goUp(), load(), loading, openCrumb(), clear() (+1 more)

### Community 118 - "StateStore"
Cohesion: 0.26
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

### Community 127 - "bootstrap_python_dependencies"
Cohesion: 0.33
Nodes (6): bootstrap_python_dependencies(), _pip_supports_flag(), _python_requirements_ready(), Install this CLI's Python dependencies when a VPS is truly new., Return whether it is safe to use the Debian-package fallback. The fallback is…, _system_python_install_fallback_available()

### Community 128 - "Pengaturan aplikasi dari Web"
Cohesion: 0.29
Nodes (6): Kontrak implementasi, Pengaturan aplikasi dari Web, Pengaturan deployment, Pengaturan yang sudah ada di Web, Pengelolaan rahasia, Status migrasi konfigurasi

### Community 129 - "WorkerEventPublisher"
Cohesion: 0.14
Nodes (5): patch, ContractWorkerRegistry, WorkerContractTests, Seed event numbering for a reused job ID., WorkerEventPublisher

### Community 130 - "02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress"
Cohesion: 0.17
Nodes (11): 02 — Inventarisasi dan migrasi state lama tanpa kehilangan progress, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 131 - "03 — Operation persisten dan transactional outbox"
Cohesion: 0.17
Nodes (11): 03 — Operation persisten dan transactional outbox, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 133 - "split_text"
Cohesion: 0.19
Nodes (4): skipIf, normalize_text(), Split normalized text into word-aware chunks no longer than 90 chars., split_text()

### Community 134 - ".setUp"
Cohesion: 0.10
Nodes (3): FakeProfiles, FakeTelegramBot, FakeWorkers

### Community 135 - "04 — Redis privat dan proses RQ untuk orkestrasi"
Cohesion: 0.17
Nodes (11): 04 — Redis privat dan proses RQ untuk orkestrasi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 136 - "TtsExecutorMixin"
Cohesion: 0.19
Nodes (9): _Executor, Any, Path, TtsExecutorMixin, RuntimeError, Request a fresh Tor circuit without logging the control credential., _tor_command(), TtsCancelled (+1 more)

### Community 137 - "test_backend_api.py"
Cohesion: 0.13
Nodes (11): _elapsed_since(), datetime, serializable(), Application services and use cases., build_execution_plan(), JobExecutionPlan, Any, Internal scheduling metadata shared by backend and worker. (+3 more)

### Community 138 - "tts_helper.py"
Cohesion: 0.31
Nodes (8): get, post, ready(), readyz(), renew_tor_circuit(), synthesize_part(), _tor_ready(), _tor_status()

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

### Community 148 - ".test_pipeline_passes_compress_settings_uploads_both_files_and_cleans_stage"
Cohesion: 0.08
Nodes (5): QuickPipelineTests, download_export_to(), run(), DownloadedJsonResult, UtilityResult

### Community 149 - "http_client.py"
Cohesion: 0.17
Nodes (11): HTTPRedirectHandler, capabilities(), FastAPI, Any, Versioned wire contract shared by the backend and worker processes., Return the non-secret version and feature set advertised by a worker., Reject workers whose advertised API cannot satisfy a backend operation., require_worker_contract() (+3 more)

### Community 150 - "12 — Supervisor login TDL yang tidak bergantung pada browser"
Cohesion: 0.17
Nodes (11): 12 — Supervisor login TDL yang tidak bergantung pada browser, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 151 - "13 — Workflow profil upload, login, adopsi, dan distribusi"
Cohesion: 0.17
Nodes (11): 13 — Workflow profil upload, login, adopsi, dan distribusi, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

### Community 152 - "14 — Penerapan konfigurasi worker saat aman"
Cohesion: 0.17
Nodes (11): 14 — Penerapan konfigurasi worker saat aman, Cara verifikasi, File yang disentuh, Konteks khusus task, Kontrak dan perilaku, Kriteria selesai, Prasyarat, Prompt untuk agent pelaksana (+3 more)

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

### Community 159 - ".verify_files"
Cohesion: 0.26
Nodes (8): Path, RuntimeError, Raised when an rclone transfer cannot be completed., Verify exact remote files without downloading or mutating them., Check remote/config access separately from per-file differences., RcloneError, inventory_matches(), remote_inventory()

### Community 160 - ".test_subprocess_runner_freezes_and_resumes_current_process"
Cohesion: 0.40
Nodes (4): CompletedProcess, skipIf, output(), run()

## Knowledge Gaps
- **452 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+447 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1160 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DomainError` connect `DomainError` to `WorkerEventPublisher`, `Job`, `normalize_tdl_chat_ref`, `test_backend_api.py`, `create_worker_app`, `executor.py`, `http_client.py`, `QuickModeExecutorMixin`, `backend.py`, `FakeDispatcher`, `create_backend_app`, `register_jobs`, `BackendContext`, `SqliteAuthRepository`, `ControlPlane`, `register_workers`, `FakeExecutor`, `WorkerApiTests`, `WorkerRuntimeSettings`, `register_storage`, `JobEvent`, `WorkerJobExecutor`, `Path`, `WorkerHttpDispatcher`, `register_utility`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `WorkerJobExecutor` connect `WorkerJobExecutor` to `WorkerEventPublisher`, `composition.py`, `ProgressReporter`, `ProfileProvisioningTests`, `TDLClient`, `TtsExecutorMixin`, `RcloneRunner`, `DomainError`, `test_profile_provisioning.py`, `executor.py`, `tme3bot/utility.py`, `QuickModeExecutorMixin`, `WorkerRuntimeSettings`, `ProfileSessionManager`, `ResourceAwareQueue`, `Path`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Why does `JsonHttpError` connect `JsonHttpError` to `WorkerEventPublisher`, `register_workers`, `test_backend_api.py`, `request_json`, `executor.py`, `telegram/app.py`, `http_client.py`, `TelegramFrontendApp`, `WorkerHttpDispatcher`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 14 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `ControlPlaneTests`) actually correct?**
  _`DomainError` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 33 inferred relationships involving `create_backend_app()` (e.g. with `_active_storage_item()` and `browser_actor_dict()`) actually correct?**
  _`create_backend_app()` has 33 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `BackupServiceTests`) actually correct?**
  _`StorageCatalog` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `WorkerJobExecutor` (e.g. with `ProfileProvisioningTests` and `QuickThumbnailTests`) actually correct?**
  _`WorkerJobExecutor` has 18 INFERRED edges - model-reasoned connections that need verification._