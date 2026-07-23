from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except (
    ModuleNotFoundError
):  # pragma: no cover - local tests may run before deps are installed

    def load_dotenv(*args, **kwargs):
        return False


@dataclass(frozen=True)
class AppConfig:
    bot_token: str
    profile_root: str
    profiles_root: Path
    default_profile: str
    tme3_host: str
    download_root: Path
    export_pending_dir: Path
    export_processing_dir: Path
    export_done_dir: Path
    export_failed_dir: Path
    state_file: Path
    legacy_max_json: Path
    tdl_export_user: str
    tdl_download_user: str
    tdl_export_home: Path
    tdl_download_home: Path
    tdl_export_storage: Path
    tdl_download_storage: Path
    tdl_export_namespace: str
    tdl_download_namespace: str
    tdl_export_stall_timeout_seconds: int
    tdl_download_stall_timeout_seconds: int
    temp_root: Path
    log_level: str
    leave_helper_binary: str = "/usr/local/bin/tdl-leave"
    utility_workspace_root: Path = Path("/workspace")
    utility_folders_file: Path = Path("/data/utility_folders.json")

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv(override=False)

        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if not bot_token:
            raise ValueError("BOT_TOKEN is required.")

        # PROFILE_ROOT is the host path used by Compose. The application sees
        # that mount at /data, so identity and runtime paths must use the
        # container path instead of the host path.
        profile_root = os.getenv("PROFILE_DATA_ROOT", "/data").strip() or "/data"
        profiles_root = Path(os.getenv("PROFILES_ROOT", "/data/profiles"))
        default_profile = os.getenv("DEFAULT_PROFILE", "default").strip() or "default"
        tme3_host = os.getenv("TME3_HOST", "t.me3").strip() or "t.me3"
        download_root = Path(os.getenv("DOWNLOAD_ROOT", "/data/download"))
        export_root = Path(os.getenv("EXPORT_ROOT", "/data/exports"))

        export_pending_dir = Path(
            os.getenv("EXPORT_PENDING_DIR", str(export_root / "pending"))
        )
        export_processing_dir = Path(
            os.getenv("EXPORT_PROCESSING_DIR", str(export_root / "processing"))
        )
        export_done_dir = Path(os.getenv("EXPORT_DONE_DIR", str(export_root / "done")))
        export_failed_dir = Path(
            os.getenv("EXPORT_FAILED_DIR", str(export_root / "failed"))
        )

        state_file = Path(os.getenv("STATE_FILE", "/data/state.json"))
        legacy_max_json = Path(os.getenv("LEGACY_MAX_JSON", "/data/max.json"))

        tdl_export_user = os.getenv("TDL_EXPORT_USER", "user1").strip() or "user1"
        tdl_download_user = os.getenv("TDL_DOWNLOAD_USER", "root").strip() or "root"
        tdl_export_home = Path(os.getenv("TDL_EXPORT_HOME", "/data/user1"))
        tdl_download_home = Path(os.getenv("TDL_DOWNLOAD_HOME", "/data/root"))
        tdl_export_storage = Path(
            os.getenv("TDL_EXPORT_STORAGE", str(tdl_export_home / ".tdl"))
        )
        tdl_download_storage = Path(
            os.getenv("TDL_DOWNLOAD_STORAGE", str(tdl_download_home / ".tdl"))
        )
        tdl_export_namespace = (
            os.getenv("TDL_EXPORT_NAMESPACE", "default").strip() or "default"
        )
        tdl_download_namespace = (
            os.getenv("TDL_DOWNLOAD_NAMESPACE", "default").strip() or "default"
        )
        tdl_export_stall_timeout_seconds = int(
            os.getenv("TDL_EXPORT_STALL_TIMEOUT_SECONDS", "300")
        )
        tdl_download_stall_timeout_seconds = int(
            os.getenv("TDL_DOWNLOAD_STALL_TIMEOUT_SECONDS", "1800")
        )
        temp_root = Path(os.getenv("TEMP_ROOT", "/data/tmp"))
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        utility_workspace_root = Path(os.getenv("UTILITY_WORKSPACE_ROOT", "/workspace"))
        utility_folders_file = Path(os.getenv("UTILITY_FOLDERS_FILE", "/data/utility_folders.json"))

        return cls(
            bot_token=bot_token,
            profile_root=profile_root,
            profiles_root=profiles_root,
            default_profile=default_profile,
            tme3_host=tme3_host,
            download_root=download_root,
            export_pending_dir=export_pending_dir,
            export_processing_dir=export_processing_dir,
            export_done_dir=export_done_dir,
            export_failed_dir=export_failed_dir,
            state_file=state_file,
            legacy_max_json=legacy_max_json,
            tdl_export_user=tdl_export_user,
            tdl_download_user=tdl_download_user,
            tdl_export_home=tdl_export_home,
            tdl_download_home=tdl_download_home,
            tdl_export_storage=tdl_export_storage,
            tdl_download_storage=tdl_download_storage,
            tdl_export_namespace=tdl_export_namespace,
            tdl_download_namespace=tdl_download_namespace,
            tdl_export_stall_timeout_seconds=tdl_export_stall_timeout_seconds,
            tdl_download_stall_timeout_seconds=tdl_download_stall_timeout_seconds,
            temp_root=temp_root,
            log_level=log_level,
            leave_helper_binary=os.getenv("LEAVE_HELPER_BINARY", "/usr/local/bin/tdl-leave"),
            utility_workspace_root=utility_workspace_root,
            utility_folders_file=utility_folders_file,
        )
