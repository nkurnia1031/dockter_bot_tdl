# Graph Report - dockter_bot_tdl  (2026-07-24)

## Corpus Check
- 84 files · ~38,865 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1097 nodes · 2913 edges · 56 communities (36 shown, 20 thin omitted)
- Extraction: 87% EXTRACTED · 13% INFERRED · 0% AMBIGUOUS · INFERRED: 384 edges (avg confidence: 0.56)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `32bb70bf`
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
- run.py
- SerialPerKeyQueue
- boltStorage
- SourceSelectionStore
- bot_text.py
- StorageCatalog
- find_best_combination
- TelegramBotApp
- get_size
- app.py
- pindah.sh script
- tme3bot-leave-helper
- tme3bot Agent Context
- build.py
- RunScriptTests
- Path
- WorkerRegistry
- ServiceTests
- ExportService
- Path
- Any
- Any
- Path
- Queue
- Any
- Path
- BackupCoordinator
- SourceState
- BatchDownloadService
- DownloadProgressTracker
- ValueError
- request_json
- ControlPlane
- SqliteAuthRepository
- DomainError
- Path
- Path
- ServiceTests
- config.py
- tme3bot
- WorkerHandler
- ArchitectureBoundaryTests
- FakeProfiles
- infrastructure/__init__.py

## God Nodes (most connected - your core abstractions)
1. `BackendContext` - 55 edges
2. `TelegramFrontendApp` - 54 edges
3. `StorageCatalog` - 49 edges
4. `DomainError` - 42 edges
5. `AppConfig` - 39 edges
6. `StateStore` - 39 edges
7. `ControlPlane` - 37 edges
8. `SqliteJobRepository` - 35 edges
9. `SqliteAuthRepository` - 33 edges
10. `TDLClient` - 33 edges

## Surprising Connections (you probably didn't know these)
- `AuthServiceTests` --uses--> `BotAuthService`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `AuthServiceTests` --uses--> `SqliteAuthRepository`  [INFERRED]
  tests/test_auth_service.py → tme3bot/infrastructure/auth.py
- `FakeProfiles` --uses--> `BackendContext`  [INFERRED]
  tests/test_backend_api.py → tme3bot/api/backend.py
- `FakeProfiles` --uses--> `ControlPlane`  [INFERRED]
  tests/test_backend_api.py → tme3bot/application/control_plane.py
- `FakeProfiles` --uses--> `Actor`  [INFERRED]
  tests/test_backend_api.py → tme3bot/domain/models.py

## Import Cycles
- None detected.

## Communities (56 total, 20 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.18
Nodes (9): ChannelRefTests, ProfileTests, Path, channel_chat_id(), channel_tdl_ref(), compact_channel_ref(), Normalize Telegram private channel links and compact numeric references., load_dotenv() (+1 more)

### Community 1 - "TelegramBotApp"
Cohesion: 0.60
Nodes (4): get_size(), main(), parse_size(), Menghitung ukuran total dari file atau folder.

### Community 2 - "TDLClient"
Cohesion: 0.14
Nodes (10): Bot, Message, PanelViewStoreTests, edit_or_send_bot_message(), PanelManager, InlineKeyboardMarkup, safe_edit_bot_message(), safe_edit_message() (+2 more)

