from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict

import uvicorn

from tme3bot.api.backend import BackendContext, create_backend_app
from tme3bot.api.worker import WorkerContext, create_worker_app
from tme3bot.application.control_plane import ControlPlane
from tme3bot.application.operations import OperationsService
from tme3bot.backup_coordinator import BackupCoordinator, BackupScheduler
from tme3bot.backend_runtime_settings import BackendRuntimeSettings
from tme3bot.config import AppConfig
from tme3bot.infrastructure.auth import BotAuthService, SqliteAuthRepository
from tme3bot.infrastructure.device_auth import DeviceAuthService
from tme3bot.infrastructure.http_client import WorkerHttpDispatcher
from tme3bot.infrastructure.job_store import SqliteJobRepository
from tme3bot.infrastructure.operation_store import SqliteOperationStore
from tme3bot.infrastructure.queue_transport import (
    QueueCommandService,
    QueueOutboxPublisher,
)
from tme3bot.infrastructure.source_store import (
    SqliteProfileStateStore,
    SqliteSourceRepository,
)
from tme3bot.infrastructure.settings_store import SqliteSettingsStore
from tme3bot.infrastructure.tdl_access_store import SqliteTdlAccessStore
from tme3bot.export_catalog import ExportArtifactCatalog
from tme3bot.labels import LabelStore
from tme3bot.profiles import ProfileManager
from tme3bot.profile_provisioning import ProfileProvisioningService, ProfileProvisioningStore
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

    runtime_settings = BackendRuntimeSettings(
        config.state_file.parent / "app_runtime_settings.json",
        {
            "backup_enabled": config.backup_enabled,
            "backup_schedule": config.backup_schedule,
            "backup_timezone": config.backup_timezone,
            "backup_retention": config.backup_retention,
            "backup_volume_size": config.backup_volume_size,
            "backup_channel": config.backup_channel,
            "backup_channel_id": config.backup_channel_id,
            "storage_trash_retention_days": config.storage_trash_retention_days,
            "job_stall_timeout_seconds": config.job_stall_timeout_seconds,
            "job_cancel_grace_seconds": config.job_cancel_grace_seconds,
            "bot_token": config.bot_token,
            "telegram_tts_chat_id": config.telegram_tts_chat_id,
        },
    )
    legacy_runtime_values = runtime_settings.get()
    legacy_utility_settings = UtilitySettingsStore(config.utility_settings_file)
    legacy_utility_values = legacy_utility_settings.get()
    runtime_settings_store = SqliteSettingsStore(
        config.storage_db_file,
        config.state_file.parent / "runtime-settings" / "settings.key",
    )
    runtime_settings_store.seed_once(
        "backend-runtime-json-env-v1",
        legacy_runtime_values,
        source="legacy-runtime-json-env",
    )
    runtime_settings_store.seed_once(
        "utility-settings-json-v1",
        legacy_utility_values,
        source="legacy-utility-json",
    )
    runtime_settings.attach_settings_store(runtime_settings_store)
    BackendRuntimeSettings.apply_to(config, runtime_settings.get())

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
    source_repository = SqliteSourceRepository(config.storage_db_file)
    profile_vault = ProfileProvisioningStore(
        config.storage_db_file,
        config.state_file.parent / "profile-vault",
    )
    profiles = ProfileManager(
        config,
        registry,
        source_repository=source_repository,
        source_state_store_factory=SqliteProfileStateStore,
    )
    for vaulted_name, telegram_user_id in profile_vault.vaulted_identities().items():
        try:
            profiles.profile_registry.register_vaulted(vaulted_name, telegram_user_id)
        except ValueError:
            LOGGER.warning("Vault identity registry conflict for profile %s.", vaulted_name)
    vaulted_profiles = set(profile_vault.vaulted_identities())
    for item in profiles.local_profile_identities():
        profile_name = str(item.get("name") or "")
        telegram_user_id = item.get("telegram_user_id")
        if not profile_name or profile_name in vaulted_profiles:
            continue
        try:
            if telegram_user_id is not None:
                profile_vault.record_legacy_discovery(
                    profile_name, int(telegram_user_id), "local"
                )
            profiles.profile_registry.register_discovered(
                profile_name,
                int(telegram_user_id) if telegram_user_id is not None else None,
            )
        except (TypeError, ValueError):
            LOGGER.warning("Local worker profile metadata is invalid for %s.", profile_name)
    catalog = StorageCatalog(config.storage_db_file)
    export_catalog = ExportArtifactCatalog(config.storage_db_file)
    jobs = SqliteJobRepository(config.storage_db_file)
    tdl_access_store = SqliteTdlAccessStore(config.storage_db_file)
    operation_store = SqliteOperationStore(jobs)
    operation_service = OperationsService(operation_store)
    queue_command_service = QueueCommandService(operation_store)
    queue_publisher = (
        QueueOutboxPublisher(
            operation_store,
            config.redis_url,
            operations=operation_service,
        )
        if config.durable_dispatch_enabled
        else None
    )
    dispatcher = WorkerHttpDispatcher(registry)
    profile_provisioner = ProfileProvisioningService(
        profile_vault,
        profiles,
        registry,
        dispatcher,
        operation_service,
    )
    folders = UtilityFolderStore(
        config.utility_folders_file, config.utility_workspace_root
    )
    settings = UtilitySettingsStore(
        config.utility_settings_file, desired_store=runtime_settings_store
    )
    labels = LabelStore(config.state_file.parent / "labels.json")
    def tdl_access_target(purpose: str) -> str:
        if purpose == "tts":
            values = runtime_settings_store.get_values("telegram", include_secrets=True)
            return str(values.get("telegram_tts_chat_id") or "")
        if purpose == "storage":
            return str(
                getattr(config, "storage_channel_ref", "")
                or getattr(config, "storage_channel", "")
                or getattr(config, "storage_channel_id", "")
                or ""
            )
        return ""

    control_plane = ControlPlane(
        jobs,
        dispatcher,
        profiles,
        storage_catalog=catalog,
        export_catalog=export_catalog,
        worker_registry=registry,
        profile_readiness=profile_provisioner.worker_ready,
        utility_folders=folders,
        utility_settings=settings,
        runtime_settings_store=runtime_settings_store,
        label_store=labels,
        tdl_access_store=tdl_access_store,
        tdl_access_target_resolver=tdl_access_target,
        job_stall_timeout_seconds=config.job_stall_timeout_seconds,
        job_cancel_grace_seconds=config.job_cancel_grace_seconds,
    )
    control_plane.add_event_observer(operation_service.on_job_event)
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
    device_auth = DeviceAuthService(
        auth_repository,
        auth,
        config.web_public_origin,
    )
    bot = Bot(token=config.bot_token)
    if config.backup_channel_ref and not config.backup_channel_id:
        try:
            from tme3bot.chat_refs import normalize_bot_api_chat_ref

            resolved = bot.get_chat(
                normalize_bot_api_chat_ref(config.backup_channel_ref)
            )
            object.__setattr__(config, "backup_channel_id", int(resolved.id))
            values = runtime_settings.get()
            if not values.get("backup_channel_id"):
                runtime_settings.update({"backup_channel_id": config.backup_channel_id})
                BackendRuntimeSettings.apply_to(config, runtime_settings.get())
        except Exception:
            LOGGER.warning(
                "Backup channel username belum bisa di-resolve ke numeric chat ID."
            )
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
        runtime_settings=runtime_settings,
        runtime_settings_store=runtime_settings_store,
        backup_scheduler=scheduler,
        profile_provisioner=profile_provisioner,
        device_auth=device_auth,
        source_repository=source_repository,
        operation_service=operation_service,
        queue_command_service=queue_command_service,
        queue_publisher=queue_publisher,
    )
    return context, scheduler


