# Graph Report - dockter_bot_tdl  (2026-07-25)

## Corpus Check
- 117 files · ~51,680 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1336 nodes · 3557 edges · 62 communities (49 shown, 13 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 392 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `a9b23a4c`
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
- `AuthServiceTests` --uses--> `DomainError`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `AuthServiceTests` --uses--> `BotAuthService`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `AuthServiceTests` --uses--> `SqliteAuthRepository`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `FakeProfiles` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py

## Import Cycles
- None detected.

## Communities (62 total, 13 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.20
Nodes (10): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, build_telegram_message_url(), ExportJobResult, ExportService, ExportResult (+2 more)

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.10
Nodes (11): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+3 more)

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.19
Nodes (30): cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory(), entry_identity() (+22 more)

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.15
Nodes (28): HTMLParser, build_orphan_group_entry(), build_reply_group_entry(), build_root_catalog(), build_root_entries(), discover_html_files(), entry_sort_key(), first_text_line() (+20 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.14
Nodes (4): ControlPlaneTests, FakeDispatcher, FakeProfiles, Actor

### Community 6 - "LabelStore"
Cohesion: 0.07
Nodes (20): LabelStoreTests, ParseTme3UrlTests, WorkerRegistryTests, label_digest(), LabelStore, Path, SavedLabel, Any (+12 more)

### Community 7 - "bot_text.py"
Cohesion: 0.23
Nodes (4): Popen, LeaveResult, LeaveService, SubprocessRunner

### Community 8 - "UtilityHandler"
Cohesion: 0.07
Nodes (25): ../styles.css, $lib/api, api(), ApiError, csrf(), patch(), post(), put() (+17 more)

### Community 9 - "ProfileManager"
Cohesion: 0.07
Nodes (65): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+57 more)

