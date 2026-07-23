from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, replace
from pathlib import Path

try:
    import pwd
except ModuleNotFoundError:  # pragma: no cover - Windows local test environment
    pwd = None

from tme3bot.config import AppConfig
from tme3bot.names import normalize_profile_name
from tme3bot.persistence import write_json_atomic
from tme3bot.progress import DownloadProgressTracker
from tme3bot.service import BatchDownloadService, ExportService
from tme3bot.state import StateStore
from tme3bot.tdl import TDLClient
from tme3bot.leave import LeaveService

LOGGER = logging.getLogger(__name__)
DOWNLOAD_MODE_SHARED = "shared"
DOWNLOAD_MODE_ISOLATED = "isolated"
VALID_DOWNLOAD_MODES = {DOWNLOAD_MODE_SHARED, DOWNLOAD_MODE_ISOLATED}


@dataclass
class ProfileRuntime:
    name: str
    config: AppConfig
    state_store: StateStore
    download_progress: DownloadProgressTracker
    export_tdl_client: TDLClient
    download_tdl_client: TDLClient
    export_service: ExportService
    download_service: BatchDownloadService
    leave_service: LeaveService


class ProfileSelectionStore:
    def __init__(self, path: Path, default_profile: str) -> None:
        self.path = path
        self.default_profile = default_profile
        self._lock = threading.RLock()
        self._chat_profiles: dict[str, str] | None = None

    def get_chat_profile(self, chat_id: int) -> str:
        with self._lock:
            self._load_locked()
            assert self._chat_profiles is not None
            return self._chat_profiles.get(str(chat_id), self.default_profile)

    def set_chat_profile(self, chat_id: int, profile_name: str) -> None:
        with self._lock:
            self._load_locked()
            assert self._chat_profiles is not None
            self._chat_profiles[str(chat_id)] = profile_name
            self._save_locked()

    def _load_locked(self) -> None:
        if self._chat_profiles is not None:
            return
        if not self.path.exists():
            self._chat_profiles = {}
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOGGER.warning("Tidak bisa membaca profile selection store: %s", self.path)
            self._chat_profiles = {}
            return
        raw_chat_profiles = (
            payload.get("chat_profiles", {}) if isinstance(payload, dict) else {}
        )
        self._chat_profiles = {
            str(chat_id): normalize_profile_name(str(profile_name))
            for chat_id, profile_name in raw_chat_profiles.items()
            if normalize_profile_name(str(profile_name))
        }

    def _save_locked(self) -> None:
        write_json_atomic(self.path, {"chat_profiles": self._chat_profiles or {}})