def run_backend(config: AppConfig) -> None:
    context, scheduler = build_backend_context(config)
    scheduler.start()
    context.storage_maintenance.start()
    if context.profile_provisioner is not None:
        context.profile_provisioner.start()
    if context.queue_publisher is not None:
        context.queue_publisher.start()
    try:
        uvicorn.run(
            create_backend_app(context),
            host=config.backend_bind_host,
            port=config.backend_port,
            log_level=config.log_level.lower(),
        )
    finally:
        if context.profile_provisioner is not None:
            context.profile_provisioner.stop()
        if context.queue_publisher is not None:
            context.queue_publisher.stop()


def run_queue(config: AppConfig) -> None:
    from redis import Redis
    from rq import Queue, Worker
    from rq.serializers import JSONSerializer

    from tme3bot.infrastructure.queue_transport import QUEUE_NAME

    connection = Redis.from_url(
        config.redis_url,
        socket_connect_timeout=5,
        socket_timeout=10,
        health_check_interval=30,
    )
    connection.ping()
    queue = Queue(QUEUE_NAME, connection=connection, serializer=JSONSerializer)
    worker = Worker(
        [queue],
        connection=connection,
        serializer=JSONSerializer,
        name=f"backend-queue-{os.getpid()}",
    )
    LOGGER.info("Backend queue runner started.")
    worker.work(with_scheduler=True, logging_level=config.log_level.upper())


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