### Community 3 - "SerialPerKeyQueue"
Cohesion: 0.06
Nodes (32): has_downloadable_media(), is_image_message(), Popen, ProgressCallback, FakeRunner, TDLClientTests, decode_process_output(), clean_tdl_output_line() (+24 more)

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.15
Nodes (27): build_orphan_group_entry(), build_reply_group_entry(), build_root_catalog(), build_root_entries(), discover_html_files(), entry_sort_key(), first_text_line(), html_to_json_path() (+19 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.18
Nodes (7): JobStoreTests, _dump(), _load(), Connection, Path, Row, SqliteJobRepository

### Community 6 - "LabelStore"
Cohesion: 0.13
Nodes (10): LabelStoreTests, ParseTme3UrlTests, label_digest(), LabelStore, SavedLabel, utc_now_iso(), parse_tme3_url(), Raised when the inbound text is not a supported Telegram URL. (+2 more)

### Community 7 - "bot_text.py"
Cohesion: 0.15
Nodes (5): BackupCoordinator, BackupNodeJob, datetime, Gateway orchestration, channel upload, scheduling, and retention., Worker-neutral command payload for one node backup.

### Community 8 - "UtilityHandler"
Cohesion: 0.17
Nodes (29): cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory(), entry_identity() (+21 more)

### Community 9 - "ProfileManager"
Cohesion: 0.08
Nodes (49): base_fingerprint(), base_manifest_is_current(), build_archive(), build_base_archive(), build_migration_archive(), is_excluded(), iter_files(), main() (+41 more)

### Community 11 - "run.py"
Cohesion: 0.11
Nodes (20): LeaveResult, LeaveService, normalize_profile_name(), write_json_atomic(), AppConfig, Fail fast when a production role is missing its trust boundary., build_profile_config(), build_profile_runtime() (+12 more)

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.20
Nodes (8): FakeExecutor, WorkerApiTests, create_worker_app(), _error(), FastAPI, JSONResponse, Request, WorkerContext

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, fail(), leave(), main(), openStorage(), DB, boltStorage (+2 more)

### Community 14 - "SourceSelectionStore"
Cohesion: 0.19
Nodes (8): BatchDownloadResult, BatchDownloadService, DownloadedJsonResult, ExportJobResult, media_ids_in_export(), ExportResult, TDLClient, TDLCommandError

### Community 16 - "StorageCatalog"
Cohesion: 0.07
Nodes (23): BackupServiceTests, make_config(), Path, item_values(), StorageCatalogTests, BackupArchive, BackupService, Path (+15 more)

### Community 17 - "find_best_combination"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 19 - "get_size"
Cohesion: 0.36
Nodes (7): find_best_combination(), find_best_combination_worker(), load_json(), main(), Membaca dan mengembalikan konten file JSON., Worker function to find the best combination within a given range of combination, Find the best combination of items to fill the space left using multiprocessing.

### Community 20 - "app.py"
Cohesion: 0.53
Nodes (4): configure_logging(), main(), run_backend(), run_worker()

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.18
Nodes (10): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+2 more)

### Community 28 - "RunScriptTests"
Cohesion: 0.11
Nodes (59): BaseModel, _add_internal_state_routes(), _add_management_routes(), BackendContext, create_backend_app(), _error(), event_dict(), job_dict() (+51 more)

### Community 35 - "WorkerRegistry"
Cohesion: 0.22
Nodes (5): WorkerRegistryTests, normalize_worker_name(), Path, Persistent gateway-owned worker endpoints, editable without a rebuild., WorkerRegistry

### Community 36 - "ServiceTests"
Cohesion: 0.17
Nodes (6): FakeDownloadTDLClient, FakeExportTDLClient, ServiceTests, StateStoreTests, Path, StateStore

### Community 38 - "ExportService"
Cohesion: 0.35
Nodes (4): build_telegram_message_url(), ExportService, unique_path(), ParsedTme3Url

### Community 51 - "BackupCoordinator"
Cohesion: 0.08
Nodes (16): SerialPerKeyQueueTests, Runs different keys concurrently while keeping each key serial., SerialPerKeyQueue, _WorkerSlot, ErrorHandler, JobHandler, JobT, KeyT (+8 more)

### Community 52 - "SourceState"
Cohesion: 0.15
Nodes (5): HttpStateStore, Any, StateStore-compatible client used by a worker without a local state file., SourceState, StateSnapshot

