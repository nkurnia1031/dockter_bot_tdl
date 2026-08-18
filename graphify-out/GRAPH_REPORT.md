# Graph Report - dockter_bot_tdl  (2026-08-18)

## Corpus Check
- 145 files · ~85,640 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1864 nodes · 4800 edges · 81 communities (67 shown, 14 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 442 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `3030e683`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- BackupService
- pindah4.py
- PanelManager
- AppConfig
- organize_media_from_json.py
- Job
- WorkerRegistry
- BatchDownloadService
- BackendApiTests
- run.py
- compress.sh
- config.py
- TelegramFrontendApp
- boltStorage
- format_job_status
- TDLCommandError
- StorageCatalog
- JobEvent
- UtilitySettingsStore
- compilerOptions
- telegram/app.py
- ExportService
- WorkerJobExecutor
- tme3bot-leave-helper
- Update
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
- StorageMaintenanceService
- RunScriptTests
- Actor
- DownloadProgressTracker
- UtilityFolderStore
- test_pindah.py
- ExportWorkspaceState
- FakeStatusPanel
- 12. Bootstrap VPS baru dan satu-command deployment
- ProfileManager
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
- Overview.svelte
- LabelStore
- pindah.py
- JobStatus
- TME3Bot Deployment Runbook
- composition.py
- ../styles.css
- ArchitectureBoundaryTests
- 5. Pesan status sementara untuk semua job
- infrastructure/__init__.py
- 2. Temuan dari kode saat ini
- 6. Source picker Export Fokus
- 3. Keputusan desain
- service.py
- ControlPlaneTests

## God Nodes (most connected - your core abstractions)
1. `StorageCatalog` - 93 edges
2. `TelegramFrontendApp` - 83 edges
3. `BackendContext` - 70 edges
4. `SqliteJobRepository` - 54 edges
5. `ControlPlane` - 47 edges
6. `StateStore` - 47 edges
7. `AppConfig` - 44 edges
8. `JobEvent` - 43 edges
9. `WorkerJobExecutor` - 40 edges
10. `DomainError` - 37 edges

## Surprising Connections (you probably didn't know these)
- `FakePanel` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `FakeClient` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `AppMenuTests` --uses--> `TelegramFrontendApp`  [INFERRED]
  tests/test_app_menu.py → tme3bot/frontend/telegram/app.py
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `DomainError`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py

## Import Cycles
- None detected.

## Communities (81 total, 14 thin omitted)

### Community 0 - "BackupService"
Cohesion: 0.26
Nodes (6): BackupArchive, BackupService, Path, Create encrypted, runtime-only per-node backup archives., safe_node_name(), utc_now()

### Community 1 - "pindah4.py"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "PanelManager"
Cohesion: 0.07
Nodes (17): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+9 more)

### Community 3 - "AppConfig"
Cohesion: 0.09
Nodes (22): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), Any, Path, utc_now_iso(), write_json_atomic(), ProfileRegistry (+14 more)

### Community 4 - "organize_media_from_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "Job"
Cohesion: 0.14
Nodes (7): Protocol, ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher, Job

### Community 6 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 7 - "BatchDownloadService"
Cohesion: 0.26
Nodes (7): BatchDownloadResult, BatchDownloadService, media_ids_in_export(), Path, Download selected opaque filenames after strict directory validation., Download selected pending/failed JSON files from validated roots., Resolve a chat in the active download session, then allow one retry.

### Community 9 - "run.py"
Cohesion: 0.05
Nodes (93): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+85 more)

### Community 11 - "config.py"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl. Bot API uses `-100<peer id>`…, load_dotenv(), _parse_named_values()

