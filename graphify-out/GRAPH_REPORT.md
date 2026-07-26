# Graph Report - dockter_bot_tdl  (2026-07-26)

## Corpus Check
- 133 files · ~59,936 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1418 nodes · 3730 edges · 70 communities (59 shown, 11 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 398 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `843030b7`
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
- build_profile_runtime
- ProfileSelectionStore
- models.py
- ControlPlaneTests
- BatchDownloadService
- UtilityFolderStore
- BatchDownloadService
- request_json
- executor.py
- SqliteAuthRepository
- WorkspaceExplorer.svelte
- job-progress.ts
- presentation.ts
- $lib/components/Shell.svelte
- TDLClient
- pindah.py
- $lib/components/Overview.svelte
- tme3bot
- ArchitectureBoundaryTests
- infrastructure/__init__.py
- _message_contains_caption

## God Nodes (most connected - your core abstractions)
1. `BackendContext` - 62 edges
2. `TelegramFrontendApp` - 54 edges
3. `StorageCatalog` - 50 edges
4. `StateStore` - 47 edges
5. `AppConfig` - 44 edges
6. `SqliteJobRepository` - 41 edges
7. `ControlPlane` - 39 edges
8. `create_backend_app()` - 38 edges
9. `DomainError` - 38 edges
10. `WorkerJobExecutor` - 38 edges

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

## Communities (70 total, 11 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.31
Nodes (6): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, ExportResult, TDLCommandError

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.14
Nodes (8): Message, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup, safe_edit_bot_message()

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.19
Nodes (30): cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory(), entry_identity() (+22 more)

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.15
Nodes (28): HTMLParser, build_orphan_group_entry(), build_reply_group_entry(), build_root_catalog(), build_root_entries(), discover_html_files(), entry_sort_key(), first_text_line() (+20 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.19
Nodes (17): PendingInput, Telegram presentation adapter and UI-only helpers., backup_menu_markup(), check_profile_markup(), clear_confirm_markup(), download_status_markup(), InlineKeyboardMarkup, Inline keyboards used by the API-backed Telegram frontend. (+9 more)

### Community 6 - "LabelStore"
Cohesion: 0.25
Nodes (5): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel

### Community 7 - "bot_text.py"
Cohesion: 0.17
Nodes (7): OutputCallback, Popen, ProgressCallback, Queue, LeaveResult, LeaveService, SubprocessRunner

### Community 8 - "UtilityHandler"
Cohesion: 0.18
Nodes (11): $lib/api, api(), ApiError, csrf(), patch(), put(), remove(), async() (+3 more)

### Community 9 - "ProfileManager"
Cohesion: 0.07
Nodes (65): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+57 more)

### Community 11 - "ExportResult"
Cohesion: 0.17
Nodes (12): ChannelRefTests, configure_logging(), main(), channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl.      Bot API uses `-100<peer i (+4 more)

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.06
Nodes (28): ProfileTests, Path, WorkerRegistryTests, normalize_profile_name(), Any, Path, write_json_atomic(), ProfileRegistry (+20 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "next"
Cohesion: 0.23
Nodes (9): has_downloadable_media(), is_image_message(), Any, build_telegram_message_url(), ExportJobResult, ExportService, media_ids_in_export(), Any (+1 more)

### Community 15 - "WorkerRegistry"
Cohesion: 0.16
Nodes (9): FakeExecutor, WorkerApiTests, WorkerJobRequest, create_worker_app(), _error(), FastAPI, JSONResponse, Request (+1 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (23): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, BackupArchive, BackupService, Path (+15 more)

### Community 17 - "composition.py"
Cohesion: 0.12
Nodes (12): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup., sha256_file(), build_backend_context() (+4 more)

### Community 18 - "config.py"
Cohesion: 0.13
Nodes (9): UtilitySummaryTests, Path, ValueError, UtilityFolderStore, UtilityPathError, UtilityResult, UtilityRunner, _validate_password() (+1 more)

### Community 19 - "ProfileManager"
Cohesion: 0.20
Nodes (9): ./.svelte-kit/tsconfig.json, compilerOptions, allowJs, checkJs, esModuleInterop, forceConsistentCasingInFileNames, skipLibCheck, strict (+1 more)

### Community 21 - "SerialPerKeyQueue"
Cohesion: 0.31
Nodes (3): Any, main_menu_markup(), edit_menu_message()

### Community 22 - "ProfileTests"
Cohesion: 0.14
Nodes (8): json_value(), Any, Exception, Path, Return a safe, shallow directory listing for the active workspace., Executes domain jobs and publishes JSON events; no UI dependency., Publish only profile metadata; .tdl files remain on this worker., WorkerJobExecutor

### Community 24 - "ExportService"
Cohesion: 0.17
Nodes (9): FakePublisher, ProgressReporterTests, _progress_percent(), ProgressReporter, Any, Throttled current-state telemetry plus persistent milestone events., Normalize transfer telemetry and smooth noisy instantaneous speed., utc_timestamp() (+1 more)

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.33
Nodes (11): cleanup_empty_directory(), emit_progress(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main() (+3 more)

### Community 27 - "TDLCommandError"
Cohesion: 0.18
Nodes (9): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, Runs different keys concurrently while keeping each key serial., SerialPerKeyQueue (+1 more)

### Community 28 - "RunScriptTests"
Cohesion: 0.08
Nodes (71): BaseModel, StorageLinkTests, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _error(), event_dict() (+63 more)

### Community 29 - "Path"
Cohesion: 0.05
Nodes (43): bits-ui, jsdom, @lucide/svelte, svelte-check, @sveltejs/adapter-static, @sveltejs/kit, @sveltejs/vite-plugin-svelte, tailwindcss (+35 more)

### Community 30 - "dependencies"
Cohesion: 0.31
Nodes (6): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., slugify_label(), URLParseError

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.18
Nodes (9): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts.  The worker owns the physical J, Return safe media statistics without assuming a single TDL JSON shape. (+1 more)

### Community 36 - "BackupCoordinator"
Cohesion: 0.11
Nodes (5): FakeDispatcher, FakeProfiles, FakeWorkers, UtilitySettingsTests, UtilitySettingsStore

### Community 37 - "ExportService"
Cohesion: 0.18
Nodes (18): _byte_multiplier(), clean_tdl_output_line(), _duration_seconds(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_elapsed_seconds(), parse_eta_seconds() (+10 more)

### Community 41 - "ProfileManager"
Cohesion: 0.25
Nodes (8): _normalize_upload_caption(), CompletedProcess, Path, RuntimeError, Raised when TDL returns unusable or malformed export data., Upload exactly one file and return its Telegram channel message id., Resolve delayed TDL upload results by polling channel history.          Some TDL, TDLDataError

### Community 43 - "HttpStateStore"
Cohesion: 0.16
Nodes (8): utc_now_iso(), HttpStateStore, normalize_chat_ref(), Any, Canonical source key: usernames ignore @ and letter case.      Numeric Telegram, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 44 - "@radix-ui/react-dropdown-menu"
Cohesion: 0.18
Nodes (7): BackendApiClient, Any, Frontend adapters. They communicate with the backend only through JSON., JsonHttpError, Any, RuntimeError, request_json()

### Community 45 - "DownloadProgressTracker"
Cohesion: 0.20
Nodes (10): Enum, AuthServiceTests, Path, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, DomainError, Any, datetime (+2 more)

### Community 46 - "tme3bot/app.py"
Cohesion: 0.27
Nodes (3): PanelViewStoreTests, PanelViewStore, Tracks which asynchronous task currently owns a chat's panel view.

### Community 49 - "build_profile_runtime"
Cohesion: 0.19
Nodes (10): AppConfig, Fail fast when a production role is missing its trust boundary., build_profile_runtime(), ProfileRuntime, BatchDownloadResult, BatchDownloadService, DownloadedJsonResult, Path (+2 more)

### Community 50 - "ProfileSelectionStore"
Cohesion: 0.32
Nodes (4): AppMenuTests, help_text(), Text helpers owned by the Telegram presentation adapter., source_digest()

### Community 52 - "ControlPlaneTests"
Cohesion: 0.05
Nodes (29): Protocol, str, ControlPlaneTests, FakeDispatcher, FakeProfiles, JobStoreTests, ControlPlane, Any (+21 more)

### Community 53 - "BatchDownloadService"
Cohesion: 0.21
Nodes (5): CallbackContext, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Update

### Community 55 - "BatchDownloadService"
Cohesion: 0.27
Nodes (3): StateStoreTests, Path, StateStore

### Community 57 - "executor.py"
Cohesion: 0.17
Nodes (4): JobLogSnapshot, Bounded raw command output retained with the persistent job history., WorkerEventPublisher, Framework-independent worker execution adapter.

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.15
Nodes (9): BotAuthService, _hash_secret(), _now(), Any, Connection, datetime, Path, SqliteAuthRepository (+1 more)

### Community 60 - "WorkspaceExplorer.svelte"
Cohesion: 0.24
Nodes (5): $lib/components/StoragePage.svelte, crumbs, goUp(), load(), openCrumb()

### Community 61 - "job-progress.ts"
Cohesion: 0.39
Nodes (6): clampPercent(), formatDuration(), JobLike, NormalizedProgress, normalizeJobProgress(), number()

### Community 62 - "presentation.ts"
Cohesion: 0.18
Nodes (10): $lib/components/BackupsPage.svelte, ./JobProgressCard.svelte, $lib/components/JobTable.svelte, formatBytes(), formatDate(), groupIdsByWorker(), jobMessage(), LabelItem (+2 more)

### Community 63 - "$lib/components/Shell.svelte"
Cohesion: 0.14
Nodes (9): ../styles.css, post(), ./Login.svelte, $lib/components/Shell.svelte, $lib/components/WorkersPage.svelte, challenge, current, loading (+1 more)

### Community 64 - "TDLClient"
Cohesion: 0.22
Nodes (4): FakeRunner, TDLClientTests, decode_process_output(), TDLClient

### Community 67 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 68 - "$lib/components/Overview.svelte"
Cohesion: 0.40
Nodes (5): $lib/components/Overview.svelte, describe(), error, icons, label()

### Community 72 - "tme3bot"
Cohesion: 0.07
Nodes (25): A. Langkah di komputer lokal, B. Langkah di VPS builder besar, Backend atau worker, Batas keamanan, C. Langkah di VPS gateway, D. Langkah di setiap VPS worker remote, E. Deploy web static di VPS gateway, F. Smoke test telemetry progress (+17 more)

### Community 81 - "_message_contains_caption"
Cohesion: 0.32
Nodes (7): _message_contains_caption(), CommandProgress, parse_terminal_size(), prepare_subprocess_command(), Any, Match captions across the different JSON shapes emitted by TDL., UploadResult

## Knowledge Gaps
- **79 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `name`, `version` (+74 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AppConfig` connect `build_profile_runtime` to `ProfileManager`, `ExportResult`, `SerialPerKeyQueue`, `next`, `StorageCatalog`, `composition.py`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `ControlPlane` connect `ControlPlaneTests` to `composition.py`, `DownloadProgressTracker`, `DownloadProgressTracker`, `BackupCoordinator`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Why does `SqliteJobRepository` connect `ControlPlaneTests` to `composition.py`, `DownloadProgressTracker`, `DownloadProgressTracker`, `BackupCoordinator`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `StateStore` (e.g. with `ProfileTests` and `.test_backend_runtime_never_uses_its_own_backend_api_url_for_state()`) actually correct?**
  _`StateStore` has 14 INFERRED edges - model-reasoned connections that need verification._