### Community 53 - "BatchDownloadService"
Cohesion: 0.09
Nodes (30): CallbackContext, AppMenuTests, PendingInput, Any, Exception, Telegram presentation adapter; all business actions use BackendApiClient., TelegramFrontendApp, Telegram presentation adapter and UI-only helpers. (+22 more)

### Community 56 - "request_json"
Cohesion: 0.09
Nodes (8): RunScriptTests, CompletedProcess, BackendApiClient, Any, Frontend adapters. They communicate with the backend only through JSON., Any, RuntimeError, request_json()

### Community 57 - "ControlPlane"
Cohesion: 0.14
Nodes (14): Protocol, ControlPlane, Any, Application facade used by every frontend adapter., _redact_secrets(), serializable(), Application services and use cases., ActorResolver (+6 more)

### Community 58 - "SqliteAuthRepository"
Cohesion: 0.15
Nodes (9): BotAuthService, _hash_secret(), _now(), Any, Connection, datetime, Path, SqliteAuthRepository (+1 more)

### Community 59 - "DomainError"
Cohesion: 0.13
Nodes (9): AuthServiceTests, Path, ControlPlaneTests, FakeDispatcher, FakeProfiles, Actor, DomainError, Any (+1 more)

### Community 65 - "ServiceTests"
Cohesion: 0.14
Nodes (3): BackendApiTests, FakeDispatcher, FakeWorkers

### Community 67 - "config.py"
Cohesion: 0.18
Nodes (8): UtilitySettingsTests, Path, ValueError, UtilityPathError, UtilityResult, UtilityRunner, UtilitySettingsStore, _validate_size()

### Community 72 - "tme3bot"
Cohesion: 0.05
Nodes (35): A1. Kirim source terbaru ke VPS besar, A2. Siapkan source di VPS besar, A3. Build base image satu kali, A. Kondisi pertama: membuat base image di VPS besar, Aturan dasar, B1. Di project lokal, B2. Ekstrak base image dengan aman di project lokal, B3. Kirim source ke VPS besar (+27 more)

### Community 74 - "WorkerHandler"
Cohesion: 0.27
Nodes (7): Enum, str, Framework-independent domain model for the tme3bot control plane., AuthChallengeStatus, JobStatus, datetime, utc_now()

### Community 76 - "FakeProfiles"
Cohesion: 0.26
Nodes (7): BackupScheduler, build_backend_context(), ControlPlaneBackupRouter, _first_actor(), _NullCoordinator, WorkerHttpDispatcher, WorkerEventPublisher

## Knowledge Gaps
- **41 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `Arsitektur`, `Security` (+36 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **20 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ProfileManager` connect `run.py` to `ProfileManager`, `WorkerRegistry`, `ServiceTests`, `ExportService`, `FakeProfiles`, `SourceSelectionStore`, `app.py`, `SourceState`, `DownloadProgressTracker`?**
  _High betweenness centrality (0.109) - this node is a cross-community bridge._
- **Why does `AppConfig` connect `run.py` to `ProfileManager`, `ServiceTests`, `ExportService`, `FakeProfiles`, `SourceSelectionStore`, `StorageCatalog`, `app.py`?**
  _High betweenness centrality (0.098) - this node is a cross-community bridge._
- **Why does `TelegramFrontendApp` connect `BatchDownloadService` to `request_json`, `TDLClient`, `app.py`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Are the 44 inferred relationships involving `BackendContext` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`BackendContext` has 44 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `TelegramFrontendApp` (e.g. with `BackendApiClient` and `PanelManager`) actually correct?**
  _`TelegramFrontendApp` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 10 inferred relationships involving `StorageCatalog` (e.g. with `BackendApiTests` and `FakeDispatcher`) actually correct?**
  _`StorageCatalog` has 10 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `DomainError` (e.g. with `AuthServiceTests` and `.test_bot_approval_issues_and_rotates_tokens()`) actually correct?**
  _`DomainError` has 16 INFERRED edges - model-reasoned connections that need verification._