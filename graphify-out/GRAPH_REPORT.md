# Graph Report - dockter_bot_tdl  (2026-08-25)

## Corpus Check
- 146 files · ~88,406 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1889 nodes · 4856 edges · 83 communities (67 shown, 16 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 445 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3f1ad016`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ProfileRegistry
- pindah4.py
- PanelManager
- AppConfig
- organize_media_from_json.py
- JobEvent
- WorkerRegistry
- BatchDownloadService
- ProfileTests
- run.py
- compress.sh
- config.py
- Any
- boltStorage
- format_job_status
- BackendApiTests
- StorageCatalog
- JobStoreTests
- BackupService
- compilerOptions
- telegram/app.py
- ExportService
- WorkerJobExecutor
- tme3bot-leave-helper
- TelegramFrontendApp
- tme3bot Agent Context
- extract.py
- ResourceAwareQueue
- backend.py
- devDependencies
- StoragePage.svelte
- tme3bot/__init__.py
- pindah.sh script
- svelte.config.js
- ExportArtifactCatalog
- BackupCoordinator
- TDLClient
- +layout.ts
- 8. Urutan implementasi
- StateStore
- api.ts
- request_json
- build_execution_plan
- DownloadProgressTracker
- FakeProfiles
- test_pindah.py
- ControlPlaneBackupRouter
- ExportWorkspaceState
- StorageMaintenanceService
- FakeStatusPanel
- 12. Bootstrap VPS baru dan satu-command deployment
- AuthServiceTests
- SqliteAuthRepository
- ControlPlane
- WorkspaceExplorer.svelte
- job-progress.ts
- presentation.ts
- session.svelte.ts
- test_app_menu.py
- SqliteJobRepository
- Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram
- 4. Arsitektur scheduler
- Overview.svelte
- LabelStore
- pindah.py
- tme3bot/app.py
- TME3Bot Deployment Runbook
- composition.py
- ../styles.css
- ArchitectureBoundaryTests
- 5. Pesan status sementara untuk semua job
- _error
- infrastructure/__init__.py
- 2. Temuan dari kode saat ini
- 6. Source picker Export Fokus
- 3. Keputusan desain
- ControlPlaneTests

## God Nodes (most connected - your core abstractions)
1. `StorageCatalog` - 93 edges
2. `TelegramFrontendApp` - 83 edges
3. `BackendContext` - 72 edges
4. `SqliteJobRepository` - 54 edges
5. `ControlPlane` - 48 edges
6. `StateStore` - 47 edges
7. `AppConfig` - 44 edges
8. `JobEvent` - 43 edges
9. `WorkerJobExecutor` - 41 edges
10. `DomainError` - 38 edges

## Surprising Connections (you probably didn't know these)
- `FakePanel` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `FakePanel` --uses--> `ExportWorkspaceStore`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/export_workspace.py
- `FakeClient` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `FakeClient` --uses--> `ExportWorkspaceStore`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/export_workspace.py
- `AppMenuTests` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py

## Import Cycles
- None detected.

## Communities (83 total, 16 thin omitted)

### Community 0 - "ProfileRegistry"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions. A…, One-way migration for installations created before the registry.

### Community 1 - "pindah4.py"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "AppConfig"
Cohesion: 0.11
Nodes (21): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), Any, Path, write_json_atomic(), build_profile_config(), build_profile_runtime() (+13 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "JobEvent"
Cohesion: 0.11
Nodes (14): Enum, Protocol, Update the latest telemetry without growing persistent event history., ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher (+6 more)

### Community 6 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 7 - "BatchDownloadService"
Cohesion: 0.12
Nodes (20): LeaveResult, LeaveService, has_downloadable_media(), is_image_message(), Any, BatchDownloadResult, BatchDownloadService, DownloadedJsonResult (+12 more)

### Community 9 - "run.py"
Cohesion: 0.05
Nodes (93): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+85 more)

### Community 11 - "config.py"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`…, load_dotenv(), _parse_named_values()

### Community 12 - "Any"
Cohesion: 0.13
Nodes (7): Thread, PendingInput, Any, Recover subscriptions after the Telegram container restarts., main_menu_markup(), edit_menu_message(), source_digest()

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.20
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (18): item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption(), _caption_value(), Connection, Path (+10 more)

### Community 18 - "BackupService"
Cohesion: 0.07
Nodes (21): BackupServiceTests, make_config(), Path, UtilitySettingsTests, UtilitySummaryTests, BackupArchive, BackupService, Path (+13 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.15
Nodes (24): Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_compact_markup(), _export_source_picker_markup() (+16 more)

### Community 21 - "ExportService"
Cohesion: 0.26
Nodes (7): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, build_telegram_message_url(), ExportService, ExportResult

### Community 22 - "WorkerJobExecutor"
Cohesion: 0.06
Nodes (27): FakePublisher, ProgressReporterTests, StorageWorkerPathTests, sha256_file(), JsonHttpError, _progress_percent(), ProgressReporter, Any (+19 more)

### Community 24 - "TelegramFrontendApp"
Cohesion: 0.20
Nodes (6): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "extract.py"
Cohesion: 0.33
Nodes (11): cleanup_empty_directory(), emit_progress(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main() (+3 more)

### Community 27 - "ResourceAwareQueue"
Cohesion: 0.09
Nodes (14): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, ResourceAwareQueueTests, SerialPerKeyQueueTests, Exception (+6 more)

### Community 28 - "backend.py"
Cohesion: 0.07
Nodes (80): BaseModel, StorageLinkTests, _active_storage_item(), _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _deliver_storage_telegram() (+72 more)

### Community 29 - "devDependencies"
Cohesion: 0.05
Nodes (43): bits-ui, jsdom, @lucide/svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss (+35 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.07
Nodes (30): post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver(), displayName (+22 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.15
Nodes (10): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape. (+2 more)

### Community 36 - "BackupCoordinator"
Cohesion: 0.15
Nodes (6): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup.

### Community 37 - "TDLClient"
Cohesion: 0.06
Nodes (38): OutputCallback, Popen, ProgressCallback, Queue, FakeRunner, TDLClientTests, decode_process_output(), _message_contains_caption() (+30 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 43 - "StateStore"
Cohesion: 0.11
Nodes (11): StateStoreTests, utc_now_iso(), HttpStateStore, normalize_chat_ref(), Any, Path, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file. (+3 more)

### Community 44 - "api.ts"
Cohesion: 0.18
Nodes (9): api(), ApiError, csrf(), patch(), put(), remove(), renameFolder(), saveItem() (+1 more)

### Community 45 - "request_json"
Cohesion: 0.07
Nodes (10): RunScriptTests, CompletedProcess, BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Frontend adapters. They communicate with the backend only through JSON., Any, RuntimeError (+2 more)

### Community 46 - "build_execution_plan"
Cohesion: 0.47
Nodes (4): build_execution_plan(), JobExecutionPlan, Any, Internal scheduling metadata shared by backend and worker.

### Community 49 - "DownloadProgressTracker"
Cohesion: 0.32
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 50 - "FakeProfiles"
Cohesion: 0.10
Nodes (4): FakeDispatcher, FakeProfiles, FakeTelegramBot, FakeWorkers

### Community 52 - "ControlPlaneBackupRouter"
Cohesion: 0.18
Nodes (5): build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, WorkerEventPublisher

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.11
Nodes (14): ExportWorkspaceTests, export_report(), ExportWorkspaceState, ExportWorkspaceStore, format_export_job(), format_export_status(), format_rate(), normalize_chat_ref() (+6 more)

### Community 55 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.14
Nodes (11): str, AuthChallengeStatus, BotAuthService, _hash_secret(), _now(), Any, Connection, datetime (+3 more)

### Community 59 - "ControlPlane"
Cohesion: 0.11
Nodes (13): FailingDispatcher, FakeDispatcher, ControlPlane, Any, Application facade used by every frontend adapter., Resume queued commands after backend restart or terminal events., _redact_secrets(), serializable() (+5 more)

### Community 60 - "WorkspaceExplorer.svelte"
Cohesion: 0.24
Nodes (7): crumbs, error, folders, goUp(), load(), loading, openCrumb()

### Community 61 - "job-progress.ts"
Cohesion: 0.39
Nodes (6): clampPercent(), formatDuration(), JobLike, NormalizedProgress, normalizeJobProgress(), number()

### Community 62 - "presentation.ts"
Cohesion: 0.16
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 63 - "session.svelte.ts"
Cohesion: 0.11
Nodes (10): challenge, contextRevision, current, loading, loadWorkers(), selectedWorkers(), Session, SessionWorker (+2 more)

### Community 64 - "test_app_menu.py"
Cohesion: 0.19
Nodes (4): AppMenuTests, fake_update(), FakeClient, FakePanel

### Community 65 - "SqliteJobRepository"
Cohesion: 0.14
Nodes (9): _dump(), _load(), Any, Connection, Path, Row, Acquire all keys or return a deterministic queue position., Keep only the newest high-frequency telemetry snapshot. (+1 more)

### Community 66 - "Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram"
Cohesion: 0.25
Nodes (7): 10. Rollout dan rollback, 11. Keputusan default untuk agent berikutnya, 1. Tujuan, 7. File/komponen yang diperkirakan, 9. Test plan, Rencana Implementasi: Concurrency Job, Notifikasi Selesai, dan Source Picker Telegram, Status eksekusi sesi ini

### Community 67 - "4. Arsitektur scheduler"
Cohesion: 0.29
Nodes (7): 4.1 Execution plan, 4.2 Backend admission, 4.3 Persistensi, 4.4 Pending dispatcher dan queue worker, 4.5 Internal command, 4.6 Utility path, 4. Arsitektur scheduler

### Community 68 - "Overview.svelte"
Cohesion: 0.29
Nodes (4): describe(), error, icons, label()

### Community 69 - "LabelStore"
Cohesion: 0.14
Nodes (11): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, parse_tme3_url(), ValueError (+3 more)

### Community 70 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 71 - "tme3bot/app.py"
Cohesion: 0.70
Nodes (3): configure_logging(), main(), run_backend()

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.04
Nodes (44): A. Langkah di komputer lokal, A. Login repository GitHub, Autentikasi GitHub dan GHCR, B. Langkah build lokal, B. Login GitHub Container Registry, Backend atau worker, Batas keamanan, Bootstrap VPS baru dengan `run.py` (+36 more)

### Community 73 - "composition.py"
Cohesion: 0.18
Nodes (6): FakeExecutor, WorkerApiTests, create_worker_app(), FastAPI, WorkerContext, run_worker()

### Community 76 - "5. Pesan status sementara untuk semua job"
Cohesion: 0.33
Nodes (6): 5.1 Komponen, 5.2 Jalur submit, 5.3 Subscription persisten, 5.4 Format message, 5.5 Polling, 5. Pesan status sementara untuk semua job

### Community 77 - "_error"
Cohesion: 0.67
Nodes (3): _error(), JSONResponse, Request

### Community 79 - "2. Temuan dari kode saat ini"
Cohesion: 0.40
Nodes (5): 2.1 Akar masalah antrean, 2.2 Resource lock saat ini, 2.3 Notifikasi Telegram, 2.4 Source picker, 2. Temuan dari kode saat ini

### Community 81 - "6. Source picker Export Fokus"
Cohesion: 0.40
Nodes (5): 6.1 Inline picker searchable, 6.2 Search dan pagination, 6.3 Callback stabil, 6.4 Mini App fase berikutnya, 6. Source picker Export Fokus

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

## Knowledge Gaps
- **160 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+155 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `test_app_menu.py`, `PanelManager`, `tme3bot/app.py`, `Any`, `request_json`, `format_job_status`, `telegram/app.py`, `ExportWorkspaceState`, `WorkerJobExecutor`, `FakeStatusPanel`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `composition.py`, `BackendApiTests`, `BackupService`, `FakeProfiles`, `ControlPlaneBackupRouter`, `SqliteAuthRepository`?**
  _High betweenness centrality (0.057) - this node is a cross-community bridge._
- **Why does `AppConfig` connect `AppConfig` to `tme3bot/app.py`, `ProfileTests`, `composition.py`, `BatchDownloadService`, `config.py`, `StateStore`, `BackupService`, `ControlPlaneBackupRouter`, `ExportService`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `FakeClient`) actually correct?**
  _`TelegramFrontendApp` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 57 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 57 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `SqliteJobRepository` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`SqliteJobRepository` has 15 INFERRED edges - model-reasoned connections that need verification._