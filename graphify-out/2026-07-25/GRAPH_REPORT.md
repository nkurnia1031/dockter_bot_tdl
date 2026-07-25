# Graph Report - dockter_bot_tdl  (2026-07-25)

## Corpus Check
- 115 files · ~49,467 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1320 nodes · 3539 edges · 60 communities (47 shown, 13 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 390 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `eebf6740`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ProfileManager
- TelegramBotApp
- TDLClient
- SerialPerKeyQueue
- telegram_messages_to_json.py
- organize_media_from_json.py
- LabelStore
- bot_text.py
- UtilityHandler
- ProfileManager
- DownloadQueueWorker
- ExportResult
- SerialPerKeyQueue
- boltStorage
- next
- WorkerRegistry
- StorageCatalog
- composition.py
- config.py
- ProfileManager
- DownloadProgressTracker
- SerialPerKeyQueue
- ProfileTests
- tme3bot-leave-helper
- ExportService
- tme3bot Agent Context
- build.py
- TDLCommandError
- RunScriptTests
- Path
- dependencies
- tme3bot/__init__.py
- pindah.sh script
- bff.ts
- ExportArtifactCatalog
- BackupCoordinator
- ExportService
- WorkerRegistry
- ProfileManager
- HttpStateStore
- @radix-ui/react-dropdown-menu
- DownloadProgressTracker
- tme3bot/app.py
- models.py
- ControlPlaneTests
- BatchDownloadService
- request_json
- SqliteAuthRepository
- TDLClient
- models.py
- pindah.py
- tme3bot
- ArchitectureBoundaryTests
- infrastructure/__init__.py
- _message_contains_caption
- next

## God Nodes (most connected - your core abstractions)
1. `BackendContext` - 62 edges
2. `TelegramFrontendApp` - 54 edges
3. `StorageCatalog` - 50 edges
4. `StateStore` - 47 edges
5. `AppConfig` - 44 edges
6. `SqliteJobRepository` - 39 edges
7. `create_backend_app()` - 38 edges
8. `ControlPlane` - 38 edges
9. `DomainError` - 38 edges
10. `ProfileManager` - 36 edges

## Surprising Connections (you probably didn't know these)
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `BotAuthService`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `AuthServiceTests` --uses--> `SqliteAuthRepository`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `FakeProfiles` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py
- `FakeProfiles` --uses--> `ControlPlane`  [INFERRED]
  tests/test_backend_api.py → tme3bot/application/control_plane.py

## Import Cycles
- None detected.

## Communities (60 total, 13 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.18
Nodes (8): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, StateStoreTests, Path, StateStore, ExportResult

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.10
Nodes (11): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+3 more)

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.26
Nodes (3): ProfileManager, Path, Metadata a worker can safely publish to the backend registry.

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.12
Nodes (9): ControlPlaneTests, FakeDispatcher, FakeProfiles, ControlPlane, Any, Application facade used by every frontend adapter., _redact_secrets(), serializable() (+1 more)

### Community 6 - "LabelStore"
Cohesion: 0.14
Nodes (11): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, parse_tme3_url(), ValueError (+3 more)

### Community 8 - "UtilityHandler"
Cohesion: 0.10
Nodes (18): ../styles.css, $lib/api, api(), ApiError, csrf(), patch(), post(), put() (+10 more)

### Community 9 - "ProfileManager"
Cohesion: 0.07
Nodes (65): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+57 more)