class ProfileManager:
    def __init__(self, base_config: AppConfig) -> None:
        self.base_config = base_config
        self.default_profile = (
            normalize_profile_name(base_config.default_profile) or "default"
        )
        self.selection_store = ProfileSelectionStore(
            base_config.state_file.parent / "profile_state.json", self.default_profile
        )
        self._lock = threading.RLock()
        self._runtimes: dict[str, ProfileRuntime] = {}

    def active_profile_for_chat(self, chat_id: int) -> str:
        profile = self.profile_for_user(chat_id)
        if profile is None:
            raise PermissionError("User Telegram belum terdaftar pada sesi TDL.")
        return profile

    def profile_for_user(self, telegram_user_id: int) -> str | None:
        for profile_name in self.list_profiles():
            config = build_profile_config(self.base_config, profile_name)
            identity_path = Path(config.profile_root) / "identity.json"
            try:
                payload = json.loads(identity_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            raw_id = payload.get("telegram_user_id", payload.get("tdl_user_id"))
            try:
                if int(raw_id) == int(telegram_user_id):
                    return profile_name
            except (TypeError, ValueError):
                continue
        return None

    def is_authorized(self, telegram_user_id: int) -> bool:
        return self.profile_for_user(telegram_user_id) is not None

    def set_active_profile_for_chat(self, chat_id: int, profile_name: str) -> str:
        del profile_name
        selected = self.profile_for_user(chat_id)
        if selected is None:
            raise PermissionError("Profile ditentukan otomatis dari identity sesi TDL.")
        return selected

    def list_profiles(self) -> list[str]:
        profiles = {self.default_profile}
        if self.base_config.profiles_root.exists():
            for child in self.base_config.profiles_root.iterdir():
                if child.is_dir():
                    profiles.add(normalize_profile_name(child.name))
        return sorted(profile for profile in profiles if profile)

    def download_mode(self, profile_name: str) -> str:
        normalized = normalize_profile_name(profile_name) or self.default_profile
        return get_profile_download_mode(self.base_config, normalized)

    def set_download_mode(self, profile_name: str, mode: str) -> str:
        normalized = normalize_profile_name(profile_name) or self.default_profile
        selected_mode = set_profile_download_mode(self.base_config, normalized, mode)
        with self._lock:
            self._runtimes.pop(normalized, None)
        self.runtime(normalized)
        return selected_mode

    def runtime(self, profile_name: str) -> ProfileRuntime:
        normalized = normalize_profile_name(profile_name) or self.default_profile
        with self._lock:
            runtime = self._runtimes.get(normalized)
            if runtime is not None:
                return runtime
            profile_config = build_profile_config(self.base_config, normalized)
            ensure_profile_runtime_dirs(profile_config)
            runtime = build_profile_runtime(normalized, profile_config)
            self._runtimes[normalized] = runtime
            return runtime


def profile_settings_path(base_config: AppConfig, profile_name: str) -> Path:
    normalized = normalize_profile_name(profile_name) or normalize_profile_name(
        base_config.default_profile
    )
    return base_config.profiles_root / normalized / "profile.json"


def read_profile_settings(
    base_config: AppConfig, profile_name: str
) -> dict[str, object]:
    path = profile_settings_path(base_config, profile_name)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Tidak bisa membaca profile settings: %s", path)
        return {}
    return payload if isinstance(payload, dict) else {}


def write_profile_settings(
    base_config: AppConfig, profile_name: str, settings: dict[str, object]
) -> None:
    path = profile_settings_path(base_config, profile_name)
    write_json_atomic(path, settings)


def get_profile_download_mode(base_config: AppConfig, profile_name: str) -> str:
    normalized = normalize_profile_name(profile_name) or normalize_profile_name(
        base_config.default_profile
    )
    if normalized == normalize_profile_name(base_config.default_profile):
        return DOWNLOAD_MODE_SHARED
    raw_mode = str(
        read_profile_settings(base_config, normalized).get("download_mode")
        or DOWNLOAD_MODE_SHARED
    )
    return raw_mode if raw_mode in VALID_DOWNLOAD_MODES else DOWNLOAD_MODE_SHARED


def set_profile_download_mode(
    base_config: AppConfig, profile_name: str, mode: str
) -> str:
    normalized = normalize_profile_name(profile_name) or normalize_profile_name(
        base_config.default_profile
    )
    selected_mode = normalize_profile_name(mode).replace("-", "_")
    if selected_mode not in VALID_DOWNLOAD_MODES:
        raise ValueError("Mode download harus 'shared' atau 'isolated'.")
    if (
        normalized == normalize_profile_name(base_config.default_profile)
        and selected_mode == DOWNLOAD_MODE_ISOLATED
    ):
        raise ValueError("Profile default selalu memakai folder download utama.")
    settings = read_profile_settings(base_config, normalized)
    settings["download_mode"] = selected_mode
    write_profile_settings(base_config, normalized, settings)
    return selected_mode


def describe_download_mode(mode: str) -> str:
    return (
        "terpisah per profile"
        if mode == DOWNLOAD_MODE_ISOLATED
        else "download utama/default"
    )


def build_profile_runtime(profile_name: str, config: AppConfig) -> ProfileRuntime:
    state_store = StateStore(config.state_file, config.legacy_max_json)
    state_store.load()
    download_progress = DownloadProgressTracker()
    export_tdl_client = TDLClient(
        storage_root=config.tdl_export_storage,
        namespace=config.tdl_export_namespace,
        debug=config.log_level == "DEBUG",
        run_as_user=config.tdl_export_user,
        home=config.tdl_export_home,
        log_prefix=f"tdl-export:{profile_name}",
        stall_timeout_seconds=config.tdl_export_stall_timeout_seconds,
    )
    download_tdl_client = TDLClient(
        storage_root=config.tdl_download_storage,
        namespace=config.tdl_download_namespace,
        debug=config.log_level == "DEBUG",
        run_as_user=config.tdl_download_user,
        home=config.tdl_download_home,
        log_prefix=f"tdl-download:{profile_name}",
        stall_timeout_seconds=config.tdl_download_stall_timeout_seconds,
        progress_callback=download_progress.update_tdl_progress,
    )
    export_service = ExportService(config, state_store, export_tdl_client)
    download_service = BatchDownloadService(
        config, state_store, download_tdl_client, progress_tracker=download_progress
    )
    leave_service = LeaveService(config)
    return ProfileRuntime(
        name=profile_name,
        config=config,
        state_store=state_store,
        download_progress=download_progress,
        export_tdl_client=export_tdl_client,
        download_tdl_client=download_tdl_client,
        export_service=export_service,
        download_service=download_service,
        leave_service=leave_service,
    )


def build_profile_config(base_config: AppConfig, profile_name: str) -> AppConfig:
    normalized = normalize_profile_name(profile_name) or base_config.default_profile
    if normalized == normalize_profile_name(base_config.default_profile):
        return base_config

    root = base_config.profiles_root / normalized
    export_root = root / "exports"
    download_home = root / "root"
    export_home = root / "user1"
    download_mode = get_profile_download_mode(base_config, normalized)
    download_root = (
        root / "download"
        if download_mode == DOWNLOAD_MODE_ISOLATED
        else base_config.download_root
    )
    return replace(
        base_config,
        profile_root=str(root),
        download_root=download_root,
        export_pending_dir=export_root / "pending",
        export_processing_dir=export_root / "processing",
        export_done_dir=export_root / "done",
        export_failed_dir=export_root / "failed",
        state_file=root / "state.json",
        legacy_max_json=root / "max.json",
        tdl_download_home=download_home,
        tdl_download_storage=download_home / ".tdl",
        tdl_export_home=export_home,
        tdl_export_storage=export_home / ".tdl",
        temp_root=root / "tmp",
    )


def ensure_profile_runtime_dirs(config: AppConfig) -> None:
    root_owned_paths = [
        config.download_root,
        config.download_root / "berlabel",
        config.download_root / "biasa",
        config.export_processing_dir,
        config.export_done_dir,
        config.export_failed_dir,
        config.tdl_download_home,
        config.tdl_download_storage,
    ]
    export_owned_paths = [
        config.tdl_export_home,
        config.tdl_export_storage,
        config.temp_root,
        config.export_pending_dir,
    ]
    for path in root_owned_paths + export_owned_paths:
        path.mkdir(parents=True, exist_ok=True)
    (config.tdl_export_storage / "log").mkdir(parents=True, exist_ok=True)
    (config.tdl_download_storage / "log").mkdir(parents=True, exist_ok=True)
    chown_paths(
        export_owned_paths + [config.tdl_export_storage / "log"], config.tdl_export_user
    )


def chown_paths(paths: list[object], username: str) -> None:
    if username == "root" or os.name == "nt" or pwd is None:
        return
    try:
        user_info = pwd.getpwnam(username)
    except KeyError:
        LOGGER.warning("User %s tidak ditemukan; skip chown runtime dirs", username)
        return
    for raw_path in paths:
        chown_tree(os.fspath(raw_path), user_info.pw_uid, user_info.pw_gid, username)


def chown_tree(path: str, uid: int, gid: int, username: str) -> None:
    try:
        os.chown(path, uid, gid)
    except PermissionError:
        LOGGER.warning("Tidak bisa chown %s ke %s", path, username)
        return
    if not os.path.isdir(path):
        return
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            child = os.path.join(dirpath, name)
            try:
                os.chown(child, uid, gid)
            except PermissionError:
                LOGGER.warning("Tidak bisa chown %s ke %s", child, username)
