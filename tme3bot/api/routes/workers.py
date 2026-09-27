from __future__ import annotations

from fastapi import Depends
from tme3bot.api.schemas import (
    ObjectResponse,
    WorkerEnabledRequest,
    WorkerListResponse,
    WorkerRequest,
    WorkerRouteRequest,
    WorkerRuntimeSettingsRequest,
    WorkerUpdateRequest,
)
from tme3bot.domain.models import DomainError
from tme3bot.infrastructure.http_client import JsonHttpError

def register_workers(app, context, *, current_actor):

    @app.get("/api/v1/workers", response_model=WorkerListResponse)
    def list_workers(actor=Depends(current_actor)):
        return {
            "items": [
                {
                    "name": name,
                    "url": value["url"],
                    "enabled": bool(value.get("enabled", True)),
                    "selected": name
                    == context.profile_manager.worker_route(actor.profile),
                }
                for name, value in context.worker_registry.list().items()
            ]
        }

    @app.post("/api/v1/workers", response_model=ObjectResponse)
    def add_worker(body: WorkerRequest, actor=Depends(current_actor)):
        del actor
        name = context.worker_registry.upsert(
            body.name, body.url, body.token, enabled=body.enabled
        )
        return {"name": name}

    @app.put("/api/v1/workers/{name}", response_model=ObjectResponse)
    def update_worker(
        name: str, body: WorkerUpdateRequest, actor=Depends(current_actor)
    ):
        del actor
        current = context.worker_registry.get(name)
        if current is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        new_token = str(body.token or "").strip()
        same_endpoint = body.url.rstrip("/") == str(current.get("url") or "").rstrip("/")
        if new_token and same_endpoint and new_token != str(current.get("token") or ""):
            update_settings = getattr(context.worker_dispatcher, "update_worker_settings", None)
            if not callable(update_settings):
                raise DomainError(
                    "WORKER_TOKEN_ROTATION_UNAVAILABLE",
                    "Worker belum mendukung rotasi token langsung; perbarui worker terlebih dahulu.",
                    status_code=409,
                )
            try:
                update_settings(name, {"worker_api_token": new_token})
            except JsonHttpError as exc:
                if exc.status == 404:
                    raise DomainError(
                        "WORKER_UPDATE_REQUIRED",
                        "Perbarui aplikasi worker agar token dapat dirotasi dari Web.",
                        status_code=409,
                    ) from exc
                raise DomainError(
                    "WORKER_TOKEN_ROTATION_FAILED",
                    "Worker menolak rotasi token. Token gateway belum diubah.",
                    status_code=502,
                ) from exc
            except Exception as exc:
                raise DomainError(
                    "WORKER_UNAVAILABLE",
                    "Worker tidak dapat dihubungi; token gateway belum diubah.",
                    status_code=502,
                ) from exc
        token = new_token or str(current.get("token") or "")
        return {
            "name": context.worker_registry.upsert(
                name, body.url, token, enabled=body.enabled
            )
        }

    @app.patch("/api/v1/workers/{name}", response_model=ObjectResponse)
    def set_worker_enabled(
        name: str, body: WorkerEnabledRequest, actor=Depends(current_actor)
    ):
        del actor
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        context.worker_registry.set_enabled(name, body.enabled)
        return {"name": name, "enabled": bool(body.enabled)}

    @app.get("/api/v1/workers/{name}/settings", response_model=ObjectResponse)
    def worker_settings(name: str, actor=Depends(current_actor)):
        del actor
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        get_settings = getattr(context.worker_dispatcher, "worker_settings", None)
        if not callable(get_settings):
            raise DomainError(
                "WORKER_SETTINGS_UNAVAILABLE",
                "Backend belum mendukung pengaturan runtime worker.",
                status_code=503,
            )
        try:
            return {"worker": name, **get_settings(name)}
        except JsonHttpError as exc:
            if exc.status == 404:
                raise DomainError(
                    "WORKER_UPDATE_REQUIRED",
                    "Perbarui aplikasi worker agar pengaturan lewat Web tersedia.",
                    status_code=409,
                    details={"worker": name},
                ) from exc
            if 400 <= exc.status < 500:
                error_payload = exc.payload.get("error")
                error = error_payload if isinstance(error_payload, dict) else {}
                raise DomainError(
                    str(error.get("code") or "WORKER_SETTINGS_REJECTED"),
                    str(error.get("message") or "Worker menolak permintaan pengaturan."),
                    status_code=exc.status,
                    details={"worker": name},
                ) from exc
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {name} tidak dapat dihubungi.",
                status_code=502,
                details={"worker": name},
            ) from exc
        except Exception as exc:
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Pengaturan worker {name} gagal dimuat.",
                status_code=502,
                details={"worker": name},
            ) from exc

    @app.put("/api/v1/workers/{name}/settings", response_model=ObjectResponse)
    def update_worker_settings(
        name: str, body: WorkerRuntimeSettingsRequest, actor=Depends(current_actor)
    ):
        del actor
        if context.worker_registry.get(name) is None:
            raise DomainError(
                "WORKER_NOT_FOUND", "Worker tidak ditemukan.", status_code=404
            )
        update_settings = getattr(context.worker_dispatcher, "update_worker_settings", None)
        if not callable(update_settings):
            raise DomainError(
                "WORKER_SETTINGS_UNAVAILABLE",
                "Backend belum mendukung pengaturan runtime worker.",
                status_code=503,
            )
        try:
            payload = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
            return {"worker": name, **update_settings(name, payload)}
        except JsonHttpError as exc:
            if exc.status == 404:
                raise DomainError(
                    "WORKER_UPDATE_REQUIRED",
                    "Perbarui aplikasi worker agar pengaturan lewat Web tersedia.",
                    status_code=409,
                    details={"worker": name},
                ) from exc
            if 400 <= exc.status < 500:
                error_payload = exc.payload.get("error")
                error = error_payload if isinstance(error_payload, dict) else {}
                raise DomainError(
                    str(error.get("code") or "WORKER_SETTINGS_REJECTED"),
                    str(error.get("message") or "Worker menolak pengaturan tersebut."),
                    status_code=exc.status,
                    details={"worker": name},
                ) from exc
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Worker {name} tidak dapat dihubungi.",
                status_code=502,
                details={"worker": name},
            ) from exc
        except Exception as exc:
            raise DomainError(
                "WORKER_UNAVAILABLE",
                f"Pengaturan worker {name} gagal disimpan.",
                status_code=502,
                details={"worker": name},
            ) from exc

    @app.delete("/api/v1/workers/{name}", response_model=ObjectResponse)
    def remove_worker(name: str, actor=Depends(current_actor)):
        del actor
        if any(
            context.profile_manager.worker_route(profile) == name
            for profile in context.profile_manager.list_profiles()
        ):
            raise DomainError(
                "WORKER_IN_USE",
                "Worker masih digunakan oleh profile.",
                status_code=409,
            )
        return {"removed": context.worker_registry.remove(name)}

    @app.put("/api/v1/me/worker-route", response_model=ObjectResponse)
    def set_worker_route(body: WorkerRouteRequest, actor=Depends(current_actor)):
        return {"route": context.control_plane.set_worker_route(actor, body.route)}