### Community 11 - "ExportResult"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl.      Bot API uses `-100<peer i, load_dotenv(), _parse_named_values()

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.14
Nodes (17): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), build_profile_config(), build_profile_runtime(), chown_paths(), chown_tree(), ensure_profile_runtime_dirs() (+9 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "next"
Cohesion: 0.15
Nodes (8): JobStoreTests, JobStatus, _dump(), _load(), Connection, Path, Row, SqliteJobRepository

### Community 15 - "WorkerRegistry"
Cohesion: 0.16
Nodes (9): FakeExecutor, WorkerApiTests, WorkerJobRequest, create_worker_app(), _error(), FastAPI, JSONResponse, Request (+1 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (23): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, BackupArchive, BackupService, Path (+15 more)

### Community 17 - "composition.py"
Cohesion: 0.12
Nodes (10): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., build_backend_context(), ControlPlaneBackupRouter (+2 more)

### Community 18 - "config.py"
Cohesion: 0.13
Nodes (11): UtilitySettingsTests, UtilitySummaryTests, Path, ValueError, UtilityFolderStore, UtilityPathError, UtilityResult, UtilityRunner (+3 more)

### Community 19 - "ProfileManager"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 22 - "ProfileTests"
Cohesion: 0.11
Nodes (13): sha256_file(), JsonHttpError, JobLogSnapshot, json_value(), Any, Exception, Path, Executes domain jobs and publishes JSON events; no UI dependency. (+5 more)

### Community 24 - "ExportService"
Cohesion: 0.19
Nodes (7): BackendApiClient, Any, Frontend adapters. They communicate with the backend only through JSON., Any, RuntimeError, request_json(), WorkerHttpDispatcher

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 27 - "TDLCommandError"
Cohesion: 0.18
Nodes (9): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, Runs different keys concurrently while keeping each key serial., SerialPerKeyQueue (+1 more)

### Community 28 - "RunScriptTests"
Cohesion: 0.08
Nodes (71): BaseModel, StorageLinkTests, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _error(), event_dict() (+63 more)

### Community 29 - "Path"
Cohesion: 0.05
Nodes (43): bits-ui, jsdom, @lucide/svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss (+35 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.18
Nodes (9): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts.  The worker owns the physical J, Return safe media statistics without assuming a single TDL JSON shape. (+1 more)

### Community 36 - "BackupCoordinator"
Cohesion: 0.12
Nodes (3): FakeDispatcher, FakeProfiles, FakeWorkers

### Community 37 - "ExportService"
Cohesion: 0.18
Nodes (12): clean_tdl_output_line(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_file_name(), parse_fraction(), parse_message_id(), parse_percent() (+4 more)

### Community 41 - "ProfileManager"
Cohesion: 0.28
Nodes (5): OutputCallback, ProgressCallback, CompletedProcess, Path, Upload exactly one file and return its Telegram channel message id.

### Community 43 - "HttpStateStore"
Cohesion: 0.11
Nodes (10): StateStoreTests, HttpStateStore, normalize_chat_ref(), Any, Path, Canonical source key: usernames ignore @ and letter case.      Numeric Telegram, StateStore-compatible client used by a worker without a local state file., SourceState (+2 more)

### Community 44 - "@radix-ui/react-dropdown-menu"
Cohesion: 0.21
Nodes (11): has_downloadable_media(), is_image_message(), Any, BatchDownloadResult, BatchDownloadService, DownloadedJsonResult, media_ids_in_export(), Any (+3 more)

### Community 46 - "tme3bot/app.py"
Cohesion: 0.29
Nodes (5): configure_logging(), main(), run_backend(), run_worker(), WorkerEventPublisher

### Community 52 - "ControlPlaneTests"
Cohesion: 0.13
Nodes (14): Protocol, ControlPlane, Any, Application facade used by every frontend adapter., _redact_secrets(), serializable(), Application services and use cases., ActorResolver (+6 more)

### Community 53 - "BatchDownloadService"
Cohesion: 0.09
Nodes (29): CallbackContext, AppMenuTests, PendingInput, Any, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Telegram presentation adapter and UI-only helpers. (+21 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.13
Nodes (12): DomainError, Any, RuntimeError, BotAuthService, _hash_secret(), _now(), Any, Connection (+4 more)

### Community 64 - "TDLClient"
Cohesion: 0.36
Nodes (3): FakeRunner, TDLClientTests, TDLClient

### Community 65 - "models.py"
Cohesion: 0.36
Nodes (6): Enum, str, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, datetime, utc_now()

### Community 67 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 72 - "tme3bot"
Cohesion: 0.12
Nodes (15): Batas keamanan, Pemeriksaan setelah deploy, Rollback, Sekali saja: gateway dan UI, TME3Bot Deployment Runbook, Update biasa, Arsitektur, Build image dasar satu kali (+7 more)

### Community 81 - "_message_contains_caption"
Cohesion: 0.16
Nodes (14): Queue, decode_process_output(), _message_contains_caption(), _normalize_upload_caption(), CommandProgress, parse_terminal_size(), prepare_subprocess_command(), Any (+6 more)

### Community 83 - "next"
Cohesion: 0.17
Nodes (5): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions.      A, One-way migration for installations created before the registry., ProfileSelectionStore

## Knowledge Gaps
- **67 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AppConfig` connect `SerialPerKeyQueue` to `ProfileManager`, `ExportResult`, `@radix-ui/react-dropdown-menu`, `DownloadProgressTracker`, `tme3bot/app.py`, `HttpStateStore`, `StorageCatalog`, `composition.py`, `next`, `dependencies`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `ProfileManager` connect `SerialPerKeyQueue` to `ProfileManager`, `TDLClient`, `LabelStore`, `bot_text.py`, `HttpStateStore`, `@radix-ui/react-dropdown-menu`, `DownloadProgressTracker`, `tme3bot/app.py`, `composition.py`, `next`, `dependencies`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Why does `SqliteJobRepository` connect `next` to `BackupCoordinator`, `organize_media_from_json.py`, `composition.py`, `DownloadProgressTracker`, `ControlPlaneTests`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `StateStore` (e.g. with `ProfileTests` and `.test_backend_runtime_never_uses_its_own_backend_api_url_for_state()`) actually correct?**
  _`StateStore` has 14 INFERRED edges - model-reasoned connections that need verification._