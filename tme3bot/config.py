from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from tme3bot.channel_ref import channel_chat_id, channel_tdl_ref, compact_channel_ref

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
    app_role: str = "backend"
    leave_helper_binary: str = "/usr/local/bin/tdl-leave"
    utility_workspace_root: Path = Path("/workspace")
    utility_folders_file: Path = Path("/data/utility_folders.json")
    utility_settings_file: Path = Path("/data/utility_settings.json")
    storage_channel_ref: str = ""
    storage_channel_id: int = 0
    storage_channel_username: str = ""
    storage_channel: str = ""
    storage_db_file: Path = Path("/data/storage.db")
    backup_enabled: bool = True
    backup_channel_ref: str = ""
    backup_channel_id: int = 0
    backup_channel_username: str = ""
    backup_channel: str = ""
    backup_schedule: str = "03:00"
    backup_timezone: str = "Asia/Jakarta"
    backup_retention: int = 7
    backup_volume_size: str = "45m"
    backup_node_name: str = "gateway"
    worker_bind_host: str = "0.0.0.0"
    gateway_port: int = 8080
    worker_port: int = 8080
    worker_api_token: str = ""
    gateway_api_url: str = ""
    gateway_api_token: str = ""
    worker_local_url: str = ""
    worker_remote_url: str = ""
    worker_routes: dict[str, str] | None = None
    worker_endpoints: dict[str, str] | None = None
    worker_api_tokens: dict[str, str] | None = None
    backend_api_url: str = ""
    backend_bind_host: str = "0.0.0.0"
    backend_port: int = 8080
    frontend_service_token: str = ""
    management_api_token: str = ""
    backend_internal_token: str = ""
    auth_jwt_secret: str = ""
    auth_access_minutes: int = 15
    auth_refresh_days: int = 30
    auth_challenge_minutes: int = 5
    bot_username: str = ""

    def validate_runtime(self) -> None:
        """Fail fast when a production role is missing its trust boundary."""

        required: dict[str, str] = {}
        if self.app_role == "backend":
            required = {
                "FRONTEND_SERVICE_TOKEN": self.frontend_service_token,
                "MANAGEMENT_API_TOKEN": self.management_api_token,
                "BACKEND_INTERNAL_TOKEN": self.backend_internal_token,
                "AUTH_JWT_SECRET": self.auth_jwt_secret,
                "BOT_USERNAME": self.bot_username,
            }
            if self.auth_jwt_secret and len(self.auth_jwt_secret) < 32:
                raise ValueError(
                    "AUTH_JWT_SECRET minimal 32 karakter untuk APP_ROLE=backend."
                )
        elif self.app_role == "telegram":
            required = {
                "BACKEND_API_URL": self.backend_api_url,
                "FRONTEND_SERVICE_TOKEN": self.frontend_service_token,
            }
        elif self.app_role == "worker":
            required = {
                "BACKEND_API_URL": self.backend_api_url,
                "BACKEND_INTERNAL_TOKEN": self.backend_internal_token,
                "WORKER_API_TOKEN": self.worker_api_token,
            }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(
                f"Konfigurasi wajib untuk APP_ROLE={self.app_role} belum diisi: "
                + ", ".join(missing)
            )

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv(override=False)

        app_role = os.getenv("APP_ROLE", "backend").strip().lower() or "backend"
        if app_role not in {"backend", "telegram", "worker"}:
            raise ValueError("APP_ROLE harus backend, telegram, atau worker.")
        bot_token = os.getenv("BOT_TOKEN", "").strip()
        if app_role in {"backend", "telegram"} and not bot_token:
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
        utility_settings_file = Path(os.getenv("UTILITY_SETTINGS_FILE", "/data/utility_settings.json"))
        storage_channel = compact_channel_ref(os.getenv("STORAGE_CHANNEL", "").strip() or os.getenv("STORAGE_CHANNEL_REF", "").strip())
        storage_channel_ref = channel_tdl_ref(storage_channel)
        storage_channel_username = os.getenv("STORAGE_CHANNEL_USERNAME", "").strip().lstrip("@")
        raw_storage_channel_id = os.getenv("STORAGE_CHANNEL_ID", "").strip()
        try:
            storage_channel_id = channel_chat_id(storage_channel) if storage_channel else (int(raw_storage_channel_id) if raw_storage_channel_id else 0)
        except ValueError as exc:
            raise ValueError("STORAGE_CHANNEL_ID harus berupa angka Telegram chat ID.") from exc
        storage_db_file = Path(os.getenv("STORAGE_DB_FILE", "/data/storage.db"))
        backup_enabled = os.getenv("BACKUP_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
        backup_channel = compact_channel_ref(os.getenv("BACKUP_CHANNEL", "").strip() or os.getenv("BACKUP_CHANNEL_REF", "").strip())
        backup_channel_ref = channel_tdl_ref(backup_channel)
        backup_channel_username = os.getenv("BACKUP_CHANNEL_USERNAME", "").strip().lstrip("@")
        raw_backup_channel_id = os.getenv("BACKUP_CHANNEL_ID", "").strip()
        try:
            backup_channel_id = channel_chat_id(backup_channel) if backup_channel else (int(raw_backup_channel_id) if raw_backup_channel_id else 0)
        except ValueError as exc:
            raise ValueError("BACKUP_CHANNEL_ID harus berupa angka Telegram chat ID.") from exc
        try:
            backup_retention = max(1, int(os.getenv("BACKUP_RETENTION", "7")))
        except ValueError as exc:
            raise ValueError("BACKUP_RETENTION harus berupa angka positif.") from exc
        backup_schedule = os.getenv("BACKUP_SCHEDULE", "03:00").strip() or "03:00"
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", backup_schedule):
            raise ValueError("BACKUP_SCHEDULE harus berformat HH:MM.")
        backup_volume_size = os.getenv("BACKUP_VOLUME_SIZE", "45m").strip() or "45m"
        backup_node_name = os.getenv("BACKUP_NODE_NAME", "gateway").strip() or "gateway"
        routes: dict[str, str] = {}
        for item in os.getenv("WORKER_ROUTES", "").split(","):
            if "=" not in item:
                continue
            profile, route = item.split("=", 1)
            profile, route = profile.strip(), route.strip().lower()
            if profile and route:
                routes[profile] = route

        endpoints = _parse_named_values(os.getenv("WORKER_ENDPOINTS", ""), lower_keys=True)
        if not endpoints:
            if worker_local_url := os.getenv("WORKER_LOCAL_URL", "").strip().rstrip("/"):
                endpoints["local"] = worker_local_url
            if worker_remote_url := os.getenv("WORKER_REMOTE_URL", "").strip().rstrip("/"):
                endpoints["remote"] = worker_remote_url
        api_tokens = _parse_named_values(os.getenv("WORKER_API_TOKENS", ""), lower_keys=True)

        return cls(
            bot_token=bot_token,
            app_role=app_role,
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
            utility_settings_file=utility_settings_file,
            storage_channel_ref=storage_channel_ref,
            storage_channel_id=storage_channel_id,
            storage_channel_username=storage_channel_username,
            storage_channel=storage_channel,
            storage_db_file=storage_db_file,
            backup_enabled=backup_enabled,
            backup_channel_ref=backup_channel_ref,
            backup_channel_id=backup_channel_id,
            backup_channel_username=backup_channel_username,
            backup_channel=backup_channel,
            backup_schedule=backup_schedule,
            backup_timezone=os.getenv("BACKUP_TIMEZONE", "Asia/Jakarta").strip() or "Asia/Jakarta",
            backup_retention=backup_retention,
            backup_volume_size=backup_volume_size,
            backup_node_name=backup_node_name,
            worker_bind_host=os.getenv("WORKER_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0",
            gateway_port=int(os.getenv("GATEWAY_PORT", "8080")),
            worker_port=int(os.getenv("WORKER_PORT", "8080")),
            worker_api_token=os.getenv("WORKER_API_TOKEN", "").strip(),
            gateway_api_url=os.getenv("GATEWAY_API_URL", "").strip().rstrip("/"),
            gateway_api_token=os.getenv("GATEWAY_API_TOKEN", "").strip(),
            worker_local_url=os.getenv("WORKER_LOCAL_URL", "").strip().rstrip("/"),
            worker_remote_url=os.getenv("WORKER_REMOTE_URL", "").strip().rstrip("/"),
            worker_routes=routes,
            worker_endpoints=endpoints,
            worker_api_tokens=api_tokens,
            backend_api_url=os.getenv("BACKEND_API_URL", "").strip().rstrip("/"),
            backend_bind_host=os.getenv("BACKEND_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0",
            backend_port=int(os.getenv("BACKEND_PORT", os.getenv("GATEWAY_PORT", "8080"))),
            frontend_service_token=os.getenv("FRONTEND_SERVICE_TOKEN", "").strip(),
            management_api_token=os.getenv("MANAGEMENT_API_TOKEN", "").strip(),
            backend_internal_token=os.getenv("BACKEND_INTERNAL_TOKEN", "").strip(),
            auth_jwt_secret=os.getenv("AUTH_JWT_SECRET", "").strip(),
            auth_access_minutes=max(1, int(os.getenv("AUTH_ACCESS_MINUTES", "15"))),
            auth_refresh_days=max(1, int(os.getenv("AUTH_REFRESH_DAYS", "30"))),
            auth_challenge_minutes=max(1, int(os.getenv("AUTH_CHALLENGE_MINUTES", "5"))),
            bot_username=os.getenv("BOT_USERNAME", "").strip().lstrip("@"),
        )


def _parse_named_values(raw: str, *, lower_keys: bool = False) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in raw.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key, value = key.strip(), value.strip()
        if lower_keys:
            key = key.lower()
        if key and value:
            values[key] = value
    return values
