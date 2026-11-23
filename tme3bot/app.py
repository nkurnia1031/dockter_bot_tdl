from __future__ import annotations

import logging
from dataclasses import replace

from tme3bot.config import AppConfig
from tme3bot.database_paths import set_private_file_creation_umask


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    config = AppConfig.from_env()
    config.validate_runtime()
    if config.app_role in {"backend", "backend-queue", "worker"}:
        set_private_file_creation_umask()
    configure_logging(config.log_level)
    if config.app_role == "backend":
        from tme3bot.composition import run_backend

        run_backend(config)
        return
    if config.app_role == "backend-queue":
        from tme3bot.composition import run_queue

        run_queue(config)
        return
    if config.app_role == "worker":
        from tme3bot.composition import run_worker

        run_worker(config)
        return
    if config.app_role in {"telegram", "telegram-login"}:
        from tme3bot.frontend.client import BackendApiClient

        client = BackendApiClient(
            config.backend_api_url, config.frontend_service_token
        )
        try:
            managed = client.telegram_bootstrap_settings()
            bot_token = str(managed.get("bot_token") or "").strip()
            if bot_token:
                config = replace(
                    config,
                    bot_token=bot_token,
                    telegram_tts_chat_id=str(
                        managed.get("telegram_tts_chat_id") or ""
                    ),
                )
        except Exception:
            # Preserve environment bootstrap for upgrades where the backend
            # has not yet received the internal bootstrap endpoint.
            logging.getLogger(__name__).warning(
                "Telegram runtime settings unavailable; using environment bootstrap"
            )
        if config.app_role == "telegram-login":
            from tme3bot.frontend.telegram_login import TelegramLoginApp

            TelegramLoginApp(config, client).start()
        else:
            from tme3bot.frontend.telegram import TelegramFrontendApp

            TelegramFrontendApp(config, client).start()
        return
    raise RuntimeError(f"APP_ROLE tidak didukung: {config.app_role}")
