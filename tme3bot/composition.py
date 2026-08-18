from __future__ import annotations

import json
import logging
from dataclasses import asdict

import uvicorn

from tme3bot.api.backend import BackendContext, create_backend_app
from tme3bot.api.worker import WorkerContext, create_worker_app
from tme3bot.application.control_plane import ControlPlane
from tme3bot.backup_coordinator import BackupCoordinator, BackupScheduler
from tme3bot.config import AppConfig
from tme3bot.infrastructure.auth import BotAuthService, SqliteAuthRepository
from tme3bot.infrastructure.http_client import WorkerHttpDispatcher
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.export_catalog import ExportArtifactCatalog
from tme3bot.labels import LabelStore
from tme3bot.profiles import ProfileManager
from tme3bot.storage_catalog import StorageCatalog
from tme3bot.storage_maintenance import StorageMaintenanceService
from tme3bot.utility import UtilityFolderStore, UtilitySettingsStore
from tme3bot.worker.executor import WorkerEventPublisher, WorkerJobExecutor
from tme3bot.worker_registry import WorkerRegistry

LOGGER = logging.getLogger(__name__)


class ControlPlaneBackupRouter:
    def __init__(self, control_plane: ControlPlane, actor) -> None:
        self.control_plane = control_plane
        self.actor = actor

    def enqueue_backup(self, worker_name: str, job) -> int:
        created = self.control_plane.submit_job(
            self.actor,
            "backup_node",
            asdict(job),
            profile=self.actor.profile,
            worker=worker_name,
        )
        return int(created.progress.get("position", 0))


def build_backend_context(config: AppConfig) -> tuple[BackendContext, BackupScheduler]:
    from telegram import Bot

    bootstrap_endpoints = config.worker_endpoints or {
        "local": "http://worker-local:8080"
    }
    bootstrap_tokens = dict(config.worker_api_tokens or {})
    for worker_name in bootstrap_endpoints:
        bootstrap_tokens.setdefault(worker_name, config.worker_api_token)
    registry = WorkerRegistry(
        config.state_file.parent / "workers.json",
        bootstrap_endpoints,
        bootstrap_tokens,
    )
    profiles = ProfileManager(config, registry)
    profiles.profile_registry.bootstrap_from_identities(
        {
            item["name"]: item.get("telegram_user_id")
            for item in profiles.local_profile_identities()
        }
    )
    catalog = StorageCatalog(config.storage_db_file)
    export_catalog = ExportArtifactCatalog(config.storage_db_file)
    jobs = SqliteJobRepository(config.storage_db_file)
    dispatcher = WorkerHttpDispatcher(registry)
    folders = UtilityFolderStore(
        config.utility_folders_file, config.utility_workspace_root
    )
    settings = UtilitySettingsStore(config.utility_settings_file)
    labels = LabelStore(config.state_file.parent / "labels.json")
    control_plane = ControlPlane(
        jobs,
        dispatcher,
        profiles,
        storage_catalog=catalog,
        export_catalog=export_catalog,
        worker_registry=registry,
        utility_folders=folders,
        utility_settings=settings,
        label_store=labels,
    )
    control_plane.start_scheduler()
    auth_repository = SqliteAuthRepository(config.storage_db_file)
    auth = BotAuthService(
        auth_repository,
        control_plane.actor,
        config.auth_jwt_secret,
        config.bot_username,
        access_minutes=config.auth_access_minutes,
        refresh_days=config.auth_refresh_days,
        challenge_minutes=config.auth_challenge_minutes,
    )
    bot = Bot(token=config.bot_token)
    storage_maintenance = StorageMaintenanceService(
        catalog, bot, config.storage_trash_retention_days
    )
    coordinator = None
    scheduler = BackupScheduler(config, _NullCoordinator())
    try:
        system_actor = _first_actor(control_plane, profiles)
        coordinator = BackupCoordinator(
            config,
            bot,
            catalog,
            worker_registry=registry,
            remote_router=ControlPlaneBackupRouter(control_plane, system_actor),
        )
        def backup_observer(event) -> None:
            if event.status.value != "succeeded":
                return
            job = control_plane.jobs.get(event.job_id)
            if job is not None and job.kind == "backup_node":
                coordinator.prune_node(
                    str(job.payload.get("node_name", job.worker))
                )

        control_plane.add_event_observer(backup_observer)
        scheduler = BackupScheduler(config, coordinator)
    except RuntimeError:
        LOGGER.warning("Backup scheduler menunggu setidaknya satu identity.")
    context = BackendContext(
        config=config,
        control_plane=control_plane,
        auth=auth,
        profile_manager=profiles,
        storage_catalog=catalog,
        export_catalog=export_catalog,
        worker_registry=registry,
        utility_folders=folders,
        utility_settings=settings,
        label_store=labels,
        backup_coordinator=coordinator,
        bot=bot,
        worker_dispatcher=dispatcher,
        storage_maintenance=storage_maintenance,
    )
    return context, scheduler


def run_backend(config: AppConfig) -> None:
    context, scheduler = build_backend_context(config)
    scheduler.start()
    context.storage_maintenance.start()
    uvicorn.run(
        create_backend_app(context),
        host=config.backend_bind_host,
        port=config.backend_port,
        log_level=config.log_level.lower(),
    )


def run_worker(config: AppConfig) -> None:
    profiles = ProfileManager(config)
    publisher = WorkerEventPublisher(
        config.backend_api_url, config.backend_internal_token
    )
    executor = WorkerJobExecutor(config, profiles, publisher)
    executor.start()
    uvicorn.run(
        create_worker_app(WorkerContext(config, executor)),
        host=config.worker_bind_host,
        port=config.worker_port,
        log_level=config.log_level.lower(),
    )


def _first_actor(control_plane: ControlPlane, profiles: ProfileManager):
    for profile in profiles.list_profiles():
        config = profiles.runtime(profile).config
        identity_path = config.state_file.parent / "identity.json"
        try:
            payload = json.loads(identity_path.read_text(encoding="utf-8"))
            user_id = int(
                payload.get("telegram_user_id", payload.get("tdl_user_id"))
            )
            return control_plane.actor(user_id)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    raise RuntimeError("No authorized identity")


class _NullCoordinator:
    def next_run(self):
        raise RuntimeError("No backup coordinator")

    def start_now(self):
        raise RuntimeError("No backup coordinator")