### Community 12 - "TelegramFrontendApp"
Cohesion: 0.15
Nodes (9): Thread, PendingInput, Any, Recover subscriptions after the Telegram container restarts., Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, short_text(), main_menu_markup() (+1 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "format_job_status"
Cohesion: 0.20
Nodes (10): JobNotificationFormatterTests, format_job_status(), JobNotificationRegistry, _kind_label(), Any, _rate(), Thread-safe lifecycle registry for transient Telegram status messages., Format a status-only Telegram message without raw object output. (+2 more)

### Community 15 - "TDLCommandError"
Cohesion: 0.22
Nodes (10): LeaveResult, LeaveService, has_downloadable_media(), is_image_message(), Any, Any, parse_terminal_size(), prepare_subprocess_command() (+2 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.06
Nodes (20): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, FakeBot, StorageMaintenanceTests, build_storage_caption() (+12 more)

### Community 17 - "JobEvent"
Cohesion: 0.28
Nodes (3): JobStoreTests, Update the latest telemetry without growing persistent event history., JobEvent

### Community 18 - "UtilitySettingsStore"
Cohesion: 0.14
Nodes (10): UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, UtilityPathError, UtilityResult, UtilityRunner, UtilitySettingsStore (+2 more)

### Community 19 - "compilerOptions"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 20 - "telegram/app.py"
Cohesion: 0.15
Nodes (23): Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), export_input_cancel_markup(), _export_source_compact_markup(), _export_source_picker_markup() (+15 more)

### Community 21 - "ExportService"
Cohesion: 0.26
Nodes (7): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, build_telegram_message_url(), ExportService, ExportResult

### Community 22 - "WorkerJobExecutor"
Cohesion: 0.06
Nodes (24): FakePublisher, ProgressReporterTests, StorageWorkerPathTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed. (+16 more)

### Community 24 - "Update"
Cohesion: 0.20
Nodes (4): CallbackContext, Exception, Accept a signed file code without requiring an application actor., Update

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
Nodes (82): BaseModel, StorageLinkTests, _active_storage_item(), _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _deliver_storage_telegram() (+74 more)

### Community 29 - "devDependencies"
Cohesion: 0.05
Nodes (43): bits-ui, jsdom, @lucide/svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss (+35 more)

### Community 30 - "StoragePage.svelte"
Cohesion: 0.06
Nodes (32): patch(), post(), chooseScope(), clearSelection(), createFolder(), createOpen, currentName, deliver() (+24 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.15
Nodes (10): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts. The worker owns the physical…, Return safe media statistics without assuming a single TDL JSON shape. (+2 more)

### Community 36 - "BackupCoordinator"
Cohesion: 0.14
Nodes (7): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., sha256_file()

### Community 37 - "TDLClient"
Cohesion: 0.06
Nodes (38): OutputCallback, Popen, ProgressCallback, Queue, FakeRunner, TDLClientTests, decode_process_output(), _message_contains_caption() (+30 more)

### Community 41 - "8. Urutan implementasi"
Cohesion: 0.25
Nodes (8): 8. Urutan implementasi, Milestone 0 — Baseline, Milestone 1 — Resource queue worker, Milestone 2 — Admission backend lintas worker, Milestone 3 — Dedicated TDL lane, Milestone 4 — Telegram notifier, Milestone 5 — Source picker, Milestone 6 — Web dan runbook

### Community 43 - "StateStore"
Cohesion: 0.12
Nodes (10): StateStoreTests, HttpStateStore, normalize_chat_ref(), Any, Path, Canonical source key: usernames ignore @ and letter case. Numeric Telegram…, StateStore-compatible client used by a worker without a local state file., SourceState (+2 more)

### Community 45 - "RunScriptTests"
Cohesion: 0.07
Nodes (9): RunScriptTests, CompletedProcess, BackendApiClient, Any, Redeem a signed capability link without creating an actor JWT., Frontend adapters. They communicate with the backend only through JSON., Any, RuntimeError (+1 more)

### Community 46 - "Actor"
Cohesion: 0.15
Nodes (9): Any, _redact_secrets(), serializable(), Application services and use cases., build_execution_plan(), JobExecutionPlan, Any, Internal scheduling metadata shared by backend and worker. (+1 more)

### Community 49 - "DownloadProgressTracker"
Cohesion: 0.29
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 53 - "ExportWorkspaceState"
Cohesion: 0.12
Nodes (14): ExportWorkspaceTests, export_report(), ExportWorkspaceState, format_export_job(), format_export_status(), format_rate(), normalize_chat_ref(), Any (+6 more)

### Community 55 - "FakeStatusPanel"
Cohesion: 0.19
Nodes (4): ExportStatusPollingTests, FakeClient, FakeStatusMessage, FakeStatusPanel

### Community 56 - "12. Bootstrap VPS baru dan satu-command deployment"
Cohesion: 0.17
Nodes (12): 12.10 Report dan exit code, 12.11 Test tambahan run.py, 12.1 Tujuan, 12.2 Preflight tools, 12.3 Pemeriksaan Git, 12.4 Deteksi base image, 12.5 Deteksi app image dan publish terbaru, 12.6 State machine run.py (+4 more)

### Community 57 - "ProfileManager"
Cohesion: 0.17
Nodes (6): ProfileTests, Path, build_profile_config(), ProfileManager, Path, Metadata a worker can safely publish to the backend registry.

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.12
Nodes (11): AuthServiceTests, Path, BotAuthService, _hash_secret(), _now(), Any, Connection, datetime (+3 more)

### Community 59 - "ControlPlane"
Cohesion: 0.10
Nodes (7): FakeDispatcher, FakeProfiles, FakeTelegramBot, FakeWorkers, ControlPlane, Resume queued commands after backend restart or terminal events., Application facade used by every frontend adapter.

### Community 60 - "WorkspaceExplorer.svelte"
Cohesion: 0.24
Nodes (5): async(), crumbs, goUp(), load(), openCrumb()

### Community 61 - "job-progress.ts"
Cohesion: 0.39
Nodes (6): clampPercent(), formatDuration(), JobLike, NormalizedProgress, normalizeJobProgress(), number()

### Community 62 - "presentation.ts"
Cohesion: 0.16
Nodes (7): formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem, resultEntries(), textValue()

### Community 63 - "session.svelte.ts"
Cohesion: 0.13
Nodes (15): api(), ApiError, csrf(), put(), remove(), challenge, contextRevision, current (+7 more)

### Community 64 - "ExportWorkspaceStore"
Cohesion: 0.13
Nodes (5): AppMenuTests, fake_update(), FakeClient, FakePanel, ExportWorkspaceStore

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
Cohesion: 0.15
Nodes (4): describe(), error, icons, label()

### Community 69 - "LabelStore"
Cohesion: 0.25
Nodes (5): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel

### Community 70 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 71 - "JobStatus"
Cohesion: 0.17
Nodes (9): Enum, str, FailingDispatcher, FakeDispatcher, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, JobStatus, datetime (+1 more)

### Community 72 - "TME3Bot Deployment Runbook"
Cohesion: 0.05
Nodes (37): A. Langkah di komputer lokal, A. Login repository GitHub, Autentikasi GitHub dan GHCR, B. Langkah build lokal, B. Login GitHub Container Registry, Backend atau worker, Batas keamanan, Bootstrap VPS baru dengan `run.py` (+29 more)

### Community 73 - "composition.py"
Cohesion: 0.08
Nodes (19): FakeExecutor, WorkerApiTests, create_worker_app(), _error(), FastAPI, JSONResponse, Request, WorkerContext (+11 more)

### Community 76 - "5. Pesan status sementara untuk semua job"
Cohesion: 0.33
Nodes (6): 5.1 Komponen, 5.2 Jalur submit, 5.3 Subscription persisten, 5.4 Format message, 5.5 Polling, 5. Pesan status sementara untuk semua job

### Community 79 - "2. Temuan dari kode saat ini"
Cohesion: 0.40
Nodes (5): 2.1 Akar masalah antrean, 2.2 Resource lock saat ini, 2.3 Notifikasi Telegram, 2.4 Source picker, 2. Temuan dari kode saat ini

### Community 81 - "6. Source picker Export Fokus"
Cohesion: 0.40
Nodes (5): 6.1 Inline picker searchable, 6.2 Search dan pagination, 6.3 Callback stabil, 6.4 Mini App fase berikutnya, 6. Source picker Export Fokus

### Community 83 - "3. Keputusan desain"
Cohesion: 0.50
Nodes (4): 3.1 Aturan concurrency, 3.2 Resource key, 3.3 Batasan dua sesi TDL, 3. Keputusan desain

### Community 87 - "service.py"
Cohesion: 0.17
Nodes (10): ParseTme3UrlTests, DownloadedJsonResult, ExportJobResult, unique_path(), parse_tme3_url(), ParsedTme3Url, ValueError, Raised when the inbound text is not a supported Telegram URL. (+2 more)

## Knowledge Gaps
- **151 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+146 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TelegramFrontendApp` connect `TelegramFrontendApp` to `ExportWorkspaceStore`, `PanelManager`, `composition.py`, `RunScriptTests`, `format_job_status`, `telegram/app.py`, `FakeStatusPanel`, `Update`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `BackendApiTests`, `BackupService`, `ControlPlane`, `composition.py`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Why does `AppConfig` connect `AppConfig` to `BatchDownloadService`, `composition.py`, `config.py`, `StorageCatalog`, `ExportService`, `service.py`, `ProfileManager`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 13 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `TelegramFrontendApp` (e.g. with `AppMenuTests` and `FakeClient`) actually correct?**
  _`TelegramFrontendApp` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 55 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 55 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `SqliteJobRepository` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`SqliteJobRepository` has 15 INFERRED edges - model-reasoned connections that need verification._