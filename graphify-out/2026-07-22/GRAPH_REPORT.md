# Graph Report - dockter_bot_tdl  (2026-07-22)

## Corpus Check
- 57 files · ~23,387 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 669 nodes · 2006 edges · 24 communities (19 shown, 5 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 226 edges (avg confidence: 0.53)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e2197787`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- ProfileManager
- StateStore
- TDLClient
- SourceHandler
- telegram_messages_to_json.py
- organize_media_from_json.py
- LabelStore
- bot_text.py
- UtilityHandler
- run.py
- SerialPerKeyQueue
- boltStorage
- SourceSelectionStore
- extract.py
- find_best_combination
- ContainerBuildTests
- get_size
- __init__.py
- compress.sh
- pindah.sh script
- tme3bot-leave-helper
- tme3bot Agent Context
- build.py

## God Nodes (most connected - your core abstractions)
1. `ProfileManager` - 50 edges
2. `StateStore` - 42 edges
3. `PanelManager` - 41 edges
4. `AppConfig` - 38 edges
5. `DownloadProgressTracker` - 35 edges
6. `main_menu_markup()` - 32 edges
7. `ExportService` - 32 edges
8. `TDLClient` - 32 edges
9. `BatchDownloadService` - 30 edges
10. `TelegramBotApp` - 29 edges

## Surprising Connections (you probably didn't know these)
- `FakeExportTDLClient` --uses--> `DownloadProgressTracker`  [INFERRED]
  tests/test_service.py → tme3bot/progress.py
- `FakeDownloadTDLClient` --uses--> `DownloadProgressTracker`  [INFERRED]
  tests/test_service.py → tme3bot/progress.py
- `ServiceTests` --uses--> `DownloadProgressTracker`  [INFERRED]
  tests/test_service.py → tme3bot/progress.py
- `FakeRunner` --uses--> `TDLCommandError`  [INFERRED]
  tests/test_tdl.py → tme3bot/tdl.py
- `TDLClientTests` --uses--> `TDLCommandError`  [INFERRED]
  tests/test_tdl.py → tme3bot/tdl.py

## Import Cycles
- None detected.

## Communities (24 total, 5 thin omitted)

### Community 0 - "ProfileManager"
Cohesion: 0.06
Nodes (31): Event, PanelViewStoreTests, download_status_markup(), edit_or_send_bot_message(), PanelManager, Bot, InlineKeyboardMarkup, Message (+23 more)

### Community 1 - "StateStore"
Cohesion: 0.07
Nodes (37): ProfileTests, Path, FakeDownloadTDLClient, FakeExportTDLClient, Path, ServiceTests, StateStoreTests, AppConfig (+29 more)

### Community 2 - "TDLClient"
Cohesion: 0.06
Nodes (29): Popen, ProgressCallback, RunScriptTests, FakeRunner, CompletedProcess, TDLClientTests, LeaveService, decode_process_output() (+21 more)

### Community 3 - "SourceHandler"
Cohesion: 0.08
Nodes (38): AppMenuTests, configure_logging(), main(), CallbackContext, Update, TelegramBotApp, batch_delete_source_confirm_markup(), batch_leave_source_confirm_markup() (+30 more)

### Community 4 - "telegram_messages_to_json.py"
Cohesion: 0.09
Nodes (58): HTMLParser, cleanup_empty_directories(), collect_potential_folder_names(), collect_referenced_media(), collect_referenced_media_from_html(), crosscheck_unreferenced_media(), discover_json_files(), ensure_target_directory() (+50 more)

### Community 5 - "organize_media_from_json.py"
Cohesion: 0.33
Nodes (5): ParseTme3UrlTests, parse_tme3_url(), ValueError, Raised when the inbound text is not a supported Telegram URL., URLParseError

### Community 6 - "LabelStore"
Cohesion: 0.10
Nodes (13): LabelStoreTests, label_digest(), LabelStore, Path, SavedLabel, Any, Path, utc_now_iso() (+5 more)

### Community 7 - "bot_text.py"
Cohesion: 0.17
Nodes (10): BotTextTests, compact_text(), format_batch_download_result(), format_download_progress(), format_elapsed(), format_export_result(), progress_bar(), DownloadProgressSnapshot (+2 more)

### Community 8 - "UtilityHandler"
Cohesion: 0.43
Nodes (4): utility_password_markup(), Message, Update, UtilityHandler

### Community 11 - "run.py"
Cohesion: 0.15
Nodes (22): add_profile(), compose_base_command(), compose_env(), ensure_container_profile_dirs(), ensure_host_subdirs(), ensure_profile_root(), find_host_tdl(), load_env_file() (+14 more)

### Community 12 - "SerialPerKeyQueue"
Cohesion: 0.07
Nodes (22): ErrorHandler, JobHandler, JobT, KeyT, SerialPerKeyQueueTests, _FakeBot, _FakePanel, UtilityWorkerTests (+14 more)

### Community 13 - "boltStorage"
Cohesion: 0.18
Nodes (10): Client, Context, DB, boltStorage, fail(), leave(), main(), openStorage() (+2 more)

### Community 14 - "SourceSelectionStore"
Cohesion: 0.24
Nodes (4): Hashable, SourceSelectionStoreTests, Thread-safe temporary selections scoped to a Telegram chat and profile., SourceSelectionStore

### Community 16 - "extract.py"
Cohesion: 0.36
Nodes (10): cleanup_empty_directory(), extract_archive(), get_extract_folder_name(), get_folder_password(), get_multipart_group(), is_main_part(), main(), run_extract() (+2 more)

### Community 17 - "find_best_combination"
Cohesion: 0.36
Nodes (7): find_best_combination(), find_best_combination_worker(), load_json(), main(), Membaca dan mengembalikan konten file JSON., Worker function to find the best combination within a given range of combination, Find the best combination of items to fill the space left using multiprocessing.

### Community 19 - "get_size"
Cohesion: 0.67
Nodes (3): get_size(), main(), Menghitung ukuran total dari file atau folder.

### Community 25 - "tme3bot Agent Context"
Cohesion: 0.12
Nodes (15): Arsitektur, graphify, Jebakan, Operasional, Profile Layout, Queue Rules, Security, tme3bot Agent Context (+7 more)

### Community 26 - "build.py"
Cohesion: 0.73
Nodes (5): build_archive(), is_excluded(), iter_files(), main(), Path

## Knowledge Gaps
- **16 isolated node(s):** `tme3bot-leave-helper`, `compress.sh script`, `pindah.sh script`, `Arsitektur`, `Security` (+11 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ProfileManager` connect `ProfileManager` to `StateStore`, `TDLClient`, `SourceHandler`, `bot_text.py`, `UtilityHandler`, `run.py`, `SerialPerKeyQueue`, `SourceSelectionStore`?**
  _High betweenness centrality (0.120) - this node is a cross-community bridge._
- **Why does `TDLClient` connect `TDLClient` to `ProfileManager`, `StateStore`, `run.py`, `bot_text.py`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Why does `PanelManager` connect `ProfileManager` to `UtilityHandler`, `SourceHandler`, `SerialPerKeyQueue`, `SourceSelectionStore`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 21 inferred relationships involving `ProfileManager` (e.g. with `TelegramBotApp` and `DownloadQueueJob`) actually correct?**
  _`ProfileManager` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `StateStore` (e.g. with `FakeDownloadTDLClient` and `FakeExportTDLClient`) actually correct?**
  _`StateStore` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `PanelManager` (e.g. with `TelegramBotApp` and `PanelViewStore`) actually correct?**
  _`PanelManager` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `AppConfig` (e.g. with `ProfileTests` and `FakeDownloadTDLClient`) actually correct?**
  _`AppConfig` has 15 INFERRED edges - model-reasoned connections that need verification._