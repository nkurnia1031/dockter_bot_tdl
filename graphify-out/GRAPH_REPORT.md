# Graph Report - dockter_bot_tdl  (2026-07-25)

## Corpus Check
- 129 files · ~53,360 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1477 nodes · 3770 edges · 83 communities (57 shown, 26 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 385 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `261de764`
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
- scripts
- package.json
- ProfileManager
- next-themes
- @playwright/test
- @radix-ui/react-dropdown-menu
- recharts
- tailwind-merge
- @types/react-dom
- next.config.ts
- next-env.d.ts
- models.py
- ControlPlaneTests
- BatchDownloadService
- request_json
- ControlPlane
- SqliteAuthRepository
- DownloadProgressTracker
- GET
- PATCH
- POST
- PUT
- TDLClient
- models.py
- FakeProfiles
- pindah.py
- BackendApiTests
- ProfileTests
- lucide-react
- UtilitySettingsStore
- tme3bot
- TDLCommandError
- JobRepository
- ArchitectureBoundaryTests
- ControlPlaneBackupRouter
- control_plane.py
- infrastructure/__init__.py
- UtilityFolderStore
- _error
- _message_contains_caption
- .__init__

## God Nodes (most connected - your core abstractions)
1. `BackendContext` - 59 edges
2. `TelegramFrontendApp` - 54 edges
3. `StorageCatalog` - 50 edges
4. `StateStore` - 46 edges
5. `AppConfig` - 44 edges
6. `SqliteJobRepository` - 39 edges
7. `ControlPlane` - 38 edges
8. `DomainError` - 38 edges
9. `create_backend_app()` - 36 edges
10. `ProfileManager` - 36 edges

## Surprising Connections (you probably didn't know these)
- `AuthServiceTests` --uses--> `Actor`  [INFERRED]
  tests/test_auth_service.py → tme3bot/domain/models.py
- `FakeProfiles` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py
- `FakeProfiles` --uses--> `ControlPlane`  [INFERRED]
  tests/test_backend_api.py → tme3bot/application/control_plane.py
- `FakeProfiles` --uses--> `Actor`  [INFERRED]
  tests/test_backend_api.py → tme3bot/domain/models.py
- `FakeProfiles` --uses--> `BotAuthService`  [INFERRED]
  tests/test_backend_api.py → tme3bot/infrastructure/auth.py

## Import Cycles
- None detected.

## Communities (83 total, 26 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.11
Nodes (9): StateStoreTests, DownloadedJsonResult, HttpStateStore, Any, Path, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot (+1 more)

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.10
Nodes (11): Message, PanelViewStoreTests, FakeBot, FakeMessage, TelegramPanelRecoveryTests, PanelManager, Bot, InlineKeyboardMarkup (+3 more)

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.27
Nodes (4): ProfileRegistry, Path, Gateway-owned registry for profile metadata, separate from TDL sessions.      A, One-way migration for installations created before the registry.

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.13
Nodes (8): ControlPlaneTests, FakeDispatcher, FakeProfiles, ControlPlane, Job, JobEvent, Application facade used by every frontend adapter., Actor

### Community 6 - "LabelStore"
Cohesion: 0.14
Nodes (12): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, Path, SavedLabel, utc_now_iso(), parse_tme3_url() (+4 more)

### Community 7 - "bot_text.py"
Cohesion: 0.21
Nodes (5): OutputCallback, Popen, ProgressCallback, Queue, SubprocessRunner

### Community 8 - "UtilityHandler"
Cohesion: 0.06
Nodes (47): metadata, Providers(), ActivityPage(), Backup, BackupsPage(), SettingsPage(), Worker, WorkersPage() (+39 more)

### Community 9 - "ProfileManager"
Cohesion: 0.08
Nodes (54): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+46 more)

