from __future__ import annotations

import hmac

from fastapi import Depends, Header, Query

from tme3bot.api.schemas import (
    ItemListResponse,
    ObjectResponse,
    RuntimeSecretsRequest,
    RuntimeSettingsAckRequest,
    RuntimeSettingsPutRequest,
)
from tme3bot.domain.models import DomainError
from tme3bot.infrastructure.settings_store import (
    SettingsConflict,
    SettingsScopeError,
)


def register_runtime_settings(
    app, context, *, current_actor, require_service, require_internal=None
):
    def desired_store():
        store = getattr(context, "runtime_settings_store", None)
        if store is None:
            raise DomainError(
                "RUNTIME_SETTINGS_UNAVAILABLE",
                "Registry pengaturan runtime belum tersedia.",
                status_code=503,
            )
        return store

    def validate_target(scope: str, worker: str | None) -> str:
        selected = str(worker or "").strip().lower()
        if scope == "worker":
            if context.worker_registry.get(selected) is None:
                raise DomainError(
                    "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
                )
            return selected
        if selected:
            raise DomainError(
                "SETTINGS_SCOPE_INVALID",
                "Parameter worker hanya berlaku untuk scope worker.",
                status_code=422,
            )
        if scope not in {"backend", "telegram"}:
            raise DomainError(
                "SETTINGS_SCOPE_INVALID", "Scope runtime settings tidak dikenal.", status_code=422
            )
        return ""

    def validate_worker_identity(worker: str, supplied_token: str | None) -> str:
        selected = validate_target("worker", worker)
        registration = context.worker_registry.get(selected) or {}
        expected = str(registration.get("token") or "")
        if not expected or not supplied_token or not hmac.compare_digest(
            expected, str(supplied_token)
        ):
            raise DomainError(
                "WORKER_UNAUTHORIZED", "Identitas worker tidak valid.", status_code=401
            )
        return selected

    @app.get("/api/v1/runtime/settings/schema", response_model=ItemListResponse)
    def runtime_settings_schema(scope: str | None = Query(default=None), actor=Depends(current_actor)):
        del actor
        try:
            return {"items": desired_store().schema(scope)}
        except SettingsScopeError as exc:
            raise DomainError("SETTINGS_SCOPE_INVALID", str(exc), status_code=422) from exc

    @app.get("/api/v1/runtime/settings", response_model=ObjectResponse)
    def get_runtime_settings(
        scope: str = Query(default="backend"),
        worker: str | None = Query(default=None),
        actor=Depends(current_actor),
    ):
        del actor
        try:
            selected_worker = validate_target(scope, worker)
            return desired_store().snapshot(scope, worker=selected_worker)
        except SettingsScopeError as exc:
            raise DomainError("SETTINGS_SCOPE_INVALID", str(exc), status_code=422) from exc

    @app.put("/api/v1/runtime/settings", response_model=ObjectResponse)
    def put_runtime_settings(
        body: RuntimeSettingsPutRequest,
        scope: str = Query(default="backend"),
        worker: str | None = Query(default=None),
        actor=Depends(current_actor),
    ):
        try:
            selected_worker = validate_target(scope, worker)
            return desired_store().update(
                scope,
                body.values,
                expected_version=body.expected_version,
                worker=selected_worker,
                clear=body.clear,
                actor_user_id=int(actor.telegram_user_id),
            )
        except SettingsConflict as exc:
            raise DomainError(
                "SETTINGS_VERSION_CONFLICT",
                str(exc),
                status_code=409,
                details={"current_version": exc.current_version},
            ) from exc
        except SettingsScopeError as exc:
            raise DomainError("SETTINGS_SCOPE_INVALID", str(exc), status_code=422) from exc
        except (TypeError, ValueError) as exc:
            raise DomainError("INVALID_RUNTIME_SETTING", str(exc), status_code=422) from exc

    if require_internal is not None:
        @app.get(
            "/internal/v1/runtime/settings",
            include_in_schema=False,
            dependencies=[Depends(require_internal)],
        )
        def worker_settings_manifest(
            worker: str = Query(..., min_length=1, max_length=48),
            worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
        ):
            selected = validate_worker_identity(worker, worker_token)
            return desired_store().manifest(selected)

        @app.post(
            "/internal/v1/runtime/settings/ack",
            include_in_schema=False,
            dependencies=[Depends(require_internal)],
        )
        def acknowledge_worker_settings(
            body: RuntimeSettingsAckRequest,
            worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
        ):
            try:
                selected = validate_worker_identity(body.worker, worker_token)
                if body.scope != "worker":
                    raise SettingsScopeError("ACK hanya berlaku untuk scope worker.")
                return desired_store().acknowledge(
                    body.scope,
                    selected,
                    body.applied_version,
                    success=body.success,
                    error_code=body.error_code,
                )
            except SettingsConflict as exc:
                raise DomainError(
                    "SETTINGS_ACK_STALE",
                    str(exc),
                    status_code=409,
                    details={"current_version": exc.current_version},
                ) from exc
            except SettingsScopeError as exc:
                raise DomainError("SETTINGS_SCOPE_INVALID", str(exc), status_code=422) from exc

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
            saved = context.runtime_settings.update(
                values, actor_user_id=int(actor.telegram_user_id)
            )
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