### Community 11 - "ExportResult"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl.      Bot API uses `-100<peer i, load_dotenv(), _parse_named_values()

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.15
Nodes (16): ProfileTests, Path, AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), build_profile_config(), build_profile_runtime(), chown_paths() (+8 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "next"
Cohesion: 0.17
Nodes (8): JobStoreTests, JobEvent, _dump(), _load(), Connection, Path, Row, SqliteJobRepository

### Community 15 - "WorkerRegistry"
Cohesion: 0.17
Nodes (8): FakeExecutor, WorkerApiTests, create_worker_app(), _error(), FastAPI, JSONResponse, Request, WorkerContext

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (23): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, BackupArchive, BackupService, Path (+15 more)

### Community 17 - "composition.py"
Cohesion: 0.15
Nodes (6): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup.

### Community 18 - "config.py"
Cohesion: 0.15
Nodes (10): UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, UtilityPathError, UtilityResult, UtilityRunner, UtilitySettingsStore (+2 more)

### Community 19 - "ProfileManager"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 21 - "SerialPerKeyQueue"
Cohesion: 0.29
Nodes (6): AuthServiceTests, Path, _owned_job(), DomainError, Any, RuntimeError

### Community 22 - "ProfileTests"
Cohesion: 0.05
Nodes (28): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, sha256_file(), BackendApiClient (+20 more)

### Community 24 - "ExportService"
Cohesion: 0.23
Nodes (6): build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, WorkerHttpDispatcher, WorkerEventPublisher

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 28 - "RunScriptTests"
Cohesion: 0.08
Nodes (71): BaseModel, StorageLinkTests, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _error(), event_dict() (+63 more)

### Community 29 - "Path"
Cohesion: 0.05
Nodes (41): bits-ui, jsdom, @lucide/svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss (+33 more)

### Community 30 - "dependencies"
Cohesion: 0.17
Nodes (12): LeaveResult, LeaveService, has_downloadable_media(), is_image_message(), Any, build_telegram_message_url(), DownloadedJsonResult, ExportJobResult (+4 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.18
Nodes (9): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts.  The worker owns the physical J, Return safe media statistics without assuming a single TDL JSON shape. (+1 more)

### Community 36 - "BackupCoordinator"
Cohesion: 0.11
Nodes (3): FakeDispatcher, FakeProfiles, FakeWorkers

### Community 37 - "ExportService"
Cohesion: 0.16
Nodes (16): clean_tdl_output_line(), CommandProgress, is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_file_name(), parse_fraction(), parse_message_id() (+8 more)

### Community 38 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 41 - "ProfileManager"
Cohesion: 0.25
Nodes (8): _normalize_upload_caption(), CompletedProcess, Path, RuntimeError, Raised when TDL returns unusable or malformed export data., Upload exactly one file and return its Telegram channel message id., Resolve delayed TDL upload results by polling channel history.          Some TDL, TDLDataError

### Community 43 - "HttpStateStore"
Cohesion: 0.16
Nodes (8): utc_now_iso(), HttpStateStore, normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case.      Numeric Telegram, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 44 - "@radix-ui/react-dropdown-menu"
Cohesion: 0.33
Nodes (6): BatchDownloadResult, BatchDownloadService, media_ids_in_export(), Path, Download selected opaque filenames after strict directory validation., unique_path()

### Community 46 - "tme3bot/app.py"
Cohesion: 0.60
Nodes (4): configure_logging(), main(), run_backend(), run_worker()

### Community 52 - "ControlPlaneTests"
Cohesion: 0.14
Nodes (8): Protocol, Application services and use cases., ActorResolver, JobRepository, Any, StorageDelivery, WorkerDispatcher, Job

### Community 53 - "BatchDownloadService"
Cohesion: 0.09
Nodes (29): CallbackContext, AppMenuTests, PendingInput, Any, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Telegram presentation adapter and UI-only helpers. (+21 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.15
Nodes (9): BotAuthService, _hash_secret(), _now(), Any, Connection, datetime, Path, SqliteAuthRepository (+1 more)

### Community 64 - "TDLClient"
Cohesion: 0.30
Nodes (4): FakeRunner, TDLClientTests, decode_process_output(), TDLClient

### Community 65 - "models.py"
Cohesion: 0.29
Nodes (7): Enum, str, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, JobStatus, datetime, utc_now()

### Community 67 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 72 - "tme3bot"
Cohesion: 0.12
Nodes (15): Batas keamanan, Pemeriksaan setelah deploy, Rollback, Sekali saja: gateway dan UI, TME3Bot Deployment Runbook, Update biasa, Arsitektur, Build image dasar satu kali (+7 more)

### Community 81 - "_message_contains_caption"
Cohesion: 0.22
Nodes (6): OutputCallback, ProgressCallback, Queue, _message_contains_caption(), Any, Match captions across the different JSON shapes emitted by TDL.

### Community 83 - "next"
Cohesion: 0.14
Nodes (8): Any, Path, write_json_atomic(), ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions.      A, One-way migration for installations created before the registry., ProfileSelectionStore

## Knowledge Gaps
- **64 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+59 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AppConfig` connect `SerialPerKeyQueue` to `ProfileManager`, `SerialPerKeyQueue`, `ExportResult`, `@radix-ui/react-dropdown-menu`, `DownloadProgressTracker`, `tme3bot/app.py`, `StorageCatalog`, `next`, `ExportService`, `dependencies`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Why does `ProfileManager` connect `SerialPerKeyQueue` to `ProfileManager`, `TDLClient`, `WorkerRegistry`, `HttpStateStore`, `SerialPerKeyQueue`, `DownloadProgressTracker`, `tme3bot/app.py`, `@radix-ui/react-dropdown-menu`, `next`, `ExportService`, `dependencies`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Why does `SqliteJobRepository` connect `next` to `models.py`, `BackupCoordinator`, `organize_media_from_json.py`, `DownloadProgressTracker`, `ControlPlaneTests`, `ExportService`, `SqliteAuthRepository`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `StateStore` (e.g. with `ProfileTests` and `.test_backend_runtime_never_uses_its_own_backend_api_url_for_state()`) actually correct?**
  _`StateStore` has 14 INFERRED edges - model-reasoned connections that need verification._