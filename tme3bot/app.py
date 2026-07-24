from __future__ import annotations

import logging

from tme3bot.config import AppConfig


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    config = AppConfig.from_env()
    config.validate_runtime()
    configure_logging(config.log_level)
    if config.app_role == "backend":
        from tme3bot.composition import run_backend

        run_backend(config)
        return
    if config.app_role == "worker":
        from tme3bot.composition import run_worker

        run_worker(config)
        return
    if config.app_role == "telegram":
        from tme3bot.frontend.client import BackendApiClient
        from tme3bot.frontend.telegram import TelegramFrontendApp

        client = BackendApiClient(
            config.backend_api_url, config.frontend_service_token
        )
        TelegramFrontendApp(config, client).start()
        return
    raise RuntimeError(f"APP_ROLE tidak didukung: {config.app_role}")