### Community 11 - "ExportResult"
Cohesion: 0.24
Nodes (8): ChannelRefTests, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., Return the peer reference format expected by tdl.      Bot API uses `-100<peer i, load_dotenv(), _parse_named_values()

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.12
Nodes (20): AppConfig, Fail fast when a production role is missing its trust boundary., normalize_profile_name(), Any, Path, write_json_atomic(), build_profile_config(), build_profile_runtime() (+12 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "next"
Cohesion: 0.19
Nodes (8): _dump(), _load(), Connection, Job, JobEvent, Path, Row, SqliteJobRepository

### Community 15 - "WorkerRegistry"
Cohesion: 0.16
Nodes (10): FakeExecutor, WorkerApiTests, WorkerJobRequest, create_worker_app(), FastAPI, WorkerContext, configure_logging(), main() (+2 more)

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (23): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, BackupArchive, BackupService, Path (+15 more)

### Community 17 - "composition.py"
Cohesion: 0.15
Nodes (6): BackupCoordinator, BackupNodeJob, BackupScheduler, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup.

### Community 18 - "config.py"
Cohesion: 0.23
Nodes (4): UtilitySummaryTests, Path, UtilityResult, UtilityRunner

### Community 19 - "ProfileManager"
Cohesion: 0.07
Nodes (27): dom, dom.iterable, esnext, .next/dev/types/**/*.ts, next-env.d.ts, .next/types/**/*.ts, node_modules, **/*.ts (+19 more)

### Community 20 - "DownloadProgressTracker"
Cohesion: 0.19
Nodes (9): FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, build_telegram_message_url(), ExportJobResult, ExportService, ExportResult (+1 more)

### Community 21 - "SerialPerKeyQueue"
Cohesion: 0.12
Nodes (15): aliases, components, hooks, lib, ui, utils, iconLibrary, rsc (+7 more)

### Community 22 - "ProfileTests"
Cohesion: 0.05
Nodes (30): ErrorHandler, JobHandler, JobT, KeyT, PriorityQueue, SerialPerKeyQueueTests, sha256_file(), BackendApiClient (+22 more)

### Community 24 - "ExportService"
Cohesion: 0.22
Nodes (9): _error(), event_dict(), job_dict(), _model_dict(), Any, Job, JobEvent, JSONResponse (+1 more)

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 26 - "build.py"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 27 - "TDLCommandError"
Cohesion: 0.18
Nodes (13): has_downloadable_media(), is_image_message(), Any, BatchDownloadResult, BatchDownloadService, media_ids_in_export(), Any, Path (+5 more)

### Community 28 - "RunScriptTests"
Cohesion: 0.12
Nodes (56): BaseModel, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _owned_job(), _profile_artifact(), FastAPI (+48 more)

### Community 29 - "Path"
Cohesion: 0.08
Nodes (25): @axe-core/playwright, jsdom, openapi-typescript, tailwindcss, @tailwindcss/postcss, @testing-library/jest-dom, @testing-library/react, @types/node (+17 more)

### Community 30 - "dependencies"
Cohesion: 0.09
Nodes (23): clsx, @hookform/resolvers, next, @radix-ui/react-dialog, @radix-ui/react-tabs, react, react-dom, react-hook-form (+15 more)

### Community 34 - "bff.ts"
Cohesion: 0.24
Nodes (13): POST(), POST(), proxy(), GET(), PUT(), backendFetch(), clearSession(), copyResponse() (+5 more)

### Community 35 - "ExportArtifactCatalog"
Cohesion: 0.18
Nodes (9): ExportArtifactCatalogTests, ExportArtifactCatalog, inspect_export_json(), Any, Connection, Path, Gateway-owned catalog for export JSON artifacts.  The worker owns the physical J, Return safe media statistics without assuming a single TDL JSON shape. (+1 more)

### Community 36 - "BackupCoordinator"
Cohesion: 0.52
Nodes (4): StorageLinkTests, Compact, stable HMAC tokens for Telegram storage deep links., sign_storage_item(), verify_storage_item()

### Community 37 - "ExportService"
Cohesion: 0.18
Nodes (12): clean_tdl_output_line(), is_nonsemantic_tdl_output_line(), is_standalone_tdl_progress_bar(), is_tdl_telemetry_line(), parse_file_name(), parse_fraction(), parse_message_id(), parse_percent() (+4 more)

### Community 38 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 39 - "scripts"
Cohesion: 0.25
Nodes (8): scripts, build, dev, lint, openapi, start, test, test:e2e

### Community 40 - "package.json"
Cohesion: 0.40
Nodes (4): name, packageManager, private, version

### Community 41 - "ProfileManager"
Cohesion: 0.25
Nodes (8): _normalize_upload_caption(), CompletedProcess, Path, RuntimeError, Raised when TDL returns unusable or malformed export data., Upload exactly one file and return its Telegram channel message id., Resolve delayed TDL upload results by polling channel history.          Some TDL, TDLDataError

### Community 52 - "ControlPlaneTests"
Cohesion: 0.20
Nodes (8): Protocol, JobStoreTests, Job, ActorResolver, Any, StorageDelivery, WorkerDispatcher, JobEvent

### Community 53 - "BatchDownloadService"
Cohesion: 0.09
Nodes (29): CallbackContext, AppMenuTests, PendingInput, Any, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Telegram presentation adapter and UI-only helpers. (+21 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.13
Nodes (13): AuthServiceTests, Path, DomainError, RuntimeError, BotAuthService, _hash_secret(), _now(), Any (+5 more)

### Community 59 - "DownloadProgressTracker"
Cohesion: 0.26
Nodes (3): DownloadProgressSnapshot, DownloadProgressTracker, CommandProgress

### Community 64 - "TDLClient"
Cohesion: 0.30
Nodes (4): FakeRunner, TDLClientTests, decode_process_output(), TDLClient

### Community 65 - "models.py"
Cohesion: 0.29
Nodes (8): Enum, str, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, Job, JobStatus, datetime, utc_now()

### Community 66 - "FakeProfiles"
Cohesion: 0.12
Nodes (3): FakeDispatcher, FakeProfiles, FakeWorkers

### Community 67 - "pindah.py"
Cohesion: 0.27
Nodes (10): find_best_combination(), find_best_combination_worker(), load_json(), main(), move_size_limit(), parse_size(), Convert the shared Utility setting (for example ``750m``) to bytes., Membaca dan mengembalikan konten file JSON. (+2 more)

### Community 71 - "UtilitySettingsStore"
Cohesion: 0.27
Nodes (6): UtilitySettingsTests, ValueError, UtilityPathError, UtilitySettingsStore, _validate_password(), _validate_size()

### Community 72 - "tme3bot"
Cohesion: 0.05
Nodes (41): A1. Kirim source terbaru ke VPS besar, A2. Siapkan source di VPS besar, A3. Build base image satu kali, A. Kondisi pertama: membuat base image di VPS besar, Aturan dasar, B1. Di project lokal, B2. Ekstrak base image dengan aman di project lokal, B3. Kirim source ke VPS besar (+33 more)

### Community 73 - "TDLCommandError"
Cohesion: 0.31
Nodes (4): LeaveResult, LeaveService, ProfileSelectionStore, TDLCommandError

### Community 74 - "JobRepository"
Cohesion: 0.33
Nodes (3): JobRepository, Job, JobEvent

### Community 76 - "ControlPlaneBackupRouter"
Cohesion: 0.25
Nodes (4): build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator

### Community 77 - "control_plane.py"
Cohesion: 0.38
Nodes (4): Any, _redact_secrets(), serializable(), Application services and use cases.

### Community 80 - "_error"
Cohesion: 0.67
Nodes (3): _error(), JSONResponse, Request

### Community 81 - "_message_contains_caption"
Cohesion: 0.67
Nodes (3): _message_contains_caption(), Any, Match captions across the different JSON shapes emitted by TDL.

## Knowledge Gaps
- **146 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `$schema`, `style` (+141 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **26 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `AppConfig` connect `SerialPerKeyQueue` to `ProfileManager`, `ProfileTests`, `TDLCommandError`, `DownloadProgressTracker`, `ExportResult`, `ControlPlaneBackupRouter`, `WorkerRegistry`, `StorageCatalog`, `DownloadProgressTracker`, `TDLCommandError`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `BatchDownloadService` to `TDLClient`, `ProfileTests`, `WorkerRegistry`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Why does `StorageCatalog` connect `StorageCatalog` to `FakeProfiles`, `BackendApiTests`, `ControlPlaneBackupRouter`, `WorkerRegistry`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 47 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 47 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `StateStore` (e.g. with `ProfileTests` and `.test_backend_runtime_never_uses_its_own_backend_api_url_for_state()`) actually correct?**
  _`StateStore` has 14 INFERRED edges - model-reasoned connections that need verification._