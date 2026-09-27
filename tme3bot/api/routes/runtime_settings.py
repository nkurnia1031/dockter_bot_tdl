from __future__ import annotations

from fastapi import Depends

from tme3bot.api.schemas import ObjectResponse, RuntimeSecretsRequest
from tme3bot.domain.models import DomainError


def register_runtime_settings(app, context, *, current_actor, require_service):
    @app.get("/api/v1/runtime/secrets", response_model=ObjectResponse)
    def runtime_secret_status(actor=Depends(current_actor)):
        del actor
        values = context.runtime_settings.get() if context.runtime_settings is not None else {}
        return {
            "telegram_bot_token_configured": bool(values.get("bot_token")),
            "telegram_tts_chat_configured": bool(values.get("telegram_tts_chat_id")),
        }

    @app.put("/api/v1/runtime/secrets", response_model=ObjectResponse)
    def update_runtime_secrets(
        body: RuntimeSecretsRequest, actor=Depends(current_actor)
    ):
        del actor
        if context.runtime_settings is None:
            raise DomainError(
                "RUNTIME_SETTINGS_UNAVAILABLE",
                "Penyimpanan pengaturan runtime belum tersedia.",
                status_code=503,
            )
        values = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
        if not values:
            raise DomainError("RUNTIME_SECRET_REQUIRED", "Masukkan nilai yang ingin disimpan.", status_code=422)
        try:
            saved = context.runtime_settings.update(values)
        except (TypeError, ValueError) as exc:
            raise DomainError("INVALID_RUNTIME_SECRET", str(exc), status_code=422) from exc
        restart_services = []
        if "bot_token" in values:
            restart_services.extend(["backend", "telegram"])
        return {
            "telegram_bot_token_configured": bool(saved.get("bot_token")),
            "telegram_tts_chat_configured": bool(saved.get("telegram_tts_chat_id")),
            "restart_required_services": list(dict.fromkeys(restart_services)),
        }

    @app.get(
        "/internal/v1/telegram/bootstrap",
        include_in_schema=False,
        dependencies=[Depends(require_service)],
    )
    def telegram_bootstrap():
        values = context.runtime_settings.get() if context.runtime_settings is not None else {}
        return {
            "bot_token": str(
                values["bot_token"] if "bot_token" in values else context.config.bot_token
            ),
            "telegram_tts_chat_id": str(
                values["telegram_tts_chat_id"]
                if "telegram_tts_chat_id" in values
                else getattr(context.config, "telegram_tts_chat_id", "")
            ),
        }
